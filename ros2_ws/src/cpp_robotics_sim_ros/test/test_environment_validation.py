#!/usr/bin/env python3
# Copyright 2026 Devansh Mishra
#
# Use of this source code is governed by an MIT-style
# license that can be found in the LICENSE file or at
# https://opensource.org/licenses/MIT.


import importlib.util
from pathlib import Path
import signal
import threading
from types import ModuleType, SimpleNamespace

import pytest
from std_msgs.msg import String


def load_simulation_manager_module() -> ModuleType:
    script_path = (
        Path(__file__).resolve().parents[1]
        / 'scripts'
        / 'simulation_manager_node.py'
    )

    specification = importlib.util.spec_from_file_location(
        'simulation_manager_node',
        script_path,
    )

    if (
        specification is None
        or specification.loader is None
    ):
        raise RuntimeError(
            'Unable to load simulation manager module'
        )

    module = importlib.util.module_from_spec(
        specification
    )
    specification.loader.exec_module(module)
    return module


MODULE = load_simulation_manager_module()
SimulationManagerNode = MODULE.SimulationManagerNode
SimulationState = MODULE.SimulationState


def make_manager(
    *,
    state=SimulationState.STOPPED,
    process_running: bool = False,
):
    manager = object.__new__(SimulationManagerNode)

    manager.environment_names = [
        'warehouse',
        'hospital',
    ]
    manager.selected_environment = 'warehouse'
    manager.state = state
    manager.process_lock = threading.RLock()

    published_statuses = []
    log_messages = []

    manager.publish_environment_status = (
        lambda *, state, message:
        published_statuses.append(
            {
                'state': state,
                'message': message,
            }
        )
    )

    manager.process_is_running = (
        lambda: process_running
    )

    class Logger:
        def info(self, message: str) -> None:
            log_messages.append(message)

    manager.get_logger = lambda: Logger()

    return manager, published_statuses, log_messages


def environment_message(value: str) -> String:
    message = String()
    message.data = value
    return message


@pytest.mark.parametrize(
    'requested_environment',
    [
        'warehouse',
        'hospital',
        ' Warehouse ',
        'HOSPITAL',
    ],
)
def test_accepts_allowlisted_environments(
    requested_environment: str,
) -> None:
    manager, statuses, _ = make_manager()

    manager.environment_request_callback(
        environment_message(requested_environment)
    )

    assert manager.selected_environment == (
        requested_environment.strip().lower()
    )
    assert statuses[-1]['state'] == 'selected'


@pytest.mark.parametrize(
    'requested_environment',
    [
        '',
        ' ',
        'office',
        'warehouse/../hospital',
        '../warehouse',
        '../../tmp',
        'warehouse;rm',
        'warehouse map',
    ],
)
def test_rejects_unsupported_environments(
    requested_environment: str,
) -> None:
    manager, statuses, _ = make_manager()

    manager.environment_request_callback(
        environment_message(requested_environment)
    )

    assert manager.selected_environment == 'warehouse'
    assert statuses[-1]['state'] == (
        'invalid_request'
    )


@pytest.mark.parametrize(
    'state',
    [
        SimulationState.STARTING,
        SimulationState.RUNNING,
        SimulationState.STOPPING,
    ],
)
def test_rejects_environment_change_while_busy(
    state,
) -> None:
    manager, statuses, _ = make_manager(
        state=state
    )

    manager.environment_request_callback(
        environment_message('hospital')
    )

    assert manager.selected_environment == 'warehouse'
    assert statuses[-1]['state'] == 'locked'


def test_rejects_environment_change_when_process_runs() -> None:
    manager, statuses, _ = make_manager(
        state=SimulationState.STOPPED,
        process_running=True,
    )

    manager.environment_request_callback(
        environment_message('hospital')
    )

    assert manager.selected_environment == 'warehouse'
    assert statuses[-1]['state'] == 'locked'


def test_allows_change_after_simulation_stops() -> None:
    manager, statuses, _ = make_manager(
        state=SimulationState.STOPPED,
        process_running=False,
    )

    manager.environment_request_callback(
        environment_message('hospital')
    )

    assert manager.selected_environment == 'hospital'
    assert statuses[-1]['state'] == 'selected'


def make_parameter_validation_manager():
    manager = object.__new__(
        SimulationManagerNode
    )

    manager.launch_package = 'cpp_robotics_sim_ros'
    manager.launch_file = (
        'interactive_control.launch.py'
    )

    manager.environment_names = [
        'warehouse',
        'hospital',
    ]
    manager.selected_environment = 'warehouse'

    manager.environment_world_files = {
        'warehouse': 'warehouse_world.sdf',
        'hospital': 'hospital_world.sdf',
    }

    manager.startup_grace_period = 4.0
    manager.shutdown_timeout = 10.0
    manager.kill_timeout = 3.0

    return manager


def test_parameter_validation_accepts_valid_values() -> None:
    manager = make_parameter_validation_manager()

    manager.validate_parameters()


@pytest.mark.parametrize(
    ('attribute', 'value'),
    [
        ('startup_grace_period', float('nan')),
        ('startup_grace_period', float('inf')),
        ('shutdown_timeout', float('nan')),
        ('shutdown_timeout', float('inf')),
        ('kill_timeout', float('nan')),
        ('kill_timeout', float('inf')),
    ],
)
def test_parameter_validation_rejects_nonfinite_timeouts(
    attribute: str,
    value: float,
) -> None:
    manager = make_parameter_validation_manager()
    setattr(manager, attribute, value)

    with pytest.raises(
        ValueError,
        match=attribute,
    ):
        manager.validate_parameters()


@pytest.mark.parametrize(
    ('attribute', 'value'),
    [
        ('launch_package', ''),
        ('launch_package', '   '),
        ('launch_file', ''),
        ('launch_file', '   '),
    ],
)
def test_parameter_validation_rejects_empty_launch_values(
    attribute: str,
    value: str,
) -> None:
    manager = make_parameter_validation_manager()
    setattr(manager, attribute, value)

    with pytest.raises(
        ValueError,
        match=attribute,
    ):
        manager.validate_parameters()


def test_parameter_validation_rejects_empty_environment_name() -> None:
    manager = make_parameter_validation_manager()
    manager.environment_names = [
        'warehouse',
        '   ',
    ]
    manager.environment_world_files = {
        'warehouse': 'warehouse_world.sdf',
        '   ': 'hospital_world.sdf',
    }

    with pytest.raises(
        ValueError,
        match='environment_names',
    ):
        manager.validate_parameters()


def test_parameter_validation_rejects_duplicate_environments() -> None:
    manager = make_parameter_validation_manager()
    manager.environment_names = [
        'warehouse',
        'warehouse',
    ]

    with pytest.raises(
        ValueError,
        match='unique',
    ):
        manager.validate_parameters()


@pytest.mark.parametrize(
    'world_filename',
    [
        '',
        '   ',
    ],
)
def test_parameter_validation_rejects_empty_world_filename(
    world_filename: str,
) -> None:
    manager = make_parameter_validation_manager()
    manager.environment_world_files[
        'warehouse'
    ] = world_filename

    with pytest.raises(
        ValueError,
        match='World filename',
    ):
        manager.validate_parameters()


def test_parameter_validation_rejects_negative_startup_period() -> None:
    manager = make_parameter_validation_manager()
    manager.startup_grace_period = -0.1

    with pytest.raises(
        ValueError,
        match='startup_grace_period',
    ):
        manager.validate_parameters()


@pytest.mark.parametrize(
    'attribute',
    [
        'shutdown_timeout',
        'kill_timeout',
    ],
)
def test_parameter_validation_rejects_zero_timeout(
    attribute: str,
) -> None:
    manager = make_parameter_validation_manager()
    setattr(manager, attribute, 0.0)

    with pytest.raises(
        ValueError,
        match=attribute,
    ):
        manager.validate_parameters()


class RecordingPublisher:
    def __init__(self) -> None:
        self.messages = []

    def publish(self, message) -> None:
        self.messages.append(message)


def make_world_path_manager(
    package_share_directory: Path,
):
    manager = object.__new__(
        SimulationManagerNode
    )

    manager.package_share_directory = str(
        package_share_directory
    )
    manager.selected_environment = 'warehouse'
    manager.environment_world_files = {
        'warehouse': 'warehouse_world.sdf',
        'hospital': 'hospital_world.sdf',
    }

    return manager


def test_resolve_selected_world_path_returns_existing_file(
    tmp_path: Path,
) -> None:
    worlds_directory = tmp_path / 'worlds'
    worlds_directory.mkdir()

    expected_world = (
        worlds_directory / 'warehouse_world.sdf'
    )
    expected_world.write_text('<sdf />\n')

    manager = make_world_path_manager(tmp_path)

    resolved_path = manager.resolve_selected_world_path()

    assert resolved_path == str(expected_world)


def test_resolve_selected_world_path_rejects_unknown_environment(
    tmp_path: Path,
) -> None:
    manager = make_world_path_manager(tmp_path)
    manager.selected_environment = 'office'

    with pytest.raises(KeyError):
        manager.resolve_selected_world_path()


def test_resolve_selected_world_path_rejects_missing_file(
    tmp_path: Path,
) -> None:
    manager = make_world_path_manager(tmp_path)

    with pytest.raises(
        FileNotFoundError,
        match='World file does not exist',
    ):
        manager.resolve_selected_world_path()


def make_environment_publisher_manager(
    *,
    state=SimulationState.STOPPED,
    process_running: bool = False,
):
    manager = object.__new__(
        SimulationManagerNode
    )

    manager.selected_environment = 'warehouse'
    manager.environment_names = [
        'warehouse',
        'hospital',
    ]
    manager.environment_world_files = {
        'warehouse': 'warehouse_world.sdf',
        'hospital': 'hospital_world.sdf',
    }
    manager.state = state
    manager.environment_status_publisher = (
        RecordingPublisher()
    )
    manager._context = object()
    manager.process_is_running = (
        lambda: process_running
    )

    return manager


def published_environment_payload(manager):
    assert (
        len(
            manager.environment_status_publisher.messages
        )
        == 1
    )

    return MODULE.json.loads(
        manager.environment_status_publisher.messages[
            0
        ].data
    )


def test_publish_environment_status_reports_unlocked_selection(
    monkeypatch,
) -> None:
    manager = make_environment_publisher_manager()

    monkeypatch.setattr(
        MODULE.rclpy,
        'ok',
        lambda **kwargs: True,
    )

    manager.publish_environment_status(
        state='selected',
        message='Selected environment: warehouse',
    )

    payload = published_environment_payload(
        manager
    )

    assert payload == {
        'state': 'selected',
        'message': 'Selected environment: warehouse',
        'selected_environment': 'warehouse',
        'available_environments': [
            'warehouse',
            'hospital',
        ],
        'world_file': 'warehouse_world.sdf',
        'selection_locked': False,
    }


@pytest.mark.parametrize(
    'state',
    [
        SimulationState.STARTING,
        SimulationState.RUNNING,
        SimulationState.STOPPING,
    ],
)
def test_publish_environment_status_locks_busy_states(
    state,
    monkeypatch,
) -> None:
    manager = make_environment_publisher_manager(
        state=state
    )

    monkeypatch.setattr(
        MODULE.rclpy,
        'ok',
        lambda **kwargs: True,
    )

    manager.publish_environment_status(
        state='status',
        message='test',
    )

    payload = published_environment_payload(
        manager
    )

    assert payload['selection_locked'] is True


def test_publish_environment_status_unlocks_error_without_process(
    monkeypatch,
) -> None:
    manager = make_environment_publisher_manager(
        state=SimulationState.ERROR,
        process_running=False,
    )

    monkeypatch.setattr(
        MODULE.rclpy,
        'ok',
        lambda **kwargs: True,
    )

    manager.publish_environment_status(
        state='error',
        message='Simulation exited unexpectedly',
    )

    payload = published_environment_payload(
        manager
    )

    assert payload['state'] == 'error'
    assert payload['selection_locked'] is False


def test_publish_environment_status_locks_running_process(
    monkeypatch,
) -> None:
    manager = make_environment_publisher_manager(
        state=SimulationState.STOPPED,
        process_running=True,
    )

    monkeypatch.setattr(
        MODULE.rclpy,
        'ok',
        lambda **kwargs: True,
    )

    manager.publish_environment_status(
        state='status',
        message='test',
    )

    payload = published_environment_payload(
        manager
    )

    assert payload['selection_locked'] is True


def test_publish_environment_status_skips_after_shutdown(
    monkeypatch,
) -> None:
    manager = make_environment_publisher_manager()

    monkeypatch.setattr(
        MODULE.rclpy,
        'ok',
        lambda **kwargs: False,
    )

    manager.publish_environment_status(
        state='status',
        message='test',
    )

    assert (
        manager.environment_status_publisher.messages
        == []
    )


class ProcessStub:
    def __init__(
        self,
        *,
        pid: int = 4242,
        poll_result=None,
        returncode=None,
    ) -> None:
        self.pid = pid
        self.poll_result = poll_result
        self.returncode = returncode

    def poll(self):
        return self.poll_result


def make_start_manager():
    manager = object.__new__(
        SimulationManagerNode
    )

    manager.process = None
    manager.process_record = None
    manager.process_registry = SimpleNamespace(
        deregister=lambda _instance_id: True,
    )
    manager.register_process = lambda registry, process, component: SimpleNamespace(
        instance_id='simulation-test', pid=process.pid,
        pgid=process.pid, component=component,
    )
    manager.release_exited_process_record = lambda _registry, _record: True
    manager.refresh_process_record = lambda _registry, record: record
    manager.persist_shutdown_report = lambda _report: None
    manager.process_lock = threading.RLock()
    manager.state = SimulationState.STOPPED
    manager.last_error = ''
    manager.shutdown_prepared = False
    manager.stop_in_progress = False
    manager.publish_emergency_stop = lambda _enabled: None

    manager.launch_package = 'cpp_robotics_sim_ros'
    manager.launch_file = (
        'interactive_control.launch.py'
    )
    manager.managed_use_sim_time = True
    manager.selected_environment = 'warehouse'
    manager.startup_grace_period = 4.0
    manager.shutdown_timeout = 4.0
    manager.kill_timeout = 1.5

    manager.states = []
    manager.environment_statuses = []
    manager.logs = []

    manager.process_is_running = lambda: (
        manager.process is not None
        and manager.process.poll() is None
    )

    manager.clear_finished_process = lambda: None

    manager.set_state = lambda state: (
        manager.states.append(state),
        setattr(manager, 'state', state),
    )[-1]

    manager.publish_environment_status = (
        lambda *, state, message:
        manager.environment_statuses.append(
            {
                'state': state,
                'message': message,
            }
        )
    )

    class Logger:
        def info(self, message: str) -> None:
            manager.logs.append(
                ('info', message)
            )

        def warning(self, message: str) -> None:
            manager.logs.append(
                ('warning', message)
            )

        def error(self, message: str) -> None:
            manager.logs.append(
                ('error', message)
            )

    manager.get_logger = lambda: Logger()

    return manager


def test_start_simulation_rejects_running_process() -> None:
    manager = make_start_manager()
    manager.process = ProcessStub(
        poll_result=None
    )

    success, message = manager.start_simulation()

    assert success is False
    assert message == 'Simulation is already running'
    assert manager.states == []
    assert manager.process is not None


def test_start_simulation_handles_missing_world() -> None:
    manager = make_start_manager()

    manager.resolve_selected_world_path = lambda: (
        (_ for _ in ()).throw(
            FileNotFoundError(
                'World file does not exist'
            )
        )
    )

    success, message = manager.start_simulation()

    assert success is False
    assert 'World file does not exist' in message
    assert manager.process is None
    assert manager.state == SimulationState.ERROR
    assert manager.last_error == message
    assert manager.states == [
        SimulationState.STARTING,
        SimulationState.ERROR,
    ]
    assert (
        manager.environment_statuses[-1]['state']
        == 'error'
    )


def test_start_simulation_builds_expected_command(
    monkeypatch,
) -> None:
    manager = make_start_manager()
    manager.resolve_selected_world_path = (
        lambda: '/tmp/warehouse_world.sdf'
    )

    recorded = {}

    def fake_popen(
        command,
        *,
        start_new_session,
    ):
        recorded['command'] = command
        recorded['start_new_session'] = (
            start_new_session
        )
        return ProcessStub(
            pid=4242,
            poll_result=None,
        )

    monkeypatch.setattr(
        MODULE.subprocess,
        'Popen',
        fake_popen,
    )
    monkeypatch.setattr(
        MODULE.time,
        'sleep',
        lambda duration: recorded.setdefault(
            'sleep',
            duration,
        ),
    )

    success, message = manager.start_simulation()

    assert success is True
    assert message == (
        'Simulation started with PID 4242'
    )
    assert recorded['command'] == [
        'ros2',
        'launch',
        'cpp_robotics_sim_ros',
        'interactive_control.launch.py',
        'world:=/tmp/warehouse_world.sdf',
        'use_sim_time:=true',
    ]
    assert recorded['start_new_session'] is True
    assert recorded['sleep'] == 4.0
    assert manager.state == SimulationState.RUNNING
    assert manager.states == [
        SimulationState.STARTING,
        SimulationState.RUNNING,
    ]
    assert (
        manager.environment_statuses[-1]['state']
        == 'running'
    )


def test_start_simulation_uses_false_sim_time_argument(
    monkeypatch,
) -> None:
    manager = make_start_manager()
    manager.managed_use_sim_time = False
    manager.resolve_selected_world_path = (
        lambda: '/tmp/hospital_world.sdf'
    )

    recorded_command = []

    def fake_popen(
        command,
        *,
        start_new_session,
    ):
        del start_new_session
        recorded_command.extend(command)
        return ProcessStub(
            poll_result=None
        )

    monkeypatch.setattr(
        MODULE.subprocess,
        'Popen',
        fake_popen,
    )
    monkeypatch.setattr(
        MODULE.time,
        'sleep',
        lambda duration: None,
    )

    success, _ = manager.start_simulation()

    assert success is True
    assert 'use_sim_time:=false' in recorded_command


def test_start_simulation_handles_process_launch_failure(
    monkeypatch,
) -> None:
    manager = make_start_manager()
    manager.resolve_selected_world_path = (
        lambda: '/tmp/warehouse_world.sdf'
    )

    def raise_os_error(*args, **kwargs):
        raise OSError(
            'ros2 executable unavailable'
        )

    monkeypatch.setattr(
        MODULE.subprocess,
        'Popen',
        raise_os_error,
    )

    success, message = manager.start_simulation()

    assert success is False
    assert 'Failed to start simulation' in message
    assert 'ros2 executable unavailable' in message
    assert manager.process is None
    assert manager.state == SimulationState.ERROR
    assert manager.last_error == (
        'ros2 executable unavailable'
    )


def test_start_simulation_detects_early_exit(
    monkeypatch,
) -> None:
    manager = make_start_manager()
    manager.resolve_selected_world_path = (
        lambda: '/tmp/warehouse_world.sdf'
    )

    process = ProcessStub(
        pid=4242,
        poll_result=7,
        returncode=7,
    )

    monkeypatch.setattr(
        MODULE.subprocess,
        'Popen',
        lambda *args, **kwargs: process,
    )
    monkeypatch.setattr(
        MODULE.time,
        'sleep',
        lambda duration: None,
    )

    success, message = manager.start_simulation()

    assert success is False
    assert 'exited during startup' in message
    assert 'return code 7' in message
    assert manager.process is None
    assert manager.state == SimulationState.ERROR
    assert manager.states == [
        SimulationState.STARTING,
        SimulationState.ERROR,
    ]


class StopProcessStub:
    def __init__(
        self,
        *,
        pid: int = 4242,
        wait_results=None,
        poll_result=None,
    ) -> None:
        self.pid = pid
        self.wait_results = list(
            wait_results or [0]
        )
        self.poll_result = poll_result
        self.wait_calls = []

    def poll(self):
        return self.poll_result

    def wait(self, *, timeout):
        self.wait_calls.append(timeout)

        if not self.wait_results:
            return 0

        result = self.wait_results.pop(0)

        if isinstance(result, BaseException):
            raise result

        return result


def make_stop_manager(
    process=None,
):
    manager = object.__new__(
        SimulationManagerNode
    )

    manager.process = process
    manager.process_record = (
        SimpleNamespace(
            instance_id='simulation-test', pid=process.pid,
            pgid=process.pid, component='simulation_launch',
        ) if process is not None else None
    )
    manager.process_registry = SimpleNamespace(
        reconcile_stale_records=lambda: [],
        list_records=lambda: [],
        refresh_group_members=lambda record: record,
    )
    manager.process_lock = threading.RLock()
    manager.state = SimulationState.RUNNING
    manager.selected_environment = 'hospital'
    manager.last_error = ''
    manager.shutdown_timeout = 10.0
    manager.kill_timeout = 3.0
    manager._context = object()

    manager.states = []
    manager.environment_statuses = []
    manager.logs = []
    manager.cleanup_calls = 0
    manager.stop_in_progress = False
    manager.last_shutdown_report = None
    manager.publish_navigation_cancel = lambda: None
    manager.publish_emergency_stop = lambda _enabled: None
    manager.wait_for_modes_stopped = lambda _timeout: True
    manager.persist_shutdown_report = lambda _report: None

    def terminate_process_record(registry, record, **kwargs):
        del registry
        for signal_value, timeout in (
            (signal.SIGINT, kwargs['sigint_timeout']),
            (signal.SIGTERM, kwargs['sigterm_timeout']),
            (signal.SIGKILL, kwargs['sigkill_timeout']),
        ):
            try:
                MODULE.os.killpg(record.pgid, signal_value)
                process.wait(timeout=timeout)
                return MODULE.ShutdownResult(
                    True, record.component, record.pid, record.pgid, 0.0,
                    signal_result='exited',
                )
            except MODULE.subprocess.TimeoutExpired:
                continue
            except ProcessLookupError:
                return MODULE.ShutdownResult(
                    True, record.component, record.pid, record.pgid, 0.0,
                    signal_result='already_exited',
                )
            except OSError as error:
                return MODULE.ShutdownResult(
                    False, record.component, record.pid, record.pgid, 0.0,
                    error=str(error),
                )
        return MODULE.ShutdownResult(
            False, record.component, record.pid, record.pgid, 0.0,
            failed_stage='SIGKILL_WAIT', error='SIGKILL timeout',
        )

    manager.terminate_process_record = terminate_process_record

    manager.process_is_running = lambda: (
        manager.process is not None
        and manager.process.poll() is None
    )

    manager.clear_finished_process = lambda: (
        setattr(manager, 'process', None)
        if (
            manager.process is not None
            and manager.process.poll() is not None
        )
        else None
    )

    manager.cleanup_remaining_processes = lambda: setattr(
        manager,
        'cleanup_calls',
        manager.cleanup_calls + 1,
    )

    manager.set_state = lambda state: (
        manager.states.append(state),
        setattr(manager, 'state', state),
    )[-1]

    manager.publish_environment_status = (
        lambda *, state, message:
        manager.environment_statuses.append(
            {
                'state': state,
                'message': message,
            }
        )
    )

    class Logger:
        def info(self, message: str) -> None:
            manager.logs.append(
                ('info', message)
            )

        def warning(self, message: str) -> None:
            manager.logs.append(
                ('warning', message)
            )

        def error(self, message: str) -> None:
            manager.logs.append(
                ('error', message)
            )

    manager.get_logger = lambda: Logger()

    return manager


def test_stop_simulation_handles_already_stopped(
    monkeypatch,
) -> None:
    manager = make_stop_manager(
        process=None
    )

    monkeypatch.setattr(
        MODULE.rclpy,
        'ok',
        lambda **kwargs: True,
    )

    success, message = manager.stop_simulation()

    assert success is True
    assert message == 'Simulation is already stopped'
    assert manager.process is None
    assert manager.state == SimulationState.STOPPED
    assert manager.states == [
        SimulationState.STOPPED,
    ]
    assert manager.cleanup_calls == 1


def test_stop_simulation_stops_with_sigint(
    monkeypatch,
) -> None:
    process = StopProcessStub(
        wait_results=[0],
        poll_result=None,
    )
    manager = make_stop_manager(process)

    sent_signals = []

    monkeypatch.setattr(
        MODULE.os,
        'getpgid',
        lambda process_id: process_id,
    )
    monkeypatch.setattr(
        MODULE.os,
        'killpg',
        lambda process_group, signal_value:
        sent_signals.append(
            (process_group, signal_value)
        ),
    )
    monkeypatch.setattr(
        MODULE.rclpy,
        'ok',
        lambda **kwargs: True,
    )

    success, message = manager.stop_simulation()

    assert success is True
    assert message == 'Simulation stopped successfully'
    assert sent_signals == [
        (4242, signal.SIGINT),
    ]
    assert process.wait_calls == [10.0]
    assert manager.process is None
    assert manager.state == SimulationState.STOPPED
    assert manager.states == [
        SimulationState.STOPPING,
        SimulationState.STOPPED,
    ]
    assert manager.cleanup_calls == 1
    assert (
        manager.environment_statuses[-1]['state']
        == 'selected'
    )


def test_stop_simulation_resets_runtime_state_preserving_environment(
    monkeypatch,
) -> None:
    process = StopProcessStub(
        wait_results=[0],
        poll_result=None,
    )
    manager = make_stop_manager(process)
    manager.last_error = 'transient stop error'
    manager.stop_in_progress = True
    manager.shutdown_prepared = False

    monkeypatch.setattr(
        MODULE.os,
        'getpgid',
        lambda process_id: process_id,
    )
    monkeypatch.setattr(
        MODULE.os,
        'killpg',
        lambda _process_group, _signal_value: None,
    )
    monkeypatch.setattr(
        MODULE.rclpy,
        'ok',
        lambda **kwargs: True,
    )

    success, _ = manager.stop_simulation()

    assert success is True
    assert manager.selected_environment == 'hospital'
    assert manager.process is None
    assert manager.process_record is None
    assert manager.state == SimulationState.STOPPED
    assert manager.last_error == ''
    assert manager.stop_in_progress is False
    assert manager.shutdown_prepared is False
    assert manager.last_shutdown_report is not None


def test_stop_simulation_escalates_to_sigterm(
    monkeypatch,
) -> None:
    process = StopProcessStub(
        wait_results=[
            MODULE.subprocess.TimeoutExpired(
                cmd='simulation',
                timeout=10.0,
            ),
            0,
        ],
        poll_result=None,
    )
    manager = make_stop_manager(process)

    sent_signals = []

    monkeypatch.setattr(
        MODULE.os,
        'getpgid',
        lambda process_id: process_id,
    )
    monkeypatch.setattr(
        MODULE.os,
        'killpg',
        lambda process_group, signal_value:
        sent_signals.append(
            (process_group, signal_value)
        ),
    )
    monkeypatch.setattr(
        MODULE.rclpy,
        'ok',
        lambda **kwargs: True,
    )

    success, _ = manager.stop_simulation()

    assert success is True
    assert sent_signals == [
        (4242, signal.SIGINT),
        (4242, signal.SIGTERM),
    ]
    assert process.wait_calls == [
        10.0,
        3.0,
    ]
    assert manager.process is None
    assert manager.cleanup_calls == 1


def test_stop_simulation_escalates_to_sigkill(
    monkeypatch,
) -> None:
    process = StopProcessStub(
        wait_results=[
            MODULE.subprocess.TimeoutExpired(
                cmd='simulation',
                timeout=10.0,
            ),
            MODULE.subprocess.TimeoutExpired(
                cmd='simulation',
                timeout=3.0,
            ),
            0,
        ],
        poll_result=None,
    )
    manager = make_stop_manager(process)

    sent_signals = []

    monkeypatch.setattr(
        MODULE.os,
        'getpgid',
        lambda process_id: process_id,
    )
    monkeypatch.setattr(
        MODULE.os,
        'killpg',
        lambda process_group, signal_value:
        sent_signals.append(
            (process_group, signal_value)
        ),
    )
    monkeypatch.setattr(
        MODULE.rclpy,
        'ok',
        lambda **kwargs: True,
    )

    success, _ = manager.stop_simulation()

    assert success is True
    assert sent_signals == [
        (4242, signal.SIGINT),
        (4242, signal.SIGTERM),
        (4242, signal.SIGKILL),
    ]
    assert process.wait_calls == [
        10.0,
        3.0,
        3.0,
    ]
    assert manager.process is None
    assert manager.cleanup_calls == 1


def test_stop_simulation_handles_missing_process_group(
    monkeypatch,
) -> None:
    process = StopProcessStub(
        poll_result=None
    )
    manager = make_stop_manager(process)

    monkeypatch.setattr(
        MODULE.os,
        'getpgid',
        lambda process_id: process_id,
    )

    def raise_process_lookup(
        process_group,
        signal_value,
    ):
        del process_group
        del signal_value
        raise ProcessLookupError

    monkeypatch.setattr(
        MODULE.os,
        'killpg',
        raise_process_lookup,
    )
    monkeypatch.setattr(
        MODULE.rclpy,
        'ok',
        lambda **kwargs: True,
    )

    success, message = manager.stop_simulation()

    assert success is True
    assert message == 'Simulation stopped successfully'
    assert manager.process is None
    assert manager.state == SimulationState.STOPPED
    assert manager.cleanup_calls == 1


def test_stop_simulation_reports_os_error(
    monkeypatch,
) -> None:
    process = StopProcessStub(
        poll_result=None
    )
    manager = make_stop_manager(process)

    monkeypatch.setattr(
        MODULE.os,
        'getpgid',
        lambda process_id: process_id,
    )

    def raise_os_error(
        process_group,
        signal_value,
    ):
        del process_group
        del signal_value
        raise OSError(
            'permission denied'
        )

    monkeypatch.setattr(
        MODULE.os,
        'killpg',
        raise_os_error,
    )
    monkeypatch.setattr(
        MODULE.rclpy,
        'ok',
        lambda **kwargs: True,
    )

    success, message = manager.stop_simulation()

    assert success is False
    assert 'permission denied' in message
    assert manager.state == SimulationState.ERROR
    assert manager.last_error == 'permission denied'
    assert manager.process is process
    assert manager.cleanup_calls == 0


def test_stop_simulation_handles_sigkill_wait_timeout(
    monkeypatch,
) -> None:
    process = StopProcessStub(
        wait_results=[
            MODULE.subprocess.TimeoutExpired(
                cmd='simulation',
                timeout=10.0,
            ),
            MODULE.subprocess.TimeoutExpired(
                cmd='simulation',
                timeout=3.0,
            ),
            MODULE.subprocess.TimeoutExpired(
                cmd='simulation',
                timeout=3.0,
            ),
        ],
        poll_result=None,
    )
    manager = make_stop_manager(process)

    monkeypatch.setattr(
        MODULE.os,
        'getpgid',
        lambda process_id: process_id,
    )
    monkeypatch.setattr(
        MODULE.os,
        'killpg',
        lambda process_group, signal_value: None,
    )
    monkeypatch.setattr(
        MODULE.rclpy,
        'ok',
        lambda **kwargs: True,
    )

    success, message = manager.stop_simulation()

    assert success is False
    assert 'SIGKILL' in message
    assert manager.state == SimulationState.ERROR
    assert manager.process is process


def make_monitor_manager(
    process=None,
    *,
    state=SimulationState.RUNNING,
):
    manager = object.__new__(
        SimulationManagerNode
    )

    manager.process = process
    manager.process_record = (
        SimpleNamespace(
            instance_id='simulation-test', pgid=process.pid,
            component='simulation_launch',
        )
        if process is not None else None
    )
    manager.process_registry = SimpleNamespace(
        deregister=lambda _instance_id: True,
    )
    manager.process_lock = threading.RLock()
    manager.state = state
    manager.last_error = ''
    manager.states = []
    manager.logs = []
    manager.environment_statuses = []
    manager.last_shutdown_report = None
    manager.persist_shutdown_report = lambda _report: None
    manager.shutdown_timeout = 4.0
    manager.kill_timeout = 1.5
    manager.release_exited_process_record = lambda _registry, _record: True

    manager.set_state = lambda new_state: (
        manager.states.append(new_state),
        setattr(manager, 'state', new_state),
    )[-1]

    manager.publish_environment_status = (
        lambda *, state, message:
        manager.environment_statuses.append(
            {
                'state': state,
                'message': message,
            }
        )
    )

    class Logger:
        def error(self, message: str) -> None:
            manager.logs.append(
                ('error', message)
            )

    manager.get_logger = lambda: Logger()

    return manager


def test_monitor_process_ignores_missing_process() -> None:
    manager = make_monitor_manager(
        process=None
    )

    manager.monitor_process()

    assert manager.states == []
    assert manager.last_error == ''


def test_monitor_process_ignores_running_process() -> None:
    process = ProcessStub(
        poll_result=None
    )
    manager = make_monitor_manager(process)

    manager.monitor_process()

    assert manager.process is process
    assert manager.states == []
    assert manager.last_error == ''


def test_monitor_process_accepts_expected_stop() -> None:
    process = ProcessStub(
        poll_result=0,
        returncode=0,
    )
    manager = make_monitor_manager(
        process,
        state=SimulationState.STOPPING,
    )

    manager.monitor_process()

    assert manager.process is None
    assert manager.state == SimulationState.STOPPED
    assert manager.states == [
        SimulationState.STOPPED,
    ]
    assert manager.last_error == ''


def test_monitor_process_reports_unexpected_exit() -> None:
    process = ProcessStub(
        poll_result=9,
        returncode=9,
    )
    manager = make_monitor_manager(
        process,
        state=SimulationState.RUNNING,
    )

    manager.monitor_process()

    assert manager.process is None
    assert manager.state == SimulationState.ERROR
    assert manager.states == [
        SimulationState.ERROR,
    ]
    assert 'return code 9' in manager.last_error
    assert manager.logs[-1] == (
        'error',
        manager.last_error,
    )
    assert manager.environment_statuses == [
        {
            'state': 'error',
            'message': manager.last_error,
        }
    ]


def make_cleanup_manager():
    manager = object.__new__(
        SimulationManagerNode
    )

    manager.logs = []
    manager.process_registry = SimpleNamespace(
        reconcile_stale_records=lambda: [],
    )

    class Logger:
        def warning(self, message: str) -> None:
            manager.logs.append(
                ('warning', message)
            )

        def error(self, message: str) -> None:
            manager.logs.append(
                ('error', message)
            )

    manager.get_logger = lambda: Logger()

    return manager


def test_cleanup_remaining_processes_handles_pgrep_failure(
    monkeypatch,
) -> None:
    manager = make_cleanup_manager()

    def raise_os_error(*args, **kwargs):
        raise OSError(
            'pgrep unavailable'
        )

    monkeypatch.setattr(
        MODULE.subprocess,
        'run',
        raise_os_error,
    )
    monkeypatch.setattr(
        MODULE.time,
        'sleep',
        lambda duration: None,
    )

    manager.cleanup_remaining_processes()

    assert manager.logs == []


def test_cleanup_remaining_processes_ignores_invalid_pids(
    monkeypatch,
) -> None:
    manager = make_cleanup_manager()
    killed = []

    results = [
        MODULE.subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='invalid\n123\n',
            stderr='',
        ),
        MODULE.subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='invalid\n',
            stderr='',
        ),
    ] * 4

    monkeypatch.setattr(
        MODULE.subprocess,
        'run',
        lambda *args, **kwargs: results.pop(0),
    )
    monkeypatch.setattr(
        MODULE.os,
        'getpid',
        lambda: 999,
    )
    monkeypatch.setattr(
        MODULE.os,
        'kill',
        lambda pid, signal_value:
        killed.append(
            (pid, signal_value)
        ),
    )
    monkeypatch.setattr(
        MODULE.time,
        'sleep',
        lambda duration: None,
    )

    manager.cleanup_remaining_processes()

    assert killed == []


def make_shutdown_manager():
    manager = object.__new__(
        SimulationManagerNode
    )

    manager._context = object()
    manager.shutdown_prepared = False
    manager.logs = []
    manager.stop_calls = 0

    class Logger:
        def info(self, message: str) -> None:
            manager.logs.append(
                ('info', message)
            )

        def error(self, message: str) -> None:
            manager.logs.append(
                ('error', message)
            )

    manager.get_logger = lambda: Logger()

    manager.stop_simulation = lambda: (
        setattr(
            manager,
            'stop_calls',
            manager.stop_calls + 1,
        ),
        (True, 'stopped'),
    )[1]

    return manager


def test_shutdown_is_idempotent(
    monkeypatch,
) -> None:
    manager = make_shutdown_manager()

    monkeypatch.setattr(
        MODULE.rclpy,
        'ok',
        lambda **kwargs: True,
    )

    manager.shutdown()
    manager.shutdown()

    assert manager.stop_calls == 1
    assert manager.shutdown_prepared is True
