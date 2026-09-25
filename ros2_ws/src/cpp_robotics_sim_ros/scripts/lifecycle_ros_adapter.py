#!/usr/bin/env python3
# Copyright 2026 Devansh Mishra
#
# Use of this source code is governed by an MIT-style
# license that can be found in the LICENSE file or at
# https://opensource.org/licenses/MIT.

"""ROS state, event, and service bindings for a ManagedComponent."""

from datetime import datetime, timezone

from cpp_robotics_sim_ros.msg import LifecycleTransitionEvent, ManagedLifecycleState
from cpp_robotics_sim_ros.srv import TransitionManagedComponent
from managed_component import LifecycleTransition, ManagedComponent
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy


LIFECYCLE_QOS = QoSProfile(
    depth=1,
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
)


def bind_lifecycle(node, component_name, hooks):
    """Attach lifecycle entities to an existing domain manager node."""
    component = ManagedComponent(component_name, hooks)
    state_publisher = node.create_publisher(
        ManagedLifecycleState, f'/lifecycle/{component_name}/state', LIFECYCLE_QOS,
    )
    event_publisher = node.create_publisher(
        LifecycleTransitionEvent, '/platform/lifecycle/transition_events', 10,
    )

    def publish_state():
        snapshot = ManagedLifecycleState()
        snapshot.component = component_name
        snapshot.state = component.state.value
        snapshot.last_transition_id = component.last_transition_id
        snapshot.observed_at = datetime.now(timezone.utc).isoformat()
        state_publisher.publish(snapshot)

    def publish_result(result, orchestration_id=''):
        event = LifecycleTransitionEvent()
        for field, value in result.to_mapping().items():
            setattr(event, field, value)
        event.orchestration_id = orchestration_id or result.orchestration_id
        event_publisher.publish(event)
        publish_state()
        return event

    def callback(request, response):
        try:
            transition = LifecycleTransition(request.transition)
            result = component.transition(
                transition,
                reason=f'requested by {request.orchestration_id or "client"}',
                orchestration_id=request.orchestration_id,
            )
        except ValueError:
            result = component.transition(request.transition)
        response.result = publish_result(result, request.orchestration_id)
        return response

    node.create_service(
        TransitionManagedComponent,
        f'/lifecycle/{component_name}/transition',
        callback,
    )
    node.publish_lifecycle_state = publish_state
    node.publish_lifecycle_result = publish_result
    publish_state()
    return component
