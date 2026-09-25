# Copyright 2026 Devansh Mishra
#
# Use of this source code is governed by an MIT-style
# license that can be found in the LICENSE file or at
# https://opensource.org/licenses/MIT.

"""Pure ordering and rollback policy for manager lifecycle transitions."""

from __future__ import annotations

from dataclasses import dataclass
import inspect
from threading import Lock
from typing import Mapping, Protocol
from uuid import uuid4

from managed_component import (
    LifecycleState, LifecycleTransition, TransitionResult, utc_now,
)


# One dependency order for the v0.1.2 manager control plane. Robot operating
# modes remain exclusively owned by mode_manager.
COMPONENT_ORDER = ('simulation', 'mapping', 'localization', 'navigation')

FORWARD = {LifecycleTransition.CONFIGURE, LifecycleTransition.ACTIVATE}
REVERSE = {
    LifecycleTransition.DEACTIVATE, LifecycleTransition.CLEANUP,
    LifecycleTransition.SHUTDOWN,
}
ROLLBACK = {
    LifecycleTransition.CONFIGURE: LifecycleTransition.CLEANUP,
    LifecycleTransition.ACTIVATE: LifecycleTransition.DEACTIVATE,
    LifecycleTransition.DEACTIVATE: LifecycleTransition.ACTIVATE,
    LifecycleTransition.CLEANUP: LifecycleTransition.CONFIGURE,
}
TARGET = {
    LifecycleTransition.CONFIGURE: LifecycleState.INACTIVE,
    LifecycleTransition.ACTIVATE: LifecycleState.ACTIVE,
    LifecycleTransition.DEACTIVATE: LifecycleState.INACTIVE,
    LifecycleTransition.CLEANUP: LifecycleState.UNCONFIGURED,
    LifecycleTransition.SHUTDOWN: LifecycleState.FINALIZED,
}


class ComponentPort(Protocol):
    @property
    def state(self) -> LifecycleState | None: ...

    def transition(self, operation: LifecycleTransition, **kwargs) -> TransitionResult: ...


@dataclass(frozen=True)
class OrchestrationResult:
    success: bool
    transition_id: str
    transition: LifecycleTransition
    code: str
    reason: str
    failed_dependency: str
    started_at: str
    completed_at: str
    results: tuple[TransitionResult, ...] = ()
    failure: TransitionResult | None = None
    rollback_results: tuple[TransitionResult, ...] = ()
    rollback_failures: tuple[TransitionResult, ...] = ()
    rollback_unavailable: tuple[str, ...] = ()


class PlatformLifecycleOrchestrator:
    """
    Apply a requested operation in dependency order.

    An identical request when all components already have the target state is
    a successful ALREADY_APPLIED no-op. A partially applied request proceeds
    in order; the component contract rejects invalid edges. On failure, only
    components changed during this request are rolled back. Shutdown has no
    inverse and reports finalized components as rollback_unavailable.
    """

    def __init__(self, components: Mapping[str, ComponentPort],
                 order: tuple[str, ...] = COMPONENT_ORDER) -> None:
        if not order or len(set(order)) != len(order):
            raise ValueError('component order must be nonempty and unique')
        if set(components) != set(order):
            raise ValueError('components must match dependency order')
        self.components = dict(components)
        self.order = tuple(order)
        self._lock = Lock()

    def _invoke(self, name: str,
                operation: LifecycleTransition,
                orchestration_id: str) -> TransitionResult:
        """Convert an adapter exception into a component failure report."""
        component = self.components[name]
        source = component.state
        started_at = utc_now()
        try:
            method = component.transition
            parameters = inspect.signature(method).parameters.values()
            accepts_correlation = any(
                parameter.name == 'orchestration_id'
                or parameter.kind == inspect.Parameter.VAR_KEYWORD
                for parameter in parameters
            )
            report = (
                method(operation, orchestration_id=orchestration_id)
                if accepts_correlation else method(operation)
            )
            if not isinstance(report, TransitionResult):
                raise TypeError('component did not return TransitionResult')
            if report.component != name or report.transition != operation:
                raise ValueError('component result identity does not match request')
            return report
        except Exception as error:
            current = component.state or source
            return TransitionResult(
                success=False, transition_id=str(uuid4()), component=name,
                transition=operation, source_state=source,
                destination_state=current, code='COMPONENT_EXCEPTION',
                reason=f'{type(error).__name__}: {error}',
                failed_dependency=name, started_at=started_at,
                completed_at=utc_now(),
                recovery_guidance='Inspect component adapter and lifecycle state.',
                orchestration_id=orchestration_id,
            )

    def transition(self, operation: LifecycleTransition) -> OrchestrationResult:
        started_at = utc_now()
        transition_id = str(uuid4())
        if not isinstance(operation, LifecycleTransition):
            operation = LifecycleTransition(operation)

        def result(success: bool, code: str, reason: str, **kwargs) -> OrchestrationResult:
            return OrchestrationResult(
                success=success, transition_id=transition_id,
                transition=operation, code=code, reason=reason,
                failed_dependency=kwargs.pop('failed_dependency', ''),
                started_at=started_at, completed_at=utc_now(), **kwargs,
            )

        if not self._lock.acquire(blocking=False):
            return result(False, 'BUSY', 'platform transition already in progress')
        try:
            if operation not in TARGET:
                return result(False, 'UNSUPPORTED_TRANSITION',
                              'platform supports configure, activate, '
                              'deactivate, cleanup, shutdown')
            unknown = next(
                (name for name in self.order if self.components[name].state is None),
                None,
            )
            if unknown is not None:
                return result(False, 'STATE_UNAVAILABLE',
                              f'no lifecycle state snapshot for {unknown}',
                              failed_dependency=unknown)
            target = TARGET[operation]
            if all(component.state == target for component in self.components.values()):
                return result(True, 'ALREADY_APPLIED',
                              f'all components already {target.value}')

            names = self.order if operation in FORWARD else tuple(reversed(self.order))
            completed: list[str] = []
            reports: list[TransitionResult] = []
            for name in names:
                component = self.components[name]
                if component.state == target:
                    continue
                report = self._invoke(name, operation, transition_id)
                reports.append(report)
                if not report.success:
                    rollback_results: list[TransitionResult] = []
                    unavailable: list[str] = []
                    inverse = ROLLBACK.get(operation)
                    for completed_name in reversed(completed):
                        if inverse is None:
                            unavailable.append(completed_name)
                            continue
                        rollback_results.append(self._invoke(
                            completed_name, inverse, transition_id,
                        ))
                    failures = tuple(item for item in rollback_results if not item.success)
                    return result(
                        False, 'DEPENDENCY_FAILED', report.reason,
                        failed_dependency=name, results=tuple(reports),
                        failure=report, rollback_results=tuple(rollback_results),
                        rollback_failures=failures,
                        rollback_unavailable=tuple(unavailable),
                    )
                completed.append(name)
            return result(True, 'SUCCESS', 'platform transition completed',
                          results=tuple(reports))
        finally:
            self._lock.release()
