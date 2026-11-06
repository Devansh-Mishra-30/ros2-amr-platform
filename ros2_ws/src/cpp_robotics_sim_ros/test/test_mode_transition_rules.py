#!/usr/bin/env python3
# Copyright 2026 Devansh Mishra
#
# Use of this source code is governed by an MIT-style
# license that can be found in the LICENSE file or at
# https://opensource.org/licenses/MIT.


import importlib.util
from pathlib import Path
import threading
from types import ModuleType, SimpleNamespace


def load_mode_manager_module() -> ModuleType:
    script_path = (
        Path(__file__).resolve().parents[1]
        / 'scripts'
        / 'mode_manager_node.py'
    )

    specification = importlib.util.spec_from_file_location(
        'mode_manager_node',
        script_path,
    )

    if (
        specification is None
        or specification.loader is None
    ):
        raise RuntimeError(
            'Unable to load mode manager module'
        )

    module = importlib.util.module_from_spec(
        specification
    )
    specification.loader.exec_module(module)
    return module


MODULE = load_mode_manager_module()
ModeManagerNode = MODULE.ModeManagerNode
OperatingMode = MODULE.OperatingMode


class FakeLogger:
    def __init__(self) -> None:
        self.messages = []

    def warning(self, message: str) -> None:
        self.messages.append(('warning', message))

    def info(self, message: str) -> None:
        self.messages.append(('info', message))

    def error(self, message: str) -> None:
        self.messages.append(('error', message))


def make_manager(
    *,
    simulation_state: str = 'running',
    mode=OperatingMode.STOPPED,
    selected_map_path: str = '',
    stop_result=(True, 'Operating mode stopped'),
):
    manager = object.__new__(ModeManagerNode)

    manager.process_lock = threading.RLock()
    manager.simulation_state = simulation_state
    manager.mode = mode
    manager.requested_mode = mode

    manager.selected_map_name = (
        'test_map'
        if selected_map_path
        else ''
    )
    manager.selected_map_path = selected_map_path

    manager.last_error = ''
    manager.process = None
    manager.process_group_id = None

    manager.managed_use_sim_time = True
    manager.readiness_timeout = 45.0
    manager.descendant_identity_timeout = 4.0
    manager.shutdown_timeout = 4.0
    manager.kill_timeout = 1.5
    manager.wait_for_mode_readiness = lambda _mode: SimpleNamespace(ready=True)

    manager.launch_package = (
        'cpp_robotics_sim_ros'
    )
    manager.launch_files = {
        OperatingMode.MAPPING:
            'slam_mapping.launch.py',
        OperatingMode.LOCALIZATION:
            'amcl_localization.launch.py',
        OperatingMode.NAVIGATION:
            'nav2_navigation.launch.py',
    }

    logger = FakeLogger()
    published_modes = []
    stop_calls = []

    manager.get_logger = lambda: logger

    def publish_mode(mode_to_publish) -> None:
        published_modes.append(mode_to_publish)
        manager.mode = mode_to_publish

    manager.publish_mode = publish_mode

    def stop_current_mode():
        stop_calls.append(True)
        return stop_result

    manager.stop_current_mode = stop_current_mode

    return (
        manager,
        logger,
        published_modes,
        stop_calls,
    )


def test_rejects_mode_when_simulation_is_stopped() -> None:
    manager, _, published_modes, stop_calls = (
        make_manager(
            simulation_state='stopped'
        )
    )

    success, message = manager.activate_mode(
        OperatingMode.MANUAL
    )

    assert success is False
    assert 'Simulation must be running' in message
    assert published_modes == []
    assert stop_calls == []


def test_localization_requires_selected_map() -> None:
    manager, _, published_modes, stop_calls = (
        make_manager()
    )

    success, message = manager.activate_mode(
        OperatingMode.LOCALIZATION
    )

    assert success is False
    assert 'Select a saved map' in message
    assert 'Localization' in message
    assert published_modes == []
    assert stop_calls == []


def test_navigation_requires_selected_map() -> None:
    manager, _, published_modes, stop_calls = (
        make_manager()
    )

    success, message = manager.activate_mode(
        OperatingMode.NAVIGATION
    )

    assert success is False
    assert 'Select a saved map' in message
    assert 'Navigation' in message
    assert published_modes == []
    assert stop_calls == []


def test_rejects_already_active_mode() -> None:
    manager, _, published_modes, stop_calls = (
        make_manager(
            mode=OperatingMode.MANUAL
        )
    )

    success, message = manager.activate_mode(
        OperatingMode.MANUAL
    )

    assert success is False
    assert 'already active' in message
    assert published_modes == []
    assert stop_calls == []


def test_manual_mode_stops_previous_mode_first() -> None:
    manager, _, published_modes, stop_calls = (
        make_manager(
            mode=OperatingMode.MAPPING
        )
    )

    success, message = manager.activate_mode(
        OperatingMode.MANUAL
    )

    assert success is True
    assert message == 'Manual mode activated'
    assert len(stop_calls) == 1
    assert published_modes == [
        OperatingMode.MANUAL
    ]
    assert manager.requested_mode == (
        OperatingMode.MANUAL
    )


def test_failed_stop_prevents_mode_change() -> None:
    manager, _, published_modes, stop_calls = (
        make_manager(
            mode=OperatingMode.MAPPING,
            stop_result=(
                False,
                'process did not stop',
            ),
        )
    )

    success, message = manager.activate_mode(
        OperatingMode.MANUAL
    )

    assert success is False
    assert 'Unable to stop previous mode' in message
    assert 'process did not stop' in message
    assert len(stop_calls) == 1
    assert published_modes == []


def test_mode_launch_with_missing_readiness_dependency_never_becomes_active(
    monkeypatch,
) -> None:
    manager, _, published_modes, _ = make_manager()
    process = SimpleNamespace(pid=4242, poll=lambda: None)
    record = SimpleNamespace(pgid=4242)
    manager.process_registry = object()
    manager.register_process = lambda *_args: record
    identity_waits = []

    def wait_for_process_record(_registry, _record, **kwargs):
        identity_waits.append({
            'timeout': kwargs['timeout'],
            'should_continue': kwargs['should_continue'](),
        })
        return record

    manager.wait_for_process_record = wait_for_process_record
    manager.terminate_process_record = lambda *_args, **_kwargs: SimpleNamespace(
        success=True, error=''
    )
    manager.persist_shutdown_report = lambda _report: None
    manager.wait_for_mode_readiness = lambda _mode: SimpleNamespace(
        ready=False,
        to_mapping=lambda: {
            'ready': False,
            'blocked_dependencies': ['/scan'],
            'checks': [{'name': '/scan', 'reason': 'no recent messages'}],
        },
    )
    monkeypatch.setattr(MODULE.subprocess, 'Popen',
                        lambda *_args, **_kwargs: process)

    success, message = manager.activate_mode(OperatingMode.MAPPING)

    assert not success
    assert 'no recent messages' in message
    assert process is not None
    assert manager.process is None
    assert OperatingMode.MAPPING not in published_modes
    assert published_modes == [OperatingMode.STARTING, OperatingMode.ERROR]
    assert len(identity_waits) == 1
    assert identity_waits[0]['timeout'] == 4.0
    assert identity_waits[0]['should_continue']


def test_parameter_validation_accepts_valid_values() -> None:
    manager = object.__new__(ModeManagerNode)

    manager.launch_package = ' cpp_robotics_sim_ros '
    manager.launch_files = {
        OperatingMode.MAPPING:
            ' slam_mapping.launch.py ',
        OperatingMode.LOCALIZATION:
            ' amcl_localization.launch.py ',
        OperatingMode.NAVIGATION:
            ' nav2_navigation.launch.py ',
    }
    manager.readiness_timeout = 45.0
    manager.descendant_identity_timeout = 4.0
    manager.shutdown_timeout = 10.0
    manager.kill_timeout = 3.0

    manager.validate_parameters()

    assert manager.launch_package == (
        'cpp_robotics_sim_ros'
    )
    assert manager.launch_files[
        OperatingMode.MAPPING
    ] == 'slam_mapping.launch.py'


def test_parameter_validation_rejects_non_finite_values() -> None:
    invalid_values = (
        float('nan'),
        float('inf'),
        float('-inf'),
    )

    for invalid_value in invalid_values:
        manager = object.__new__(ModeManagerNode)

        manager.launch_package = (
            'cpp_robotics_sim_ros'
        )
        manager.launch_files = {
            OperatingMode.MAPPING:
                'slam_mapping.launch.py',
            OperatingMode.LOCALIZATION:
                'amcl_localization.launch.py',
            OperatingMode.NAVIGATION:
                'nav2_navigation.launch.py',
        }
        manager.readiness_timeout = (
            invalid_value
        )
        manager.descendant_identity_timeout = 4.0
        manager.shutdown_timeout = 10.0
        manager.kill_timeout = 3.0

        try:
            manager.validate_parameters()
        except ValueError:
            continue

        raise AssertionError(
            f'Expected ValueError for {invalid_value}'
        )


def test_parameter_validation_rejects_empty_launch_values() -> None:
    manager = object.__new__(ModeManagerNode)

    manager.launch_package = '   '
    manager.launch_files = {
        OperatingMode.MAPPING:
            'slam_mapping.launch.py',
        OperatingMode.LOCALIZATION:
            'amcl_localization.launch.py',
        OperatingMode.NAVIGATION:
            'nav2_navigation.launch.py',
    }
    manager.readiness_timeout = 45.0
    manager.descendant_identity_timeout = 4.0
    manager.shutdown_timeout = 10.0
    manager.kill_timeout = 3.0

    try:
        manager.validate_parameters()
    except ValueError as error:
        assert 'launch_package' in str(error)
        return

    raise AssertionError(
        'Expected empty launch_package to fail'
    )


def test_parameter_validation_rejects_nonpositive_identity_timeout() -> None:
    manager = object.__new__(ModeManagerNode)
    manager.launch_package = 'cpp_robotics_sim_ros'
    manager.launch_files = {
        OperatingMode.MAPPING: 'slam_mapping.launch.py',
        OperatingMode.LOCALIZATION: 'amcl_localization.launch.py',
        OperatingMode.NAVIGATION: 'nav2_navigation.launch.py',
    }
    manager.readiness_timeout = 45.0
    manager.descendant_identity_timeout = 0.0
    manager.shutdown_timeout = 4.0
    manager.kill_timeout = 1.5

    try:
        manager.validate_parameters()
    except ValueError as error:
        assert 'descendant_identity_timeout' in str(error)
        return

    raise AssertionError('Expected nonpositive identity timeout to fail')


def test_selected_map_callback_accepts_object_payload() -> None:
    manager = object.__new__(ModeManagerNode)

    manager.selected_map_name = ''
    manager.selected_map_path = ''

    logger = FakeLogger()
    manager.get_logger = lambda: logger

    message = MODULE.String()
    message.data = (
        '{"name": " warehouse ", '
        '"yaml_path": " /tmp/warehouse.yaml "}'
    )

    manager.selected_map_callback(message)

    assert manager.selected_map_name == 'warehouse'
    assert manager.selected_map_path == (
        '/tmp/warehouse.yaml'
    )
    assert logger.messages == []


def test_selected_map_callback_rejects_non_object_payload() -> None:
    manager = object.__new__(ModeManagerNode)

    manager.selected_map_name = 'existing'
    manager.selected_map_path = (
        '/tmp/existing.yaml'
    )

    logger = FakeLogger()
    manager.get_logger = lambda: logger

    message = MODULE.String()
    message.data = '["not", "an", "object"]'

    manager.selected_map_callback(message)

    assert manager.selected_map_name == 'existing'
    assert manager.selected_map_path == (
        '/tmp/existing.yaml'
    )
    assert logger.messages == [
        (
            'error',
            'Selected-map payload must be a JSON object',
        )
    ]


def test_selected_map_callback_rejects_invalid_json() -> None:
    manager = object.__new__(ModeManagerNode)

    manager.selected_map_name = 'existing'
    manager.selected_map_path = (
        '/tmp/existing.yaml'
    )

    logger = FakeLogger()
    manager.get_logger = lambda: logger

    message = MODULE.String()
    message.data = '{invalid json'

    manager.selected_map_callback(message)

    assert manager.selected_map_name == 'existing'
    assert manager.selected_map_path == (
        '/tmp/existing.yaml'
    )
    assert logger.messages == [
        (
            'error',
            'Received invalid selected-map payload',
        )
    ]


def test_shutdown_is_idempotent(monkeypatch) -> None:
    manager = object.__new__(ModeManagerNode)

    manager._context = object()
    manager.shutdown_complete = False

    stop_calls = []
    manager.stop_current_mode = lambda: (
        stop_calls.append(True)
        or (True, 'Operating mode stopped')
    )

    monkeypatch.setattr(
        MODULE.rclpy,
        'ok',
        lambda context=None: False,
    )

    manager.shutdown()
    manager.shutdown()

    assert manager.shutdown_complete is True
    assert len(stop_calls) == 1


class FakeProcess:
    """Provide controllable process state for manager tests."""

    def __init__(
        self,
        *,
        pid: int = 1234,
        return_code=None,
    ) -> None:
        """Initialize the fake process."""
        self.pid = pid
        self.returncode = return_code

    def poll(self):
        """Return the configured process result."""
        return self.returncode


def make_process_monitor_manager(
    *,
    process_return_code,
    mode=OperatingMode.NAVIGATION,
    requested_mode=OperatingMode.NAVIGATION,
):
    """Create a manager configured for process-monitor tests."""
    manager = object.__new__(ModeManagerNode)

    manager.process_lock = threading.RLock()
    manager.process = FakeProcess(
        return_code=process_return_code,
    )
    manager.process_group_id = 4321
    manager.process_record = SimpleNamespace(
        instance_id='mode-test', pgid=4321, component='mode_navigation'
    )
    deregistered = []
    manager.process_registry = SimpleNamespace(
        deregister=lambda instance_id: deregistered.append(instance_id),
    )
    manager.mode = mode
    manager.requested_mode = requested_mode
    manager.last_error = ''
    manager.last_shutdown_report = None
    manager.persist_shutdown_report = lambda _report: None
    manager.shutdown_timeout = 4.0
    manager.kill_timeout = 1.5
    manager.release_exited_process_record = lambda _registry, _record: True

    logger = FakeLogger()
    manager.get_logger = lambda: logger

    published_modes = []

    def publish_mode(mode_to_publish) -> None:
        published_modes.append(mode_to_publish)
        manager.mode = mode_to_publish

    terminated_groups = []

    manager.publish_mode = publish_mode
    manager.terminate_process_group = (
        lambda process_group_id:
            terminated_groups.append(
                process_group_id
            )
    )

    return (
        manager,
        logger,
        published_modes,
        terminated_groups,
    )


def test_monitor_process_ignores_running_process() -> None:
    """Keep manager state unchanged while process is running."""
    (
        manager,
        logger,
        published_modes,
        terminated_groups,
    ) = make_process_monitor_manager(
        process_return_code=None,
    )

    manager.monitor_process()

    assert manager.process is not None
    assert manager.process_group_id == 4321
    assert published_modes == []
    assert terminated_groups == []
    assert logger.messages == []


def test_monitor_process_reports_unexpected_exit(
    monkeypatch,
) -> None:
    """Report an unexpected managed-process exit."""
    (
        manager,
        logger,
        published_modes,
        terminated_groups,
    ) = make_process_monitor_manager(
        process_return_code=7,
    )

    manager._context = object()

    monkeypatch.setattr(
        MODULE.rclpy,
        'ok',
        lambda context=None: True,
    )

    manager.monitor_process()

    assert manager.process is None
    assert manager.process_group_id is None
    assert terminated_groups == []
    assert published_modes == [
        OperatingMode.ERROR
    ]
    assert manager.last_error == (
        'navigation mode exited unexpectedly '
        'with return code 7'
    )
    assert logger.messages == [
        (
            'error',
            manager.last_error,
        )
    ]


def test_monitor_process_accepts_expected_stop() -> None:
    """Convert an expected stopping-process exit to stopped."""
    (
        manager,
        logger,
        published_modes,
        terminated_groups,
    ) = make_process_monitor_manager(
        process_return_code=0,
        mode=OperatingMode.STOPPING,
    )

    manager.monitor_process()

    assert manager.process is None
    assert manager.process_group_id is None
    assert terminated_groups == []
    assert published_modes == [
        OperatingMode.STOPPED
    ]
    assert manager.last_error == ''
    assert logger.messages == []


def test_clear_finished_process_cleans_process_group() -> None:
    """Clear a completed process and terminate its remaining group."""
    manager = object.__new__(ModeManagerNode)

    manager.process = FakeProcess(
        return_code=0,
    )
    manager.process_group_id = 6789
    manager.process_record = SimpleNamespace(
        instance_id='mode-test', pgid=6789, component='mode_mapping'
    )
    manager.process_registry = SimpleNamespace(deregister=lambda _value: True)
    manager.release_exited_process_record = lambda _registry, _record: True

    terminated_groups = []
    manager.terminate_process_group = (
        lambda process_group_id:
            terminated_groups.append(
                process_group_id
            )
    )

    manager.clear_finished_process()

    assert manager.process is None
    assert manager.process_group_id is None
    assert terminated_groups == []


def test_clear_finished_process_preserves_running_process() -> None:
    """Preserve manager state while its process remains active."""
    manager = object.__new__(ModeManagerNode)

    process = FakeProcess(
        return_code=None,
    )
    manager.process = process
    manager.process_group_id = 6789
    manager.process_record = SimpleNamespace(instance_id='mode-test')

    terminated_groups = []
    manager.terminate_process_group = (
        lambda process_group_id:
            terminated_groups.append(
                process_group_id
            )
    )

    manager.clear_finished_process()

    assert manager.process is process
    assert manager.process_group_id == 6789
    assert terminated_groups == []


def test_reset_runtime_state_restores_stopped_baseline() -> None:
    manager = object.__new__(ModeManagerNode)
    manager.process = FakeProcess(return_code=None)
    manager.process_group_id = 6789
    manager.process_record = SimpleNamespace(instance_id='mode-test')
    manager.mode = OperatingMode.NAVIGATION
    manager.requested_mode = OperatingMode.NAVIGATION
    manager.last_error = 'transient mode error'
    published_modes = []
    manager.publish_mode = lambda mode: (
        published_modes.append(mode),
        setattr(manager, 'mode', mode),
    )[-1]

    manager.reset_runtime_state()

    assert manager.process is None
    assert manager.process_group_id is None
    assert manager.process_record is None
    assert manager.requested_mode == OperatingMode.STOPPED
    assert manager.mode == OperatingMode.STOPPED
    assert manager.last_error == ''
    assert published_modes == [OperatingMode.STOPPED]


def test_stop_current_mode_refreshes_descendants_before_termination(
    monkeypatch,
) -> None:
    """Persist late same-session children before signaling a live mode."""
    manager = object.__new__(ModeManagerNode)
    process = FakeProcess(return_code=None)
    original = SimpleNamespace(
        instance_id='mode-test',
        pgid=6789,
        component='mode_navigation',
    )
    refreshed = SimpleNamespace(
        instance_id='mode-test',
        pgid=6789,
        component='mode_navigation',
        member_identities=('late-nav2-child',),
    )
    manager.process_lock = threading.RLock()
    manager.process = process
    manager.process_group_id = 6789
    manager.process_record = original
    manager.process_registry = object()
    manager.process_is_running = lambda: True
    manager.shutdown_timeout = 4.0
    manager.kill_timeout = 1.5
    manager._context = object()
    manager.requested_mode = OperatingMode.NAVIGATION
    manager.last_error = ''
    manager.last_shutdown_report = None
    manager.get_logger = lambda: FakeLogger()
    manager.cleanup_orphan_scan_frame_bridges = lambda: None
    manager.persist_shutdown_report = lambda _report: None

    published_modes = []
    manager.publish_mode = lambda mode: published_modes.append(mode)
    refresh_calls = []
    terminate_calls = []

    def refresh_process_record(registry, record):
        refresh_calls.append((registry, record))
        return refreshed

    def terminate_process_record(registry, record, **kwargs):
        terminate_calls.append((registry, record, kwargs))
        return SimpleNamespace(success=True, error='')

    manager.refresh_process_record = refresh_process_record
    manager.terminate_process_record = terminate_process_record

    monkeypatch.setattr(
        MODULE.rclpy,
        'ok',
        lambda context=None: True,
    )

    success, message = manager.stop_current_mode()

    assert success is True
    assert message == 'Operating mode stopped'
    assert refresh_calls == [(manager.process_registry, original)]
    assert terminate_calls[0][0:2] == (
        manager.process_registry,
        refreshed,
    )
    assert terminate_calls[0][2]['process'] is process
    assert manager.process is None
    assert manager.process_record is None
    assert published_modes == [
        OperatingMode.STOPPING,
        OperatingMode.STOPPED,
    ]


def test_stop_current_mode_refuses_signal_when_refresh_fails(
    monkeypatch,
) -> None:
    """Keep the live owner intact when descendant persistence is unsafe."""
    manager = object.__new__(ModeManagerNode)
    original = SimpleNamespace(
        instance_id='mode-test',
        pgid=6789,
        component='mode_navigation',
    )
    manager.process_lock = threading.RLock()
    manager.process = FakeProcess(return_code=None)
    manager.process_group_id = 6789
    manager.process_record = original
    manager.process_registry = object()
    manager.process_is_running = lambda: True
    manager.shutdown_timeout = 4.0
    manager.kill_timeout = 1.5
    manager._context = object()
    manager.requested_mode = OperatingMode.NAVIGATION
    manager.last_error = ''
    manager.get_logger = lambda: FakeLogger()
    manager.publish_mode = lambda mode: setattr(manager, 'mode', mode)
    manager.refresh_process_record = lambda *_args: (
        (_ for _ in ()).throw(RuntimeError('leader changed'))
    )
    terminate_calls = []
    manager.terminate_process_record = lambda *_args, **_kwargs: (
        terminate_calls.append(True)
    )

    monkeypatch.setattr(
        MODULE.rclpy,
        'ok',
        lambda context=None: True,
    )

    success, message = manager.stop_current_mode()

    assert success is False
    assert message == (
        'Failed to refresh mode descendant identities: leader changed'
    )
    assert terminate_calls == []
    assert manager.process_record is original
    assert manager.process is not None
    assert manager.requested_mode == OperatingMode.ERROR
    assert manager.mode == OperatingMode.ERROR


def test_terminate_process_group_returns_true_when_absent() -> None:
    """Treat an already absent process group as successfully stopped."""
    manager = object.__new__(ModeManagerNode)

    manager.process_group_exists = (
        lambda process_group_id: False
    )

    assert manager.terminate_process_group(1234) is True


def test_terminate_process_group_confirms_sigterm_exit(
    monkeypatch,
) -> None:
    """Delegate termination only for the matching ownership record."""
    manager = object.__new__(ModeManagerNode)
    manager.process_record = SimpleNamespace(pgid=1234)
    manager.process_registry = object()
    manager.process = None
    manager.shutdown_timeout = 10.0
    manager.kill_timeout = 0.2
    calls = []
    manager.terminate_process_record = lambda *args, **kwargs: (
        calls.append((args, kwargs))
        or SimpleNamespace(success=True)
    )

    result = manager.terminate_process_group(1234)

    assert result is True
    assert len(calls) == 1
    assert manager.process_record is None


def test_terminate_process_group_reports_sigkill_survivor(
    monkeypatch,
) -> None:
    """Preserve ownership when identity-safe termination reports failure."""
    manager = object.__new__(ModeManagerNode)
    record = SimpleNamespace(pgid=1234)
    manager.process_record = record
    manager.process_registry = object()
    manager.process = None
    manager.shutdown_timeout = 10.0
    manager.kill_timeout = 0.0
    manager.terminate_process_record = lambda *args, **kwargs: SimpleNamespace(
        success=False
    )

    result = manager.terminate_process_group(1234)

    assert result is False
    assert manager.process_record is record
