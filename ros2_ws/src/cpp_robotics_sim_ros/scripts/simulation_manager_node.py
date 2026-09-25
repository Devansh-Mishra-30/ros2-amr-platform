#!/usr/bin/env python3
# Copyright 2026 Devansh Mishra
#
# Use of this source code is governed by an MIT-style
# license that can be found in the LICENSE file or at
# https://opensource.org/licenses/MIT.

from enum import Enum
import json
import math
import os
import subprocess
import sys
import threading
import time
from typing import Optional

from ament_index_python.packages import (
    get_package_share_directory,
)
import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import (
    DurabilityPolicy,
    HistoryPolicy,
    QoSProfile,
    ReliabilityPolicy,
)
from std_msgs.msg import Bool
from std_msgs.msg import String
from std_srvs.srv import Trigger
SCRIPT_DIRECTORY = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIRECTORY not in sys.path:
    sys.path.insert(0, SCRIPT_DIRECTORY)

from process_lifecycle import (  # noqa: E402,I100,I101
    defer_termination_signals,
    deregister_exited_process,
    persist_shutdown_result,
    register_managed_process,
    ShutdownResult,
    terminate_owned_process,
)
from process_registry import ProcessRecord, ProcessRegistry  # noqa: E402,I100
from lifecycle_ros_adapter import bind_lifecycle  # noqa: E402,I100
from managed_component import LifecycleState, LifecycleTransition  # noqa: E402,I100


class SimulationState(str, Enum):
    STOPPED = 'stopped'
    STARTING = 'starting'
    RUNNING = 'running'
    STOPPING = 'stopping'
    ERROR = 'error'


class SimulationManagerNode(Node):
    """Manage simulation startup, state, and shutdown."""

    def __init__(self) -> None:
        super().__init__('simulation_manager')

        self.declare_parameter(
            'launch_package',
            'cpp_robotics_sim_ros',
        )
        self.declare_parameter(
            'launch_file',
            'interactive_control.launch.py',
        )
        self.declare_parameter(
            'managed_use_sim_time',
            True,
        )

        self.declare_parameter(
            'default_environment',
            'warehouse',
        )
        self.declare_parameter(
            'environment_names',
            [
                'warehouse',
                'hospital',
            ],
        )
        self.declare_parameter(
            'warehouse_world_file',
            'warehouse_world.sdf',
        )
        self.declare_parameter(
            'hospital_world_file',
            'hospital_world.sdf',
        )

        self.declare_parameter(
            'startup_grace_period',
            4.0,
        )
        self.declare_parameter(
            'shutdown_timeout',
            4.0,
        )
        self.declare_parameter(
            'kill_timeout',
            1.5,
        )

        self.launch_package = str(
            self.get_parameter('launch_package').value
        )
        self.launch_file = str(
            self.get_parameter('launch_file').value
        )
        self.managed_use_sim_time = bool(
            self.get_parameter(
                'managed_use_sim_time'
            ).value
        )

        self.environment_names = [
            str(name)
            for name in self.get_parameter(
                'environment_names'
            ).value
        ]
        self.selected_environment = str(
            self.get_parameter(
                'default_environment'
            ).value
        )

        self.environment_world_files = {
            'warehouse': str(
                self.get_parameter(
                    'warehouse_world_file'
                ).value
            ),
            'hospital': str(
                self.get_parameter(
                    'hospital_world_file'
                ).value
            ),
        }

        self.package_share_directory = (
            get_package_share_directory(
                self.launch_package
            )
        )

        self.startup_grace_period = float(
            self.get_parameter('startup_grace_period').value
        )
        self.shutdown_timeout = float(
            self.get_parameter('shutdown_timeout').value
        )
        self.kill_timeout = float(
            self.get_parameter('kill_timeout').value
        )

        self.validate_parameters()

        status_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )

        self.status_publisher = self.create_publisher(
            String,
            '/simulation/status',
            status_qos,
        )

        self.environment_status_publisher = (
            self.create_publisher(
                String,
                '/simulation/environment_status',
                status_qos,
            )
        )

        self.environment_request_subscription = (
            self.create_subscription(
                String,
                '/simulation/environment_request',
                self.environment_request_callback,
                10,
            )
        )
        self.navigation_cancel_publisher = self.create_publisher(
            String,
            '/navigation/cancel_request',
            10,
        )
        self.emergency_stop_publisher = self.create_publisher(
            Bool,
            '/control/emergency_stop',
            10,
        )

        self.start_service = self.create_service(
            Trigger,
            '/simulation/start',
            self.start_callback,
        )

        self.stop_service = self.create_service(
            Trigger,
            '/simulation/stop',
            self.stop_callback,
        )

        self.reset_service = self.create_service(
            Trigger,
            '/simulation/reset',
            self.reset_callback,
        )

        self.process: Optional[subprocess.Popen] = None
        self.process_record: Optional[ProcessRecord] = None
        self.process_registry = ProcessRegistry()
        self.process_registry.reconcile_stale_records()
        self.process_lock = threading.RLock()
        self.state = SimulationState.STOPPED
        self.last_error = ''
        self.shutdown_prepared = False
        self.stop_in_progress = False
        self.last_shutdown_report: Optional[ShutdownResult] = None

        self.monitor_timer = self.create_timer(
            0.5,
            self.monitor_process,
        )

        self.set_state(SimulationState.STOPPED)
        self.lifecycle_component = bind_lifecycle(self, 'simulation', self)
        self.publish_environment_status(
            state='ready',
            message=(
                'Environment selection ready'
            ),
        )

        self.get_logger().info(
            'Simulation manager ready'
        )
        self.get_logger().info(
            f'Managed launch: '
            f'{self.launch_package} {self.launch_file}'
        )

    def validate_parameters(self) -> None:
        if not self.launch_package.strip():
            raise ValueError(
                'launch_package must not be empty'
            )

        if not self.launch_file.strip():
            raise ValueError(
                'launch_file must not be empty'
            )

        if not self.environment_names:
            raise ValueError(
                'environment_names must not be empty'
            )

        if any(
            not environment.strip()
            for environment in self.environment_names
        ):
            raise ValueError(
                'environment_names must not contain '
                'empty values'
            )

        if (
            len(set(self.environment_names))
            != len(self.environment_names)
        ):
            raise ValueError(
                'environment_names must contain unique '
                'values'
            )

        if (
            self.selected_environment
            not in self.environment_names
        ):
            raise ValueError(
                'default_environment must be one of '
                f'{self.environment_names}'
            )

        missing_world_entries = [
            environment
            for environment in self.environment_names
            if environment
            not in self.environment_world_files
        ]

        if missing_world_entries:
            raise ValueError(
                'Missing world-file configuration for: '
                f'{missing_world_entries}'
            )

        for environment in self.environment_names:
            world_file = self.environment_world_files[
                environment
            ]

            if not world_file.strip():
                raise ValueError(
                    'World filename must not be empty for '
                    f'{environment}'
                )

        if (
            not math.isfinite(
                self.startup_grace_period
            )
            or self.startup_grace_period < 0.0
        ):
            raise ValueError(
                'startup_grace_period must be finite and '
                'not negative'
            )

        if (
            not math.isfinite(self.shutdown_timeout)
            or self.shutdown_timeout <= 0.0
        ):
            raise ValueError(
                'shutdown_timeout must be finite and '
                'greater than zero'
            )

        if (
            not math.isfinite(self.kill_timeout)
            or self.kill_timeout <= 0.0
        ):
            raise ValueError(
                'kill_timeout must be finite and '
                'greater than zero'
            )

    def environment_request_callback(
        self,
        message: String,
    ) -> None:
        requested_environment = message.data.strip().lower()

        if not requested_environment:
            self.publish_environment_status(
                state='invalid_request',
                message=(
                    'Environment request must not be empty'
                ),
            )
            return

        if (
            requested_environment
            not in self.environment_names
        ):
            self.publish_environment_status(
                state='invalid_request',
                message=(
                    'Unsupported environment: '
                    f'{requested_environment}'
                ),
            )
            return

        with self.process_lock:
            if (
                self.process_is_running()
                or self.state
                in (
                    SimulationState.STARTING,
                    SimulationState.RUNNING,
                    SimulationState.STOPPING,
                )
            ):
                self.publish_environment_status(
                    state='locked',
                    message=(
                        'Stop the simulation before changing '
                        'the environment'
                    ),
                )
                return

            self.selected_environment = (
                requested_environment
            )

        self.get_logger().info(
            'Selected simulation environment: '
            f'{self.selected_environment}'
        )

        self.publish_environment_status(
            state='selected',
            message=(
                'Selected environment: '
                f'{self.selected_environment}'
            ),
        )

    def resolve_selected_world_path(self) -> str:
        world_filename = self.environment_world_files[
            self.selected_environment
        ]

        world_path = os.path.join(
            self.package_share_directory,
            'worlds',
            world_filename,
        )

        if not os.path.isfile(world_path):
            raise FileNotFoundError(
                'World file does not exist: '
                f'{world_path}'
            )

        return world_path

    def publish_environment_status(
        self,
        state: str,
        message: str,
    ) -> None:
        if not rclpy.ok(context=self.context):
            return

        world_filename = self.environment_world_files.get(
            self.selected_environment,
            '',
        )

        payload = {
            'state': state,
            'message': message,
            'selected_environment': (
                self.selected_environment
            ),
            'available_environments': (
                self.environment_names
            ),
            'world_file': world_filename,
            'selection_locked': (
                self.state
                in (
                    SimulationState.STARTING,
                    SimulationState.RUNNING,
                    SimulationState.STOPPING,
                )
                or self.process_is_running()
            ),
        }

        ros_message = String()
        ros_message.data = json.dumps(
            payload,
            separators=(',', ':'),
        )

        self.environment_status_publisher.publish(
            ros_message
        )

    def start_callback(
        self,
        request: Trigger.Request,
        response: Trigger.Response,
    ) -> Trigger.Response:
        del request

        if not self.lifecycle_accepts_operations():
            response.success = False
            response.message = self.lifecycle_rejection_reason()
            return response

        success, message = self.start_simulation()
        response.success = success
        response.message = message
        return response

    def stop_callback(
        self,
        request: Trigger.Request,
        response: Trigger.Response,
    ) -> Trigger.Response:
        del request

        if not self.lifecycle_accepts_operations():
            response.success = False
            response.message = self.lifecycle_rejection_reason()
            return response

        success, message = self.stop_simulation()
        response.success = success
        response.message = message
        return response

    def reset_callback(
        self,
        request: Trigger.Request,
        response: Trigger.Response,
    ) -> Trigger.Response:
        del request

        if not self.lifecycle_accepts_operations():
            response.success = False
            response.message = self.lifecycle_rejection_reason()
            return response

        self.get_logger().info(
            'Simulation reset requested'
        )

        stopped, stop_message = self.stop_simulation()

        if not stopped:
            response.success = False
            response.message = (
                f'Reset failed while stopping: {stop_message}'
            )
            return response

        time.sleep(1.0)

        started, start_message = self.start_simulation()

        response.success = started
        response.message = (
            'Simulation reset successfully'
            if started
            else f'Reset failed while starting: {start_message}'
        )

        return response

    def start_simulation(self) -> tuple[bool, str]:
        with self.process_lock:
            if self.shutdown_prepared or self.stop_in_progress:
                return False, 'Simulation manager is shutting down'
            if self.process_is_running():
                message = (
                    'Simulation is already running'
                )
                self.get_logger().warning(message)
                return False, message

            self.clear_finished_process()
            self.last_error = ''
            self.set_state(SimulationState.STARTING)

            try:
                selected_world_path = (
                    self.resolve_selected_world_path()
                )
            except (KeyError, FileNotFoundError) as error:
                self.last_error = str(error)
                self.set_state(SimulationState.ERROR)

                self.publish_environment_status(
                    state='error',
                    message=self.last_error,
                )

                self.get_logger().error(
                    self.last_error
                )
                return False, self.last_error

            command = [
                'ros2',
                'launch',
                self.launch_package,
                self.launch_file,
                f'world:={selected_world_path}',
                f"use_sim_time:={'true' if self.managed_use_sim_time else 'false'}",
            ]

            self.get_logger().info(
                'Starting simulation: '
                + ' '.join(command)
            )

            try:
                self.process = subprocess.Popen(
                    command,
                    start_new_session=True,
                )
                self.process_record = self.register_process(
                    self.process_registry,
                    self.process,
                    'simulation_launch',
                )
            except (OSError, RuntimeError, subprocess.SubprocessError) as error:
                self.process = None
                self.process_record = None
                self.last_error = str(error)
                self.set_state(SimulationState.ERROR)

                message = (
                    f'Failed to start simulation: {error}'
                )
                self.get_logger().error(message)
                return False, message

            time.sleep(self.startup_grace_period)

            if self.process.poll() is not None:
                return_code = self.process.returncode
                self.last_error = (
                    'Simulation launch exited during startup '
                    f'with return code {return_code}'
                )
                self.process = None
                if self.process_record is not None:
                    if self.release_exited_process_record(
                        self.process_registry,
                        self.process_record,
                    ):
                        self.process_record = None
                    else:
                        self.last_error += (
                            '; process-group descendants remain and the '
                            'ownership record was retained'
                        )
                self.set_state(SimulationState.ERROR)

                self.get_logger().error(self.last_error)
                return False, self.last_error

            try:
                self.process_record = self.refresh_process_record(
                    self.process_registry, self.process_record
                )
            except (OSError, RuntimeError, ValueError) as error:
                report = self.terminate_process_record(
                    self.process_registry,
                    self.process_record,
                    process=self.process,
                    sigint_timeout=self.shutdown_timeout,
                    sigterm_timeout=self.kill_timeout,
                    sigkill_timeout=self.kill_timeout,
                )
                self.last_shutdown_report = report
                self.persist_shutdown_report(report)
                if report.success:
                    self.process = None
                    self.process_record = None
                self.last_error = (
                    'Failed to persist simulation descendant identities: '
                    + str(error)
                )
                self.set_state(SimulationState.ERROR)
                self.get_logger().error(self.last_error)
                return False, self.last_error

            self.set_state(SimulationState.RUNNING)
            self.publish_emergency_stop(False)
            self.publish_environment_status(
                state='running',
                message=(
                    'Simulation running in '
                    f'{self.selected_environment}'
                ),
            )

            message = (
                f'Simulation started with PID '
                f'{self.process.pid}'
            )
            self.get_logger().info(message)
            return True, message

    def lifecycle_accepts_operations(self) -> bool:
        return (
            not hasattr(self, 'lifecycle_component')
            or (
                self.lifecycle_component.state == LifecycleState.ACTIVE
                and not self.stop_in_progress
            )
        )

    def lifecycle_rejection_reason(self) -> str:
        return (
            'Simulation lifecycle is not ACTIVE '
            f'(state={self.lifecycle_component.state.value})'
        )

    def on_configure(self) -> None:
        return None

    def on_activate(self) -> None:
        return None

    def on_deactivate(self) -> None:
        success, reason = self.stop_simulation()
        if not success:
            raise RuntimeError(f'simulation cleanup failed: {reason}')

    def on_cleanup(self) -> None:
        success, reason = self.stop_simulation()
        if not success:
            raise RuntimeError(f'simulation cleanup failed: {reason}')

    def on_shutdown(self) -> None:
        success, reason = self.stop_simulation()
        if not success:
            raise RuntimeError(f'simulation shutdown cleanup failed: {reason}')

    def on_error(self) -> None:
        success, reason = self.stop_simulation()
        if not success:
            raise RuntimeError(f'simulation error cleanup failed: {reason}')

    def on_recover(self) -> bool:
        success, reason = self.stop_simulation()
        if not success:
            raise RuntimeError(f'simulation recovery cleanup failed: {reason}')
        return (
            self.process_record is None
            and not any(
                record.component == 'simulation_launch'
                for record in self.process_registry.list_records()
            )
        )

    def on_rollback(self, transition, source_state) -> bool:
        del transition, source_state
        success, _reason = self.stop_simulation()
        return success

    def stop_simulation(self) -> tuple[bool, str]:
        with self.process_lock:
            shutdown_started = time.monotonic()
            if not self.process_is_running():
                self.clear_finished_process()
                self.cleanup_remaining_processes()
                if self.process_record is not None:
                    report = self.terminate_process_record(
                        self.process_registry,
                        self.process_record,
                        sigint_timeout=self.shutdown_timeout,
                        sigterm_timeout=self.kill_timeout,
                        sigkill_timeout=self.kill_timeout,
                    )
                    self.last_shutdown_report = report
                    self.persist_shutdown_report(report)
                    if not report.success:
                        self.last_error = report.error
                        self.stop_in_progress = False
                        self.set_state(SimulationState.ERROR)
                        return False, self.last_error
                    self.process_record = None
                self.set_state(SimulationState.STOPPED)

                self.stop_in_progress = False
                self.last_shutdown_report = ShutdownResult(
                    success=True,
                    component='simulation_launch',
                    pid=None,
                    pgid=None,
                    total_duration_seconds=round(
                        time.monotonic() - shutdown_started, 6
                    ),
                    signal_result='already_exited',
                    stages_completed=[
                        'reject_new_operations',
                        'clear_runtime_state',
                        'produce_shutdown_report',
                    ],
                )
                self.persist_shutdown_report(self.last_shutdown_report)
                self.reset_runtime_state()

                message = 'Simulation is already stopped'
                self.get_logger().info(message)
                return True, message

            assert self.process is not None
            process = self.process
            self.stop_in_progress = True
            self.set_state(SimulationState.STOPPING)

            stages = ['reject_new_operations']
            self.publish_navigation_cancel()
            stages.append('cancel_navigation_goal')
            self.publish_emergency_stop(True)
            stages.append('command_zero_velocity')

            if not self.wait_for_modes_stopped(self.shutdown_timeout):
                self.last_error = (
                    'Timed out waiting for the owned operating mode to stop'
                )
                self.last_shutdown_report = ShutdownResult(
                    success=False,
                    component='simulation_launch',
                    pid=process.pid,
                    pgid=(
                        self.process_record.pgid
                        if self.process_record is not None
                        else None
                    ),
                    total_duration_seconds=round(
                        time.monotonic() - shutdown_started, 6
                    ),
                    failed_stage='stop_active_mode',
                    error=self.last_error,
                    stages_completed=stages,
                )
                self.persist_shutdown_report(self.last_shutdown_report)
                self.stop_in_progress = False
                self.set_state(SimulationState.ERROR)
                return False, self.last_error
            stages.extend(['stop_active_mode', 'stop_mode_launch_group'])

            if self.process_record is None:
                self.last_error = (
                    'Simulation process has no ownership record; refusing '
                    'to signal it'
                )
                self.last_shutdown_report = ShutdownResult(
                    success=False,
                    component='simulation_launch',
                    pid=process.pid,
                    pgid=None,
                    total_duration_seconds=round(
                        time.monotonic() - shutdown_started, 6
                    ),
                    failed_stage='verify_simulation_ownership',
                    identity_verification_status='missing_record',
                    signal_result='refused',
                    error=self.last_error,
                    stages_completed=stages,
                )
                self.persist_shutdown_report(self.last_shutdown_report)
                self.stop_in_progress = False
                self.set_state(SimulationState.ERROR)
                return False, self.last_error

            try:
                # Gazebo can create additional same-session process groups
                # after startup. Capture their stable identities immediately
                # before cleanup so ownership remains explicit and bounded.
                self.process_record = self.refresh_process_record(
                    self.process_registry, self.process_record
                )
            except (OSError, RuntimeError, ValueError) as error:
                self.last_error = (
                    'Failed to refresh simulation descendant identities: '
                    + str(error)
                )
                self.last_shutdown_report = ShutdownResult(
                    success=False,
                    component='simulation_launch',
                    pid=process.pid,
                    pgid=self.process_record.pgid,
                    total_duration_seconds=round(
                        time.monotonic() - shutdown_started, 6
                    ),
                    failed_stage='refresh_simulation_ownership',
                    identity_verification_status='refused',
                    signal_result='refused',
                    error=self.last_error,
                    stages_completed=stages,
                )
                self.persist_shutdown_report(self.last_shutdown_report)
                self.stop_in_progress = False
                self.set_state(SimulationState.ERROR)
                return False, self.last_error

            self.get_logger().info(
                'Stopping verified simulation process group '
                f'{self.process_record.pgid}'
            )
            report = self.terminate_process_record(
                self.process_registry,
                self.process_record,
                process=process,
                sigint_timeout=self.shutdown_timeout,
                sigterm_timeout=self.kill_timeout,
                sigkill_timeout=self.kill_timeout,
            )
            self.last_shutdown_report = report
            report.stages_completed = stages
            report.total_duration_seconds = round(
                time.monotonic() - shutdown_started, 6
            )

            if not report.success:
                self.last_error = report.error
                self.set_state(SimulationState.ERROR)
                self.get_logger().error(self.last_error)
                self.persist_shutdown_report(report)
                self.stop_in_progress = False
                return False, self.last_error

            stages.extend(
                [
                    'stop_simulation_controllers',
                    'stop_gazebo',
                    'clear_runtime_state',
                ]
            )

            self.cleanup_remaining_processes()
            self.reset_runtime_state()
            self.publish_environment_status(
                state='selected',
                message=(
                    'Simulation stopped; environment '
                    'selection unlocked'
                ),
            )

            message = 'Simulation stopped successfully'
            self.stop_in_progress = False
            self.publish_emergency_stop(False)
            stages.append('produce_shutdown_report')
            report.stages_completed = stages
            report.total_duration_seconds = round(
                time.monotonic() - shutdown_started, 6
            )
            self.persist_shutdown_report(report)

            if rclpy.ok(context=self.context):
                self.get_logger().info(message)

            return True, message

    @staticmethod
    def register_process(registry, process, component):
        return register_managed_process(registry, process, component)

    @staticmethod
    def terminate_process_record(registry, record, **kwargs):
        return terminate_owned_process(registry, record, **kwargs)

    @staticmethod
    def refresh_process_record(registry, record):
        return registry.refresh_group_members(record)

    @staticmethod
    def release_exited_process_record(registry, record):
        return deregister_exited_process(registry, record)

    def publish_navigation_cancel(self) -> None:
        if not rclpy.ok(context=self.context):
            return
        message = String()
        message.data = '{"cancel":true}'
        self.navigation_cancel_publisher.publish(message)

    def publish_emergency_stop(self, enabled: bool) -> None:
        if not rclpy.ok(context=self.context):
            return
        message = Bool()
        message.data = enabled
        self.emergency_stop_publisher.publish(message)

    def wait_for_modes_stopped(self, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.process_registry.reconcile_stale_records()
            active_modes = [
                record
                for record in self.process_registry.list_records()
                if record.component.startswith('mode_')
            ]
            if not active_modes:
                return True
            time.sleep(0.05)
        return False

    @staticmethod
    def persist_shutdown_report(report: ShutdownResult) -> None:
        persist_shutdown_result(report)

    def monitor_process(self) -> None:
        with self.process_lock:
            if self.process is None:
                return

            return_code = self.process.poll()

            if return_code is None:
                return

            previous_state = self.state
            self.process = None
            if self.process_record is not None:
                if self.release_exited_process_record(
                    self.process_registry,
                    self.process_record,
                ):
                    self.process_record = None

            if self.process_record is not None:
                report = self.terminate_process_record(
                    self.process_registry,
                    self.process_record,
                    sigint_timeout=self.shutdown_timeout,
                    sigterm_timeout=self.kill_timeout,
                    sigkill_timeout=self.kill_timeout,
                )
                self.last_shutdown_report = report
                self.persist_shutdown_report(report)
                if report.success:
                    self.process_record = None
                else:
                    self.last_error = report.error
                    self.set_state(SimulationState.ERROR)
                    self.publish_environment_status(
                        state='error', message=self.last_error
                    )
                    self.get_logger().error(self.last_error)
                    return

            if previous_state in (
                SimulationState.STOPPING,
                SimulationState.STOPPED,
            ):
                self.set_state(SimulationState.STOPPED)
                return

            self.last_error = (
                'Simulation process exited unexpectedly '
                f'with return code {return_code}'
            )

            self.set_state(SimulationState.ERROR)
            self.publish_environment_status(
                state='error',
                message=self.last_error,
            )
            self.get_logger().error(self.last_error)

    def process_is_running(self) -> bool:
        return (
            self.process is not None
            and self.process.poll() is None
        )

    def reset_runtime_state(self) -> None:
        """
        Restore the next-run baseline without changing the environment.

        ``last_shutdown_report`` remains available as historical diagnostic
        state, and ``shutdown_prepared`` remains untouched so final node
        shutdown remains idempotent.  ``selected_environment`` is persistent
        operator state and is intentionally not assigned here.
        """
        self.process = None
        self.process_record = None
        self.last_error = ''
        self.stop_in_progress = False
        if self.state != SimulationState.STOPPED:
            self.set_state(SimulationState.STOPPED)

    def clear_finished_process(self) -> None:
        if (
            self.process is not None
            and self.process.poll() is not None
        ):
            self.process = None
            if self.process_record is not None:
                if self.release_exited_process_record(
                    self.process_registry,
                    self.process_record,
                ):
                    self.process_record = None

    def set_state(
        self,
        new_state: SimulationState,
    ) -> None:
        state_changed = new_state != self.state
        self.state = new_state

        # SIGINT may invalidate the ROS context before shutdown cleanup
        # completes. Process cleanup must continue even when publishing
        # status is no longer possible.
        if not rclpy.ok(context=self.context):
            return

        message = String()
        message.data = new_state.value

        try:
            self.status_publisher.publish(message)
        except Exception as error:
            # Publishing is noncritical during shutdown. The managed
            # simulation process still needs to be terminated.
            if rclpy.ok(context=self.context):
                raise error
            return

        if state_changed:
            self.get_logger().info(
                f'Simulation state: {new_state.value}'
            )

    def cleanup_remaining_processes(self) -> None:
        """Reconcile exited records without process-name-based signaling."""
        self.process_registry.reconcile_stale_records()

    def shutdown(self) -> None:
        if self.shutdown_prepared:
            return

        if (
            hasattr(self, 'lifecycle_component')
            and self.lifecycle_component.state == LifecycleState.FINALIZED
        ):
            self.shutdown_prepared = True
            return

        self.shutdown_prepared = True

        if rclpy.ok(context=self.context):
            self.get_logger().info(
                'Simulation manager shutting down'
            )

        if hasattr(self, 'lifecycle_component'):
            result = self.lifecycle_component.transition(
                LifecycleTransition.SHUTDOWN
            )
            success, message = result.success, result.reason
        else:
            success, message = self.stop_simulation()

        if hasattr(self, 'publish_lifecycle_result'):
            self.publish_lifecycle_result(result)

        if (
            not success
            and rclpy.ok(context=self.context)
        ):
            self.get_logger().error(message)

        if rclpy.ok(context=self.context):
            self.get_logger().info(
                'Simulation shutdown cleanup complete'
            )


def main(args=None) -> None:
    rclpy.init(args=args)

    node: Optional[SimulationManagerNode] = None

    try:
        node = SimulationManagerNode()
        rclpy.spin(node)

    except (
        KeyboardInterrupt,
        ExternalShutdownException,
    ):
        pass

    finally:
        with defer_termination_signals():
            if node is not None:
                node.shutdown()
                node.destroy_node()

            if rclpy.ok():
                rclpy.shutdown()


if __name__ == '__main__':
    main()
