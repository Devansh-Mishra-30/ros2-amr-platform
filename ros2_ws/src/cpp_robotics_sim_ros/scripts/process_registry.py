#!/usr/bin/env python3
# Copyright 2026 Devansh Mishra
#
# Use of this source code is governed by an MIT-style
# license that can be found in the LICENSE file or at
# https://opensource.org/licenses/MIT.

"""File-backed process ownership records and Linux process identity checks."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, replace
import fcntl
import json
import os
from pathlib import Path
import stat
import tempfile
from typing import Iterator, Mapping
import uuid


SCHEMA_VERSION = 1
_ALLOWED_STATES = frozenset({'active', 'stopping', 'exited', 'stale'})


class RegistryFormatError(ValueError):
    """Raised when the registry manifest or one record is malformed."""


@dataclass(frozen=True)
class RegistryPaths:
    """Filesystem paths used by one per-user process registry."""

    directory: Path
    manifest: Path
    lock: Path

    @classmethod
    def default(cls) -> 'RegistryPaths':
        directory = Path.home() / '.ros' / 'cpp_robotics_sim'
        return cls(
            directory=directory,
            manifest=directory / 'process_registry.json',
            lock=directory / 'process_registry.lock',
        )


@dataclass(frozen=True)
class ProcessIdentity:
    """Stable identity snapshot captured from one live Linux process."""

    pid: int
    pgid: int
    session_id: int
    parent_pid: int
    proc_start_time: int
    exe: str
    cmdline_fingerprint: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> 'ProcessIdentity':
        required = (
            'pid', 'pgid', 'session_id', 'parent_pid', 'proc_start_time',
            'exe', 'cmdline_fingerprint',
        )
        missing = [key for key in required if key not in value]
        if missing:
            raise RegistryFormatError(
                'process identity missing fields: ' + ', '.join(missing)
            )
        identity = cls(
            pid=value['pid'],  # type: ignore[arg-type]
            pgid=value['pgid'],  # type: ignore[arg-type]
            session_id=value['session_id'],  # type: ignore[arg-type]
            parent_pid=value['parent_pid'],  # type: ignore[arg-type]
            proc_start_time=value['proc_start_time'],  # type: ignore[arg-type]
            exe=value['exe'],  # type: ignore[arg-type]
            cmdline_fingerprint=value['cmdline_fingerprint'],  # type: ignore[arg-type]
        )
        identity.validate()
        return identity

    def validate(self) -> None:
        for name in ('pid', 'pgid', 'session_id', 'proc_start_time'):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise RegistryFormatError(name + ' must be a positive integer')
        if (
            not isinstance(self.parent_pid, int)
            or isinstance(self.parent_pid, bool)
            or self.parent_pid < 0
        ):
            raise RegistryFormatError('parent_pid must be a non-negative integer')
        if not isinstance(self.exe, str) or not self.exe:
            raise RegistryFormatError('exe must be non-empty')
        if not isinstance(self.cmdline_fingerprint, str):
            raise RegistryFormatError('cmdline_fingerprint must be a string')

    def to_mapping(self) -> dict[str, object]:
        self.validate()
        return {
            'pid': self.pid,
            'pgid': self.pgid,
            'session_id': self.session_id,
            'parent_pid': self.parent_pid,
            'proc_start_time': self.proc_start_time,
            'exe': self.exe,
            'cmdline_fingerprint': self.cmdline_fingerprint,
        }


@dataclass(frozen=True)
class ProcessRecord:
    """One owned long-lived launch leader / process group."""

    schema_version: int
    instance_id: str
    component: str
    pid: int
    pgid: int
    session_id: int
    parent_pid: int
    proc_start_time: int
    exe: str
    cmdline_fingerprint: str
    member_identities: tuple[ProcessIdentity, ...] = ()
    state: str = 'active'

    @classmethod
    def from_identity(
        cls,
        identity: ProcessIdentity,
        component: str,
        instance_id: str | None = None,
        state: str = 'active',
    ) -> 'ProcessRecord':
        """Create a registry record from a captured process identity."""
        return cls(
            schema_version=SCHEMA_VERSION,
            instance_id=instance_id or uuid.uuid4().hex,
            component=component,
            pid=identity.pid,
            pgid=identity.pgid,
            session_id=identity.session_id,
            parent_pid=identity.parent_pid,
            proc_start_time=identity.proc_start_time,
            exe=identity.exe,
            cmdline_fingerprint=identity.cmdline_fingerprint,
            member_identities=(),
            state=state,
        )

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, object],
    ) -> 'ProcessRecord':
        """Parse and validate one JSON-compatible record mapping."""
        required = (
            'schema_version',
            'instance_id',
            'component',
            'pid',
            'pgid',
            'session_id',
            'parent_pid',
            'proc_start_time',
            'exe',
            'cmdline_fingerprint',
            'state',
        )
        missing = [key for key in required if key not in value]
        if missing:
            raise RegistryFormatError(
                'record missing fields: ' + ', '.join(missing)
            )
        raw_members = value.get('member_identities', [])
        if not isinstance(raw_members, list) or not all(
            isinstance(item, Mapping) for item in raw_members
        ):
            raise RegistryFormatError('member_identities must be a list of objects')

        record = cls(
            schema_version=value['schema_version'],  # type: ignore[arg-type]
            instance_id=value['instance_id'],  # type: ignore[arg-type]
            component=value['component'],  # type: ignore[arg-type]
            pid=value['pid'],  # type: ignore[arg-type]
            pgid=value['pgid'],  # type: ignore[arg-type]
            session_id=value['session_id'],  # type: ignore[arg-type]
            parent_pid=value['parent_pid'],  # type: ignore[arg-type]
            proc_start_time=value['proc_start_time'],  # type: ignore[arg-type]
            exe=value['exe'],  # type: ignore[arg-type]
            cmdline_fingerprint=value['cmdline_fingerprint'],  # type: ignore[arg-type]
            member_identities=tuple(
                ProcessIdentity.from_mapping(item)
                for item in raw_members
            ),
            state=value['state'],  # type: ignore[arg-type]
        )
        record.validate()
        return record

    def validate(self) -> None:
        """Validate fields that are persisted in the ownership manifest."""
        if (
            not isinstance(self.schema_version, int)
            or isinstance(self.schema_version, bool)
            or self.schema_version != SCHEMA_VERSION
        ):
            raise RegistryFormatError(
                'unsupported registry record schema version'
            )

        if not isinstance(self.instance_id, str) or not self.instance_id.strip():
            raise RegistryFormatError('instance_id must be non-empty')

        if not isinstance(self.component, str) or not self.component.strip():
            raise RegistryFormatError('component must be non-empty')

        for name in ('pid', 'pgid', 'session_id', 'proc_start_time'):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool):
                raise RegistryFormatError(name + ' must be an integer')
            if value <= 0:
                raise RegistryFormatError(
                    name + ' must be greater than zero'
                )

        if (
            not isinstance(self.parent_pid, int)
            or isinstance(self.parent_pid, bool)
        ):
            raise RegistryFormatError('parent_pid must be an integer')
        if self.parent_pid < 0:
            raise RegistryFormatError('parent_pid must be non-negative')

        if not isinstance(self.exe, str) or not self.exe:
            raise RegistryFormatError('exe must be non-empty')

        if not isinstance(self.cmdline_fingerprint, str):
            raise RegistryFormatError(
                'cmdline_fingerprint must be a string'
            )

        if not isinstance(self.member_identities, tuple):
            raise RegistryFormatError('member_identities must be a tuple')
        for identity in self.member_identities:
            if not isinstance(identity, ProcessIdentity):
                raise RegistryFormatError(
                    'member_identities entries must be process identities'
                )
            identity.validate()
            if identity.pid == self.pid:
                raise RegistryFormatError(
                    'member_identities must not repeat the launch leader'
                )
            if identity.session_id != self.session_id:
                raise RegistryFormatError(
                    'member identity is outside the recorded session'
                )

        if self.state not in _ALLOWED_STATES:
            raise RegistryFormatError('unsupported record state')

    def to_mapping(self) -> dict[str, object]:
        """Return a deterministic JSON-compatible record mapping."""
        self.validate()
        return {
            'schema_version': self.schema_version,
            'instance_id': self.instance_id,
            'component': self.component,
            'pid': self.pid,
            'pgid': self.pgid,
            'session_id': self.session_id,
            'parent_pid': self.parent_pid,
            'proc_start_time': self.proc_start_time,
            'exe': self.exe,
            'cmdline_fingerprint': self.cmdline_fingerprint,
            'member_identities': [
                identity.to_mapping() for identity in self.member_identities
            ],
            'state': self.state,
        }


def _parse_proc_stat(pid: int, text: str) -> tuple[int, int, int, int, int]:
    """Parse /proc/<pid>/stat even when the comm field has spaces or ')'."""
    opening = text.find('(')
    closing = text.rfind(')')
    if opening <= 0 or closing <= opening:
        raise ValueError('malformed /proc stat')

    try:
        parsed_pid = int(text[:opening].strip())
    except ValueError as error:
        raise ValueError('malformed /proc stat PID') from error

    if parsed_pid != pid:
        raise ValueError('unexpected /proc stat PID')

    # fields[0] is field 3 (state), fields[1] is PPID (field 4),
    # fields[2] is PGRP (field 5), fields[3] is session (field 6), and
    # fields[19] is starttime (field 22).
    fields = text[closing + 1:].strip().split()
    if len(fields) <= 19:
        raise ValueError('incomplete /proc stat')

    try:
        parent_pid = int(fields[1])
        pgid = int(fields[2])
        session_id = int(fields[3])
        start_time = int(fields[19])
    except ValueError as error:
        raise ValueError('malformed /proc stat fields') from error

    return parsed_pid, pgid, session_id, parent_pid, start_time


def _normalize_cmdline(raw: bytes) -> str:
    """Convert NUL-separated argv bytes into a stable JSON fingerprint."""
    arguments = [
        argument.decode('utf-8', errors='surrogateescape')
        for argument in raw.split(b'\0')
        if argument
    ]
    return json.dumps(
        arguments,
        ensure_ascii=True,
        separators=(',', ':'),
    )


def _read_process_snapshot(pid: int) -> tuple[int, int, int, int, str, str]:
    """Read one process snapshot from procfs."""
    proc_dir = Path('/proc') / str(pid)
    stat_text = (proc_dir / 'stat').read_text(encoding='utf-8')
    _, pgid, session_id, parent_pid, start_time = _parse_proc_stat(
        pid, stat_text
    )
    exe = os.path.realpath(os.readlink(proc_dir / 'exe'))
    cmdline = _normalize_cmdline((proc_dir / 'cmdline').read_bytes())
    return pgid, session_id, parent_pid, start_time, exe, cmdline


def capture_process_identity(pid: int) -> ProcessIdentity:
    """Capture a stable identity snapshot for one Linux process."""
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        raise ValueError('pid must be a positive integer')

    try:
        first = _read_process_snapshot(pid)
        second = _read_process_snapshot(pid)
    except FileNotFoundError as error:
        raise ProcessLookupError(pid) from error
    except PermissionError as error:
        raise PermissionError(
            'unable to inspect process identity for PID ' + str(pid)
        ) from error
    except OSError as error:
        raise OSError(
            'unable to inspect process identity for PID ' + str(pid)
        ) from error

    (
        first_pgid,
        first_session,
        first_parent,
        first_start,
        first_exe,
        first_cmdline,
    ) = first
    (
        second_pgid,
        second_session,
        _,
        second_start,
        second_exe,
        second_cmdline,
    ) = second

    if (
        first_pgid != second_pgid
        or first_session != second_session
        or first_start != second_start
        or first_exe != second_exe
        or first_cmdline != second_cmdline
    ):
        raise ProcessLookupError(
            'process identity changed while being inspected: ' + str(pid)
        )

    if first_cmdline == '[]':
        raise ProcessLookupError(
            'process command line is not stable yet: ' + str(pid)
        )

    return ProcessIdentity(
        pid=pid,
        pgid=first_pgid,
        session_id=first_session,
        parent_pid=first_parent,
        proc_start_time=first_start,
        exe=first_exe,
        cmdline_fingerprint=first_cmdline,
    )


def verify_process_identity(
    record: ProcessRecord | Mapping[str, object],
) -> bool:
    """Return true only when the recorded process still has the same identity."""
    try:
        if not isinstance(record, ProcessRecord):
            record = ProcessRecord.from_mapping(record)
        expected = ProcessIdentity(
            pid=record.pid,
            pgid=record.pgid,
            session_id=record.session_id,
            parent_pid=record.parent_pid,
            proc_start_time=record.proc_start_time,
            exe=record.exe,
            cmdline_fingerprint=record.cmdline_fingerprint,
        )
        return verify_captured_identity(expected)
    except (OSError, RegistryFormatError, ValueError):
        return False


def verify_captured_identity(expected: ProcessIdentity) -> bool:
    """Verify a leader or descendant identity, excluding mutable PPID."""
    try:
        expected.validate()
        current = capture_process_identity(expected.pid)
    except (OSError, RegistryFormatError, ValueError):
        return False

    # PPID is intentionally diagnostic-only: an owned process can be reparented
    # after its manager dies while still being the same process.
    return (
        current.pid == expected.pid
        and current.pgid == expected.pgid
        and current.session_id == expected.session_id
        and current.proc_start_time == expected.proc_start_time
        and current.exe == expected.exe
        and current.cmdline_fingerprint == expected.cmdline_fingerprint
    )


def process_group_exists(pgid: int) -> bool:
    """Return whether a process group exists without sending it a signal."""
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def process_group_session_ids(pgid: int) -> set[int]:
    """Return session IDs for every currently visible member of a group."""
    session_ids: set[int] = set()
    try:
        proc_entries = Path('/proc').iterdir()
    except OSError:
        return session_ids

    for entry in proc_entries:
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        try:
            stat_text = (entry / 'stat').read_text(encoding='utf-8')
            _, current_pgid, session_id, _, _ = _parse_proc_stat(
                pid, stat_text
            )
        except (OSError, ValueError):
            continue
        state = stat_text[stat_text.rfind(')') + 1:].strip().split()[0]
        if current_pgid == pgid and state != 'Z':
            session_ids.add(session_id)
    return session_ids


def capture_process_group_members(
    pgid: int,
    session_id: int,
    *,
    exclude_pid: int,
) -> tuple[ProcessIdentity, ...]:
    """Capture stable descendant identities for persisted crash recovery."""
    identities = []
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if pid == exclude_pid:
            continue
        try:
            identity = capture_process_identity(pid)
        except (OSError, ValueError):
            continue
        if identity.pgid == pgid and identity.session_id == session_id:
            identities.append(identity)
    return tuple(sorted(identities, key=lambda item: item.pid))


def capture_process_session_members(
    session_id: int,
    *,
    exclude_pid: int,
) -> tuple[ProcessIdentity, ...]:
    """Capture stable identities for every non-leader process in a session."""
    identities = []
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if pid == exclude_pid:
            continue
        try:
            identity = capture_process_identity(pid)
        except (OSError, ValueError):
            continue
        if identity.session_id == session_id:
            identities.append(identity)
    return tuple(sorted(identities, key=lambda item: item.pid))


def _session_process_groups(
    record: ProcessRecord,
) -> tuple[str, tuple[int, ...], tuple[ProcessIdentity, ...]]:
    """Classify and return only groups backed by verified owned identities."""
    expected = {
        identity.pid: identity
        for identity in (
            ProcessIdentity(
                pid=record.pid,
                pgid=record.pgid,
                session_id=record.session_id,
                parent_pid=record.parent_pid,
                proc_start_time=record.proc_start_time,
                exe=record.exe,
                cmdline_fingerprint=record.cmdline_fingerprint,
            ),
            *record.member_identities,
        )
    }
    current = capture_process_session_members(
        record.session_id,
        exclude_pid=-1,
    )
    leader_verified = verify_process_identity(record)
    if leader_verified:
        current = current + (
            expected[record.pid],
        ) if not any(item.pid == record.pid for item in current) else current

    if not current:
        return (
            ('ambiguous', (), ())
            if process_group_exists(record.pgid)
            else ('absent', (), ())
        )

    verified: list[ProcessIdentity] = []
    for identity in current:
        persisted = expected.get(identity.pid)
        if persisted is None or not verify_captured_identity(persisted):
            return 'ambiguous', (), tuple(current)
        verified.append(persisted)

    if not leader_verified and record.pid in {item.pid for item in current}:
        return 'ambiguous', (), tuple(current)

    groups = tuple(sorted({identity.pgid for identity in verified}))
    return (
        'leader_verified' if leader_verified else 'session_verified',
        groups,
        tuple(verified),
    )


def owned_process_group_ids(
    record: ProcessRecord,
) -> tuple[str, tuple[int, ...], tuple[ProcessIdentity, ...]]:
    """Return verified surviving groups and identities for one owned session."""
    try:
        return _session_process_groups(record)
    except (OSError, RegistryFormatError, ValueError):
        return 'ambiguous', (), ()


def owned_process_group_status(record: ProcessRecord) -> str:
    """Classify a persisted group without authorizing by PID or PGID alone."""
    status, _, _ = owned_process_group_ids(record)
    return status


def _open_nofollow(path: Path, flags: int, mode: int = 0o600) -> int:
    """Open a registry file without following a final-component symlink."""
    flags |= getattr(os, 'O_NOFOLLOW', 0)
    return os.open(path, flags, mode)


class ProcessRegistry:
    """Locked, atomically updated process ownership state for one Linux user."""

    def __init__(self, paths: RegistryPaths | None = None) -> None:
        self.paths = paths or RegistryPaths.default()

    def _ensure_directory(self) -> None:
        self.paths.directory.mkdir(
            parents=True,
            exist_ok=True,
            mode=0o700,
        )

        if self.paths.directory.is_symlink():
            raise OSError('registry directory must not be a symbolic link')

        if not self.paths.directory.is_dir():
            raise OSError('registry path is not a directory')

        directory_stat = self.paths.directory.stat()
        if directory_stat.st_uid != os.geteuid():
            raise PermissionError(
                'registry directory is not owned by the current user'
            )

        os.chmod(self.paths.directory, 0o700)

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self._ensure_directory()
        fd = _open_nofollow(
            self.paths.lock,
            os.O_RDWR | os.O_CREAT,
        )

        try:
            os.fchmod(fd, 0o600)
            lock_stat = os.fstat(fd)
            if not stat.S_ISREG(lock_stat.st_mode):
                raise OSError('registry lock must be a regular file')
            if lock_stat.st_uid != os.geteuid():
                raise PermissionError(
                    'registry lock is not owned by the current user'
                )
            handle = os.fdopen(fd, 'r+', encoding='utf-8')
        except BaseException:
            os.close(fd)
            raise

        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
        finally:
            handle.close()

    @staticmethod
    def _empty_manifest() -> dict[str, object]:
        return {
            'schema_version': SCHEMA_VERSION,
            'records': [],
        }

    def _read_manifest_unlocked(self) -> dict[str, object]:
        try:
            fd = _open_nofollow(self.paths.manifest, os.O_RDONLY)
        except FileNotFoundError:
            return self._empty_manifest()

        try:
            manifest_stat = os.fstat(fd)
            if not stat.S_ISREG(manifest_stat.st_mode):
                raise OSError('registry manifest must be a regular file')
            if manifest_stat.st_uid != os.geteuid():
                raise PermissionError(
                    'registry manifest is not owned by the current user'
                )
            handle = os.fdopen(fd, 'r', encoding='utf-8')
        except BaseException:
            try:
                os.close(fd)
            except OSError:
                pass
            raise

        try:
            with handle:
                payload = json.load(handle)
        except json.JSONDecodeError as error:
            raise RegistryFormatError(
                'registry manifest is not valid JSON'
            ) from error

        if not isinstance(payload, dict):
            raise RegistryFormatError('registry manifest must be an object')

        if payload.get('schema_version') != SCHEMA_VERSION:
            raise RegistryFormatError('unsupported registry schema version')

        records = payload.get('records')
        if not isinstance(records, list):
            raise RegistryFormatError('registry records must be a list')

        parsed: list[ProcessRecord] = []
        for record in records:
            if not isinstance(record, Mapping):
                raise RegistryFormatError('registry record must be an object')
            parsed.append(ProcessRecord.from_mapping(record))

        return {
            'schema_version': SCHEMA_VERSION,
            'records': parsed,
        }

    def _atomic_write_unlocked(
        self,
        manifest: dict[str, object],
    ) -> None:
        records = manifest.get('records')
        if not isinstance(records, list):
            raise RegistryFormatError('registry records must be a list')

        payload = {
            'schema_version': SCHEMA_VERSION,
            'records': [record.to_mapping() for record in records],
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        ) + '\n'

        self._ensure_directory()
        temp_fd, temp_name = tempfile.mkstemp(
            prefix='.process_registry.',
            dir=self.paths.directory,
        )
        temp_path = Path(temp_name)

        try:
            os.fchmod(temp_fd, 0o600)
            with os.fdopen(temp_fd, 'w', encoding='utf-8') as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())

            os.replace(temp_path, self.paths.manifest)

            directory_fd = os.open(
                self.paths.directory,
                os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0),
            )
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except BaseException:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass
            raise

    def _records_unlocked(self) -> list[ProcessRecord]:
        payload = self._read_manifest_unlocked()
        records = payload['records']
        assert isinstance(records, list)
        return list(records)

    def load(self) -> list[ProcessRecord]:
        """Load records, initializing a valid empty manifest if needed."""
        with self._locked():
            records = self._records_unlocked()
            if not self.paths.manifest.exists():
                self._atomic_write_unlocked(
                    {
                        'schema_version': SCHEMA_VERSION,
                        'records': records,
                    }
                )
            return records

    def list_records(self) -> list[ProcessRecord]:
        """Return current ownership records without changing them."""
        return self.load()

    def register(self, record: ProcessRecord) -> None:
        """Insert or replace one record under the registry lock."""
        record.validate()
        with self._locked():
            records = self._records_unlocked()
            records = [
                existing
                for existing in records
                if existing.instance_id != record.instance_id
            ]
            records.append(record)
            records.sort(key=lambda item: item.instance_id)
            self._atomic_write_unlocked(
                {
                    'schema_version': SCHEMA_VERSION,
                    'records': records,
                }
            )

    def register_unique(self, record: ProcessRecord) -> None:
        """Register one live component, rejecting an existing live owner."""
        record.validate()
        with self._locked():
            records = self._records_unlocked()
            active: list[ProcessRecord] = []

            for existing in records:
                if owned_process_group_status(existing) != 'absent':
                    active.append(existing)

            duplicates = [
                existing
                for existing in active
                if existing.component == record.component
                and existing.instance_id != record.instance_id
            ]
            if duplicates:
                owner = duplicates[0]
                raise RuntimeError(
                    f'component {record.component!r} already has an active '
                    'or ambiguous owner '
                    f'(PID {owner.pid}, instance {owner.instance_id})'
                )

            active = [
                existing
                for existing in active
                if existing.instance_id != record.instance_id
            ]
            active.append(record)
            active.sort(key=lambda item: item.instance_id)
            self._atomic_write_unlocked(
                {
                    'schema_version': SCHEMA_VERSION,
                    'records': active,
                }
            )

    def refresh_group_members(self, record: ProcessRecord) -> ProcessRecord:
        """Persist verified descendants without weakening leader ownership."""
        if not verify_process_identity(record):
            raise RuntimeError(
                'cannot refresh descendants for an unverified launch leader'
            )
        members = capture_process_session_members(
            record.session_id,
            exclude_pid=record.pid,
        )
        if not members:
            raise RuntimeError(
                'managed launch group has no stable descendant identity'
            )
        if not verify_process_identity(record):
            raise RuntimeError(
                'launch leader identity changed while descendants were captured'
            )
        updated = replace(record, member_identities=members)
        updated.validate()
        with self._locked():
            records = self._records_unlocked()
            matching = [
                existing
                for existing in records
                if existing.instance_id == record.instance_id
            ]
            if matching != [record]:
                raise RuntimeError('ownership record changed during refresh')
            records = [
                updated if existing.instance_id == record.instance_id else existing
                for existing in records
            ]
            self._atomic_write_unlocked(
                {'schema_version': SCHEMA_VERSION, 'records': records}
            )
        return updated

    def duplicate_components(self) -> dict[str, list[ProcessRecord]]:
        """Return verified live ownership duplicates grouped by component."""
        with self._locked():
            records = self._records_unlocked()
            active = [
                record
                for record in records
                if owned_process_group_status(record)
                in ('leader_verified', 'session_verified')
            ]

        grouped: dict[str, list[ProcessRecord]] = {}
        for record in active:
            grouped.setdefault(record.component, []).append(record)
        return {
            component: items
            for component, items in grouped.items()
            if len(items) > 1
        }

    def deregister(self, instance_id: str) -> bool:
        """Remove one record and return whether it existed."""
        if not isinstance(instance_id, str) or not instance_id.strip():
            raise ValueError('instance_id must be non-empty')

        with self._locked():
            records = self._records_unlocked()
            remaining = [
                record
                for record in records
                if record.instance_id != instance_id
            ]
            removed = len(remaining) != len(records)
            if removed:
                self._atomic_write_unlocked(
                    {
                        'schema_version': SCHEMA_VERSION,
                        'records': remaining,
                    }
                )
            return removed

    def reconcile_stale_records(self) -> list[ProcessRecord]:
        """Remove records only when identity and process group are both gone."""
        with self._locked():
            records = self._records_unlocked()
            active: list[ProcessRecord] = []
            stale: list[ProcessRecord] = []

            for record in records:
                if owned_process_group_status(record) != 'absent':
                    active.append(record)
                else:
                    stale.append(record)

            if stale:
                self._atomic_write_unlocked(
                    {
                        'schema_version': SCHEMA_VERSION,
                        'records': active,
                    }
                )

            return stale
