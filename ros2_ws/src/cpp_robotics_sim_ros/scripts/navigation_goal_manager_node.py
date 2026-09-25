#!/usr/bin/env python3
# Copyright 2026 Devansh Mishra
#
# Use of this source code is governed by an MIT-style
# license that can be found in the LICENSE file or at
# https://opensource.org/licenses/MIT.

import json
import math
import threading
from typing import Any, Optional

from action_msgs.msg import GoalStatus
from nav2_msgs.action import NavigateToPose
import rclpy
from rclpy.action import ActionClient
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import (
    DurabilityPolicy,
    HistoryPolicy,
    QoSProfile,
    ReliabilityPolicy,
)
from std_msgs.msg import String


class NavigationGoalManagerNode(Node):
    """
    Manage Nav2 NavigateToPose goals for ROS CLI and dashboard clients.

    Inputs:
        /navigation/goal_request
            JSON String containing:
            {
                "x": number,
                "y": number,
                "yaw": number
            }

        /navigation/cancel_request
            JSON String containing:
            {
                "cancel": true
            }

        /mode/status
            Current operating-mode state.

        /simulation/status
            Current simulation lifecycle state.

    Outputs:
        /navigation/status
            Transient-local JSON status and final-result information.

        /navigation/feedback
            JSON NavigateToPose feedback information.

    Action:
        /navigate_to_pose
            nav2_msgs/action/NavigateToPose
    """

    def __init__(self) -> None:
        super().__init__('navigation_goal_manager')

        self.declare_parameter(
            'action_name',
            '/navigate_to_pose',
        )
        self.declare_parameter(
            'goal_frame',
            'map',
        )
        self.declare_parameter(
            'server_wait_timeout',
            2.0,
        )
        self.declare_parameter(
            'minimum_goal_x',
            -9.5,
        )
        self.declare_parameter(
            'maximum_goal_x',
            9.5,
        )
        self.declare_parameter(
            'minimum_goal_y',
            -7.5,
        )
        self.declare_parameter(
            'maximum_goal_y',
            7.5,
        )

        self.action_name = str(
            self.get_parameter('action_name').value
        ).strip()
        self.goal_frame = str(
            self.get_parameter('goal_frame').value
        ).strip()
        self.server_wait_timeout = float(
            self.get_parameter(
                'server_wait_timeout'
            ).value
        )
        self.minimum_goal_x = float(
            self.get_parameter(
                'minimum_goal_x'
            ).value
        )
        self.maximum_goal_x = float(
            self.get_parameter(
                'maximum_goal_x'
            ).value
        )
        self.minimum_goal_y = float(
            self.get_parameter(
                'minimum_goal_y'
            ).value
        )
        self.maximum_goal_y = float(
            self.get_parameter(
                'maximum_goal_y'
            ).value
        )

        self.validate_parameters()

        transient_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )

        self.status_publisher = self.create_publisher(
            String,
            '/navigation/status',
            transient_qos,
        )

        self.feedback_publisher = self.create_publisher(
            String,
            '/navigation/feedback',
            transient_qos,
        )

        self.goal_request_subscription = (
            self.create_subscription(
                String,
                '/navigation/goal_request',
                self.goal_request_callback,
                10,
            )
        )

        self.cancel_request_subscription = (
            self.create_subscription(
                String,
                '/navigation/cancel_request',
                self.cancel_request_callback,
                10,
            )
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

        self.action_client = ActionClient(
            self,
            NavigateToPose,
            self.action_name,
        )

        self.state_lock = threading.RLock()

        self.mode_state = 'stopped'
        self.simulation_state = 'stopped'

        self.goal_request_in_progress = False
        self.active_goal_handle = None
        self.cancel_requested = False
        self.shutdown_prepared = False

        self.request_sequence = 0
        self.current_request_id: Optional[int] = None

        self.current_goal: Optional[dict[str, float]] = None
        self.last_feedback: dict[str, Any] = {}

        self.publish_status(
            state='ready',
            message='Navigation goal manager ready',
        )

        self.publish_feedback(
            state='idle',
            message='No navigation goal is active',
        )

        self.get_logger().info(
            'Navigation goal manager ready: '
            f'action={self.action_name}, '
            f'frame={self.goal_frame}'
        )

    def validate_parameters(self) -> None:
        if not self.action_name:
            raise ValueError(
                'action_name must not be empty'
            )

        if not self.action_name.startswith('/'):
            raise ValueError(
                'action_name must be an absolute ROS name'
            )

        if not self.goal_frame.strip():
            raise ValueError(
                'goal_frame must not be empty'
            )

        if (
            not math.isfinite(self.server_wait_timeout)
            or self.server_wait_timeout <= 0.0
        ):
            raise ValueError(
                'server_wait_timeout must be finite and '
                'greater than zero'
            )

        goal_bounds = (
            self.minimum_goal_x,
            self.maximum_goal_x,
            self.minimum_goal_y,
            self.maximum_goal_y,
        )

        if not all(
            math.isfinite(value)
            for value in goal_bounds
        ):
            raise ValueError(
                'Navigation goal bounds must be finite'
            )

        if self.minimum_goal_x >= self.maximum_goal_x:
            raise ValueError(
                'minimum_goal_x must be less than '
                'maximum_goal_x'
            )

        if self.minimum_goal_y >= self.maximum_goal_y:
            raise ValueError(
                'minimum_goal_y must be less than '
                'maximum_goal_y'
            )

    def mode_status_callback(
        self,
        message: String,
    ) -> None:
        previous_mode = self.mode_state
        self.mode_state = message.data.strip()

        if (
            previous_mode == 'navigation'
            and self.mode_state != 'navigation'
        ):
            with self.state_lock:
                goal_is_active = (
                    self.goal_request_in_progress
                    or self.active_goal_handle is not None
                )

            if goal_is_active:
                self.get_logger().warning(
                    'Navigation mode stopped while a goal '
                    'was active; requesting cancellation'
                )
                self.request_cancel(
                    reason=(
                        'Navigation mode stopped; '
                        'canceling active goal'
                    ),
                )
            else:
                self.publish_status(
                    state='inactive',
                    message=(
                        'Navigation mode is not active'
                    ),
                )
                self.publish_feedback(
                    state='idle',
                    message=(
                        'No navigation goal is active'
                    ),
                )

        elif (
            self.mode_state == 'navigation'
            and previous_mode != 'navigation'
        ):
            with self.state_lock:
                goal_is_active = (
                    self.goal_request_in_progress
                    or self.active_goal_handle is not None
                )

            if not goal_is_active:
                self.publish_status(
                    state='ready',
                    message=(
                        'Navigation mode is active and '
                        'ready for a goal'
                    ),
                )

    def simulation_status_callback(
        self,
        message: String,
    ) -> None:
        previous_state = self.simulation_state
        self.simulation_state = message.data.strip()

        if (
            previous_state in ('running', 'starting')
            and self.simulation_state
            not in ('running', 'starting')
        ):
            with self.state_lock:
                goal_is_active = (
                    self.goal_request_in_progress
                    or self.active_goal_handle is not None
                )

            if goal_is_active:
                self.get_logger().warning(
                    'Simulation stopped while a navigation '
                    'goal was active; requesting cancellation'
                )
                self.request_cancel(
                    reason=(
                        'Simulation stopped; canceling '
                        'active navigation goal'
                    ),
                )

    def goal_request_callback(
        self,
        message: String,
    ) -> None:
        goal, validation_error = (
            self.parse_goal_request(message.data)
        )

        if validation_error:
            self.publish_status(
                state='invalid_request',
                message=validation_error,
                result='invalid_request',
            )
            return

        if self.simulation_state != 'running':
            self.publish_status(
                state='rejected',
                message=(
                    'Simulation must be running before '
                    'sending a navigation goal'
                ),
                result='rejected',
                goal=goal,
            )
            return

        if self.mode_state != 'navigation':
            self.publish_status(
                state='rejected',
                message=(
                    'Navigation mode must be active before '
                    'sending a navigation goal'
                ),
                result='rejected',
                goal=goal,
            )
            return

        with self.state_lock:
            if (
                self.goal_request_in_progress
                or self.active_goal_handle is not None
            ):
                self.publish_status(
                    state='rejected',
                    message=(
                        'A navigation goal is already active. '
                        'Cancel it before sending another goal.'
                    ),
                    result='rejected',
                    goal=goal,
                )
                return

            self.goal_request_in_progress = True
            self.cancel_requested = False

            self.request_sequence += 1
            request_id = self.request_sequence

            self.current_request_id = request_id
            self.current_goal = goal
            self.last_feedback = {}

        self.publish_status(
            state='waiting_for_server',
            message=(
                'Waiting for NavigateToPose action server'
            ),
            goal=goal,
        )

        server_available = (
            self.action_client.wait_for_server(
                timeout_sec=self.server_wait_timeout
            )
        )

        if not server_available:
            with self.state_lock:
                if self.current_request_id == request_id:
                    self.reset_goal_state_locked()

            self.publish_status(
                state='server_unavailable',
                message=(
                    'NavigateToPose action server is '
                    'unavailable'
                ),
                result='server_unavailable',
                goal=goal,
            )

            self.get_logger().error(
                'NavigateToPose action server unavailable: '
                f'{self.action_name}'
            )
            return

        action_goal = NavigateToPose.Goal()

        action_goal.pose.header.stamp = (
            self.get_clock().now().to_msg()
        )
        action_goal.pose.header.frame_id = self.goal_frame

        action_goal.pose.pose.position.x = goal['x']
        action_goal.pose.pose.position.y = goal['y']
        action_goal.pose.pose.position.z = 0.0

        half_yaw = goal['yaw'] * 0.5

        action_goal.pose.pose.orientation.x = 0.0
        action_goal.pose.pose.orientation.y = 0.0
        action_goal.pose.pose.orientation.z = math.sin(
            half_yaw
        )
        action_goal.pose.pose.orientation.w = math.cos(
            half_yaw
        )

        self.publish_status(
            state='sending',
            message=(
                'Sending navigation goal to Nav2'
            ),
            goal=goal,
        )

        try:
            send_goal_future = (
                self.action_client.send_goal_async(
                    action_goal,
                    feedback_callback=(
                        lambda feedback_message:
                        self.navigation_feedback_callback(
                            request_id,
                            feedback_message,
                        )
                    ),
                )
            )

            send_goal_future.add_done_callback(
                lambda future:
                self.goal_response_callback(
                    request_id,
                    future,
                )
            )

        except Exception as error:
            with self.state_lock:
                if self.current_request_id == request_id:
                    self.reset_goal_state_locked()

            self.publish_status(
                state='aborted',
                message=(
                    'Unable to send navigation goal: '
                    f'{error}'
                ),
                result='aborted',
                goal=goal,
            )

            self.get_logger().exception(
                'Failed to send NavigateToPose goal'
            )

    def parse_goal_request(
        self,
        raw_message: str,
    ) -> tuple[
        Optional[dict[str, float]],
        Optional[str],
    ]:
        try:
            payload = json.loads(raw_message)
        except json.JSONDecodeError:
            return None, (
                'Navigation goal request must be valid JSON'
            )

        if not isinstance(payload, dict):
            return None, (
                'Navigation goal request must be a JSON '
                'object'
            )

        missing_fields = [
            field
            for field in ('x', 'y', 'yaw')
            if field not in payload
        ]

        if missing_fields:
            return None, (
                'Navigation goal request is missing: '
                + ', '.join(missing_fields)
            )

        raw_values = (
            payload['x'],
            payload['y'],
            payload['yaw'],
        )

        if any(
            isinstance(value, bool)
            for value in raw_values
        ):
            return None, (
                'Navigation goal x, y, and yaw must be '
                'numeric values, not booleans'
            )

        try:
            x = float(payload['x'])
            y = float(payload['y'])
            yaw = float(payload['yaw'])
        except (TypeError, ValueError):
            return None, (
                'Navigation goal must contain numeric '
                'x, y, and yaw values'
            )

        if not all(
            math.isfinite(value)
            for value in (x, y, yaw)
        ):
            return None, (
                'Navigation goal values must be finite'
            )

        if not (
            self.minimum_goal_x
            <= x
            <= self.maximum_goal_x
        ):
            return None, (
                'Navigation goal x must be within '
                f'[{self.minimum_goal_x}, '
                f'{self.maximum_goal_x}]'
            )

        if not (
            self.minimum_goal_y
            <= y
            <= self.maximum_goal_y
        ):
            return None, (
                'Navigation goal y must be within '
                f'[{self.minimum_goal_y}, '
                f'{self.maximum_goal_y}]'
            )

        return {
            'x': x,
            'y': y,
            'yaw': yaw,
        }, None

    def goal_response_callback(
        self,
        request_id: int,
        future,
    ) -> None:
        with self.state_lock:
            if self.current_request_id != request_id:
                return

        try:
            goal_handle = future.result()
        except Exception as error:
            with self.state_lock:
                if self.current_request_id == request_id:
                    goal = self.current_goal
                    self.reset_goal_state_locked()
                else:
                    goal = None

            self.publish_status(
                state='aborted',
                message=(
                    'Navigation goal response failed: '
                    f'{error}'
                ),
                result='aborted',
                goal=goal,
            )

            self.get_logger().exception(
                'NavigateToPose goal-response failure'
            )
            return

        if not goal_handle.accepted:
            with self.state_lock:
                if self.current_request_id == request_id:
                    goal = self.current_goal
                    self.reset_goal_state_locked()
                else:
                    goal = None

            self.publish_status(
                state='rejected',
                message=(
                    'NavigateToPose action server rejected '
                    'the goal'
                ),
                result='rejected',
                goal=goal,
            )

            self.publish_feedback(
                state='idle',
                message='Navigation goal was rejected',
            )

            self.get_logger().warning(
                'NavigateToPose goal rejected'
            )
            return

        with self.state_lock:
            if self.current_request_id != request_id:
                return

            self.goal_request_in_progress = False
            self.active_goal_handle = goal_handle

            should_cancel = self.cancel_requested
            goal = self.current_goal

        self.publish_status(
            state='accepted',
            message='Navigation goal accepted by Nav2',
            goal=goal,
        )

        self.publish_feedback(
            state='navigating',
            message='Navigation goal is active',
            goal=goal,
            distance_remaining=None,
            estimated_time_remaining=None,
            navigation_time=None,
            recovery_count=0,
        )

        self.get_logger().info(
            'NavigateToPose goal accepted'
        )

        try:
            result_future = goal_handle.get_result_async()

            result_future.add_done_callback(
                lambda completed_future:
                self.navigation_result_callback(
                    request_id,
                    completed_future,
                )
            )

        except Exception as error:
            with self.state_lock:
                if self.current_request_id == request_id:
                    failed_goal = self.current_goal
                    self.reset_goal_state_locked()
                else:
                    failed_goal = None

            self.publish_status(
                state='aborted',
                message=(
                    'Unable to monitor navigation result: '
                    f'{error}'
                ),
                result='aborted',
                goal=failed_goal,
            )

            self.publish_feedback(
                state='idle',
                message=(
                    'Navigation result monitoring failed'
                ),
            )

            self.get_logger().exception(
                'Failed to monitor NavigateToPose result'
            )
            return

        if should_cancel:
            self.request_cancel(
                reason=(
                    'Cancellation was requested while the '
                    'goal was being accepted'
                ),
            )

    def navigation_feedback_callback(
        self,
        request_id: int,
        feedback_message,
    ) -> None:
        with self.state_lock:
            if self.current_request_id != request_id:
                return

            goal = self.current_goal

        feedback = feedback_message.feedback

        distance_remaining = self.safe_float(
            feedback.distance_remaining
        )

        estimated_time_remaining = (
            self.duration_to_seconds(
                feedback.estimated_time_remaining
            )
        )

        navigation_time = self.duration_to_seconds(
            feedback.navigation_time
        )

        recovery_count = int(
            feedback.number_of_recoveries
        )

        feedback_payload = {
            'distance_remaining': distance_remaining,
            'estimated_time_remaining': (
                estimated_time_remaining
            ),
            'navigation_time': navigation_time,
            'recovery_count': recovery_count,
        }

        with self.state_lock:
            if self.current_request_id != request_id:
                return

            self.last_feedback = feedback_payload

        self.publish_feedback(
            state='navigating',
            message='Navigation is in progress',
            goal=goal,
            **feedback_payload,
        )

    def cancel_request_callback(
        self,
        message: String,
    ) -> None:
        try:
            payload = json.loads(message.data)
        except json.JSONDecodeError:
            self.publish_status(
                state='invalid_request',
                message=(
                    'Navigation cancel request must be '
                    'valid JSON'
                ),
                result='invalid_request',
            )
            return

        if not isinstance(payload, dict):
            self.publish_status(
                state='invalid_request',
                message=(
                    'Navigation cancel request must be a '
                    'JSON object'
                ),
                result='invalid_request',
            )
            return

        if payload.get('cancel') is not True:
            self.publish_status(
                state='invalid_request',
                message=(
                    'Navigation cancel request must contain '
                    '{"cancel": true}'
                ),
                result='invalid_request',
            )
            return

        self.request_cancel(
            reason='Cancel requested by user',
        )

    def request_cancel(
        self,
        reason: str,
    ) -> None:
        with self.state_lock:
            if (
                not self.goal_request_in_progress
                and self.active_goal_handle is None
            ):
                self.publish_status(
                    state='rejected',
                    message=(
                        'There is no active navigation goal '
                        'to cancel'
                    ),
                    result='rejected',
                )
                return

            self.cancel_requested = True
            request_id = self.current_request_id
            goal_handle = self.active_goal_handle
            goal = self.current_goal

        if goal_handle is None:
            self.publish_status(
                state='cancel_pending',
                message=(
                    f'{reason}. The goal is still being '
                    'submitted and will be canceled if '
                    'accepted.'
                ),
                goal=goal,
            )
            return

        self.publish_status(
            state='canceling',
            message=reason,
            goal=goal,
        )

        try:
            cancel_future = (
                goal_handle.cancel_goal_async()
            )

            cancel_future.add_done_callback(
                lambda completed_future:
                self.cancel_response_callback(
                    request_id,
                    completed_future,
                )
            )

        except Exception as error:
            with self.state_lock:
                if self.current_request_id == request_id:
                    self.cancel_requested = False

            self.publish_status(
                state='aborted',
                message=(
                    'Unable to request navigation '
                    f'cancellation: {error}'
                ),
                result='aborted',
                goal=goal,
            )

            self.get_logger().exception(
                'Failed to request navigation cancellation'
            )

    def cancel_response_callback(
        self,
        request_id: Optional[int],
        future,
    ) -> None:
        with self.state_lock:
            if self.current_request_id != request_id:
                return

            goal = self.current_goal

        try:
            cancel_response = future.result()
        except Exception as error:
            with self.state_lock:
                if self.current_request_id != request_id:
                    return

                self.cancel_requested = False

            self.publish_status(
                state='aborted',
                message=(
                    'Navigation cancellation response '
                    f'failed: {error}'
                ),
                result='aborted',
                goal=goal,
            )

            self.get_logger().exception(
                'NavigateToPose cancellation failure'
            )
            return

        goals_canceling = list(
            cancel_response.goals_canceling
        )

        with self.state_lock:
            if self.current_request_id != request_id:
                return

        if goals_canceling:
            self.publish_status(
                state='canceling',
                message=(
                    'Nav2 accepted the cancellation request'
                ),
                goal=goal,
            )
        else:
            with self.state_lock:
                if self.current_request_id != request_id:
                    return

                self.cancel_requested = False

            self.publish_status(
                state='rejected',
                message=(
                    'Nav2 did not accept the cancellation '
                    'request'
                ),
                result='rejected',
                goal=goal,
            )

    def navigation_result_callback(
        self,
        request_id: int,
        future,
    ) -> None:
        with self.state_lock:
            if self.current_request_id != request_id:
                return

            goal = self.current_goal
            feedback = dict(self.last_feedback)

        try:
            wrapped_result = future.result()
            status_code = wrapped_result.status
            result_message = wrapped_result.result

        except Exception as error:
            with self.state_lock:
                if self.current_request_id == request_id:
                    self.reset_goal_state_locked()

            self.publish_status(
                state='aborted',
                message=(
                    'Navigation result failed: '
                    f'{error}'
                ),
                result='aborted',
                goal=goal,
                feedback=feedback,
            )

            self.publish_feedback(
                state='idle',
                message=(
                    'Navigation result could not be read'
                ),
            )

            self.get_logger().exception(
                'NavigateToPose result failure'
            )
            return

        outcome, default_message = (
            self.result_status_to_outcome(status_code)
        )

        nav2_error_code = int(
            getattr(result_message, 'error_code', 0)
        )

        nav2_error_message = str(
            getattr(result_message, 'error_msg', '')
        ).strip()

        final_message = (
            nav2_error_message
            if nav2_error_message
            else default_message
        )

        with self.state_lock:
            if self.current_request_id == request_id:
                self.reset_goal_state_locked()

        self.publish_status(
            state=outcome,
            message=final_message,
            result=outcome,
            goal=goal,
            feedback=feedback,
            nav2_error_code=nav2_error_code,
            nav2_error_message=nav2_error_message,
        )

        self.publish_feedback(
            state='idle',
            message=(
                f'Navigation finished: {outcome}'
            ),
            goal=goal,
            **feedback,
        )

        log_message = (
            f'NavigateToPose finished: {outcome}; '
            f'Nav2 error code={nav2_error_code}'
        )

        if outcome == 'succeeded':
            self.get_logger().info(log_message)
        elif outcome == 'canceled':
            self.get_logger().warning(log_message)
        else:
            self.get_logger().error(log_message)

    @staticmethod
    def result_status_to_outcome(
        status_code: int,
    ) -> tuple[str, str]:
        if status_code == GoalStatus.STATUS_SUCCEEDED:
            return (
                'succeeded',
                'Navigation goal succeeded',
            )

        if status_code == GoalStatus.STATUS_CANCELED:
            return (
                'canceled',
                'Navigation goal was canceled',
            )

        if status_code == GoalStatus.STATUS_ABORTED:
            return (
                'aborted',
                'Navigation goal was aborted',
            )

        return (
            'aborted',
            'Navigation goal ended with unexpected '
            f'action status {status_code}',
        )

    @staticmethod
    def duration_to_seconds(duration_message) -> float:
        return (
            float(duration_message.sec)
            + float(duration_message.nanosec) * 1.0e-9
        )

    @staticmethod
    def safe_float(value: Any) -> Optional[float]:
        try:
            converted = float(value)
        except (TypeError, ValueError):
            return None

        if not math.isfinite(converted):
            return None

        return converted

    def reset_goal_state_locked(self) -> None:
        self.goal_request_in_progress = False
        self.active_goal_handle = None
        self.cancel_requested = False
        self.current_request_id = None
        self.current_goal = None
        self.last_feedback = {}

    def publish_status(
        self,
        state: str,
        message: str,
        result: str = '',
        goal: Optional[dict[str, float]] = None,
        feedback: Optional[dict[str, Any]] = None,
        nav2_error_code: int = 0,
        nav2_error_message: str = '',
    ) -> None:
        payload = {
            'state': state,
            'message': message,
            'result': result,
            'goal_active': self.goal_is_active(),
            'goal': goal,
            'feedback': feedback or {},
            'nav2_error_code': nav2_error_code,
            'nav2_error_message': nav2_error_message,
        }

        ros_message = String()
        ros_message.data = json.dumps(payload)

        if rclpy.ok(context=self.context):
            self.status_publisher.publish(ros_message)

    def publish_feedback(
        self,
        state: str,
        message: str,
        goal: Optional[dict[str, float]] = None,
        distance_remaining: Optional[float] = None,
        estimated_time_remaining: Optional[float] = None,
        navigation_time: Optional[float] = None,
        recovery_count: int = 0,
    ) -> None:
        payload = {
            'state': state,
            'message': message,
            'goal': goal,
            'distance_remaining': distance_remaining,
            'estimated_time_remaining': (
                estimated_time_remaining
            ),
            'navigation_time': navigation_time,
            'recovery_count': recovery_count,
        }

        ros_message = String()
        ros_message.data = json.dumps(payload)

        if rclpy.ok(context=self.context):
            self.feedback_publisher.publish(ros_message)

    def goal_is_active(self) -> bool:
        with self.state_lock:
            return (
                self.goal_request_in_progress
                or self.active_goal_handle is not None
            )

    def prepare_shutdown(self) -> None:
        with self.state_lock:
            if self.shutdown_prepared:
                return

            self.shutdown_prepared = True
            goal_handle = self.active_goal_handle

        if goal_handle is None:
            return

        try:
            goal_handle.cancel_goal_async()
            self.get_logger().info(
                'Requested active navigation goal '
                'cancellation during shutdown'
            )
        except Exception:
            self.get_logger().exception(
                'Unable to cancel navigation goal '
                'during shutdown'
            )
        finally:
            with self.state_lock:
                self.reset_goal_state_locked()


def main(args=None) -> None:
    rclpy.init(args=args)

    node: Optional[NavigationGoalManagerNode] = None

    try:
        node = NavigationGoalManagerNode()
        rclpy.spin(node)

    except (
        KeyboardInterrupt,
        ExternalShutdownException,
    ):
        pass

    finally:
        if node is not None:
            node.prepare_shutdown()
            node.destroy_node()

        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
