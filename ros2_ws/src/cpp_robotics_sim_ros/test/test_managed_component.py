# Copyright 2026 Devansh Mishra
#
# Use of this source code is governed by an MIT-style
# license that can be found in the LICENSE file or at
# https://opensource.org/licenses/MIT.

"""Contract tests for the shared manager lifecycle."""

from dataclasses import FrozenInstanceError
from datetime import datetime
from pathlib import Path
import sys
from threading import Event, Thread

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

import managed_component as life  # noqa: E402,I100

State = life.LifecycleState
Transition = life.LifecycleTransition
ManagedComponent = life.ManagedComponent
RetryPolicy = life.RetryPolicy


class Hooks:
    def __init__(self):
        self.calls = []
        self.failures = {}
        self.recovery_verified = True

    def _call(self, name):
        self.calls.append(name)
        remaining = self.failures.get(name, 0)
        if remaining:
            self.failures[name] = remaining - 1
            raise RuntimeError(f'{name} failed')

    def on_configure(self): self._call('configure')
    def on_activate(self): self._call('activate')
    def on_deactivate(self): self._call('deactivate')
    def on_cleanup(self): self._call('cleanup')
    def on_shutdown(self): self._call('shutdown')
    def on_error(self): self._call('error')

    def on_recover(self):
        self._call('recover')
        return self.recovery_verified

    def on_rollback(self, transition, source_state):
        self._call('rollback')
        return True


def test_all_legal_transitions_and_finalized_rejection():
    hooks = Hooks()
    component = ManagedComponent('simulation', hooks)
    for transition, destination in (
        (Transition.CONFIGURE, State.INACTIVE),
        (Transition.ACTIVATE, State.ACTIVE),
        (Transition.DEACTIVATE, State.INACTIVE),
        (Transition.CLEANUP, State.UNCONFIGURED),
        (Transition.CONFIGURE, State.INACTIVE),
        (Transition.SHUTDOWN, State.FINALIZED),
    ):
        result = component.transition(transition)
        assert result.success and result.destination_state == destination
        assert component.state == destination
    rejected = component.transition(Transition.CONFIGURE)
    assert not rejected.success and rejected.code == 'ILLEGAL_TRANSITION'
    assert component.state == State.FINALIZED


@pytest.mark.parametrize('transition', [
    Transition.ACTIVATE, Transition.DEACTIVATE,
    Transition.CLEANUP, Transition.RECOVER,
])
def test_illegal_transition_does_not_call_hook(transition):
    hooks = Hooks()
    component = ManagedComponent('simulation', hooks)
    result = component.transition(transition)
    assert result.code == 'ILLEGAL_TRANSITION'
    assert result.source_state == result.destination_state == State.UNCONFIGURED
    assert hooks.calls == []


def test_unknown_transition_returns_structured_rejection():
    component = ManagedComponent('x', Hooks())
    result = component.transition('teleport')
    assert result.code == 'INVALID_TRANSITION'
    assert result.transition == 'teleport'
    assert component.state == State.UNCONFIGURED
    assert result.transition_id
    assert result.to_mapping()['transition'] == 'teleport'


def test_explicit_false_hook_result_enters_error():
    hooks = Hooks()
    hooks.on_configure = lambda: False
    component = ManagedComponent('x', hooks)
    result = component.transition(Transition.CONFIGURE)
    assert result.code == 'HOOK_FAILED'
    assert component.state == State.ERROR


def test_lifecycle_state_cannot_be_assigned_by_consumer():
    component = ManagedComponent('x', Hooks())
    with pytest.raises(AttributeError):
        component.state = State.ACTIVE
    assert component.state == State.UNCONFIGURED


def test_active_only_after_successful_hook_and_results_are_structured():
    hooks = Hooks()
    component = ManagedComponent('simulation', hooks)
    component.transition(Transition.CONFIGURE)
    hooks.failures['activate'] = 1
    result = component.transition(Transition.ACTIVATE)
    assert not result.success and result.code == 'HOOK_FAILED'
    assert component.state == State.ERROR
    assert result.source_state == State.INACTIVE
    assert result.destination_state == State.ERROR
    assert 'activate failed' in result.reason
    assert result.transition_id and result.component == 'simulation'
    assert result.failed_dependency == ''
    assert result.recovery_guidance
    assert datetime.fromisoformat(result.started_at) <= datetime.fromisoformat(
        result.completed_at
    )
    with pytest.raises(FrozenInstanceError):
        result.code = 'SUCCESS'
    next_result = component.transition(Transition.CONFIGURE)
    assert next_result.transition_id != result.transition_id


def test_runtime_fault_and_verified_recovery():
    hooks = Hooks()
    component = ManagedComponent('simulation', hooks)
    assert component.transition(
        Transition.ERROR, reason='lost child'
    ).destination_state == State.ERROR
    hooks.recovery_verified = False
    failed = component.transition(Transition.RECOVER)
    assert failed.code == 'RECOVERY_FAILED' and component.state == State.ERROR
    hooks.recovery_verified = True
    assert component.transition(Transition.RECOVER).destination_state == State.UNCONFIGURED


def test_concurrent_attempt_is_rejected_without_waiting():
    entered, release = Event(), Event()

    class BlockingHooks(Hooks):
        def on_configure(self):
            entered.set()
            assert release.wait(3)

    component = ManagedComponent('simulation', BlockingHooks())
    worker = Thread(target=lambda: component.transition(Transition.CONFIGURE))
    worker.start()
    try:
        assert entered.wait(3)
        result = component.transition(Transition.CONFIGURE)
        assert result.code == 'BUSY' and component.state == State.UNCONFIGURED
    finally:
        release.set()
        worker.join(3)
    assert component.state == State.INACTIVE


def test_retry_rolls_back_before_second_attempt():
    hooks = Hooks()
    hooks.failures['configure'] = 1
    component = ManagedComponent(
        'simulation', hooks,
        retry_policy=RetryPolicy(
            max_retries=1, retry_safe=frozenset({Transition.CONFIGURE}),
        ),
    )
    result = component.transition(Transition.CONFIGURE)
    assert result.success and result.rollback_performed
    assert result.rollback_result == 'SUCCESS' and result.attempts == 2
    assert hooks.calls == ['configure', 'rollback', 'configure']


def test_exhausted_retry_enters_error():
    hooks = Hooks()
    hooks.failures['configure'] = 2
    component = ManagedComponent(
        'simulation', hooks,
        retry_policy=RetryPolicy(
            max_retries=1, retry_safe=frozenset({Transition.CONFIGURE}),
        ),
    )
    result = component.transition(Transition.CONFIGURE)
    assert result.code == 'RETRY_EXHAUSTED' and result.attempts == 2
    assert result.rollback_performed and component.state == State.ERROR


def test_failed_rollback_enters_error_without_retry():
    hooks = Hooks()
    hooks.failures.update(configure=1, rollback=1)
    component = ManagedComponent(
        'simulation', hooks,
        retry_policy=RetryPolicy(
            max_retries=1, retry_safe=frozenset({Transition.CONFIGURE}),
        ),
    )
    result = component.transition(Transition.CONFIGURE)
    assert result.code == 'ROLLBACK_FAILED' and result.attempts == 1
    assert result.rollback_performed and 'rollback failed' in result.rollback_result
    assert hooks.calls == ['configure', 'rollback', 'error']
    assert component.state == State.ERROR


def test_default_policy_never_retries():
    hooks = Hooks()
    hooks.failures['configure'] = 1
    result = ManagedComponent('simulation', hooks).transition(Transition.CONFIGURE)
    assert result.attempts == 1 and not result.rollback_performed
    assert hooks.calls == ['configure', 'error']


def test_missing_hook_and_error_hook_exception_are_structured():
    class IncompleteHooks:
        def on_error(self):
            raise RuntimeError('diagnostic failed')

    component = ManagedComponent('x', IncompleteHooks())
    result = component.transition(Transition.CONFIGURE)
    assert result.code == 'HOOK_FAILED'
    assert 'AttributeError' in result.reason
    assert 'diagnostic failed' in result.reason
    assert component.state == State.ERROR


def test_retry_policy_rejects_unbounded_or_irreversible_retry():
    with pytest.raises(ValueError):
        RetryPolicy(max_retries=4)
    with pytest.raises(ValueError):
        RetryPolicy(max_retries=1, retry_safe={Transition.SHUTDOWN})


def test_shutdown_from_all_supported_states():
    for setup in ((), (Transition.CONFIGURE,),
                  (Transition.CONFIGURE, Transition.ACTIVATE,), (Transition.ERROR,)):
        component = ManagedComponent('x', Hooks())
        for operation in setup:
            assert component.transition(operation).success
        assert component.transition(Transition.SHUTDOWN).destination_state == State.FINALIZED
