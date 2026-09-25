# Copyright 2026 Devansh Mishra
#
# Use of this source code is governed by an MIT-style
# license that can be found in the LICENSE file or at
# https://opensource.org/licenses/MIT.

"""Orchestration order and failure behavior with manager fixtures."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

from managed_component import (  # noqa: E402
    LifecycleState as State,
    LifecycleTransition as Transition,
    ManagedComponent,
)
from platform_lifecycle_orchestrator import PlatformLifecycleOrchestrator  # noqa: E402


class Hooks:
    def __init__(self, name, log, fail=None):
        self.name, self.log, self.fail = name, log, fail

    def _run(self, operation):
        self.log.append((self.name, operation))
        if self.fail == operation:
            raise RuntimeError(f'{self.name} {operation} failed')

    def on_configure(self): self._run('configure')
    def on_activate(self): self._run('activate')
    def on_deactivate(self): self._run('deactivate')
    def on_cleanup(self): self._run('cleanup')
    def on_shutdown(self): self._run('shutdown')
    def on_error(self): self._run('error')
    def on_recover(self): return True


def make_platform(fail=None):
    log = []
    names = ('simulation', 'mapping', 'localization', 'navigation')
    components = {
        name: ManagedComponent(
            name, Hooks(name, log, fail if name == 'localization' else None)
        )
        for name in names
    }
    return PlatformLifecycleOrchestrator(components, names), components, log


def test_forward_and_reverse_order_and_repeat_policy():
    platform, components, log = make_platform()
    assert platform.transition(Transition.CONFIGURE).success
    assert [name for name, operation in log if operation == 'configure'] == list(
        components
    )
    repeated = platform.transition(Transition.CONFIGURE)
    assert repeated.success and repeated.code == 'ALREADY_APPLIED'
    assert len(log) == 4
    assert platform.transition(Transition.ACTIVATE).success
    assert platform.transition(Transition.DEACTIVATE).success
    assert [name for name, operation in log if operation == 'deactivate'] == list(
        reversed(components)
    )
    assert platform.transition(Transition.CLEANUP).success
    assert [name for name, operation in log if operation == 'cleanup'] == list(
        reversed(components)
    )


def test_failed_dependency_rolls_back_upstream_in_reverse():
    platform, components, log = make_platform(fail='configure')
    result = platform.transition(Transition.CONFIGURE)
    assert not result.success and result.failed_dependency == 'localization'
    assert result.failure is not None and result.rollback_failures == ()
    assert log == [('simulation', 'configure'), ('mapping', 'configure'),
                   ('localization', 'configure'), ('localization', 'error'),
                   ('mapping', 'cleanup'), ('simulation', 'cleanup')]
    assert components['navigation'].state == State.UNCONFIGURED


def test_rollback_failure_is_reported_separately():
    platform, components, log = make_platform(fail='configure')
    components['mapping']._hooks.fail = 'cleanup'
    result = platform.transition(Transition.CONFIGURE)
    assert result.failed_dependency == 'localization'
    assert result.failure is not None
    assert len(result.rollback_failures) == 1
    assert result.rollback_failures[0].component == 'mapping'
    assert components['simulation'].state == State.UNCONFIGURED
    assert components['navigation'].state == State.UNCONFIGURED


def test_activate_failure_does_not_activate_downstream():
    platform, components, log = make_platform(fail='activate')
    assert platform.transition(Transition.CONFIGURE).success
    result = platform.transition(Transition.ACTIVATE)
    assert result.failed_dependency == 'localization'
    assert components['navigation'].state == State.INACTIVE
    assert ('navigation', 'activate') not in log
    assert components['mapping'].state == State.INACTIVE
    assert components['simulation'].state == State.INACTIVE


def test_shutdown_uses_reverse_order_and_reports_irreversible_progress():
    platform, components, log = make_platform()
    assert platform.transition(Transition.CONFIGURE).success
    components['localization']._hooks.fail = 'shutdown'
    result = platform.transition(Transition.SHUTDOWN)
    assert result.failed_dependency == 'localization'
    assert result.rollback_unavailable == ('navigation',)
    assert [name for name, operation in log if operation == 'shutdown'] == [
        'navigation', 'localization',
    ]
    assert components['navigation'].state == State.FINALIZED
    assert components['mapping'].state == State.INACTIVE


def test_unknown_component_state_prevents_partial_transition():
    platform, components, log = make_platform()

    class MissingState:
        state = None

        def transition(self, operation):
            raise AssertionError(f'unexpected {operation}')

    platform.components['mapping'] = MissingState()
    result = platform.transition(Transition.CONFIGURE)
    assert result.code == 'STATE_UNAVAILABLE'
    assert result.failed_dependency == 'mapping'
    assert log == []


def test_adapter_exception_stops_downstream_and_preserves_rollback_report():
    platform, components, log = make_platform()

    class ThrowingAdapter:
        state = State.UNCONFIGURED

        def transition(self, operation):
            raise RuntimeError('transport failed')

    platform.components['localization'] = ThrowingAdapter()
    result = platform.transition(Transition.CONFIGURE)
    assert result.failed_dependency == 'localization'
    assert result.failure.code == 'COMPONENT_EXCEPTION'
    assert 'transport failed' in result.failure.reason
    assert result.rollback_failures == ()
    assert [item.component for item in result.rollback_results] == [
        'mapping', 'simulation',
    ]
    assert components['navigation'].state == State.UNCONFIGURED
