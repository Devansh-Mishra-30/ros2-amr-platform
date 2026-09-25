#!/usr/bin/env python3
# Copyright 2026 Devansh Mishra
#
# Use of this source code is governed by an MIT-style
# license that can be found in the LICENSE file or at
# https://opensource.org/licenses/MIT.

"""
Pure-Python lifecycle contract for control-plane components.

Hooks perform domain work. This module alone owns lifecycle state changes.
Process ownership and runtime readiness remain outside this contract.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from threading import Lock
from typing import Any, Protocol
from uuid import uuid4


class LifecycleState(str, Enum):
    UNCONFIGURED = 'unconfigured'
    INACTIVE = 'inactive'
    ACTIVE = 'active'
    ERROR = 'error'
    FINALIZED = 'finalized'


class LifecycleTransition(str, Enum):
    CONFIGURE = 'configure'
    ACTIVATE = 'activate'
    DEACTIVATE = 'deactivate'
    CLEANUP = 'cleanup'
    SHUTDOWN = 'shutdown'
    ERROR = 'error'
    RECOVER = 'recover'


LEGAL_TRANSITIONS = {
    LifecycleTransition.CONFIGURE: ({LifecycleState.UNCONFIGURED}, LifecycleState.INACTIVE),
    LifecycleTransition.ACTIVATE: ({LifecycleState.INACTIVE}, LifecycleState.ACTIVE),
    LifecycleTransition.DEACTIVATE: ({LifecycleState.ACTIVE}, LifecycleState.INACTIVE),
    LifecycleTransition.CLEANUP: ({LifecycleState.INACTIVE}, LifecycleState.UNCONFIGURED),
    LifecycleTransition.SHUTDOWN: (
        {LifecycleState.UNCONFIGURED, LifecycleState.INACTIVE,
         LifecycleState.ACTIVE, LifecycleState.ERROR}, LifecycleState.FINALIZED),
    LifecycleTransition.ERROR: (
        {LifecycleState.UNCONFIGURED, LifecycleState.INACTIVE,
         LifecycleState.ACTIVE}, LifecycleState.ERROR),
    LifecycleTransition.RECOVER: ({LifecycleState.ERROR}, LifecycleState.UNCONFIGURED),
}


class LifecycleHooks(Protocol):
    def on_configure(self) -> None: ...
    def on_activate(self) -> None: ...
    def on_deactivate(self) -> None: ...
    def on_cleanup(self) -> None: ...
    def on_shutdown(self) -> None: ...
    def on_error(self) -> None: ...
    def on_recover(self) -> bool: ...
    def on_rollback(self, transition: LifecycleTransition,
                    source_state: LifecycleState) -> bool: ...


@dataclass(frozen=True)
class RetryPolicy:
    max_retries: int = 0
    retry_safe: frozenset[LifecycleTransition] = frozenset()

    def __post_init__(self) -> None:
        if isinstance(self.max_retries, bool) or not isinstance(self.max_retries, int):
            raise ValueError('max_retries must be an integer')
        if not 0 <= self.max_retries <= 3:
            raise ValueError('max_retries must be between 0 and 3')
        object.__setattr__(
            self, 'retry_safe',
            frozenset(LifecycleTransition(item) for item in self.retry_safe),
        )
        if not self.retry_safe.issubset({
            LifecycleTransition.CONFIGURE, LifecycleTransition.ACTIVATE,
            LifecycleTransition.DEACTIVATE, LifecycleTransition.CLEANUP,
        }):
            raise ValueError('only reversible transitions may be retry-safe')


@dataclass(frozen=True)
class TransitionResult:
    success: bool
    transition_id: str
    component: str
    transition: LifecycleTransition | str
    source_state: LifecycleState
    destination_state: LifecycleState
    code: str
    reason: str
    failed_dependency: str
    started_at: str
    completed_at: str
    recovery_guidance: str
    rollback_performed: bool = False
    rollback_result: str = ''
    attempts: int = 0
    orchestration_id: str = ''

    def to_mapping(self) -> dict[str, Any]:
        result = asdict(self)
        for key in ('transition', 'source_state', 'destination_state'):
            result[key] = getattr(result[key], 'value', result[key])
        return result


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ManagedComponent:
    """
    Serialize and validate one manager's lifecycle transitions.

    on_rollback(transition, source_state) must return True to authorize a retry.
    on_recover must return True only after domain cleanup has been verified.
    An unhandled hook failure enters ERROR, including when a rollback succeeds
    after the final retry. Hooks must not modify lifecycle state directly.
    """

    def __init__(self, name: str, hooks: LifecycleHooks,
                 retry_policy: RetryPolicy = RetryPolicy()) -> None:
        if not name.strip():
            raise ValueError('component name must not be empty')
        self.name = name
        self._hooks = hooks
        self._retry_policy = retry_policy
        self.__state = LifecycleState.UNCONFIGURED
        self._lock = Lock()
        self._last_transition_id = ''

    @property
    def state(self) -> LifecycleState:
        return self.__state

    @property
    def last_transition_id(self) -> str:
        return self._last_transition_id

    def transition(self, operation: LifecycleTransition,
                   *, reason: str = '', failed_dependency: str = '',
                   orchestration_id: str = '') -> TransitionResult:
        started_at = utc_now()
        transition_id = str(uuid4())
        if not isinstance(operation, LifecycleTransition):
            try:
                operation = LifecycleTransition(operation)
            except (ValueError, TypeError):
                source = self.__state
                return TransitionResult(
                    success=False, transition_id=transition_id,
                    component=self.name, transition=str(operation),
                    source_state=source, destination_state=source,
                    code='INVALID_TRANSITION',
                    reason=f'unknown lifecycle transition: {operation}',
                    failed_dependency=failed_dependency,
                    started_at=started_at, completed_at=utc_now(),
                    recovery_guidance='Use a defined lifecycle transition.',
                )

        def result(success: bool, source: LifecycleState, code: str,
                   details: str, *, rollback_performed: bool = False,
                   rollback_result: str = '', attempts: int = 0,
                   destination_override: LifecycleState | None = None) -> TransitionResult:
            return TransitionResult(
                success=success, transition_id=transition_id, component=self.name,
                transition=operation, source_state=source,
                destination_state=(
                    self.__state if destination_override is None
                    else destination_override
                ), code=code, reason=details,
                failed_dependency=failed_dependency, started_at=started_at,
                completed_at=utc_now(),
                recovery_guidance=(
                    '' if success else
                    'Resolve the cause; if in ERROR, run verified recover then configure.'
                ), rollback_performed=rollback_performed,
                rollback_result=rollback_result, attempts=attempts,
                orchestration_id=orchestration_id,
            )

        # Reject without waiting, so concurrent attempts have a stable outcome.
        if not self._lock.acquire(blocking=False):
            snapshot = self.__state
            return result(False, snapshot, 'BUSY', 'transition already in progress',
                          destination_override=snapshot)
        try:
            source = self.__state
            allowed, destination = LEGAL_TRANSITIONS[operation]
            if source not in allowed:
                return result(False, source, 'ILLEGAL_TRANSITION',
                              f'{operation.value} is illegal from {source.value}')

            if operation == LifecycleTransition.ERROR:
                self.__state = LifecycleState.ERROR
                self._last_transition_id = transition_id
                try:
                    self._hooks.on_error()
                except Exception as error:
                    return result(False, source, 'ERROR_HOOK_FAILED',
                                  f'{reason}; on_error: {type(error).__name__}: {error}')
                return result(True, source, 'SUCCESS', reason or 'runtime lifecycle fault')

            max_attempts = 1 + (
                self._retry_policy.max_retries
                if operation in self._retry_policy.retry_safe else 0
            )
            rollback_performed = False
            rollback_result = ''
            for attempt in range(1, max_attempts + 1):
                try:
                    hook = getattr(self._hooks, f'on_{operation.value}')
                    verification = hook()
                    if verification is False:
                        raise RuntimeError(f'{operation.value} hook returned False')
                    if operation == LifecycleTransition.RECOVER and verification is not True:
                        raise RuntimeError('recovery cleanup was not verified')
                except Exception as error:
                    detail = f'{type(error).__name__}: {error}'
                    if attempt < max_attempts:
                        rollback_performed = True
                        try:
                            rollback = getattr(self._hooks, 'on_rollback')
                            verified = rollback(operation, source)
                            if verified is not True:
                                raise RuntimeError('rollback to source state was not verified')
                            rollback_result = 'SUCCESS'
                        except Exception as rollback_error:
                            rollback_result = (
                                f'{type(rollback_error).__name__}: {rollback_error}'
                            )
                            return self._enter_error(
                                source, transition_id, result, 'ROLLBACK_FAILED',
                                f'{detail}; rollback: {rollback_result}',
                                rollback_performed, rollback_result, attempt,
                            )
                        continue

                    if operation == LifecycleTransition.RECOVER:
                        return result(False, source, 'RECOVERY_FAILED', detail,
                                      attempts=attempt)
                    code = 'RETRY_EXHAUSTED' if max_attempts > 1 else 'HOOK_FAILED'
                    return self._enter_error(
                        source, transition_id, result, code, detail,
                        rollback_performed, rollback_result, attempt,
                    )

                self.__state = destination
                self._last_transition_id = transition_id
                return result(True, source, 'SUCCESS', reason or 'transition completed',
                              rollback_performed=rollback_performed,
                              rollback_result=rollback_result, attempts=attempt)

            raise AssertionError('unreachable transition attempt state')
        finally:
            self._lock.release()

    def _enter_error(self, source: LifecycleState, transition_id: str,
                     make_result: Any, code: str, detail: str,
                     rollback_performed: bool, rollback_result: str,
                     attempt: int) -> TransitionResult:
        self.__state = LifecycleState.ERROR
        self._last_transition_id = transition_id
        try:
            self._hooks.on_error()
        except Exception as error:
            detail += f'; on_error: {type(error).__name__}: {error}'
        return make_result(
            False, source, code, detail, rollback_performed=rollback_performed,
            rollback_result=rollback_result, attempts=attempt,
        )
