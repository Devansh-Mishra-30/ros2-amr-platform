#!/usr/bin/env python3
# Copyright 2026 Devansh Mishra
#
# Use of this source code is governed by an MIT-style
# license that can be found in the LICENSE file or at
# https://opensource.org/licenses/MIT.

from dataclasses import replace
import os
from pathlib import Path
import signal
import subprocess
import sys

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))

import process_lifecycle as lifecycle  # noqa: E402,I100
import process_registry as registry_module  # noqa: E402,I100
from runtime_verification import (  # noqa: E402,I100
    find_duplicate_os_processes,
    find_duplicate_ros_nodes,
)


class RegistryStub:
    def __init__(self, fail=False):
        self.fail = fail
        self.registered = []
        self.deregistered = []

    def register_unique(self, record):
        if self.fail:
            raise OSError('manifest write failed')
        self.registered.append(record)

    def deregister(self, instance_id):
        self.deregistered.append(instance_id)
        return True


def record_for_self():
    return registry_module.ProcessRecord.from_identity(
        registry_module.capture_process_identity(os.getpid()),
        component='test_component', instance_id='test-instance',
    )


def test_registration_captures_child_and_persists():
    process = subprocess.Popen(
        [sys.executable, '-c', 'import time; time.sleep(30)'],
        start_new_session=True,
    )
    registry = RegistryStub()
    try:
        record = lifecycle.register_managed_process(
            registry, process, 'simulation_launch'
        )
        assert record.pid == process.pid
        assert record.pgid == process.pid
        assert registry.registered == [record]
    finally:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=3)


def test_registration_failure_rolls_back_child():
    process = subprocess.Popen(
        [sys.executable, '-c', 'import time; time.sleep(30)'],
        start_new_session=True,
    )
    with pytest.raises(OSError, match='manifest write failed'):
        lifecycle.register_managed_process(
            RegistryStub(fail=True), process, 'simulation_launch'
        )
    process.wait(timeout=3)
    assert process.poll() is not None


def test_registration_retries_transient_pre_exec_identity(monkeypatch):
    process = subprocess.Popen(
        [sys.executable, '-c', 'import time; time.sleep(30)'],
        start_new_session=True,
    )
    real_capture = lifecycle.capture_process_identity
    calls = []

    def transient_capture(pid):
        calls.append(pid)
        if len(calls) == 1:
            raise ProcessLookupError('command line is not stable yet')
        return real_capture(pid)

    monkeypatch.setattr(lifecycle, 'capture_process_identity', transient_capture)
    try:
        record = lifecycle.register_managed_process(
            RegistryStub(), process, 'simulation_launch'
        )
        assert record.cmdline_fingerprint != '[]'
        assert len(calls) == 2
    finally:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=3)


def test_sigint_success_revalidates_and_deregisters(monkeypatch):
    record = record_for_self()
    registry = RegistryStub()
    sent = []
    monkeypatch.setattr(lifecycle, '_identity_status', lambda _r: ('verified', ''))
    owned_statuses = iter(
        [
            ('leader_verified', (record.pgid,), (record,)),
            ('leader_verified', (record.pgid,), (record,)),
            ('absent', (), ()),
        ]
    )
    monkeypatch.setattr(
        lifecycle,
        'owned_process_group_ids',
        lambda _r: next(owned_statuses),
    )
    monkeypatch.setattr(lifecycle, 'process_group_exists', lambda _pgid: True)
    monkeypatch.setattr(
        lifecycle.os, 'killpg', lambda pgid, sig: sent.append((pgid, sig))
    )
    monkeypatch.setattr(lifecycle, '_wait_for_group_exit', lambda *args: True)
    result = lifecycle.terminate_owned_process(registry, record)
    assert result.success is True
    assert sent == [(record.pgid, signal.SIGINT)]
    assert registry.deregistered == ['test-instance']


def test_escalation_revalidates_before_every_signal(monkeypatch):
    record = record_for_self()
    sent = []
    monkeypatch.setattr(lifecycle, '_identity_status', lambda _r: ('verified', ''))
    calls = []
    monkeypatch.setattr(
        lifecycle,
        'owned_process_group_ids',
        lambda _r: (
            calls.append(True)
            or (
                ('absent', (), ())
                if len(calls) == 9
                else ('leader_verified', (record.pgid,), (record,))
            )
        ),
    )
    monkeypatch.setattr(
        lifecycle.os, 'killpg', lambda pgid, sig: sent.append((pgid, sig))
    )
    monkeypatch.setattr(lifecycle, '_wait_for_group_exit', lambda *args: len(sent) == 3)
    result = lifecycle.terminate_owned_process(RegistryStub(), record)
    assert result.success is True
    assert [item[1] for item in sent] == [
        signal.SIGINT, signal.SIGTERM, signal.SIGKILL
    ]


def test_group_existence_fails_safe_when_proc_members_are_unreadable(
    monkeypatch,
):
    monkeypatch.setattr(
        lifecycle, 'process_group_session_ids', lambda _pgid: set()
    )
    monkeypatch.setattr(
        lifecycle, 'kernel_process_group_exists', lambda _pgid: True
    )

    assert lifecycle.process_group_exists(12345) is True


@pytest.mark.parametrize('status', ['mismatch', 'unverifiable'])
def test_identity_failure_refuses_signal(monkeypatch, status):
    record = record_for_self()
    monkeypatch.setattr(lifecycle, '_identity_status', lambda _r: (status, 'changed'))
    monkeypatch.setattr(
        lifecycle.os, 'killpg',
        lambda *_args: pytest.fail('must not signal an unverified owner'),
    )
    result = lifecycle.terminate_owned_process(RegistryStub(), record)
    assert result.success is False
    assert result.signal_result == 'refused'
    assert result.identity_verification_status == status


def test_pid_start_time_and_pgid_mismatch_are_rejected():
    record = record_for_self()
    assert registry_module.verify_process_identity(
        replace(record, proc_start_time=record.proc_start_time + 1)
    ) is False
    assert registry_module.verify_process_identity(
        replace(record, pgid=record.pgid + 1)
    ) is False


def test_ros_duplicates_are_exact_and_domain_snapshot_scoped():
    duplicates = find_duplicate_ros_nodes(
        ['/mode_manager', '/mode_manager', '/unrelated', '/unrelated']
    )
    assert duplicates == {'/mode_manager': 2}


def test_os_duplicates_use_exact_platform_entry_points():
    duplicates = find_duplicate_os_processes(
        [
            {
                'pid': 10,
                'arguments': ['/usr/bin/python3', '/tmp/simulation_manager_node.py'],
            },
            {
                'pid': 11,
                'arguments': ['/usr/bin/python3', '/tmp/simulation_manager_node.py'],
            },
            {
                'pid': 12,
                'arguments': ['gz', 'sim', 'unrelated_world.sdf'],
            },
            {
                'pid': 13,
                'arguments': ['contains simulation_manager_node.py in text'],
            },
        ]
    )
    assert duplicates == {'simulation_manager': [10, 11]}


def test_dead_session_leader_group_is_recovered_safely():
    leader = subprocess.Popen(
        [
            sys.executable,
            '-c',
            (
                'import os,time; child=os.fork(); '
                'print(child, flush=True) if child else None; '
                'time.sleep(0.5 if child else 30)'
            ),
        ],
        start_new_session=True,
        stdout=subprocess.PIPE,
        text=True,
    )
    assert leader.stdout is not None
    child_pid = int(leader.stdout.readline().strip())
    record = registry_module.ProcessRecord.from_identity(
        registry_module.capture_process_identity(leader.pid),
        component='simulation_launch',
        instance_id='orphan-test',
    )
    record = replace(
        record,
        member_identities=registry_module.capture_process_group_members(
            record.pgid,
            record.session_id,
            exclude_pid=record.pid,
        ),
    )
    try:
        leader.wait(timeout=3)
        assert registry_module.owned_process_group_status(record) == (
            'session_verified'
        )
        result = lifecycle.terminate_owned_process(
            RegistryStub(),
            record,
            sigint_timeout=1.0,
            sigterm_timeout=1.0,
            sigkill_timeout=1.0,
        )
        assert result.success is True
        assert result.identity_verification_status == 'absent'
        assert result.signals_attempted[0].signal == 'SIGINT'
    finally:
        try:
            os.killpg(record.pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            os.kill(child_pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


@pytest.mark.skipif(sys.platform != 'linux', reason='requires Linux procfs')
def test_dead_session_leader_with_second_pgid_is_recovered_safely(tmp_path):
    """Reproduce Gazebo's orphan topology: one owned SID, two PGIDs."""
    helper = subprocess.Popen(
        [
            sys.executable,
            '-c',
            (
                'import os,time; '
                'child=os.fork(); '
                'os.setpgid(0, 0) if child == 0 else None; '
                'print(("child" if child == 0 else "leader"), '
                'os.getpid(), os.getpgid(0), os.getsid(0), flush=True); '
                'time.sleep(30)'
            ),
        ],
        start_new_session=True,
        stdout=subprocess.PIPE,
        text=True,
    )
    assert helper.stdout is not None
    observations = {
        fields[0]: tuple(map(int, fields[1:]))
        for fields in (
            helper.stdout.readline().split(),
            helper.stdout.readline().split(),
        )
    }
    leader_pid, leader_pgid, leader_sid = observations['leader']
    child_pid, child_pgid, child_sid = observations['child']
    assert leader_pid == helper.pid
    assert (leader_pid, leader_pgid, leader_sid) == (
        helper.pid, helper.pid, helper.pid
    )
    assert child_pgid == child_pid
    assert child_pgid != leader_pgid
    assert child_sid == leader_sid

    registry = registry_module.ProcessRegistry(
        registry_module.RegistryPaths(
            directory=tmp_path / 'runtime',
            manifest=tmp_path / 'runtime' / 'process_registry.json',
            lock=tmp_path / 'runtime' / 'process_registry.lock',
        )
    )
    record = registry_module.ProcessRecord.from_identity(
        registry_module.capture_process_identity(leader_pid),
        component='simulation_launch',
        instance_id='second-pgid-orphan-test',
    )
    child_identity = registry_module.capture_process_identity(child_pid)
    assert child_identity.pgid == child_pgid
    assert child_identity.session_id == leader_sid
    record = replace(record, member_identities=(child_identity,))
    registry.register(record)

    try:
        helper.kill()
        helper.wait(timeout=3)
        assert registry_module.verify_captured_identity(child_identity) is True
        assert registry_module.process_group_exists(child_pgid) is True

        result = lifecycle.terminate_owned_process(
            registry,
            record,
            sigint_timeout=1.0,
            sigterm_timeout=1.0,
            sigkill_timeout=1.0,
        )
        assert result.success is True
        assert not registry_module.process_group_exists(child_pgid)
        assert registry.list_records() == []
    finally:
        try:
            os.killpg(child_pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            helper.wait(timeout=1)
        except subprocess.TimeoutExpired:
            helper.kill()
            helper.wait(timeout=1)


def test_dead_leader_ambiguous_group_refuses_signal(monkeypatch):
    record = record_for_self()
    monkeypatch.setattr(lifecycle, '_identity_status', lambda _r: ('absent', ''))
    monkeypatch.setattr(
        lifecycle, 'owned_process_group_status', lambda _r: 'ambiguous'
    )
    monkeypatch.setattr(
        lifecycle.os, 'killpg',
        lambda *_args: pytest.fail('ambiguous group must not be signaled'),
    )
    result = lifecycle.terminate_owned_process(RegistryStub(), record)
    assert result.success is False
    assert result.identity_verification_status == 'ambiguous'
    assert result.signal_result == 'refused'


def test_same_session_without_stable_owned_member_refuses_signal(monkeypatch):
    record = record_for_self()
    monkeypatch.setattr(lifecycle, '_identity_status', lambda _r: ('absent', ''))
    monkeypatch.setattr(
        lifecycle,
        'owned_process_group_ids',
        lambda _r: ('ambiguous', (record.pgid + 1,), ()),
    )
    monkeypatch.setattr(
        lifecycle.os,
        'killpg',
        lambda *_args: pytest.fail('unidentified same-session group was signaled'),
    )

    result = lifecycle.terminate_owned_process(RegistryStub(), record)

    assert result.success is False
    assert result.identity_verification_status == 'ambiguous'
    assert result.signal_result == 'refused'


def test_only_verified_owned_groups_are_signaled(monkeypatch):
    record = record_for_self()
    second_pgid = record.pgid + 9000
    sent = []
    calls = []
    identities = (record, replace(record, pid=second_pgid, pgid=second_pgid))
    monkeypatch.setattr(lifecycle, '_identity_status', lambda _r: ('verified', ''))
    monkeypatch.setattr(
        lifecycle,
        'owned_process_group_ids',
        lambda _r: (
            calls.append(True)
            or (
                ('absent', (), ())
                if len(calls) == 4
                else ('leader_verified', (record.pgid, second_pgid), identities)
            )
        ),
    )
    monkeypatch.setattr(
        lifecycle.os,
        'killpg',
        lambda pgid, signal_value: sent.append((pgid, signal_value)),
    )
    monkeypatch.setattr(lifecycle, '_wait_for_group_exit', lambda *args: True)

    result = lifecycle.terminate_owned_process(RegistryStub(), record)

    assert result.success is True
    assert {pgid for pgid, _ in sent} == {record.pgid, second_pgid}


def test_recovery_orders_modes_before_simulation(monkeypatch):
    simulation = record_for_self()
    simulation = replace(
        simulation, component='simulation_launch', instance_id='simulation'
    )
    mode = replace(
        simulation, component='mode_mapping', instance_id='mode'
    )

    class RecoveryRegistry(RegistryStub):
        def list_records(self):
            return [simulation, mode]

        def reconcile_stale_records(self):
            return []

    order = []
    monkeypatch.setattr(
        lifecycle,
        'terminate_owned_process',
        lambda _registry, record, **_kwargs: (
            order.append(record.component)
            or lifecycle.ShutdownResult(
                True, record.component, record.pid, record.pgid, 0.0
            )
        ),
    )
    lifecycle.recover_owned_processes(RecoveryRegistry())
    assert order == ['mode_mapping', 'simulation_launch']
