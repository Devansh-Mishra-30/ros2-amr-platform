# Copyright 2026 Devansh Mishra
#
# Use of this source code is governed by an MIT-style
# license that can be found in the LICENSE file or at
# https://opensource.org/licenses/MIT.

"""Verify the generated lifecycle wire contract and result conversion."""

from pathlib import Path
import sys

from cpp_robotics_sim_ros.msg import LifecycleTransitionEvent, ManagedLifecycleState
from cpp_robotics_sim_ros.srv import TransitionManagedComponent

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

import managed_component as lifecycle  # noqa: E402,I100
import platform_lifecycle_orchestrator_node as transport  # noqa: E402,I100


def test_result_round_trip_to_typed_ros_response():
    result = lifecycle.TransitionResult(
        success=True,
        transition_id='transition-1',
        component='simulation',
        transition=lifecycle.LifecycleTransition.ACTIVATE,
        source_state=lifecycle.LifecycleState.INACTIVE,
        destination_state=lifecycle.LifecycleState.ACTIVE,
        code='SUCCESS',
        reason='activated',
        failed_dependency='',
        started_at='2026-09-24T00:00:00+00:00',
        completed_at='2026-09-24T00:00:01+00:00',
        recovery_guidance='',
        attempts=1,
    )
    event = transport.event_from_result(result)
    assert isinstance(event, LifecycleTransitionEvent)
    assert event.transition == 'activate'
    assert event.source_state == 'inactive'
    assert event.destination_state == 'active'
    response = TransitionManagedComponent.Response()
    response.result = event
    assert response.result.transition_id == 'transition-1'
    snapshot = ManagedLifecycleState()
    snapshot.component = result.component
    snapshot.state = result.destination_state.value
    snapshot.last_transition_id = result.transition_id
    assert snapshot.state == 'active'


def test_transport_failure_requires_new_state_snapshot():
    class MissingClient:
        def wait_for_service(self, timeout_sec):
            return False

    adapter = object.__new__(transport.RemoteComponent)
    adapter.name = 'simulation'
    adapter._state = lifecycle.LifecycleState.INACTIVE
    adapter._client = MissingClient()
    result = adapter.transition(lifecycle.LifecycleTransition.ACTIVATE)
    assert result.code == 'TRANSPORT_FAILED'
    assert not result.success
    assert adapter.state is None
