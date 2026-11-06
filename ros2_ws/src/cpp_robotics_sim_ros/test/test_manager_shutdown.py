# Copyright 2026 Devansh Mishra
#
# Use of this source code is governed by an MIT-style
# license that can be found in the LICENSE file or at
# https://opensource.org/licenses/MIT.

"""Focused manager shutdown ordering and error propagation tests."""

from pathlib import Path
import sys
import threading
from types import SimpleNamespace

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))

import lifecycle_ros_adapter  # noqa: E402,I100
import navigation_goal_manager_node as navigation  # noqa: E402,I100
import simulation_manager_node as simulation  # noqa: E402,I100
from managed_component import LifecycleState, LifecycleTransition  # noqa: E402,I100
from rclpy.signals import SignalHandlerOptions  # noqa: E402,I100


class FakeLogger:
    def __init__(self, events):
        self.events = events

    def info(self, message):
        self.events.append(('log', message))

    def error(self, message):
        self.events.append(('error', message))


class FakeNode:
    def __init__(self, events, cleanup_result=True, cleanup_error=None,
                 destroy_error=None):
        self.events = events
        self.context = object()
        self.logger = FakeLogger(events)
        self.cleanup_result = cleanup_result
        self.cleanup_error = cleanup_error
        self.destroy_error = destroy_error

    def get_logger(self):
        return self.logger

    def _cleanup(self):
        self.events.append('timer_cancel')
        self.events.append('resource_cleanup')
        if self.cleanup_error:
            raise self.cleanup_error
        return self.cleanup_result

    def shutdown(self):
        return self._cleanup()

    def prepare_shutdown(self):
        return self._cleanup()

    def destroy_node(self):
        self.events.append('destroy_node')
        if self.destroy_error:
            raise self.destroy_error


class FakeExecutor:
    def __init__(self, events, spin_error=None, shutdown_error=None):
        self.events = events
        self.spin_error = spin_error
        self.shutdown_error = shutdown_error

    def add_node(self, _node):
        self.events.append('add_node')

    def spin(self):
        self.events.append('spin')
        raise self.spin_error or KeyboardInterrupt()

    def shutdown(self):
        self.events.append('executor_shutdown')
        if self.shutdown_error:
            raise self.shutdown_error


def _patch_sim(monkeypatch, events, node, spin_error=None, context_ok=True):
    monkeypatch.setattr(simulation, 'SimulationManagerNode', lambda: node)
    monkeypatch.setattr(simulation.rclpy, 'init',
                        lambda **kwargs: events.append(('init', kwargs)))
    if spin_error is None:
        spin_error = KeyboardInterrupt()
    monkeypatch.setattr(simulation.rclpy, 'spin',
                        lambda _node: (_ for _ in ()).throw(spin_error))
    monkeypatch.setattr(simulation.rclpy, 'ok', lambda **kwargs: context_ok)
    monkeypatch.setattr(simulation.rclpy, 'shutdown',
                        lambda **kwargs: events.append('context_shutdown'))


def _patch_nav(monkeypatch, events, node, executor, context_ok=True):
    monkeypatch.setattr(navigation, 'NavigationGoalManagerNode', lambda: node)
    monkeypatch.setattr(navigation.rclpy, 'init',
                        lambda **kwargs: events.append(('init', kwargs)))
    monkeypatch.setattr(navigation.rclpy, 'ok', lambda **kwargs: context_ok)
    monkeypatch.setattr(navigation.rclpy, 'shutdown',
                        lambda **kwargs: events.append('context_shutdown'))
    monkeypatch.setattr('rclpy.executors.MultiThreadedExecutor',
                        lambda num_threads: executor)


def test_simulation_cleanup_success_returns_zero_and_orders_teardown(monkeypatch):
    events = []
    node = FakeNode(events)
    _patch_sim(monkeypatch, events, node)

    assert simulation.main() == 0
    assert events[0][1]['signal_handler_options'] == SignalHandlerOptions.NO
    assert events.index('timer_cancel') < events.index('resource_cleanup')
    assert events.index('resource_cleanup') < events.index('destroy_node')
    assert events.index('destroy_node') < events.index('context_shutdown')


def test_simulation_unsuccessful_cleanup_returns_failure_status(monkeypatch):
    events = []
    node = FakeNode(events, cleanup_result=False)
    _patch_sim(monkeypatch, events, node)

    assert simulation.main() == 1
    assert 'destroy_node' in events and 'context_shutdown' in events


def test_simulation_cleanup_exception_preserves_primary_and_finishes_teardown(
    monkeypatch,
):
    events = []
    original = RuntimeError('simulation cleanup failed')
    node = FakeNode(events, cleanup_error=original,
                    destroy_error=ValueError('secondary destroy failure'))
    _patch_sim(monkeypatch, events, node)
    monkeypatch.setattr(simulation.rclpy, 'shutdown',
                        lambda **kwargs: (_ for _ in ()).throw(
                            LookupError('secondary context failure')))

    with pytest.raises(RuntimeError, match='simulation cleanup failed') as caught:
        simulation.main()
    assert events.index('resource_cleanup') < events.index('destroy_node')
    assert events.index('destroy_node') < len(events)
    assert any('Secondary teardown failure' in note
               for note in getattr(caught.value, '__notes__', []))


def test_simulation_valid_context_publication_failure_does_not_skip_teardown(
    monkeypatch,
):
    events = []
    publication_error = RuntimeError('lifecycle publication failed')
    node = FakeNode(events, cleanup_error=publication_error)
    _patch_sim(monkeypatch, events, node, context_ok=True)

    with pytest.raises(RuntimeError, match='lifecycle publication failed'):
        simulation.main()
    assert events.index('resource_cleanup') < events.index('destroy_node')
    assert events.index('destroy_node') < events.index('context_shutdown')


def test_navigation_cleanup_success_returns_zero_and_orders_teardown(monkeypatch):
    events = []
    node = FakeNode(events)
    executor = FakeExecutor(events)
    _patch_nav(monkeypatch, events, node, executor)

    assert navigation.main() == 0
    assert events[0][1]['signal_handler_options'] == SignalHandlerOptions.NO
    assert events.index('timer_cancel') < events.index('resource_cleanup')
    assert events.index('resource_cleanup') < events.index('executor_shutdown')
    assert events.index('executor_shutdown') < events.index('destroy_node')
    assert events.index('destroy_node') < events.index('context_shutdown')


def test_navigation_unsuccessful_cleanup_returns_failure_status(monkeypatch):
    events = []
    node = FakeNode(events, cleanup_result=False)
    executor = FakeExecutor(events)
    _patch_nav(monkeypatch, events, node, executor)

    assert navigation.main() == 1
    assert events.index('executor_shutdown') < events.index('destroy_node')
    assert 'context_shutdown' in events


def test_navigation_cleanup_exception_preserves_primary_and_finishes_teardown(
    monkeypatch,
):
    events = []
    original = RuntimeError('navigation cleanup failed')
    node = FakeNode(events, cleanup_error=original)
    executor = FakeExecutor(events, shutdown_error=ValueError('secondary executor error'))
    _patch_nav(monkeypatch, events, node, executor)
    monkeypatch.setattr(navigation.rclpy, 'shutdown',
                        lambda **kwargs: events.append('context_shutdown'))

    with pytest.raises(RuntimeError, match='navigation cleanup failed') as caught:
        navigation.main()
    assert events.index('resource_cleanup') < events.index('executor_shutdown')
    assert events.index('executor_shutdown') < events.index('destroy_node')
    assert events.index('destroy_node') < events.index('context_shutdown')
    assert any('Secondary teardown failure' in note
               for note in getattr(caught.value, '__notes__', []))


def test_navigation_cancel_exception_fails_process_and_preserves_goal(
    monkeypatch,
):
    events = []

    class GoalHandle:
        def cancel_goal_async(self):
            events.append('cancel_requested')
            raise RuntimeError('goal cancellation failed')

    class ActiveGoalNode:
        context = object()
        prepare_shutdown = navigation.NavigationGoalManagerNode.prepare_shutdown
        _shutdown_navigation_resources = (
            navigation.NavigationGoalManagerNode._shutdown_navigation_resources
        )
        reset_goal_state_locked = (
            navigation.NavigationGoalManagerNode.reset_goal_state_locked
        )

        def __init__(self):
            self.state_lock = threading.RLock()
            self.shutdown_prepared = False
            self.lifecycle_state_timer = None
            self.goal_request_in_progress = False
            self.active_goal_handle = GoalHandle()
            self.cancel_requested = False
            self.current_request_id = 'goal-1'
            self.current_goal = {'x': 1.0}
            self.last_feedback = {'progress': 0.5}

        def destroy_node(self):
            events.append('destroy_node')

    node = ActiveGoalNode()

    executor = FakeExecutor(events)
    _patch_nav(monkeypatch, events, node, executor)

    with pytest.raises(RuntimeError, match='goal cancellation failed'):
        navigation.main()

    assert events.index('cancel_requested') < events.index('executor_shutdown')
    assert events.index('executor_shutdown') < events.index('destroy_node')
    assert events.index('destroy_node') < events.index('context_shutdown')
    assert node.active_goal_handle is not None
    assert node.current_request_id == 'goal-1'
    assert node.current_goal == {'x': 1.0}
    assert node.last_feedback == {'progress': 0.5}


def test_navigation_valid_context_publication_failure_still_tears_down(monkeypatch):
    events = []
    node = FakeNode(events, cleanup_error=RuntimeError('publisher raise'))
    executor = FakeExecutor(events)
    _patch_nav(monkeypatch, events, node, executor)

    with pytest.raises(RuntimeError, match='publisher raise'):
        navigation.main()
    assert events.index('executor_shutdown') < events.index('destroy_node')
    assert 'context_shutdown' in events


def test_invalid_context_skips_lifecycle_publication_and_exits_cleanly(monkeypatch):
    events = []
    node = FakeNode(events)
    _patch_sim(monkeypatch, events, node, context_ok=False)

    assert simulation.main() == 0
    assert 'context_shutdown' not in events
    assert 'destroy_node' in events


def test_unexpected_spin_exception_remains_failure_after_cleanup(monkeypatch):
    events = []
    node = FakeNode(events)
    _patch_sim(monkeypatch, events, node, spin_error=RuntimeError('unexpected spin'))

    with pytest.raises(RuntimeError, match='unexpected spin'):
        simulation.main()
    assert 'destroy_node' in events and 'context_shutdown' in events


@pytest.mark.parametrize('raises', [False, True], ids=['publishes', 'publisher-fails'])
def test_valid_context_lifecycle_publication_is_enabled_and_errors_propagate(
    monkeypatch, raises,
):
    events = []
    fail_publish = {'enabled': False}

    class Publisher:
        def publish(self, _message):
            events.append('published')
            if raises and fail_publish['enabled']:
                raise RuntimeError('publisher failure')

    class Timer:
        def __init__(self, callback):
            self.callback = callback

        def cancel(self):
            events.append('timer_cancel')

    class NodeFixture:
        context = object()

        def create_publisher(self, *_args):
            return Publisher()

        def create_service(self, *_args):
            return None

        def create_timer(self, _period, callback):
            return Timer(callback)

    node = NodeFixture()
    monkeypatch.setattr(lifecycle_ros_adapter.rclpy, 'ok', lambda **kwargs: True)
    component = lifecycle_ros_adapter.bind_lifecycle(node, 'test', object())
    events.clear()
    result = component.transition(LifecycleTransition.CONFIGURE)
    fail_publish['enabled'] = raises

    if raises:
        with pytest.raises(RuntimeError, match='publisher failure'):
            node.publish_lifecycle_result(result)
        assert events == ['published']
    else:
        node.publish_lifecycle_result(result)
        assert events == ['published', 'published']


def test_manager_methods_cancel_timers_before_resource_lifecycle_cleanup(monkeypatch):
    events = []

    class Timer:
        def cancel(self):
            events.append('timer_cancel')

    class Logger(FakeLogger):
        pass

    result = SimpleNamespace(success=True, reason='ok')
    simulation_node = object.__new__(simulation.SimulationManagerNode)
    simulation_node.shutdown_prepared = False
    simulation_node.monitor_timer = Timer()
    simulation_node.lifecycle_state_timer = Timer()
    simulation_node.lifecycle_component = SimpleNamespace(
        state=LifecycleState.ACTIVE,
        transition=lambda _transition: events.append('resource_cleanup') or result,
    )
    simulation_node._context = object()
    simulation_node.get_logger = lambda: Logger(events)
    simulation_node.publish_lifecycle_result = lambda _result: events.append('publish')
    monkeypatch.setattr(simulation.rclpy, 'ok', lambda **kwargs: True)

    assert simulation_node.shutdown() is True
    assert events.index('timer_cancel') < events.index('resource_cleanup')
    assert events.index('resource_cleanup') < events.index('publish')

    events.clear()
    navigation_node = object.__new__(navigation.NavigationGoalManagerNode)
    navigation_node.shutdown_prepared = False
    navigation_node.lifecycle_state_timer = Timer()
    navigation_node.lifecycle_component = SimpleNamespace(
        state=LifecycleState.ACTIVE,
        transition=lambda _transition: events.append('resource_cleanup') or result,
    )
    navigation_node._context = object()
    navigation_node.get_logger = lambda: Logger(events)
    navigation_node.publish_lifecycle_result = lambda _result: events.append('publish')
    monkeypatch.setattr(navigation.rclpy, 'ok', lambda **kwargs: True)

    assert navigation_node.prepare_shutdown() is True
    assert events.index('timer_cancel') < events.index('resource_cleanup')
    assert events.index('resource_cleanup') < events.index('publish')


def test_invalid_context_skips_adapter_publication(monkeypatch):
    events = []

    class Publisher:
        def publish(self, _message):
            events.append('published')

    class Timer:
        def __init__(self, callback):
            self.callback = callback

    class NodeFixture:
        context = object()

        def create_publisher(self, *_args):
            return Publisher()

        def create_service(self, *_args):
            return None

        def create_timer(self, _period, callback):
            return Timer(callback)

    node = NodeFixture()
    monkeypatch.setattr(lifecycle_ros_adapter.rclpy, 'ok', lambda **kwargs: False)
    component = lifecycle_ros_adapter.bind_lifecycle(node, 'test', object())
    result = component.transition(LifecycleTransition.CONFIGURE)

    node.lifecycle_state_timer.callback()
    assert node.publish_lifecycle_result(result) is None
    assert events == []
