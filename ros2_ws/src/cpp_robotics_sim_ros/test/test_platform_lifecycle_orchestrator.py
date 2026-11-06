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


def test_stale_remote_active_snapshot_cannot_satisfy_platform_noop():
    platform, components, _ = make_platform()
    assert platform.transition(Transition.CONFIGURE).success
    assert platform.transition(Transition.ACTIVATE).success

    class ExpiredRemote:
        state = None

        def target_satisfied(self, target):
            return False

        def transition(self, operation):
            raise AssertionError('expired publisher must not be called')

    platform.components['localization'] = ExpiredRemote()
    repeated = platform.transition(Transition.ACTIVATE)
    assert not repeated.success
    assert repeated.code == 'STATE_UNAVAILABLE'
    assert repeated.failed_dependency == 'localization'


def test_active_state_without_matching_activation_provenance_is_rejected():
    platform, components, _ = make_platform()
    assert platform.transition(Transition.CONFIGURE).success
    assert platform.transition(Transition.ACTIVATE).success

    class UnprovenRemote:
        state = State.ACTIVE
        last_transition_id = ''
        verified_activation_id = 'different-transition'

        def target_satisfied(self, target):
            return (target != State.ACTIVE
                    or bool(self.last_transition_id)
                    and self.last_transition_id == self.verified_activation_id)

        def transition(self, operation):
            raise AssertionError('unproven ACTIVE state must not be trusted')

    platform.components['localization'] = UnprovenRemote()
    result = platform.transition(Transition.ACTIVATE)
    assert not result.success
    assert result.code == 'STATE_UNVERIFIED'
    assert result.failed_dependency == 'localization'


def test_direct_component_transition_during_platform_request_is_detected():
    platform, components, _ = make_platform()
    assert platform.transition(Transition.CONFIGURE).success

    navigation = components['navigation']
    original_transition = navigation.transition

    def racing_transition(operation, **kwargs):
        report = original_transition(operation, **kwargs)
        if operation == Transition.ACTIVATE and report.success:
            direct = components['simulation'].transition(Transition.DEACTIVATE)
            assert direct.success
        return report

    navigation.transition = racing_transition
    result = platform.transition(Transition.ACTIVATE)
    assert not result.success
    assert result.code == 'STATE_CHANGED'
    assert result.failed_dependency == 'simulation'
    assert components['simulation'].state == State.INACTIVE


def test_delayed_ros_snapshot_cannot_hide_authoritative_direct_transition():
    platform, components, _ = make_platform()
    assert platform.transition(Transition.CONFIGURE).success

    class DelayedRemote:
        def __init__(self, authoritative):
            self.authoritative = authoritative
            self.cached_state = authoritative.state

        @property
        def state(self):
            return self.cached_state

        def refresh_state(self):
            self.cached_state = self.authoritative.state
            return True

        def target_satisfied(self, target):
            return self.cached_state == target

        def transition(self, operation, **kwargs):
            return self.authoritative.transition(operation, **kwargs)

    authoritative = components['simulation']
    remote = DelayedRemote(authoritative)
    platform.components['simulation'] = remote
    navigation = components['navigation']
    original_transition = navigation.transition

    def race_on_last_component(operation, **kwargs):
        result = original_transition(operation, **kwargs)
        if operation == Transition.ACTIVATE and result.success:
            assert authoritative.transition(Transition.DEACTIVATE).success
            # The transient-local state callback remains delayed; only the
            # authoritative read can observe the manager's current state.
        return result

    navigation.transition = race_on_last_component
    result = platform.transition(Transition.ACTIVATE)
    assert not result.success
    assert result.code == 'STATE_CHANGED'
    assert result.failed_dependency == 'simulation'
    assert remote.state == State.INACTIVE


def test_direct_transition_between_final_component_refreshes_is_not_success():
    platform, components, _ = make_platform()
    assert platform.transition(Transition.CONFIGURE).success

    class RemoteSnapshot:
        def __init__(self, authoritative):
            self.authoritative = authoritative
            self.cached_state = authoritative.state

        @property
        def state(self):
            return self.cached_state

        def target_satisfied(self, target):
            return self.cached_state == target

        def refresh_state(self):
            self.cached_state = self.authoritative.state
            return True

        def transition(self, operation, **kwargs):
            return self.authoritative.transition(operation, **kwargs)

    authoritative = components['simulation']
    simulation_remote = RemoteSnapshot(authoritative)
    platform.components['simulation'] = simulation_remote

    localization = components['localization']
    original_refresh = getattr(localization, 'refresh_state', None)

    def deactivate_simulation_after_localization_read():
        if original_refresh is not None:
            assert original_refresh()
        if authoritative.state == State.ACTIVE:
            assert authoritative.transition(Transition.DEACTIVATE).success
        return True

    localization.refresh_state = deactivate_simulation_after_localization_read
    result = platform.transition(Transition.ACTIVATE)
    assert not result.success
    assert result.code == 'STATE_CHANGED'
    assert authoritative.state == State.INACTIVE


def test_stable_authoritative_state_and_version_across_both_passes_succeeds():
    platform, components, _ = make_platform()
    assert platform.transition(Transition.CONFIGURE).success
    refresh_counts = {name: 0 for name in components}

    class RemoteSnapshot:
        def __init__(self, name, authoritative):
            self.name = name
            self.authoritative = authoritative
            self.cached_state = authoritative.state

        @property
        def state(self):
            return self.cached_state

        @property
        def last_transition_id(self):
            return self.authoritative.last_transition_id

        @property
        def last_transition(self):
            return self.authoritative.last_transition

        def target_satisfied(self, target):
            return self.cached_state == target

        def refresh_state(self):
            refresh_counts[self.name] += 1
            self.cached_state = self.authoritative.state
            return True

        def transition(self, operation, **kwargs):
            return self.authoritative.transition(operation, **kwargs)

    platform.components = {
        name: RemoteSnapshot(name, component)
        for name, component in components.items()
    }
    result = platform.transition(Transition.ACTIVATE)
    assert result.success
    # One request preflight plus the two complete final verification passes.
    assert all(count >= 3 for count in refresh_counts.values())


def test_second_pass_authoritative_refresh_failure_fails_closed():
    platform, components, _ = make_platform()
    assert platform.transition(Transition.CONFIGURE).success
    simulation = components['simulation']
    original_transition = simulation.transition
    reads = 0

    class RemoteSnapshot:
        @property
        def state(self):
            return simulation.state

        @property
        def last_transition_id(self):
            return simulation.last_transition_id

        @property
        def last_transition(self):
            return simulation.last_transition

        def refresh_state(self):
            nonlocal reads
            reads += 1
            return reads < 3

        def target_satisfied(self, target):
            return simulation.state == target

        def transition(self, operation, **kwargs):
            return original_transition(operation, **kwargs)

    platform.components['simulation'] = RemoteSnapshot()
    result = platform.transition(Transition.ACTIVATE)
    assert not result.success
    assert result.code == 'STATE_UNAVAILABLE'
    assert result.failed_dependency == 'simulation'
