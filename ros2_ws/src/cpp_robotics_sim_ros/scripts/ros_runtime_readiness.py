#!/usr/bin/env python3
# Copyright 2026 Devansh Mishra
#
# Use of this source code is governed by an MIT-style
# license that can be found in the LICENSE file or at
# https://opensource.org/licenses/MIT.

"""ROS observations used to decide whether the simulation is operational."""

from collections import deque
import math
import threading
import time
import uuid

from controller_manager_msgs.srv import ListControllers
from geometry_msgs.msg import PoseWithCovarianceStamped, TransformStamped
from lifecycle_msgs.srv import GetState
from nav2_msgs.action import NavigateToPose
from nav_msgs.msg import OccupancyGrid, Odometry
from rclpy.action import ActionClient
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.duration import Duration
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from rclpy.qos import qos_profile_sensor_data
from rclpy.time import Time
from readiness_contract import (
    aggregate, check_clock, check_controllers, check_endpoint,
    check_localization, check_map, check_navigation_action_server,
    check_tf, check_topic,
    LatchedMapObservation, PROFILE_REQUIREMENTS, ReadinessProfile,
    select_profile_checks,
)
from rosgraph_msgs.msg import Clock
from sensor_msgs.msg import JointState, LaserScan
from tf2_ros import Buffer, TransformListener


CLOCK_SAMPLE_BUFFER_SIZE = 2048
CONTROLLER_REQUEST_TIMEOUT_SECONDS = 1.0


class SimulationReadinessProbe:
    """Collect fresh core simulation evidence on a private spinning node."""

    def __init__(self, *, use_sim_time: bool,
                 profile: ReadinessProfile = ReadinessProfile.SIMULATION_READY,
                 map_path: str = ''):
        # This probe is created from manager nodes launched with a global
        # ``__node`` remap. Ignore process-wide CLI remaps so the helper keeps
        # its own graph identity instead of appearing as another manager.
        self.node = Node(
            'simulation_readiness_probe', use_global_arguments=False,
        )
        self.node.set_parameters([Parameter('use_sim_time', value=use_sim_time)])
        self.use_sim_time = use_sim_time
        self.runtime_id = str(uuid.uuid4())
        self.profile = profile
        self.map_path = map_path
        self._lock = threading.Lock()
        self._received = {
            '/scan': deque(maxlen=100),
            '/diff_drive_controller/odom': deque(maxlen=100),
            '/joint_states': deque(maxlen=100),
        }
        # Keep enough of the live high-rate stream to prove the contract's
        # 50 ms receive-time span. Ten samples covered only about 9 ms at the
        # observed ~900 Hz Gazebo clock rate.
        self._clock_samples = deque(maxlen=CLOCK_SAMPLE_BUFFER_SIZE)
        self._controller_response = None
        self._controller_response_at = 0.0
        self._controller_future = None
        self._controller_request_started = None
        self._navigation_state = None
        self._navigation_state_at = 0.0
        self._navigation_state_future = None
        self._navigation_state_started = None
        self._map_observation = LatchedMapObservation(self.runtime_id)
        self._pose_received = 0.0
        self._pose_stamp = None
        self._pose_valid = False
        self._callback_group = ReentrantCallbackGroup()
        self._subscriptions = [
            self.node.create_subscription(Clock, '/clock', self._clock, 10,
                                          callback_group=self._callback_group),
            self.node.create_subscription(LaserScan, '/scan',
                                          lambda _msg: self._topic('/scan'),
                                          qos_profile_sensor_data,
                                          callback_group=self._callback_group),
            self.node.create_subscription(
                Odometry, '/diff_drive_controller/odom',
                lambda _msg: self._topic('/diff_drive_controller/odom'), 10,
                callback_group=self._callback_group,
            ),
            self.node.create_subscription(JointState, '/joint_states',
                                          lambda _msg: self._topic('/joint_states'), 10,
                                          callback_group=self._callback_group),
        ]
        self._subscriptions.extend([
            self.node.create_subscription(
                OccupancyGrid, '/map', self._map_callback,
                QoSProfile(
                    depth=1, reliability=ReliabilityPolicy.RELIABLE,
                    durability=DurabilityPolicy.TRANSIENT_LOCAL,
                ),
                callback_group=self._callback_group,
            ),
            self.node.create_subscription(
                PoseWithCovarianceStamped, '/amcl_pose', self._pose_callback, 10,
                callback_group=self._callback_group,
            ),
        ])
        self._tf_buffer = Buffer(node=self.node)
        self._tf_listener = TransformListener(self._tf_buffer, self.node,
                                              spin_thread=False)
        self._controller_client = self.node.create_client(
            ListControllers, '/controller_manager/list_controllers',
            callback_group=self._callback_group,
        )
        self._navigate_client = ActionClient(
            self.node, NavigateToPose, '/navigate_to_pose',
            callback_group=self._callback_group,
        )
        self._navigation_state_client = self.node.create_client(
            GetState, '/bt_navigator/get_state',
            callback_group=self._callback_group,
        )
        self._executor = SingleThreadedExecutor()
        self._executor.add_node(self.node)
        self._thread = threading.Thread(target=self._executor.spin, daemon=True)
        self._thread.start()

    def _clock(self, message):
        receive_time = time.monotonic()
        ros_seconds = float(message.clock.sec) + message.clock.nanosec * 1e-9
        with self._lock:
            self._clock_samples.append((ros_seconds, receive_time))

    def _topic(self, name):
        with self._lock:
            self._received[name].append(time.monotonic())

    def _map_callback(self, message):
        valid = (
            message.header.frame_id == 'map'
            and message.info.width > 0 and message.info.height > 0
            and math.isfinite(message.info.resolution)
            and message.info.resolution > 0.0
            and len(message.data) == message.info.width * message.info.height
            and all(-1 <= value <= 100 for value in message.data)
        )
        self._map_observation.observe(valid=valid, runtime_id=self.runtime_id)

    def _pose_callback(self, message):
        self._pose_received = time.monotonic()
        stamp = message.header.stamp
        self._pose_stamp = stamp.sec + stamp.nanosec * 1e-9
        pose = message.pose.pose
        values = (
            pose.position.x, pose.position.y, pose.position.z,
            pose.orientation.x, pose.orientation.y,
            pose.orientation.z, pose.orientation.w,
            *message.pose.covariance,
        )
        orientation_norm = sum(value * value for value in (
            pose.orientation.x, pose.orientation.y,
            pose.orientation.z, pose.orientation.w,
        ))
        self._pose_valid = (
            message.header.frame_id == 'map'
            and all(math.isfinite(value) for value in values)
            and orientation_norm > 1e-9
        )

    def _request_controller_state(self):
        now = time.monotonic()
        if self._controller_future is not None and self._controller_future.done():
            try:
                self._controller_response = self._controller_future.result()
                self._controller_response_at = now
            except Exception:
                self._controller_response = None
                self._controller_response_at = 0.0
            self._controller_future = None
            self._controller_request_started = None
        elif (
            self._controller_future is not None
            and self._controller_request_started is not None
            and now - self._controller_request_started
            >= CONTROLLER_REQUEST_TIMEOUT_SECONDS
        ):
            self._controller_client.remove_pending_request(
                self._controller_future
            )
            self._controller_future.cancel()
            self._controller_future = None
            self._controller_request_started = None

        available = self._controller_client.service_is_ready()
        if available and self._controller_future is None:
            self._controller_future = self._controller_client.call_async(
                ListControllers.Request()
            )
            self._controller_request_started = now
        response = (self._controller_response
                    if now - self._controller_response_at <= 1.0
                    else None)
        return available, response

    def _request_navigation_state(self):
        now = time.monotonic()
        future = self._navigation_state_future
        if future is not None and future.done():
            try:
                self._navigation_state = future.result().current_state.label.lower()
                self._navigation_state_at = now
            except Exception:
                self._navigation_state = None
                self._navigation_state_at = 0.0
            self._navigation_state_future = None
            self._navigation_state_started = None
        elif (
            future is not None
            and self._navigation_state_started is not None
            and now - self._navigation_state_started
            >= CONTROLLER_REQUEST_TIMEOUT_SECONDS
        ):
            self._navigation_state_client.remove_pending_request(future)
            future.cancel()
            self._navigation_state_future = None
            self._navigation_state_started = None

        if (
            self._navigation_state_client.service_is_ready()
            and self._navigation_state_future is None
        ):
            self._navigation_state_future = (
                self._navigation_state_client.call_async(GetState.Request())
            )
            self._navigation_state_started = now

        state = (
            self._navigation_state
            if now - self._navigation_state_at <= 1.0 else None
        )
        return self._navigate_client.server_is_ready(), state

    def __call__(self):
        now = time.monotonic()
        with self._lock:
            clocks = tuple(self._clock_samples)
            samples = {name: tuple(values) for name, values in self._received.items()}
        checks = [check_clock(clocks, use_sim_time=self.use_sim_time, now=now,
                              runtime_id=self.runtime_id)]
        checks.extend((
            check_topic('/scan', samples['/scan'], now=now,
                        min_rate_hz=1.0, max_age=1.0, runtime_id=self.runtime_id),
            check_topic('/diff_drive_controller/odom',
                        samples['/diff_drive_controller/odom'], now=now,
                        min_rate_hz=5.0, max_age=1.0, runtime_id=self.runtime_id),
        ))
        if '/joint_states' in PROFILE_REQUIREMENTS[self.profile]:
            checks.append(check_topic('/joint_states', samples['/joint_states'], now=now,
                                      min_rate_hz=5.0, max_age=1.0,
                                      runtime_id=self.runtime_id))
        try:
            lookup_started = time.monotonic()
            can_transform = self._tf_buffer.can_transform(
                'odom', 'base_link', Time(), timeout=Duration(seconds=0.05)
            )
            transform: TransformStamped | None = self._tf_buffer.lookup_transform(
                'odom', 'base_link', Time()
            ) if can_transform else None
            stamp = (
                transform.header.stamp.sec
                + transform.header.stamp.nanosec * 1e-9
                if transform else 0.0
            )
            clock_now = clocks[-1][0] if clocks else 0.0
            age = clock_now - stamp if transform else None
            lookup_time = time.monotonic() - lookup_started
            checks.append(check_tf('odom', 'base_link', available=can_transform,
                                   age_seconds=age, max_age=1.0,
                                   lookup_seconds=lookup_time, timeout=0.1,
                                   runtime_id=self.runtime_id))
        except Exception as error:
            checks.append(check_tf('odom', 'base_link', available=False,
                                   age_seconds=None, max_age=1.0,
                                   lookup_seconds=0.0, timeout=0.1,
                                   runtime_id=self.runtime_id))
            self.node.get_logger().debug(f'TF readiness probe: {error}')

        if self.profile in (ReadinessProfile.LOCALIZATION_READY,
                            ReadinessProfile.NAVIGATION_READY):
            checks.extend((
                check_map(self.map_path,
                          available=self._map_observation.available_for(self.runtime_id),
                          runtime_id=self.runtime_id),
                check_localization(
                    valid=(self._pose_valid
                           and 0.0 <= now - self._pose_received <= 1.0),
                    age_seconds=(clocks[-1][0] - self._pose_stamp
                                 if clocks and self._pose_stamp is not None else None),
                    max_age=1.0, runtime_id=self.runtime_id,
                ),
            ))
            try:
                lookup_started = time.monotonic()
                can_transform = self._tf_buffer.can_transform(
                    'map', 'odom', Time(), timeout=Duration(seconds=0.05)
                )
                transform = self._tf_buffer.lookup_transform(
                    'map', 'odom', Time()
                ) if can_transform else None
                stamp = (transform.header.stamp.sec
                         + transform.header.stamp.nanosec * 1e-9) if transform else 0.0
                checks.append(check_tf(
                    'map', 'odom', available=can_transform,
                    age_seconds=clocks[-1][0] - stamp if transform and clocks else None,
                    max_age=1.0,
                    lookup_seconds=time.monotonic() - lookup_started,
                    timeout=0.1, runtime_id=self.runtime_id,
                ))
            except Exception:
                checks.append(check_tf(
                    'map', 'odom', available=False, age_seconds=None,
                    max_age=1.0, lookup_seconds=0.0, timeout=0.1,
                    runtime_id=self.runtime_id,
                ))

        if self.profile == ReadinessProfile.NAVIGATION_READY:
            action_available, lifecycle_state = self._request_navigation_state()
            checks.append(check_navigation_action_server(
                available=action_available,
                lifecycle_state=lifecycle_state,
                runtime_id=self.runtime_id,
            ))

        if self.profile in (ReadinessProfile.SIMULATION_READY,
                            ReadinessProfile.NAVIGATION_READY):
            service_available, response = self._request_controller_state()
            checks.append(check_endpoint(
                '/controller_manager/list_controllers', 'service',
                available=service_available, responsive=response is not None,
                runtime_id=self.runtime_id,
            ))
            active = [] if response is None else [
                item.name for item in response.controller if item.state == 'active'
            ]
            checks.append(check_controllers(
                active, ('joint_state_broadcaster', 'diff_drive_controller'),
                response_received=response is not None, runtime_id=self.runtime_id,
            ))
        blocking_checks = select_profile_checks(self.profile, checks)
        return aggregate(blocking_checks, profile=self.profile,
                         runtime_id=self.runtime_id)

    def close(self):
        self._executor.shutdown(timeout_sec=1.0)
        self.node.destroy_node()
        self._thread.join(timeout=1.0)
