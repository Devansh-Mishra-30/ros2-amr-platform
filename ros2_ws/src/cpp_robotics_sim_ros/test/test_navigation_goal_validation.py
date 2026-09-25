#!/usr/bin/env python3
# Copyright 2026 Devansh Mishra
#
# Use of this source code is governed by an MIT-style
# license that can be found in the LICENSE file or at
# https://opensource.org/licenses/MIT.


import importlib.util
import json
import math
from pathlib import Path
import threading
from types import ModuleType


def load_navigation_manager_module() -> ModuleType:
    script_path = (
        Path(__file__).resolve().parents[1]
        / 'scripts'
        / 'navigation_goal_manager_node.py'
    )

    specification = importlib.util.spec_from_file_location(
        'navigation_goal_manager_node',
        script_path,
    )

    if (
        specification is None
        or specification.loader is None
    ):
        raise RuntimeError(
            'Unable to load navigation goal manager module'
        )

    module = importlib.util.module_from_spec(
        specification
    )
    specification.loader.exec_module(module)
    return module


MODULE = load_navigation_manager_module()
NavigationGoalManagerNode = (
    MODULE.NavigationGoalManagerNode
)


def parse_request(raw_request: str):
    node = object.__new__(NavigationGoalManagerNode)
    node.minimum_goal_x = -9.5
    node.maximum_goal_x = 9.5
    node.minimum_goal_y = -7.5
    node.maximum_goal_y = 7.5
    return node.parse_goal_request(raw_request)


def test_accepts_valid_navigation_goal() -> None:
    goal, error = parse_request(
        json.dumps(
            {
                'x': 1.25,
                'y': -2.5,
                'yaw': math.pi / 2.0,
            }
        )
    )

    assert error is None
    assert goal == {
        'x': 1.25,
        'y': -2.5,
        'yaw': math.pi / 2.0,
    }


def test_rejects_malformed_json() -> None:
    goal, error = parse_request(
        '{"x": 1.0, "y": 2.0,'
    )

    assert goal is None
    assert error is not None
    assert 'valid JSON' in error


def test_rejects_non_object_json() -> None:
    goal, error = parse_request(
        json.dumps([1.0, 2.0, 3.0])
    )

    assert goal is None
    assert error is not None
    assert 'JSON object' in error


def test_rejects_missing_fields() -> None:
    goal, error = parse_request(
        json.dumps(
            {
                'x': 1.0,
                'y': 2.0,
            }
        )
    )

    assert goal is None
    assert error is not None
    assert 'yaw' in error


def test_rejects_boolean_values() -> None:
    goal, error = parse_request(
        json.dumps(
            {
                'x': True,
                'y': 2.0,
                'yaw': 0.0,
            }
        )
    )

    assert goal is None
    assert error is not None
    assert 'booleans' in error


def test_rejects_non_numeric_values() -> None:
    goal, error = parse_request(
        json.dumps(
            {
                'x': 'not-a-number',
                'y': 2.0,
                'yaw': 0.0,
            }
        )
    )

    assert goal is None
    assert error is not None
    assert 'numeric' in error


def test_rejects_nan() -> None:
    goal, error = parse_request(
        json.dumps(
            {
                'x': float('nan'),
                'y': 2.0,
                'yaw': 0.0,
            }
        )
    )

    assert goal is None
    assert error is not None
    assert 'finite' in error


def test_rejects_positive_infinity() -> None:
    goal, error = parse_request(
        json.dumps(
            {
                'x': 1.0,
                'y': float('inf'),
                'yaw': 0.0,
            }
        )
    )

    assert goal is None
    assert error is not None
    assert 'finite' in error


def test_rejects_negative_infinity() -> None:
    goal, error = parse_request(
        json.dumps(
            {
                'x': 1.0,
                'y': 2.0,
                'yaw': float('-inf'),
            }
        )
    )

    assert goal is None
    assert error is not None
    assert 'finite' in error


def test_accepts_goal_on_coordinate_boundaries() -> None:
    goal, error = parse_request(
        json.dumps(
            {
                'x': 9.5,
                'y': -7.5,
                'yaw': 0.0,
            }
        )
    )

    assert error is None
    assert goal is not None


def test_rejects_x_below_minimum() -> None:
    goal, error = parse_request(
        json.dumps(
            {
                'x': -9.5001,
                'y': 0.0,
                'yaw': 0.0,
            }
        )
    )

    assert goal is None
    assert error is not None
    assert 'goal x' in error


def test_rejects_x_above_maximum() -> None:
    goal, error = parse_request(
        json.dumps(
            {
                'x': 9.5001,
                'y': 0.0,
                'yaw': 0.0,
            }
        )
    )

    assert goal is None
    assert error is not None
    assert 'goal x' in error


def test_rejects_y_below_minimum() -> None:
    goal, error = parse_request(
        json.dumps(
            {
                'x': 0.0,
                'y': -7.5001,
                'yaw': 0.0,
            }
        )
    )

    assert goal is None
    assert error is not None
    assert 'goal y' in error


def test_rejects_y_above_maximum() -> None:
    goal, error = parse_request(
        json.dumps(
            {
                'x': 0.0,
                'y': 7.5001,
                'yaw': 0.0,
            }
        )
    )

    assert goal is None
    assert error is not None
    assert 'goal y' in error


def make_parameter_validation_node():
    node = object.__new__(NavigationGoalManagerNode)
    node.action_name = '/navigate_to_pose'
    node.goal_frame = 'map'
    node.server_wait_timeout = 2.0
    node.minimum_goal_x = -9.5
    node.maximum_goal_x = 9.5
    node.minimum_goal_y = -7.5
    node.maximum_goal_y = 7.5
    return node


def test_parameter_validation_accepts_valid_configuration() -> None:
    node = make_parameter_validation_node()

    node.validate_parameters()


def test_parameter_validation_rejects_whitespace_action_name() -> None:
    node = make_parameter_validation_node()
    node.action_name = '   '

    try:
        node.validate_parameters()
    except ValueError as error:
        assert 'action_name' in str(error)
    else:
        raise AssertionError(
            'Whitespace-only action_name should be rejected'
        )


def test_parameter_validation_rejects_whitespace_goal_frame() -> None:
    node = make_parameter_validation_node()
    node.goal_frame = '   '

    try:
        node.validate_parameters()
    except ValueError as error:
        assert 'goal_frame' in str(error)
    else:
        raise AssertionError(
            'Whitespace-only goal_frame should be rejected'
        )


def test_parameter_validation_rejects_nan_server_timeout() -> None:
    node = make_parameter_validation_node()
    node.server_wait_timeout = float('nan')

    try:
        node.validate_parameters()
    except ValueError as error:
        assert 'server_wait_timeout' in str(error)
    else:
        raise AssertionError(
            'NaN server_wait_timeout should be rejected'
        )


def test_parameter_validation_rejects_infinite_server_timeout() -> None:
    node = make_parameter_validation_node()
    node.server_wait_timeout = float('inf')

    try:
        node.validate_parameters()
    except ValueError as error:
        assert 'server_wait_timeout' in str(error)
    else:
        raise AssertionError(
            'Infinite server_wait_timeout should be rejected'
        )


def test_parameter_validation_rejects_reversed_x_bounds() -> None:
    node = make_parameter_validation_node()
    node.minimum_goal_x = 5.0
    node.maximum_goal_x = -5.0

    try:
        node.validate_parameters()
    except ValueError as error:
        assert 'minimum_goal_x' in str(error)
    else:
        raise AssertionError(
            'Reversed x-coordinate bounds should be rejected'
        )


def test_parameter_validation_rejects_equal_y_bounds() -> None:
    node = make_parameter_validation_node()
    node.minimum_goal_y = 4.0
    node.maximum_goal_y = 4.0

    try:
        node.validate_parameters()
    except ValueError as error:
        assert 'minimum_goal_y' in str(error)
    else:
        raise AssertionError(
            'Equal y-coordinate bounds should be rejected'
        )


def test_parameter_validation_rejects_nonfinite_goal_bound() -> None:
    node = make_parameter_validation_node()
    node.maximum_goal_y = float('-inf')

    try:
        node.validate_parameters()
    except ValueError as error:
        assert 'finite' in str(error)
    else:
        raise AssertionError(
            'Non-finite navigation bounds should be rejected'
        )


class RecordingLogger:
    def __init__(self) -> None:
        self.messages = []

    def info(self, message: str) -> None:
        self.messages.append(('info', message))

    def warning(self, message: str) -> None:
        self.messages.append(('warning', message))

    def error(self, message: str) -> None:
        self.messages.append(('error', message))

    def exception(self, message: str) -> None:
        self.messages.append(('exception', message))


class CompletedFuture:
    def __init__(self, result=None, error=None) -> None:
        self._result = result
        self._error = error

    def result(self):
        if self._error is not None:
            raise self._error

        return self._result


class ResultFuture:
    def __init__(self) -> None:
        self.callback = None

    def add_done_callback(self, callback) -> None:
        self.callback = callback


class AcceptedGoalHandle:
    accepted = True

    def __init__(self, result_future=None, result_error=None) -> None:
        self.result_future = result_future
        self.result_error = result_error

    def get_result_async(self):
        if self.result_error is not None:
            raise self.result_error

        return self.result_future


def make_goal_response_node():
    node = object.__new__(NavigationGoalManagerNode)
    node.state_lock = threading.RLock()
    node.goal_request_in_progress = True
    node.active_goal_handle = None
    node.cancel_requested = False
    node.current_request_id = 7
    node.current_goal = {
        'x': 1.0,
        'y': 2.0,
        'yaw': 0.5,
    }
    node.last_feedback = {}

    node.status_messages = []
    node.feedback_messages = []
    node.test_logger = RecordingLogger()

    node.publish_status = (
        lambda **payload: node.status_messages.append(payload)
    )
    node.publish_feedback = (
        lambda **payload: node.feedback_messages.append(payload)
    )
    node.get_logger = lambda: node.test_logger
    return node


def test_goal_response_ignores_stale_request() -> None:
    node = make_goal_response_node()
    stale_future = CompletedFuture(
        error=AssertionError(
            'Stale future result must not be accessed'
        )
    )

    node.goal_response_callback(6, stale_future)

    assert node.current_request_id == 7
    assert node.goal_request_in_progress is True
    assert node.active_goal_handle is None
    assert node.status_messages == []
    assert node.feedback_messages == []


def test_goal_response_registers_result_callback() -> None:
    node = make_goal_response_node()
    result_future = ResultFuture()
    goal_handle = AcceptedGoalHandle(
        result_future=result_future
    )

    node.goal_response_callback(
        7,
        CompletedFuture(result=goal_handle),
    )

    assert node.goal_request_in_progress is False
    assert node.active_goal_handle is goal_handle
    assert result_future.callback is not None
    assert node.status_messages[-1]['state'] == 'accepted'
    assert node.feedback_messages[-1]['state'] == 'navigating'


def test_goal_response_handles_result_future_creation_failure() -> None:
    node = make_goal_response_node()
    goal_handle = AcceptedGoalHandle(
        result_error=RuntimeError(
            'Unable to create result future'
        )
    )

    node.goal_response_callback(
        7,
        CompletedFuture(result=goal_handle),
    )

    assert node.goal_request_in_progress is False
    assert node.active_goal_handle is None
    assert node.current_request_id is None
    assert node.current_goal is None
    assert node.status_messages[-1]['state'] == 'aborted'
    assert node.status_messages[-1]['result'] == 'aborted'
    assert node.feedback_messages[-1]['state'] == 'idle'


class CancelGoalHandle:
    def __init__(
        self,
        cancel_future=None,
        cancel_error=None,
    ) -> None:
        self.cancel_future = cancel_future
        self.cancel_error = cancel_error

    def cancel_goal_async(self):
        if self.cancel_error is not None:
            raise self.cancel_error

        return self.cancel_future


class CancelResponse:
    def __init__(self, goals_canceling) -> None:
        self.goals_canceling = goals_canceling


def make_cancellation_node():
    node = make_goal_response_node()
    node.goal_request_in_progress = False
    node.cancel_requested = False
    return node


def test_request_cancel_registers_response_callback() -> None:
    node = make_cancellation_node()
    cancel_future = ResultFuture()
    goal_handle = CancelGoalHandle(cancel_future)
    node.active_goal_handle = goal_handle

    node.request_cancel(reason='Cancel requested by test')

    assert node.cancel_requested is True
    assert cancel_future.callback is not None
    assert node.status_messages[-1]['state'] == 'canceling'


def test_stale_cancel_response_is_ignored() -> None:
    node = make_cancellation_node()
    cancel_future = ResultFuture()
    goal_handle = CancelGoalHandle(cancel_future)
    node.active_goal_handle = goal_handle

    node.request_cancel(reason='Cancel old goal')

    callback = cancel_future.callback
    assert callback is not None

    node.current_request_id = 8
    node.current_goal = {
        'x': 8.0,
        'y': 1.0,
        'yaw': 0.0,
    }
    status_count_before_response = len(node.status_messages)

    callback(
        CompletedFuture(
            result=CancelResponse(
                goals_canceling=[object()]
            )
        )
    )

    assert len(node.status_messages) == status_count_before_response


def test_cancel_dispatch_failure_clears_pending_flag() -> None:
    node = make_cancellation_node()
    goal_handle = CancelGoalHandle(
        cancel_error=RuntimeError(
            'Unable to dispatch cancellation'
        )
    )
    node.active_goal_handle = goal_handle

    node.request_cancel(reason='Cancel requested by test')

    assert node.active_goal_handle is goal_handle
    assert node.current_request_id == 7
    assert node.current_goal == {
        'x': 1.0,
        'y': 2.0,
        'yaw': 0.5,
    }
    assert node.cancel_requested is False
    assert node.status_messages[-1]['state'] == 'aborted'
    assert node.status_messages[-1]['result'] == 'aborted'


def test_cancel_response_failure_clears_pending_flag() -> None:
    node = make_cancellation_node()
    cancel_future = ResultFuture()
    goal_handle = CancelGoalHandle(cancel_future)
    node.active_goal_handle = goal_handle

    node.request_cancel(reason='Cancel requested by test')

    callback = cancel_future.callback
    assert callback is not None
    assert node.cancel_requested is True

    callback(
        CompletedFuture(
            error=RuntimeError(
                'Cancellation response unavailable'
            )
        )
    )

    assert node.active_goal_handle is goal_handle
    assert node.current_request_id == 7
    assert node.current_goal == {
        'x': 1.0,
        'y': 2.0,
        'yaw': 0.5,
    }
    assert node.cancel_requested is False
    assert node.status_messages[-1]['state'] == 'aborted'
    assert node.status_messages[-1]['result'] == 'aborted'


def test_cancel_rejection_clears_pending_flag() -> None:
    node = make_cancellation_node()
    cancel_future = ResultFuture()
    goal_handle = CancelGoalHandle(cancel_future)
    node.active_goal_handle = goal_handle

    node.request_cancel(reason='Cancel requested by test')

    callback = cancel_future.callback
    assert callback is not None
    assert node.cancel_requested is True

    callback(
        CompletedFuture(
            result=CancelResponse(
                goals_canceling=[]
            )
        )
    )

    assert node.active_goal_handle is goal_handle
    assert node.current_request_id == 7
    assert node.current_goal == {
        'x': 1.0,
        'y': 2.0,
        'yaw': 0.5,
    }
    assert node.cancel_requested is False
    assert node.status_messages[-1]['state'] == 'rejected'
    assert node.status_messages[-1]['result'] == 'rejected'


class NavigationResultMessage:
    def __init__(
        self,
        error_code=0,
        error_msg='',
    ) -> None:
        self.error_code = error_code
        self.error_msg = error_msg


class WrappedNavigationResult:
    def __init__(
        self,
        status,
        result=None,
    ) -> None:
        self.status = status
        self.result = (
            result
            if result is not None
            else NavigationResultMessage()
        )


def make_navigation_result_node():
    node = make_goal_response_node()
    node.goal_request_in_progress = False
    node.active_goal_handle = object()
    node.last_feedback = {
        'distance_remaining': 1.5,
        'estimated_time_remaining': 4.0,
        'navigation_time': 2.0,
        'recovery_count': 1,
    }
    return node


def test_navigation_result_ignores_stale_request() -> None:
    node = make_navigation_result_node()
    stale_future = CompletedFuture(
        error=AssertionError(
            'Stale result future must not be accessed'
        )
    )

    node.navigation_result_callback(6, stale_future)

    assert node.current_request_id == 7
    assert node.active_goal_handle is not None
    assert node.status_messages == []
    assert node.feedback_messages == []


def test_navigation_result_maps_success_and_resets_state() -> None:
    node = make_navigation_result_node()

    node.navigation_result_callback(
        7,
        CompletedFuture(
            result=WrappedNavigationResult(
                status=MODULE.GoalStatus.STATUS_SUCCEEDED,
            )
        ),
    )

    assert node.current_request_id is None
    assert node.current_goal is None
    assert node.active_goal_handle is None
    assert node.cancel_requested is False
    assert node.status_messages[-1]['state'] == 'succeeded'
    assert node.status_messages[-1]['result'] == 'succeeded'
    assert node.feedback_messages[-1]['state'] == 'idle'


def test_navigation_result_maps_canceled() -> None:
    node = make_navigation_result_node()

    node.navigation_result_callback(
        7,
        CompletedFuture(
            result=WrappedNavigationResult(
                status=MODULE.GoalStatus.STATUS_CANCELED,
            )
        ),
    )

    assert node.status_messages[-1]['state'] == 'canceled'
    assert node.status_messages[-1]['result'] == 'canceled'


def test_navigation_result_uses_nav2_error_message() -> None:
    node = make_navigation_result_node()

    node.navigation_result_callback(
        7,
        CompletedFuture(
            result=WrappedNavigationResult(
                status=MODULE.GoalStatus.STATUS_ABORTED,
                result=NavigationResultMessage(
                    error_code=42,
                    error_msg='  Planner failed  ',
                ),
            )
        ),
    )

    assert node.status_messages[-1]['state'] == 'aborted'
    assert node.status_messages[-1]['message'] == 'Planner failed'
    assert node.status_messages[-1]['nav2_error_code'] == 42
    assert (
        node.status_messages[-1]['nav2_error_message']
        == 'Planner failed'
    )


def test_navigation_result_failure_resets_state() -> None:
    node = make_navigation_result_node()

    node.navigation_result_callback(
        7,
        CompletedFuture(
            error=RuntimeError(
                'Unable to read navigation result'
            )
        ),
    )

    assert node.current_request_id is None
    assert node.current_goal is None
    assert node.active_goal_handle is None
    assert node.cancel_requested is False
    assert node.status_messages[-1]['state'] == 'aborted'
    assert node.status_messages[-1]['result'] == 'aborted'
    assert node.feedback_messages[-1]['state'] == 'idle'


def test_unexpected_navigation_status_maps_to_aborted() -> None:
    outcome, message = (
        NavigationGoalManagerNode.result_status_to_outcome(
            999
        )
    )

    assert outcome == 'aborted'
    assert 'unexpected action status 999' in message


class DurationMessage:
    def __init__(
        self,
        sec=0,
        nanosec=0,
    ) -> None:
        self.sec = sec
        self.nanosec = nanosec


class NavigationFeedback:
    def __init__(
        self,
        distance_remaining=2.5,
        estimated_time_remaining=None,
        navigation_time=None,
        number_of_recoveries=0,
    ) -> None:
        self.distance_remaining = distance_remaining
        self.estimated_time_remaining = (
            estimated_time_remaining
            if estimated_time_remaining is not None
            else DurationMessage()
        )
        self.navigation_time = (
            navigation_time
            if navigation_time is not None
            else DurationMessage()
        )
        self.number_of_recoveries = number_of_recoveries


class NavigationFeedbackMessage:
    def __init__(self, feedback) -> None:
        self.feedback = feedback


def make_navigation_feedback_node():
    node = make_goal_response_node()
    node.goal_request_in_progress = False
    node.active_goal_handle = object()
    return node


def test_navigation_feedback_ignores_stale_request() -> None:
    node = make_navigation_feedback_node()
    feedback_message = NavigationFeedbackMessage(
        NavigationFeedback()
    )

    node.navigation_feedback_callback(
        6,
        feedback_message,
    )

    assert node.last_feedback == {}
    assert node.feedback_messages == []


def test_navigation_feedback_publishes_finite_values() -> None:
    node = make_navigation_feedback_node()
    feedback_message = NavigationFeedbackMessage(
        NavigationFeedback(
            distance_remaining=3.25,
            estimated_time_remaining=DurationMessage(
                sec=4,
                nanosec=500_000_000,
            ),
            navigation_time=DurationMessage(
                sec=2,
                nanosec=250_000_000,
            ),
            number_of_recoveries=2,
        )
    )

    node.navigation_feedback_callback(
        7,
        feedback_message,
    )

    assert node.last_feedback == {
        'distance_remaining': 3.25,
        'estimated_time_remaining': 4.5,
        'navigation_time': 2.25,
        'recovery_count': 2,
    }
    assert node.feedback_messages[-1]['state'] == 'navigating'
    assert node.feedback_messages[-1]['distance_remaining'] == 3.25
    assert (
        node.feedback_messages[-1]['estimated_time_remaining']
        == 4.5
    )
    assert node.feedback_messages[-1]['navigation_time'] == 2.25
    assert node.feedback_messages[-1]['recovery_count'] == 2


def test_navigation_feedback_sanitizes_nonfinite_distance() -> None:
    node = make_navigation_feedback_node()
    feedback_message = NavigationFeedbackMessage(
        NavigationFeedback(
            distance_remaining=float('nan'),
        )
    )

    node.navigation_feedback_callback(
        7,
        feedback_message,
    )

    assert node.last_feedback['distance_remaining'] is None
    assert (
        node.feedback_messages[-1]['distance_remaining']
        is None
    )


def test_safe_float_rejects_non_numeric_and_nonfinite_values() -> None:
    assert NavigationGoalManagerNode.safe_float(
        'not-a-number'
    ) is None
    assert NavigationGoalManagerNode.safe_float(
        float('inf')
    ) is None
    assert NavigationGoalManagerNode.safe_float(
        float('-inf')
    ) is None
    assert NavigationGoalManagerNode.safe_float(
        float('nan')
    ) is None


def test_safe_float_accepts_finite_numeric_value() -> None:
    assert NavigationGoalManagerNode.safe_float(
        '2.75'
    ) == 2.75


def test_duration_to_seconds_converts_nanoseconds() -> None:
    seconds = NavigationGoalManagerNode.duration_to_seconds(
        DurationMessage(
            sec=3,
            nanosec=125_000_000,
        )
    )

    assert seconds == 3.125


class ShutdownGoalHandle:
    def __init__(self, cancel_error=None) -> None:
        self.cancel_error = cancel_error
        self.cancel_call_count = 0

    def cancel_goal_async(self):
        self.cancel_call_count += 1

        if self.cancel_error is not None:
            raise self.cancel_error

        return ResultFuture()


def make_shutdown_node():
    node = make_goal_response_node()
    node.goal_request_in_progress = False
    node.active_goal_handle = None
    node.shutdown_prepared = False
    return node


def test_prepare_shutdown_without_active_goal_is_noop() -> None:
    node = make_shutdown_node()

    node.prepare_shutdown()

    assert node.active_goal_handle is None
    assert node.test_logger.messages == []


def test_prepare_shutdown_requests_active_goal_cancellation() -> None:
    node = make_shutdown_node()
    goal_handle = ShutdownGoalHandle()
    node.active_goal_handle = goal_handle

    node.prepare_shutdown()

    assert goal_handle.cancel_call_count == 1
    assert (
        'info',
        'Requested active navigation goal cancellation during shutdown',
    ) in node.test_logger.messages


def test_prepare_shutdown_handles_cancellation_failure() -> None:
    node = make_shutdown_node()
    goal_handle = ShutdownGoalHandle(
        cancel_error=RuntimeError(
            'Shutdown cancellation failed'
        )
    )
    node.active_goal_handle = goal_handle

    node.prepare_shutdown()

    assert goal_handle.cancel_call_count == 1
    assert (
        'exception',
        'Unable to cancel navigation goal during shutdown',
    ) in node.test_logger.messages
    assert node.goal_request_in_progress is False
    assert node.active_goal_handle is None
    assert node.cancel_requested is False
    assert node.current_request_id is None
    assert node.current_goal is None
    assert node.last_feedback == {}


def test_prepare_shutdown_is_idempotent() -> None:
    node = make_shutdown_node()
    goal_handle = ShutdownGoalHandle()
    node.active_goal_handle = goal_handle

    node.prepare_shutdown()
    node.prepare_shutdown()

    assert goal_handle.cancel_call_count == 1


def test_prepare_shutdown_resets_goal_runtime_state() -> None:
    node = make_shutdown_node()
    goal_handle = ShutdownGoalHandle()
    node.active_goal_handle = goal_handle
    node.cancel_requested = True
    node.current_request_id = 7
    node.current_goal = {'x': 1.0, 'y': 2.0, 'yaw': 0.5}
    node.last_feedback = {'distance_remaining': 1.25}

    node.prepare_shutdown()

    assert node.shutdown_prepared is True
    assert node.goal_request_in_progress is False
    assert node.active_goal_handle is None
    assert node.cancel_requested is False
    assert node.current_request_id is None
    assert node.current_goal is None
    assert node.last_feedback == {}
