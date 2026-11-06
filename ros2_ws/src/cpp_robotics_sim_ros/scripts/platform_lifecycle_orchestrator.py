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

    @staticmethod
    def _target_satisfied(component: ComponentPort,
                          target: LifecycleState) -> bool:
        """Use adapter provenance checks when available, then lifecycle state."""
        validator = getattr(component, 'target_satisfied', None)
        if callable(validator):
            return bool(validator(target))
        return component.state == target

    @staticmethod
    def _refresh(component: ComponentPort) -> bool:
        """Ask remote adapters for authoritative state when supported."""
        refresh = getattr(component, 'refresh_state', None)
        return not callable(refresh) or bool(refresh())

    @staticmethod
    def _snapshot_version(component: ComponentPort) -> tuple:
        """Return state and lifecycle transition identity after an authoritative read."""
        explicit = getattr(component, 'snapshot_version', None)
        if callable(explicit):
            explicit = explicit()
        return (component.state, explicit,
                getattr(component, 'last_transition_id', ''),
                getattr(component, 'last_transition', ''))

    def _stable_target_snapshot(self, target: LifecycleState) -> str | None:
        """
        Verify two consecutive authoritative state/version vectors agree.

        A successful result has an interval between the two complete reads in
        which every component held the target with unchanged transition identity.
        """
        first = {}
        for name in self.order:
            component = self.components[name]
            if not self._refresh(component):
                return f'{name}: authoritative lifecycle state unavailable'
            if not self._target_satisfied(component, target):
                return f'{name}: component does not satisfy {target.value}'
            first[name] = self._snapshot_version(component)
        for name in self.order:
            component = self.components[name]
            if not self._refresh(component):
                return f'{name}: authoritative lifecycle state unavailable'
            if (not self._target_satisfied(component, target)
                    or self._snapshot_version(component) != first[name]):
                return f'{name}: state or transition identity changed during verification'
        return None

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
            for name, component in self.components.items():
                if not self._refresh(component):
                    return result(False, 'STATE_UNAVAILABLE',
                                  f'authoritative lifecycle state unavailable for {name}',
                                  failed_dependency=name)
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
            if (target == LifecycleState.ACTIVE and any(
                    component.state == target
                    and not self._target_satisfied(component, target)
                    for component in self.components.values())):
                return result(False, 'STATE_UNVERIFIED',
                              'an ACTIVE snapshot has no verified activation provenance',
                              failed_dependency=next(
                                  name for name, component in self.components.items()
                                  if component.state == target
                                  and not self._target_satisfied(component, target)
                              ))
            if all(self._target_satisfied(component, target)
                   for component in self.components.values()):
                changed = self._stable_target_snapshot(target)
                if changed is None:
                    return result(True, 'ALREADY_APPLIED',
                                  f'all components already {target.value}')
                name = changed.split(':', 1)[0]
                unavailable = 'unavailable' in changed
                return result(False,
                              'STATE_UNAVAILABLE' if unavailable else 'STATE_CHANGED',
                              f'{changed} while verifying no-op',
                              failed_dependency=name)

            names = self.order if operation in FORWARD else tuple(reversed(self.order))
            completed: list[str] = []
            reports: list[TransitionResult] = []
            for name in names:
                component = self.components[name]
                if self._target_satisfied(component, target):
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
            changed = self._stable_target_snapshot(target)
            if changed is not None:
                name = changed.split(':', 1)[0]
                unavailable = 'unavailable' in changed
                return result(False,
                              'STATE_UNAVAILABLE' if unavailable else 'STATE_CHANGED',
                              f'{changed} during final verification',
                              failed_dependency=name, results=tuple(reports))
            return result(True, 'SUCCESS', 'platform transition completed',
                          results=tuple(reports))
        finally:
            self._lock.release()
