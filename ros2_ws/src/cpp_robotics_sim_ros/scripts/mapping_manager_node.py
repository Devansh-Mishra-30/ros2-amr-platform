#!/usr/bin/env python3
# Copyright 2026 Devansh Mishra
#
# Use of this source code is governed by an MIT-style
# license that can be found in the LICENSE file or at
# https://opensource.org/licenses/MIT.


import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
from typing import Optional

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import (
    DurabilityPolicy,
    HistoryPolicy,
    QoSProfile,
    ReliabilityPolicy,
)
from std_msgs.msg import String

SCRIPT_DIRECTORY = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIRECTORY not in sys.path:
    sys.path.insert(0, SCRIPT_DIRECTORY)

from lifecycle_ros_adapter import bind_lifecycle  # noqa: E402,I100


class MappingManagerNode(Node):
    MAP_NAME_PATTERN = re.compile(
        r'^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$'
    )

    def __init__(self) -> None:
        super().__init__('mapping_manager')

        self.declare_parameter(
            'map_directory',
            str(
                Path.home()
                / '.ros'
                / 'cpp_robotics_sim'
                / 'maps'
            ),
        )
        self.declare_parameter('save_timeout', 20.0)
        self.declare_parameter('free_threshold', 0.25)
        self.declare_parameter('occupied_threshold', 0.65)

        self.map_directory = Path(
            str(
                self.get_parameter(
                    'map_directory'
                ).value
            )
        ).expanduser()

        self.save_timeout = float(
            self.get_parameter('save_timeout').value
        )
        self.free_threshold = float(
            self.get_parameter(
                'free_threshold'
            ).value
        )
        self.occupied_threshold = float(
            self.get_parameter(
                'occupied_threshold'
            ).value
        )

        self.validate_parameters()

        self.map_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        transient_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )

        self.status_publisher = self.create_publisher(
            String,
            '/mapping/save_status',
            transient_qos,
        )

        self.maps_publisher = self.create_publisher(
            String,
            '/mapping/saved_maps',
            transient_qos,
        )

        self.save_subscription = self.create_subscription(
            String,
            '/mapping/save_request',
            self.save_request_callback,
            10,
        )

        self.mode_subscription = self.create_subscription(
            String,
            '/mode/status',
            self.mode_status_callback,
            transient_qos,
        )

        self.simulation_subscription = (
            self.create_subscription(
                String,
                '/simulation/status',
                self.simulation_status_callback,
                transient_qos,
            )
        )

        self.environment_subscription = (
            self.create_subscription(
                String,
                '/simulation/environment_status',
                self.environment_status_callback,
                transient_qos,
            )
        )

        self.mode_state = 'stopped'
        self.simulation_state = 'stopped'
        self.selected_environment = ''
        self.save_in_progress = False
        self.save_lock = threading.Lock()
        self.save_completed = threading.Event()
        self.save_completed.set()
        self.lifecycle_accepting = False
        self.lifecycle_component = bind_lifecycle(self, 'mapping', self)

        self.publish_status(
            status='ready',
            message='Mapping manager ready',
        )

        self.publish_saved_maps()

        self.get_logger().info(
            f'Mapping manager ready: {self.map_directory}'
        )

    def validate_parameters(self) -> None:
        if (
            not math.isfinite(self.save_timeout)
            or self.save_timeout <= 0.0
        ):
            raise ValueError(
                'save_timeout must be finite and '
                'greater than zero'
            )

        if not 0.0 <= self.free_threshold <= 1.0:
            raise ValueError(
                'free_threshold must be within [0, 1]'
            )

        if not 0.0 <= self.occupied_threshold <= 1.0:
            raise ValueError(
                'occupied_threshold must be within [0, 1]'
            )

        if (
            self.free_threshold
            >= self.occupied_threshold
        ):
            raise ValueError(
                'free_threshold must be less than '
                'occupied_threshold'
            )

    def mode_status_callback(
        self,
        message: String,
    ) -> None:
        self.mode_state = message.data.strip()

    def simulation_status_callback(
        self,
        message: String,
    ) -> None:
        self.simulation_state = message.data.strip()

    def environment_status_callback(
        self,
        message: String,
    ) -> None:
        try:
            payload = json.loads(message.data)
        except json.JSONDecodeError:
            self.get_logger().warning(
                'Ignoring malformed environment status'
            )
            return

        if not isinstance(payload, dict):
            self.get_logger().warning(
                'Ignoring non-object environment status'
            )
            return

        raw_environment = payload.get(
            'selected_environment',
            '',
        )

        if (
            not isinstance(raw_environment, str)
            or not raw_environment.strip()
        ):
            self.get_logger().warning(
                'Ignoring invalid environment status value'
            )
            return

        environment = raw_environment.strip().lower()

        environment_changed = (
            environment
            != self.selected_environment
        )

        self.selected_environment = environment

        if environment_changed:
            self.publish_saved_maps()

    def save_request_callback(
        self,
        message: String,
    ) -> None:
        map_name = message.data.strip()

        if not getattr(self, 'lifecycle_accepting', True):
            self.publish_status(
                status='error',
                message=(
                    'Mapping lifecycle is not ACTIVE '
                    f'(state={self.lifecycle_component.state.value})'
                ),
            )
            return

        with self.save_lock:
            if not getattr(self, 'lifecycle_accepting', True):
                self.publish_status(
                    status='error',
                    message='Mapping lifecycle is deactivating',
                )
                return
            if self.save_in_progress:
                self.publish_status(
                    status='error',
                    message=(
                        'A map save operation is already '
                        'in progress'
                    ),
                )
                return

            validation_error = (
                self.validate_save_request(map_name)
            )

            if validation_error:
                self.publish_status(
                    status='error',
                    message=validation_error,
                )
                return

            self.save_in_progress = True
            if not hasattr(self, 'save_completed'):
                self.save_completed = threading.Event()
                self.save_completed.set()
            self.save_completed.clear()
            environment = self.selected_environment

        thread = threading.Thread(
            target=self.save_map,
            args=(
                map_name,
                environment,
            ),
            daemon=True,
        )
        thread.start()

    def validate_save_request(
        self,
        map_name: str,
    ) -> Optional[str]:
        if self.simulation_state != 'running':
            return (
                'Simulation must be running before '
                'saving a map'
            )

        if self.mode_state != 'mapping':
            return (
                'Mapping mode must be active before '
                'saving a map'
            )

        if not self.selected_environment:
            return (
                'No simulation environment is selected'
            )

        if not map_name:
            return 'Map name must not be empty'

        if not self.MAP_NAME_PATTERN.fullmatch(
            map_name
        ):
            return (
                'Map name may contain letters, numbers, '
                'underscores, and hyphens only'
            )

        return None

    def save_map(
        self,
        map_name: str,
        environment: str,
    ) -> None:
        try:
            environment_directory = (
                self.map_directory
                / environment
            )

            try:
                environment_directory.mkdir(
                    parents=True,
                    exist_ok=True,
                )
            except OSError as error:
                self.publish_status(
                    status='error',
                    message=(
                        'Unable to prepare map directory: '
                        f'{error}'
                    ),
                    map_name=map_name,
                    environment=environment,
                )
                return

            output_prefix = (
                environment_directory / map_name
            )

            self.publish_status(
                status='saving',
                message=(
                    f"Saving map '{map_name}' for "
                    f'{environment}...'
                ),
                map_name=map_name,
                environment=environment,
            )

            command = [
                'ros2',
                'run',
                'nav2_map_server',
                'map_saver_cli',
                '-f',
                str(output_prefix),
                '--free',
                str(self.free_threshold),
                '--occ',
                str(self.occupied_threshold),
                '--ros-args',
                '-p',
                'save_map_timeout:=5.0',
            ]

            try:
                result = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=self.save_timeout,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                self.publish_status(
                    status='error',
                    message=(
                        f"Saving map '{map_name}' timed out"
                    ),
                    map_name=map_name,
                    environment=environment,
                )
                return
            except OSError as error:
                self.publish_status(
                    status='error',
                    message=(
                        f'Unable to run map saver: {error}'
                    ),
                    map_name=map_name,
                    environment=environment,
                )
                return

            yaml_path = output_prefix.with_suffix(
                '.yaml'
            )
            pgm_path = output_prefix.with_suffix(
                '.pgm'
            )

            if (
                result.returncode != 0
                or not yaml_path.exists()
                or not pgm_path.exists()
            ):
                details = (
                    result.stderr.strip()
                    or result.stdout.strip()
                    or 'Expected map files were not created'
                )

                self.publish_status(
                    status='error',
                    message=(
                        f'Failed to save map '
                        f"'{map_name}': {details}"
                    ),
                    map_name=map_name,
                    environment=environment,
                )
                return

            self.publish_status(
                status='success',
                message=(
                    f"Map '{map_name}' saved successfully "
                    f'for {environment}'
                ),
                map_name=map_name,
                environment=environment,
                yaml_path=str(yaml_path),
                image_path=str(pgm_path),
            )

            self.publish_saved_maps()
        finally:
            with self.save_lock:
                self.save_in_progress = False
                completed = getattr(self, 'save_completed', None)
                if completed is not None:
                    completed.set()

    def on_configure(self) -> None:
        return None

    def on_activate(self) -> None:
        self.lifecycle_accepting = True

    def on_deactivate(self) -> None:
        self.lifecycle_accepting = False
        if not self.save_completed.wait(timeout=self.save_timeout + 2.0):
            raise TimeoutError('map save did not complete before deactivation timeout')
        with self.save_lock:
            if self.save_in_progress:
                raise RuntimeError('map save completion was not verified')

    def on_cleanup(self) -> None:
        self.on_deactivate()

    def on_shutdown(self) -> None:
        self.on_deactivate()

    def on_error(self) -> None:
        self.on_deactivate()

    def on_recover(self) -> bool:
        self.on_deactivate()
        with self.save_lock:
            return not self.save_in_progress and self.save_completed.is_set()

    def on_rollback(self, transition, source_state) -> bool:
        del transition, source_state
        self.on_deactivate()
        return True

    def publish_status(
        self,
        status: str,
        message: str,
        map_name: str = '',
        environment: str = '',
        yaml_path: str = '',
        image_path: str = '',
    ) -> None:
        payload = {
            'status': status,
            'message': message,
            'map_name': map_name,
            'environment': environment,
            'yaml_path': yaml_path,
            'image_path': image_path,
        }

        ros_message = String()
        ros_message.data = json.dumps(payload)

        if rclpy.ok(context=self.context):
            self.status_publisher.publish(
                ros_message
            )

    def publish_saved_maps(self) -> None:
        maps = []

        for yaml_path in sorted(
            self.map_directory.rglob('*.yaml')
        ):
            image_path = yaml_path.with_suffix(
                '.pgm'
            )

            relative_path = yaml_path.relative_to(
                self.map_directory
            )

            if len(relative_path.parts) > 1:
                environment = relative_path.parts[0]
                legacy = False
            else:
                environment = 'legacy'
                legacy = True

            if (
                self.selected_environment
                and not legacy
                and environment
                != self.selected_environment
            ):
                continue

            maps.append(
                {
                    'name': yaml_path.stem,
                    'environment': environment,
                    'legacy': legacy,
                    'yaml_path': str(
                        yaml_path.resolve()
                    ),
                    'image_path': str(
                        image_path.resolve()
                    ),
                    'complete': image_path.exists(),
                }
            )

        message = String()
        message.data = json.dumps(maps)

        if rclpy.ok(context=self.context):
            self.maps_publisher.publish(message)


def main(args=None) -> None:
    rclpy.init(args=args)

    node: Optional[MappingManagerNode] = None

    try:
        node = MappingManagerNode()
        rclpy.spin(node)

    except (
        KeyboardInterrupt,
        ExternalShutdownException,
    ):
        pass

    finally:
        if node is not None:
            node.destroy_node()

        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
