#!/usr/bin/env python3
# Copyright 2026 Devansh Mishra
#
# Use of this source code is governed by an MIT-style
# license that can be found in the LICENSE file or at
# https://opensource.org/licenses/MIT.

"""Identity-safe registration and bounded process-group termination."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
from typing import Callable, Optional

from process_registry import (
    capture_process_identity,
    owned_process_group_ids,
    owned_process_group_status,
    process_group_exists as kernel_process_group_exists,
    process_group_session_ids,
    ProcessRecord,
    ProcessRegistry,
)


@dataclass
class SignalAttempt:
    signal: str
    identity_status: str
    result: str


@dataclass
class ShutdownResult:
    success: bool
    component: str
    pid: Optional[int]
    pgid: Optional[int]
    total_duration_seconds: float
    failed_stage: str = ''
    identity_verification_status: str = 'not_checked'
    signals_attempted: list[SignalAttempt] = field(default_factory=list)
    signal_result: str = ''
    surviving_owned_records: list[str] = field(default_factory=list)
    surviving_pgids: list[int] = field(default_factory=list)
    surviving_pids: list[int] = field(default_factory=list)
    remaining_critical_ros_nodes: list[str] = field(default_factory=list)
    error: str = ''
    stages_completed: list[str] = field(default_factory=list)

    def to_mapping(self) -> dict[str, object]:
        return asdict(self)


def _identity_status(record: ProcessRecord) -> tuple[str, str]:
    try:
        current = capture_process_identity(record.pid)
    except ProcessLookupError:
        return 'absent', ''
    except (OSError, ValueError) as error:
        return 'unverifiable', str(error)

    fields = (
        ('pgid', current.pgid, record.pgid),
        ('session_id', current.session_id, record.session_id),
        ('start_time', current.proc_start_time, record.proc_start_time),
        ('executable', current.exe, record.exe),
        ('command_line', current.cmdline_fingerprint, record.cmdline_fingerprint),
    )
    mismatches = [name for name, actual, expected in fields if actual != expected]
    if mismatches:
        return 'mismatch', ', '.join(mismatches)
    return 'verified', ''


def process_group_exists(pgid: int) -> bool:
    return bool(process_group_session_ids(pgid)) or kernel_process_group_exists(
        pgid
    )


@contextmanager
def defer_termination_signals():
    """Prevent a repeated launcher signal from interrupting bounded cleanup."""
    previous = {}
    for signal_value in (signal.SIGINT, signal.SIGTERM):
        previous[signal_value] = signal.getsignal(signal_value)
        signal.signal(signal_value, signal.SIG_IGN)
    try:
        yield
    finally:
        for signal_value, handler in previous.items():
            signal.signal(signal_value, handler)


def _wait_for_group_exit(
    pgid: int,
    timeout: float,
    process: Optional[subprocess.Popen],
    sleep: Callable[[float], None],
) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process is not None:
            process.poll()
        if not process_group_exists(pgid):
            return True
        sleep(0.05)
    if process is not None:
        process.poll()
    return not process_group_exists(pgid)


def deregister_exited_process(
    registry: ProcessRegistry,
    record: ProcessRecord,
) -> bool:
    """Deregister an exited leader only when no group member remains."""
    if owned_process_group_status(record) != 'absent':
        return False
    registry.deregister(record.instance_id)
    return True


def _rollback_created_process(process: subprocess.Popen) -> None:
    """Kill a directly created session after ownership registration fails."""
    if process.poll() is not None:
        return

    try:
        pgid = os.getpgid(process.pid)
    except ProcessLookupError:
        process.poll()
        return

    try:
        if pgid == process.pid:
            os.killpg(pgid, signal.SIGKILL)
        else:
            process.kill()
        process.wait(timeout=1.0)
    except (OSError, subprocess.SubprocessError) as error:
        raise RuntimeError(
            'registration failed and the new child could not be rolled back'
        ) from error

    if pgid == process.pid and process_group_exists(pgid):
        raise RuntimeError(
            'registration failed and the new child process group survived '
            'rollback'
        )


def register_managed_process(
    registry: ProcessRegistry,
    process: subprocess.Popen,
    component: str,
) -> ProcessRecord:
    """Capture and persist a newly created child or stop it on failure."""
    record: Optional[ProcessRecord] = None
    try:
        deadline = time.monotonic() + 1.0
        while True:
            try:
                identity = capture_process_identity(process.pid)
                break
            except ProcessLookupError:
                if process.poll() is not None or time.monotonic() >= deadline:
                    raise
                time.sleep(0.01)
        if identity.pgid != process.pid:
            raise RuntimeError(
                'managed child is not the leader of its process group'
            )
        if identity.session_id != process.pid:
            raise RuntimeError(
                'managed child is not the leader of its operating-system '
                'session'
            )
        record = ProcessRecord.from_identity(identity, component=component)
        registry.register_unique(record)
        return record
    except BaseException as registration_error:
        if record is not None:
            rollback = terminate_owned_process(
                registry,
                record,
                process=process,
                sigint_timeout=1.0,
                sigterm_timeout=1.0,
                sigkill_timeout=1.0,
                deregister=False,
            )
            if not rollback.success:
                raise RuntimeError(
                    'registration failed and the new child process group '
                    f'could not be rolled back: {rollback.error}'
                ) from registration_error
        else:
            _rollback_created_process(process)
        raise registration_error


def terminate_owned_process(
    registry: ProcessRegistry,
    record: ProcessRecord,
    *,
    process: Optional[subprocess.Popen] = None,
    sigint_timeout: float = 10.0,
    sigterm_timeout: float = 3.0,
    sigkill_timeout: float = 3.0,
    deregister: bool = True,
    sleep: Callable[[float], None] = time.sleep,
) -> ShutdownResult:
    """Stop a verified process group with bounded, revalidated escalation."""
    started = time.monotonic()
    attempts: list[SignalAttempt] = []

    def result(success: bool, **values) -> ShutdownResult:
        if success and deregister:
            registry.deregister(record.instance_id)
        return ShutdownResult(
            success=success,
            component=record.component,
            pid=record.pid,
            pgid=record.pgid,
            total_duration_seconds=round(time.monotonic() - started, 6),
            signals_attempted=attempts,
            **values,
        )

    stages = (
        (signal.SIGINT, sigint_timeout),
        (signal.SIGTERM, sigterm_timeout),
        (signal.SIGKILL, sigkill_timeout),
    )
    identity_status = 'not_checked'
    for signal_value, timeout in stages:
        leader_status, leader_detail = _identity_status(record)
        if leader_status in ('mismatch', 'unverifiable'):
            attempts.append(
                SignalAttempt(signal_value.name, leader_status, 'refused')
            )
            return result(
                False,
                failed_stage=signal_value.name,
                identity_verification_status=leader_status,
                signal_result='refused',
                surviving_owned_records=[record.instance_id],
                error='ownership verification failed: ' + leader_detail,
            )
        identity_status, groups, identities = owned_process_group_ids(record)
        surviving_pids = sorted(identity.pid for identity in identities)
        if identity_status == 'absent':
            return result(
                True,
                identity_verification_status='absent',
                signal_result='already_exited',
            )
        if identity_status not in ('leader_verified', 'session_verified'):
            attempts.append(
                SignalAttempt(signal_value.name, identity_status, 'refused')
            )
            return result(
                False,
                failed_stage=signal_value.name,
                identity_verification_status=identity_status,
                signal_result='refused',
                surviving_owned_records=[record.instance_id],
                surviving_pgids=sorted({identity.pgid for identity in identities}),
                surviving_pids=surviving_pids,
                error=(
                    'owned session contains a process without a verified '
                    'persisted identity'
                ),
            )

        for pgid in groups:
            # Revalidate immediately before every signal, including each group
            # in a multi-group session and every escalation stage.
            current_status, current_groups, current_identities = (
                owned_process_group_ids(record)
            )
            if current_status == 'absent':
                break
            if current_status not in ('leader_verified', 'session_verified'):
                attempts.append(
                    SignalAttempt(signal_value.name, current_status, 'refused')
                )
                return result(
                    False,
                    failed_stage=signal_value.name,
                    identity_verification_status=current_status,
                    signal_result='refused',
                    surviving_owned_records=[record.instance_id],
                    surviving_pgids=sorted(
                        {identity.pgid for identity in current_identities}
                    ),
                    surviving_pids=sorted(
                        identity.pid for identity in current_identities
                    ),
                    error='ownership changed before signal delivery',
                )
            if pgid not in current_groups:
                continue
            try:
                os.killpg(pgid, signal_value)
            except ProcessLookupError:
                attempts.append(
                    SignalAttempt(
                        signal_value.name, current_status, 'already_exited'
                    )
                )
                continue
            except OSError as error:
                attempts.append(
                    SignalAttempt(signal_value.name, current_status, 'error')
                )
                return result(
                    False,
                    failed_stage=signal_value.name,
                    identity_verification_status=current_status,
                    signal_result='error',
                    surviving_owned_records=[record.instance_id],
                    surviving_pgids=list(current_groups),
                    surviving_pids=sorted(
                        identity.pid for identity in current_identities
                    ),
                    error=str(error),
                )
            attempts.append(SignalAttempt(signal_value.name, current_status, 'sent'))

        for pgid in groups:
            _wait_for_group_exit(pgid, timeout, process, sleep)

        # Rescan after every escalation stage. Only a fully absent owned
        # session is allowed to deregister.
        identity_status, remaining_groups, identities = owned_process_group_ids(
            record
        )
        if identity_status == 'absent':
            return result(
                True,
                identity_verification_status='absent',
                signal_result='exited',
            )
        if identity_status == 'ambiguous':
            return result(
                False,
                failed_stage=signal_value.name,
                identity_verification_status=identity_status,
                signal_result='refused',
                surviving_owned_records=[record.instance_id],
                surviving_pgids=sorted(
                    {identity.pgid for identity in identities}
                ),
                surviving_pids=sorted(identity.pid for identity in identities),
                error='ownership became ambiguous after signal delivery',
            )

    return result(
        False,
        failed_stage='SIGKILL_WAIT',
        identity_verification_status=identity_status,
        signal_result='survived',
        surviving_owned_records=[record.instance_id],
        surviving_pgids=list(remaining_groups),
        surviving_pids=sorted(identity.pid for identity in identities),
        error='owned process groups survived SIGKILL timeout',
    )


def recovery_order(record: ProcessRecord) -> tuple[int, str, str]:
    """Stop mode groups before the simulation group during reconciliation."""
    if record.component.startswith('mode_'):
        priority = 0
    elif record.component == 'simulation_launch':
        priority = 1
    else:
        priority = 2
    return priority, record.component, record.instance_id


def recover_owned_processes(
    registry: ProcessRegistry,
    *,
    sigint_timeout: float = 4.0,
    sigterm_timeout: float = 1.5,
    sigkill_timeout: float = 1.5,
) -> list[ShutdownResult]:
    """Reconcile all persisted owners in deterministic dependency order."""
    reports = []
    for record in sorted(registry.list_records(), key=recovery_order):
        reports.append(
            terminate_owned_process(
                registry,
                record,
                sigint_timeout=sigint_timeout,
                sigterm_timeout=sigterm_timeout,
                sigkill_timeout=sigkill_timeout,
            )
        )
    registry.reconcile_stale_records()
    return reports


def write_json_atomic(path: Path, payload: object) -> None:
    """Persist private JSON diagnostics atomically."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix='.' + path.name + '.', dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


def persist_shutdown_result(
    report: ShutdownResult,
    *,
    runtime_directory: Optional[Path] = None,
) -> Path:
    """Persist a component-specific report for use after ROS is unavailable."""
    directory = runtime_directory or (
        Path.home() / '.ros' / 'cpp_robotics_sim' / 'shutdown_reports'
    )
    safe_component = ''.join(
        character if character.isalnum() or character in ('_', '-') else '_'
        for character in report.component
    )
    path = directory / f'{safe_component}.json'
    write_json_atomic(path, report.to_mapping())
    return path


def _run_recovery(report_path: Optional[Path]) -> int:
    registry = ProcessRegistry()
    reports = recover_owned_processes(registry)
    remaining = [record.to_mapping() for record in registry.list_records()]
    payload = {
        'success': all(report.success for report in reports) and not remaining,
        'reports': [report.to_mapping() for report in reports],
        'remaining_records': remaining,
    }
    if report_path is not None:
        write_json_atomic(report_path, payload)
    else:
        json.dump(payload, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write('\n')
    return 0 if payload['success'] else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Identity-safe cleanup for registered AMR process groups.'
    )
    parser.add_argument('--recover', action='store_true')
    parser.add_argument('--report', type=Path)
    arguments = parser.parse_args()
    if not arguments.recover:
        parser.error('--recover is required')
    return _run_recovery(arguments.report)


if __name__ == '__main__':
    raise SystemExit(main())
