#!/usr/bin/env python3
# Copyright 2026 Devansh Mishra
#
# Use of this source code is governed by an MIT-style
# license that can be found in the LICENSE file or at
# https://opensource.org/licenses/MIT.


import importlib.util
import json
from pathlib import Path
import threading
from types import ModuleType

import pytest
from std_msgs.msg import String


def load_mapping_manager_module() -> ModuleType:
    script_path = (
        Path(__file__).resolve().parents[1]
        / 'scripts'
        / 'mapping_manager_node.py'
    )

    specification = importlib.util.spec_from_file_location(
        'mapping_manager_node',
        script_path,
    )

    if (
        specification is None
        or specification.loader is None
    ):
        raise RuntimeError(
            'Unable to load mapping manager module'
        )

    module = importlib.util.module_from_spec(
        specification
    )
    specification.loader.exec_module(module)
    return module


MODULE = load_mapping_manager_module()
MappingManagerNode = MODULE.MappingManagerNode


def make_mapping_manager(
    *,
    simulation_state: str = 'running',
    mode_state: str = 'mapping',
    selected_environment: str = 'warehouse',
):
    node = object.__new__(MappingManagerNode)
    node.simulation_state = simulation_state
    node.mode_state = mode_state
    node.selected_environment = selected_environment
    return node


@pytest.mark.parametrize(
    'map_name',
    [
        'warehouse',
        'warehouse_map',
        'warehouse-map',
        'Map01',
        'a',
        'a' * 64,
    ],
)
def test_accepts_valid_map_names(
    map_name: str,
) -> None:
    node = make_mapping_manager()

    error = node.validate_save_request(map_name)

    assert error is None


@pytest.mark.parametrize(
    'map_name',
    [
        '',
        '../secret',
        '../../tmp/map',
        'warehouse/map',
        r'warehouse\map',
        '.',
        '..',
        '-warehouse',
        '_warehouse',
        'warehouse map',
        'warehouse.map',
        'warehouse;rm',
        'warehouse$(whoami)',
        'warehouse\nmap',
        'a' * 65,
    ],
)
def test_rejects_unsafe_map_names(
    map_name: str,
) -> None:
    node = make_mapping_manager()

    error = node.validate_save_request(map_name)

    assert error is not None


def test_requires_running_simulation() -> None:
    node = make_mapping_manager(
        simulation_state='stopped'
    )

    error = node.validate_save_request(
        'warehouse_map'
    )

    assert error is not None
    assert 'Simulation must be running' in error


def test_requires_mapping_mode() -> None:
    node = make_mapping_manager(
        mode_state='navigation'
    )

    error = node.validate_save_request(
        'warehouse_map'
    )

    assert error is not None
    assert 'Mapping mode must be active' in error


def test_requires_selected_environment() -> None:
    node = make_mapping_manager(
        selected_environment=''
    )

    error = node.validate_save_request(
        'warehouse_map'
    )

    assert error is not None
    assert 'No simulation environment' in error


def make_parameter_validation_manager():
    node = object.__new__(MappingManagerNode)
    node.save_timeout = 20.0
    node.free_threshold = 0.25
    node.occupied_threshold = 0.65
    return node


def test_parameter_validation_accepts_valid_values() -> None:
    node = make_parameter_validation_manager()

    node.validate_parameters()


@pytest.mark.parametrize(
    ('attribute', 'value'),
    [
        ('save_timeout', float('nan')),
        ('save_timeout', float('inf')),
        ('free_threshold', float('nan')),
        ('free_threshold', float('inf')),
        ('occupied_threshold', float('nan')),
        ('occupied_threshold', float('inf')),
    ],
)
def test_parameter_validation_rejects_nonfinite_values(
    attribute: str,
    value: float,
) -> None:
    node = make_parameter_validation_manager()
    setattr(node, attribute, value)

    with pytest.raises(
        ValueError,
        match=attribute,
    ):
        node.validate_parameters()


def test_mode_status_callback_trims_state() -> None:
    node = object.__new__(MappingManagerNode)
    node.mode_state = 'stopped'

    message = String()
    message.data = '  mapping\n'

    node.mode_status_callback(message)

    assert node.mode_state == 'mapping'


def test_simulation_status_callback_trims_state() -> None:
    node = object.__new__(MappingManagerNode)
    node.simulation_state = 'stopped'

    message = String()
    message.data = '  running\n'

    node.simulation_status_callback(message)

    assert node.simulation_state == 'running'


def make_environment_status_manager():
    node = object.__new__(MappingManagerNode)
    node.selected_environment = 'warehouse'
    node.published_map_lists = 0
    node.warnings = []

    node.publish_saved_maps = lambda: setattr(
        node,
        'published_map_lists',
        node.published_map_lists + 1,
    )

    class Logger:
        def warning(self, message: str) -> None:
            node.warnings.append(message)

    node.get_logger = lambda: Logger()

    return node


def environment_status_message(payload) -> String:
    message = String()
    message.data = json.dumps(payload)
    return message


def test_environment_status_rejects_non_object_json() -> None:
    node = make_environment_status_manager()

    node.environment_status_callback(
        environment_status_message(
            ['hospital']
        )
    )

    assert node.selected_environment == 'warehouse'
    assert node.published_map_lists == 0
    assert node.warnings


@pytest.mark.parametrize(
    'invalid_environment',
    [
        None,
        True,
        False,
        42,
        [],
        {},
    ],
)
def test_environment_status_rejects_non_string_value(
    invalid_environment,
) -> None:
    node = make_environment_status_manager()

    node.environment_status_callback(
        environment_status_message(
            {
                'selected_environment': (
                    invalid_environment
                ),
            }
        )
    )

    assert node.selected_environment == 'warehouse'
    assert node.published_map_lists == 0
    assert node.warnings


def test_environment_status_normalizes_valid_value() -> None:
    node = make_environment_status_manager()

    node.environment_status_callback(
        environment_status_message(
            {
                'selected_environment': (
                    '  HOSPITAL  '
                ),
            }
        )
    )

    assert node.selected_environment == 'hospital'
    assert node.published_map_lists == 1
    assert node.warnings == []


def test_environment_status_does_not_republish_unchanged_value() -> None:
    node = make_environment_status_manager()

    node.environment_status_callback(
        environment_status_message(
            {
                'selected_environment': (
                    '  WAREHOUSE  '
                ),
            }
        )
    )

    assert node.selected_environment == 'warehouse'
    assert node.published_map_lists == 0
    assert node.warnings == []


class RecordingThread:
    created = []

    def __init__(
        self,
        *,
        target,
        args,
        daemon,
    ) -> None:
        self.target = target
        self.args = args
        self.daemon = daemon
        self.started = False
        self.__class__.created.append(self)

    def start(self) -> None:
        self.started = True


def make_save_request_manager():
    node = object.__new__(MappingManagerNode)
    node.simulation_state = 'running'
    node.mode_state = 'mapping'
    node.selected_environment = 'warehouse'
    node.save_in_progress = False
    node.save_lock = threading.Lock()
    node.published_statuses = []

    node.publish_status = (
        lambda **payload:
        node.published_statuses.append(payload)
    )

    return node


def test_save_request_captures_environment_snapshot(
    monkeypatch,
) -> None:
    node = make_save_request_manager()
    RecordingThread.created = []

    monkeypatch.setattr(
        MODULE.threading,
        'Thread',
        RecordingThread,
    )

    message = String()
    message.data = 'warehouse_map'

    node.save_request_callback(message)

    assert node.save_in_progress is True
    assert len(RecordingThread.created) == 1

    worker = RecordingThread.created[0]

    assert worker.target == node.save_map
    assert worker.args == (
        'warehouse_map',
        'warehouse',
    )
    assert worker.daemon is True
    assert worker.started is True


def test_environment_change_after_request_does_not_change_worker_args(
    monkeypatch,
) -> None:
    node = make_save_request_manager()
    RecordingThread.created = []

    monkeypatch.setattr(
        MODULE.threading,
        'Thread',
        RecordingThread,
    )

    message = String()
    message.data = 'warehouse_map'

    node.save_request_callback(message)

    node.selected_environment = 'hospital'

    worker = RecordingThread.created[0]

    assert worker.args == (
        'warehouse_map',
        'warehouse',
    )


def test_busy_save_request_does_not_create_thread(
    monkeypatch,
) -> None:
    node = make_save_request_manager()
    node.save_in_progress = True
    RecordingThread.created = []

    monkeypatch.setattr(
        MODULE.threading,
        'Thread',
        RecordingThread,
    )

    message = String()
    message.data = 'warehouse_map'

    node.save_request_callback(message)

    assert RecordingThread.created == []
    assert node.save_in_progress is True
    assert node.published_statuses[-1]['status'] == 'error'
    assert 'already' in (
        node.published_statuses[-1]['message']
    )


def test_save_map_handles_directory_creation_failure(
    tmp_path: Path,
) -> None:
    node = object.__new__(MappingManagerNode)

    invalid_root = tmp_path / 'maps'
    invalid_root.write_text(
        'This path is intentionally a file'
    )

    node.map_directory = invalid_root
    node.save_timeout = 20.0
    node.free_threshold = 0.25
    node.occupied_threshold = 0.65
    node.save_in_progress = True
    node.save_lock = threading.Lock()
    node.published_statuses = []
    node.published_map_lists = 0

    node.publish_status = (
        lambda **payload:
        node.published_statuses.append(payload)
    )
    node.publish_saved_maps = lambda: setattr(
        node,
        'published_map_lists',
        node.published_map_lists + 1,
    )

    node.save_map(
        'warehouse_map',
        'warehouse',
    )

    assert node.save_in_progress is False
    assert node.published_map_lists == 0
    assert node.published_statuses[-1]['status'] == 'error'
    assert node.published_statuses[-1]['environment'] == (
        'warehouse'
    )
    assert 'Unable to prepare map directory' in (
        node.published_statuses[-1]['message']
    )


class CompletedProcessStub:
    def __init__(
        self,
        *,
        returncode: int = 0,
        stdout: str = '',
        stderr: str = '',
    ) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def make_save_map_manager(
    map_directory: Path,
):
    node = object.__new__(MappingManagerNode)

    node.map_directory = map_directory
    node.save_timeout = 12.5
    node.free_threshold = 0.25
    node.occupied_threshold = 0.65
    node.save_in_progress = True
    node.save_lock = threading.Lock()

    node.published_statuses = []
    node.published_map_lists = 0

    node.publish_status = (
        lambda **payload:
        node.published_statuses.append(payload)
    )

    node.publish_saved_maps = lambda: setattr(
        node,
        'published_map_lists',
        node.published_map_lists + 1,
    )

    return node


def test_save_map_runs_expected_command_and_reports_success(
    tmp_path: Path,
    monkeypatch,
) -> None:
    node = make_save_map_manager(tmp_path)
    recorded_calls = []

    def fake_run(
        command,
        *,
        capture_output,
        text,
        timeout,
        check,
    ):
        recorded_calls.append(
            {
                'command': command,
                'capture_output': capture_output,
                'text': text,
                'timeout': timeout,
                'check': check,
            }
        )

        output_prefix = Path(
            command[
                command.index('-f') + 1
            ]
        )

        output_prefix.with_suffix(
            '.yaml'
        ).write_text(
            'image: warehouse_map.pgm\n'
        )

        output_prefix.with_suffix(
            '.pgm'
        ).write_bytes(
            b'P5\n1 1\n255\n\x00'
        )

        return CompletedProcessStub()

    monkeypatch.setattr(
        MODULE.subprocess,
        'run',
        fake_run,
    )

    node.save_map(
        'warehouse_map',
        'warehouse',
    )

    assert len(recorded_calls) == 1

    call = recorded_calls[0]
    command = call['command']

    expected_prefix = (
        tmp_path
        / 'warehouse'
        / 'warehouse_map'
    )

    assert command == [
        'ros2',
        'run',
        'nav2_map_server',
        'map_saver_cli',
        '-f',
        str(expected_prefix),
        '--free',
        '0.25',
        '--occ',
        '0.65',
        '--ros-args',
        '-p',
        'save_map_timeout:=5.0',
    ]

    assert call['capture_output'] is True
    assert call['text'] is True
    assert call['timeout'] == 12.5
    assert call['check'] is False

    assert node.published_statuses[0]['status'] == 'saving'
    assert node.published_statuses[-1]['status'] == 'success'
    assert node.published_statuses[-1]['environment'] == (
        'warehouse'
    )

    assert node.published_statuses[-1]['yaml_path'] == str(
        expected_prefix.with_suffix('.yaml')
    )
    assert node.published_statuses[-1]['image_path'] == str(
        expected_prefix.with_suffix('.pgm')
    )

    assert node.published_map_lists == 1
    assert node.save_in_progress is False


def test_save_map_reports_nonzero_exit(
    tmp_path: Path,
    monkeypatch,
) -> None:
    node = make_save_map_manager(tmp_path)

    monkeypatch.setattr(
        MODULE.subprocess,
        'run',
        lambda *args, **kwargs: CompletedProcessStub(
            returncode=1,
            stderr='map saver failed',
        ),
    )

    node.save_map(
        'warehouse_map',
        'warehouse',
    )

    assert node.published_statuses[0]['status'] == 'saving'
    assert node.published_statuses[-1]['status'] == 'error'
    assert 'map saver failed' in (
        node.published_statuses[-1]['message']
    )
    assert node.published_map_lists == 0
    assert node.save_in_progress is False


def test_save_map_reports_missing_output_files(
    tmp_path: Path,
    monkeypatch,
) -> None:
    node = make_save_map_manager(tmp_path)

    monkeypatch.setattr(
        MODULE.subprocess,
        'run',
        lambda *args, **kwargs: CompletedProcessStub(),
    )

    node.save_map(
        'warehouse_map',
        'warehouse',
    )

    assert node.published_statuses[-1]['status'] == 'error'
    assert 'Expected map files were not created' in (
        node.published_statuses[-1]['message']
    )
    assert node.published_map_lists == 0
    assert node.save_in_progress is False


def test_save_map_reports_timeout(
    tmp_path: Path,
    monkeypatch,
) -> None:
    node = make_save_map_manager(tmp_path)

    def raise_timeout(*args, **kwargs):
        raise MODULE.subprocess.TimeoutExpired(
            cmd='map_saver_cli',
            timeout=12.5,
        )

    monkeypatch.setattr(
        MODULE.subprocess,
        'run',
        raise_timeout,
    )

    node.save_map(
        'warehouse_map',
        'warehouse',
    )

    assert node.published_statuses[-1]['status'] == 'error'
    assert 'timed out' in (
        node.published_statuses[-1]['message']
    )
    assert node.published_map_lists == 0
    assert node.save_in_progress is False


def test_save_map_reports_process_launch_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    node = make_save_map_manager(tmp_path)

    def raise_os_error(*args, **kwargs):
        raise OSError(
            'ros2 executable unavailable'
        )

    monkeypatch.setattr(
        MODULE.subprocess,
        'run',
        raise_os_error,
    )

    node.save_map(
        'warehouse_map',
        'warehouse',
    )

    assert node.published_statuses[-1]['status'] == 'error'
    assert 'Unable to run map saver' in (
        node.published_statuses[-1]['message']
    )
    assert 'ros2 executable unavailable' in (
        node.published_statuses[-1]['message']
    )
    assert node.published_map_lists == 0
    assert node.save_in_progress is False


class RecordingPublisher:
    def __init__(self) -> None:
        self.messages = []

    def publish(self, message) -> None:
        self.messages.append(message)


def make_saved_maps_manager(
    map_directory: Path,
    *,
    selected_environment: str = '',
):
    node = object.__new__(MappingManagerNode)
    node.map_directory = map_directory
    node.selected_environment = selected_environment
    node.maps_publisher = RecordingPublisher()
    node._context = object()
    return node


def create_saved_map(
    directory: Path,
    map_name: str,
    *,
    complete: bool = True,
) -> None:
    directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    (
        directory / f'{map_name}.yaml'
    ).write_text(
        f'image: {map_name}.pgm\n'
    )

    if complete:
        (
            directory / f'{map_name}.pgm'
        ).write_bytes(
            b'P5\n1 1\n255\n\x00'
        )


def published_saved_maps(node):
    assert len(node.maps_publisher.messages) == 1
    return json.loads(
        node.maps_publisher.messages[0].data
    )


def test_publish_saved_maps_lists_all_maps_without_filter(
    tmp_path: Path,
    monkeypatch,
) -> None:
    create_saved_map(
        tmp_path / 'warehouse',
        'warehouse_map',
    )
    create_saved_map(
        tmp_path / 'hospital',
        'hospital_map',
    )
    create_saved_map(
        tmp_path,
        'legacy_map',
    )

    node = make_saved_maps_manager(tmp_path)

    monkeypatch.setattr(
        MODULE.rclpy,
        'ok',
        lambda **kwargs: True,
    )

    node.publish_saved_maps()

    maps = published_saved_maps(node)

    assert {
        (
            item['name'],
            item['environment'],
            item['legacy'],
        )
        for item in maps
    } == {
        ('warehouse_map', 'warehouse', False),
        ('hospital_map', 'hospital', False),
        ('legacy_map', 'legacy', True),
    }


def test_publish_saved_maps_filters_other_environments(
    tmp_path: Path,
    monkeypatch,
) -> None:
    create_saved_map(
        tmp_path / 'warehouse',
        'warehouse_map',
    )
    create_saved_map(
        tmp_path / 'hospital',
        'hospital_map',
    )
    create_saved_map(
        tmp_path,
        'legacy_map',
    )

    node = make_saved_maps_manager(
        tmp_path,
        selected_environment='hospital',
    )

    monkeypatch.setattr(
        MODULE.rclpy,
        'ok',
        lambda **kwargs: True,
    )

    node.publish_saved_maps()

    maps = published_saved_maps(node)

    assert {
        item['name']
        for item in maps
    } == {
        'legacy_map',
        'hospital_map',
    }


def test_publish_saved_maps_marks_missing_image_incomplete(
    tmp_path: Path,
    monkeypatch,
) -> None:
    create_saved_map(
        tmp_path / 'warehouse',
        'incomplete_map',
        complete=False,
    )

    node = make_saved_maps_manager(
        tmp_path,
        selected_environment='warehouse',
    )

    monkeypatch.setattr(
        MODULE.rclpy,
        'ok',
        lambda **kwargs: True,
    )

    node.publish_saved_maps()

    maps = published_saved_maps(node)

    assert len(maps) == 1
    assert maps[0]['name'] == 'incomplete_map'
    assert maps[0]['complete'] is False
    assert maps[0]['image_path'].endswith(
        'incomplete_map.pgm'
    )


def test_publish_saved_maps_uses_resolved_paths(
    tmp_path: Path,
    monkeypatch,
) -> None:
    create_saved_map(
        tmp_path / 'warehouse',
        'warehouse_map',
    )

    node = make_saved_maps_manager(
        tmp_path,
        selected_environment='warehouse',
    )

    monkeypatch.setattr(
        MODULE.rclpy,
        'ok',
        lambda **kwargs: True,
    )

    node.publish_saved_maps()

    maps = published_saved_maps(node)

    yaml_path = (
        tmp_path
        / 'warehouse'
        / 'warehouse_map.yaml'
    ).resolve()

    image_path = (
        tmp_path
        / 'warehouse'
        / 'warehouse_map.pgm'
    ).resolve()

    assert maps[0]['yaml_path'] == str(yaml_path)
    assert maps[0]['image_path'] == str(image_path)


def test_publish_saved_maps_is_deterministic(
    tmp_path: Path,
    monkeypatch,
) -> None:
    create_saved_map(
        tmp_path / 'warehouse',
        'zeta',
    )
    create_saved_map(
        tmp_path / 'warehouse',
        'alpha',
    )
    create_saved_map(
        tmp_path,
        'legacy_beta',
    )

    node = make_saved_maps_manager(
        tmp_path,
        selected_environment='warehouse',
    )

    monkeypatch.setattr(
        MODULE.rclpy,
        'ok',
        lambda **kwargs: True,
    )

    node.publish_saved_maps()

    maps = published_saved_maps(node)

    assert [
        item['name']
        for item in maps
    ] == [
        'legacy_beta',
        'alpha',
        'zeta',
    ]


def test_publish_saved_maps_does_not_publish_after_shutdown(
    tmp_path: Path,
    monkeypatch,
) -> None:
    create_saved_map(
        tmp_path / 'warehouse',
        'warehouse_map',
    )

    node = make_saved_maps_manager(
        tmp_path,
        selected_environment='warehouse',
    )

    monkeypatch.setattr(
        MODULE.rclpy,
        'ok',
        lambda **kwargs: False,
    )

    node.publish_saved_maps()

    assert node.maps_publisher.messages == []
