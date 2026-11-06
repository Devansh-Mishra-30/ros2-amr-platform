#!/usr/bin/env python3
# Copyright 2026 Devansh Mishra
#
# Use of this source code is governed by an MIT-style
# license that can be found in the LICENSE file or at
# https://opensource.org/licenses/MIT.

"""ROS state, event, and service bindings for a ManagedComponent."""

from datetime import datetime, timezone

from cpp_robotics_sim_ros.msg import LifecycleTransitionEvent, ManagedLifecycleState
from cpp_robotics_sim_ros.srv import (
    GetManagedComponentState, TransitionManagedComponent,
)
from managed_component import LifecycleTransition, ManagedComponent
import rclpy
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
        if not rclpy.ok(context=node.context):
            return
        snapshot = ManagedLifecycleState()
        snapshot.component = component_name
        snapshot.state = component.state.value
        snapshot.last_transition_id = component.last_transition_id
        snapshot.observed_at = datetime.now(timezone.utc).isoformat()
        state_publisher.publish(snapshot)

    def publish_result(result, orchestration_id=''):
        if not rclpy.ok(context=node.context):
            return None
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

    def get_state(_request, response):
        response.component = component_name
        response.state = component.state.value
        response.last_transition = component.last_transition
        response.last_transition_id = component.last_transition_id
        response.observed_at = datetime.now(timezone.utc).isoformat()
        return response

    node.create_service(
        GetManagedComponentState,
        f'/lifecycle/{component_name}/state_snapshot',
        get_state,
    )
    node.publish_lifecycle_state = publish_state
    node.publish_lifecycle_result = publish_result
    # Transient-local state communicates the last value to late joiners, but
    # cannot prove the publisher is still alive. Periodic snapshots provide a
    # small lease for remote consumers without adding readiness to lifecycle.
    node.lifecycle_state_timer = node.create_timer(1.0, publish_state)
    publish_state()
    return component
