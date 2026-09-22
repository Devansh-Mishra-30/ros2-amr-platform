#!/usr/bin/env python3
# Copyright 2026 Devansh Mishra
#
# Use of this source code is governed by an MIT-style
# license that can be found in the LICENSE file or at
# https://opensource.org/licenses/MIT.

"""Unit tests for dashboard runtime admission ordering."""

import fcntl
import importlib.util
from pathlib import Path
import select
import subprocess
import sys
import textwrap
from types import ModuleType

import pytest


def load_web_interface_module() -> ModuleType:
    launch_path = (
        Path(__file__).resolve().parents[1]
        / 'launch'
        / 'web_interface.launch.py'
    )
    specification = importlib.util.spec_from_file_location(
        'web_interface_launch',
        launch_path,
    )
    if specification is None or specification.loader is None:
        raise RuntimeError('Unable to load web interface launch module')
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


MODULE = load_web_interface_module()


@pytest.fixture(autouse=True)
def isolated_lock_path(monkeypatch, tmp_path):
    """Keep lock ownership isolated from a real local dashboard."""
    lock_path = tmp_path / 'web_interface.lock'
    monkeypatch.setattr(
        MODULE, 'get_single_instance_lock_path', lambda: lock_path
    )
    MODULE.release_single_instance_lock()
    yield lock_path
    MODULE.release_single_instance_lock()


def _readline_with_timeout(process, timeout=5.0) -> str:
    ready, _, _ = select.select([process.stdout], [], [], timeout)
    assert ready, 'helper process did not produce output in time'
    line = process.stdout.readline()
    assert line
    return line.strip()


def _start_helper(role, lock_path, marker_path=None):
    helper = textwrap.dedent(
        """
        import importlib.util
        from pathlib import Path
        import sys

        launch_path, lock_path, role = sys.argv[1:4]
        specification = importlib.util.spec_from_file_location(
            'web_interface_launch_helper',
            launch_path,
        )
        module = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(module)
        module.get_single_instance_lock_path = lambda: Path(lock_path)

        if role == 'owner':
            module.acquire_single_instance_lock()
            print('READY', flush=True)
            sys.stdin.readline()
            module.release_single_instance_lock()
        else:
            marker_path = Path(sys.argv[4])
            module.cleanup_stale_project_processes = (
                lambda: marker_path.write_text('called')
            )
            try:
                module.prepare_runtime_admission()
            except RuntimeError as error:
                print(str(error), flush=True)
            else:
                print('UNEXPECTED_ADMISSION', flush=True)
                module.release_single_instance_lock()
        """
    )
    command = [
        sys.executable,
        '-c',
        helper,
        str(Path(__file__).resolve().parents[1] / 'launch'
            / 'web_interface.launch.py'),
        str(lock_path),
        role,
    ]
    if marker_path is not None:
        command.append(str(marker_path))
    return subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def test_two_processes_contend_without_disturbing_owner(tmp_path) -> None:
    lock_path = tmp_path / 'web_interface.lock'
    marker_path = tmp_path / 'cleanup-called'
    owner = _start_helper('owner', lock_path)

    try:
        assert _readline_with_timeout(owner) == 'READY'
        contender = _start_helper('contender', lock_path, marker_path)
        try:
            assert 'already running' in _readline_with_timeout(contender)
            contender.wait(timeout=5)
        finally:
            if contender.poll() is None:
                contender.kill()
                contender.wait(timeout=5)

        assert not marker_path.exists()
        assert owner.poll() is None
        owner.stdin.write('\n')
        owner.stdin.flush()
        owner.wait(timeout=5)

        replacement = _start_helper('owner', lock_path)
        try:
            assert _readline_with_timeout(replacement) == 'READY'
            replacement.stdin.write('\n')
            replacement.stdin.flush()
            replacement.wait(timeout=5)
        finally:
            if replacement.poll() is None:
                replacement.kill()
                replacement.wait(timeout=5)
    finally:
        if owner.poll() is None:
            owner.kill()
            owner.wait(timeout=5)


def test_first_instance_acquires_runtime_ownership(
    monkeypatch, isolated_lock_path
) -> None:
    cleanup_calls = []
    monkeypatch.setattr(
        MODULE,
        'cleanup_stale_project_processes',
        lambda: cleanup_calls.append(True),
    )
    MODULE.prepare_runtime_admission()
    assert MODULE._LOCK_FILE_HANDLE is not None
    assert cleanup_calls == [True]
    assert isolated_lock_path.read_text(encoding='utf-8')


def test_second_instance_is_rejected_without_cleanup(
    monkeypatch, isolated_lock_path
) -> None:
    cleanup_calls = []
    termination_calls = []
    healthy_owner = isolated_lock_path.open('a+', encoding='utf-8')
    fcntl.flock(
        healthy_owner.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB
    )
    monkeypatch.setattr(
        MODULE,
        'cleanup_stale_project_processes',
        lambda: cleanup_calls.append(True),
    )
    monkeypatch.setattr(
        MODULE,
        'terminate_processes',
        lambda pids, signal_number: termination_calls.append(
            (pids, signal_number)
        ),
    )
    try:
        with pytest.raises(RuntimeError, match='already running'):
            MODULE.prepare_runtime_admission()
    finally:
        fcntl.flock(healthy_owner.fileno(), fcntl.LOCK_UN)
        healthy_owner.close()
    assert cleanup_calls == []
    assert termination_calls == []
    assert MODULE._LOCK_FILE_HANDLE is None


def test_stale_recovery_runs_only_after_admission(monkeypatch) -> None:
    cleanup_calls = []
    monkeypatch.setattr(
        MODULE,
        'cleanup_stale_project_processes',
        lambda: cleanup_calls.append(True),
    )
    MODULE.prepare_runtime_admission()
    assert cleanup_calls == [True]


def test_failed_stale_recovery_releases_runtime_ownership(
    monkeypatch, isolated_lock_path
) -> None:
    def fail_cleanup() -> None:
        raise RuntimeError('stale recovery failed')

    monkeypatch.setattr(
        MODULE, 'cleanup_stale_project_processes', fail_cleanup
    )
    with pytest.raises(RuntimeError, match='stale recovery failed'):
        MODULE.prepare_runtime_admission()
    assert MODULE._LOCK_FILE_HANDLE is None

    replacement_owner = isolated_lock_path.open('a+', encoding='utf-8')
    try:
        fcntl.flock(
            replacement_owner.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB
        )
    finally:
        fcntl.flock(replacement_owner.fileno(), fcntl.LOCK_UN)
        replacement_owner.close()


def test_lock_can_be_reacquired_after_release(monkeypatch) -> None:
    monkeypatch.setattr(
        MODULE, 'cleanup_stale_project_processes', lambda: None
    )
    MODULE.prepare_runtime_admission()
    MODULE.release_single_instance_lock()
    MODULE.prepare_runtime_admission()
    assert MODULE._LOCK_FILE_HANDLE is not None


def test_launch_build_failure_releases_runtime_ownership(
    monkeypatch, isolated_lock_path
) -> None:
    monkeypatch.setattr(
        MODULE, 'cleanup_stale_project_processes', lambda: None
    )

    def fail_build():
        raise RuntimeError('launch description failed')

    monkeypatch.setattr(MODULE, '_build_launch_description', fail_build)

    with pytest.raises(RuntimeError, match='launch description failed'):
        MODULE.generate_launch_description()

    assert MODULE._LOCK_FILE_HANDLE is None

    replacement_owner = isolated_lock_path.open('a+', encoding='utf-8')
    try:
        fcntl.flock(
            replacement_owner.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB
        )
    finally:
        fcntl.flock(replacement_owner.fileno(), fcntl.LOCK_UN)
        replacement_owner.close()


class _TrackingLock:
    def __init__(self, fileno=41):
        self._fileno = fileno
        self.closed = False

    def fileno(self):
        return self._fileno

    def seek(self, *_args):
        return None

    def truncate(self):
        return None

    def write(self, _value):
        return None

    def flush(self):
        return None

    def close(self):
        self.closed = True


def test_non_contention_flock_failure_closes_file(
    monkeypatch, isolated_lock_path
) -> None:
    lock_file = _TrackingLock()
    monkeypatch.setattr(type(isolated_lock_path), 'open',
                        lambda *_args, **_kwargs: lock_file)

    def fail_flock(*_args):
        raise OSError('lock service unavailable')

    monkeypatch.setattr(MODULE.fcntl, 'flock', fail_flock)
    with pytest.raises(OSError, match='lock service unavailable'):
        MODULE.acquire_single_instance_lock()
    assert lock_file.closed
    assert MODULE._LOCK_FILE_HANDLE is None


def test_metadata_failure_unlock_failure_still_closes_file(
    monkeypatch, isolated_lock_path
) -> None:
    lock_file = _TrackingLock()
    monkeypatch.setattr(type(isolated_lock_path), 'open',
                        lambda *_args, **_kwargs: lock_file)

    calls = []

    def flock_side_effect(_fd, operation):
        calls.append(operation)
        if operation == fcntl.LOCK_UN:
            raise OSError('unlock failed')

    monkeypatch.setattr(MODULE.fcntl, 'flock', flock_side_effect)
    monkeypatch.setattr(lock_file, 'write',
                        lambda _value: (_ for _ in ()).throw(
                            OSError('metadata failed')
                        ))
    with pytest.raises(OSError, match='metadata failed'):
        MODULE.acquire_single_instance_lock()
    assert calls == [fcntl.LOCK_EX | fcntl.LOCK_NB, fcntl.LOCK_UN]
    assert lock_file.closed
    assert MODULE._LOCK_FILE_HANDLE is None


def test_atexit_registration_failure_releases_ownership(
    monkeypatch, isolated_lock_path
) -> None:
    monkeypatch.setattr(
        MODULE, 'cleanup_stale_project_processes', lambda: None
    )
    monkeypatch.setattr(
        MODULE.atexit, 'register',
        lambda _callback: (_ for _ in ()).throw(
            RuntimeError('atexit registration failed')
        ),
    )
    with pytest.raises(RuntimeError, match='atexit registration failed'):
        MODULE.generate_launch_description()
    assert MODULE._LOCK_FILE_HANDLE is None

    replacement_owner = isolated_lock_path.open('a+', encoding='utf-8')
    try:
        fcntl.flock(
            replacement_owner.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB
        )
    finally:
        fcntl.flock(replacement_owner.fileno(), fcntl.LOCK_UN)
        replacement_owner.close()
