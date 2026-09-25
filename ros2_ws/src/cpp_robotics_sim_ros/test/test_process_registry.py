#!/usr/bin/env python3
# Copyright 2026 Devansh Mishra
#
# Use of this source code is governed by an MIT-style
# license that can be found in the LICENSE file or at
# https://opensource.org/licenses/MIT.

"""Tests for file-backed process ownership and Linux process identity."""

from dataclasses import replace
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import textwrap

import pytest


def _load_module():
    module_path = Path(__file__).resolve().parents[1] / 'scripts' / 'process_registry.py'
    spec = importlib.util.spec_from_file_location('process_registry', module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError('unable to load process_registry.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = _load_module()


def _paths(tmp_path: Path):
    directory = tmp_path / 'runtime'
    return MODULE.RegistryPaths(
        directory=directory,
        manifest=directory / 'process_registry.json',
        lock=directory / 'process_registry.lock',
    )


def _record(instance_id: str = 'instance-a', *, pid: int = 101):
    return MODULE.ProcessRecord(
        schema_version=MODULE.SCHEMA_VERSION,
        instance_id=instance_id,
        component='simulation',
        pid=pid,
        pgid=pid,
        session_id=pid,
        parent_pid=1,
        proc_start_time=1000 + pid,
        exe='/usr/bin/python3',
        cmdline_fingerprint='["python3","helper.py"]',
        state='active',
    )


def _stop_helper(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=3)


def test_empty_registry_initializes_manifest(tmp_path) -> None:
    registry = MODULE.ProcessRegistry(_paths(tmp_path))
    assert registry.load() == []
    payload = json.loads(registry.paths.manifest.read_text(encoding='utf-8'))
    assert payload == {'schema_version': 1, 'records': []}
    assert (registry.paths.directory.stat().st_mode & 0o777) == 0o700
    assert (registry.paths.manifest.stat().st_mode & 0o777) == 0o600
    assert (registry.paths.lock.stat().st_mode & 0o777) == 0o600


def test_record_round_trip_and_validation() -> None:
    record = _record()
    assert MODULE.ProcessRecord.from_mapping(record.to_mapping()) == record

    with pytest.raises(MODULE.RegistryFormatError):
        replace(record, pid=0).validate()
    with pytest.raises(MODULE.RegistryFormatError):
        replace(record, pgid=0).validate()
    with pytest.raises(MODULE.RegistryFormatError):
        replace(record, proc_start_time=0).validate()
    replace(record, parent_pid=0).validate()


def test_register_replace_sort_and_deregister(tmp_path) -> None:
    registry = MODULE.ProcessRegistry(_paths(tmp_path))
    registry.register(_record('b', pid=102))
    registry.register(_record('a', pid=101))
    assert [record.instance_id for record in registry.list_records()] == ['a', 'b']

    replacement = replace(_record('a', pid=103), component='mode')
    registry.register(replacement)
    records = registry.list_records()
    assert len(records) == 2
    assert next(record for record in records if record.instance_id == 'a') == replacement

    assert registry.deregister('a') is True
    assert registry.deregister('a') is False
    assert [record.instance_id for record in registry.list_records()] == ['b']


def test_parse_proc_stat_handles_spaces_and_parentheses() -> None:
    pid = 321
    fields = ['S', '10', '20', '20'] + ['0'] * 15 + ['123456']
    text = f'{pid} (worker ) with spaces) ' + ' '.join(fields)
    assert MODULE._parse_proc_stat(pid, text) == (pid, 20, 20, 10, 123456)


def test_real_helper_identity_captures_and_verifies() -> None:
    process = subprocess.Popen(
        [sys.executable, '-c', 'import time; time.sleep(30)'],
        start_new_session=True,
    )
    try:
        identity = MODULE.capture_process_identity(process.pid)
        record = MODULE.ProcessRecord.from_identity(
            identity,
            component='test-helper',
            instance_id='helper',
        )
        assert identity.pid == process.pid
        assert identity.pgid == process.pid
        assert identity.session_id == process.pid
        assert identity.proc_start_time > 0
        assert identity.exe
        assert MODULE.verify_process_identity(record) is True
    finally:
        _stop_helper(process)


def test_parent_pid_is_diagnostic_not_authoritative() -> None:
    identity = MODULE.capture_process_identity(os.getpid())
    record = MODULE.ProcessRecord.from_identity(
        identity,
        component='self-test',
        instance_id='self',
    )
    assert MODULE.verify_process_identity(
        replace(record, parent_pid=record.parent_pid + 999)
    ) is True


def test_missing_pid_is_rejected() -> None:
    assert MODULE.verify_process_identity(_record(pid=99999999)) is False


@pytest.mark.parametrize(
    'field,value_factory',
    [
        ('proc_start_time', lambda record: record.proc_start_time + 1),
        ('pgid', lambda record: record.pgid + 1),
        ('session_id', lambda record: record.session_id + 1),
        ('exe', lambda _record: '/definitely/not/the/real/executable'),
        ('cmdline_fingerprint', lambda _record: '["different"]'),
    ],
)
def test_identity_mismatch_is_rejected(field, value_factory) -> None:
    identity = MODULE.capture_process_identity(os.getpid())
    record = MODULE.ProcessRecord.from_identity(
        identity,
        component='self-test',
        instance_id='self',
    )
    mismatched = replace(record, **{field: value_factory(record)})
    assert MODULE.verify_process_identity(mismatched) is False


def test_reconcile_removes_stale_without_signaling(tmp_path, monkeypatch) -> None:
    registry = MODULE.ProcessRegistry(_paths(tmp_path))
    registry.register(_record('stale', pid=99999999))

    monkeypatch.setattr(
        MODULE.os,
        'kill',
        lambda *_args, **_kwargs: pytest.fail('registry must not signal'),
    )
    monkeypatch.setattr(
        MODULE.os,
        'killpg',
        lambda _pgid, signal_value: (
            (_ for _ in ()).throw(ProcessLookupError())
            if signal_value == 0
            else pytest.fail('registry must not send a terminating signal')
        ),
        raising=False,
    )

    stale = registry.reconcile_stale_records()
    assert [record.instance_id for record in stale] == ['stale']
    assert registry.list_records() == []


def test_reconcile_retains_record_while_process_group_exists(
    tmp_path, monkeypatch
) -> None:
    registry = MODULE.ProcessRegistry(_paths(tmp_path))
    record = _record('questionable-group', pid=99999999)
    registry.register(record)
    monkeypatch.setattr(
        MODULE, 'owned_process_group_status', lambda _item: 'ambiguous'
    )

    assert registry.reconcile_stale_records() == []
    assert registry.list_records() == [record]


def test_existing_group_with_no_readable_members_is_ambiguous(
    monkeypatch,
) -> None:
    record = _record('unreadable-group', pid=99999999)
    monkeypatch.setattr(
        MODULE, 'verify_process_identity', lambda _item: False
    )
    monkeypatch.setattr(
        MODULE, 'process_group_session_ids', lambda _pgid: set()
    )
    monkeypatch.setattr(
        MODULE, 'process_group_exists', lambda _pgid: True
    )

    assert MODULE.owned_process_group_status(record) == 'ambiguous'


def test_unique_registration_rejects_questionable_existing_group(
    tmp_path, monkeypatch
) -> None:
    registry = MODULE.ProcessRegistry(_paths(tmp_path))
    registry.register(_record('existing', pid=101))
    monkeypatch.setattr(
        MODULE, 'owned_process_group_status', lambda _item: 'ambiguous'
    )

    with pytest.raises(RuntimeError, match='active or ambiguous owner'):
        registry.register_unique(_record('replacement', pid=202))


def test_refresh_group_members_rechecks_leader_after_proc_scan(
    tmp_path, monkeypatch
) -> None:
    registry = MODULE.ProcessRegistry(_paths(tmp_path))
    record = _record('changing-leader', pid=202)
    registry.register(record)
    member = MODULE.ProcessIdentity(
        pid=203,
        pgid=record.pgid,
        session_id=record.session_id,
        parent_pid=record.pid,
        proc_start_time=1203,
        exe='/usr/bin/python3',
        cmdline_fingerprint='["python3","child.py"]',
    )
    verification_results = iter((True, False))
    monkeypatch.setattr(
        MODULE,
        'verify_process_identity',
        lambda _record: next(verification_results),
    )
    monkeypatch.setattr(
        MODULE,
        'capture_process_session_members',
        lambda *_args, **_kwargs: (member,),
    )

    with pytest.raises(RuntimeError, match='changed while descendants'):
        registry.refresh_group_members(record)

    assert registry.list_records() == [record]


def test_malformed_manifest_is_rejected(tmp_path) -> None:
    paths = _paths(tmp_path)
    paths.directory.mkdir(parents=True)
    paths.manifest.write_text('{broken json', encoding='utf-8')
    registry = MODULE.ProcessRegistry(paths)
    with pytest.raises(MODULE.RegistryFormatError, match='not valid JSON'):
        registry.load()


def test_atomic_write_failure_preserves_previous_manifest(tmp_path, monkeypatch) -> None:
    registry = MODULE.ProcessRegistry(_paths(tmp_path))
    registry.register(_record('first', pid=101))
    before = registry.paths.manifest.read_bytes()

    def fail_replace(*_args, **_kwargs):
        raise OSError('injected replace failure')

    monkeypatch.setattr(MODULE.os, 'replace', fail_replace)
    with pytest.raises(OSError, match='injected replace failure'):
        registry.register(_record('second', pid=102))

    assert registry.paths.manifest.read_bytes() == before
    assert not list(registry.paths.directory.glob('.process_registry.*'))


def test_concurrent_writers_do_not_lose_records(tmp_path) -> None:
    paths = _paths(tmp_path)
    module_path = Path(__file__).resolve().parents[1] / 'scripts' / 'process_registry.py'
    helper = textwrap.dedent(
        """
        import importlib.util
        from pathlib import Path
        import sys

        module_path = Path(sys.argv[1])
        runtime_dir = Path(sys.argv[2])
        instance_id = sys.argv[3]
        pid_value = int(sys.argv[4])
        spec = importlib.util.spec_from_file_location('registry_helper', module_path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        paths = module.RegistryPaths(
            directory=runtime_dir,
            manifest=runtime_dir / 'process_registry.json',
            lock=runtime_dir / 'process_registry.lock',
        )
        registry = module.ProcessRegistry(paths)
        registry.register(module.ProcessRecord(
            schema_version=module.SCHEMA_VERSION,
            instance_id=instance_id,
            component='writer',
            pid=pid_value,
            pgid=pid_value,
            session_id=pid_value,
            parent_pid=1,
            proc_start_time=100000 + pid_value,
            exe='/usr/bin/python3',
            cmdline_fingerprint='["writer"]',
            state='active',
        ))
        """
    )

    processes = [
        subprocess.Popen(
            [
                sys.executable,
                '-c',
                helper,
                str(module_path),
                str(paths.directory),
                f'writer-{index}',
                str(1000 + index),
            ]
        )
        for index in range(8)
    ]
    for process in processes:
        assert process.wait(timeout=10) == 0

    records = MODULE.ProcessRegistry(paths).list_records()
    assert len(records) == 8
    assert {record.instance_id for record in records} == {
        f'writer-{index}' for index in range(8)
    }


def test_registry_directory_symlink_is_rejected(tmp_path) -> None:
    actual = tmp_path / 'actual'
    actual.mkdir()
    link = tmp_path / 'runtime'
    link.symlink_to(actual, target_is_directory=True)
    paths = MODULE.RegistryPaths(
        directory=link,
        manifest=link / 'process_registry.json',
        lock=link / 'process_registry.lock',
    )
    with pytest.raises(OSError, match='symbolic link'):
        MODULE.ProcessRegistry(paths).load()
