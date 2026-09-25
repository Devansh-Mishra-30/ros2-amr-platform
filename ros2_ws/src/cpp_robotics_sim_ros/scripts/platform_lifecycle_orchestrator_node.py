#!/usr/bin/env python3
# Copyright 2026 Devansh Mishra
#
# Use of this source code is governed by an MIT-style
# license that can be found in the LICENSE file or at
# https://opensource.org/licenses/MIT.

"""
ROS transport for the platform lifecycle ordering core.

This node is installed but not launched until manager lifecycle adapters exist.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import uuid4

from cpp_robotics_sim_ros.msg import (
    LifecycleTransitionEvent,
    ManagedLifecycleState,
)
from cpp_robotics_sim_ros.srv import TransitionManagedComponent
from managed_component import (
    LEGAL_TRANSITIONS, LifecycleState, LifecycleTransition,
    TransitionResult, utc_now,
)
from platform_lifecycle_orchestrator import (
    COMPONENT_ORDER, OrchestrationResult, PlatformLifecycleOrchestrator,
)
import rclpy
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy

STATE_QOS = QoSProfile(
    depth=1,
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
)


def event_from_result(result: TransitionResult) -> LifecycleTransitionEvent:
    event = LifecycleTransitionEvent()
    for field, value in result.to_mapping().items():
        setattr(event, field, value)
    return event


class RemoteComponent:
    """Adapter for a manager's future typed lifecycle endpoint."""

    def __init__(self, node: Node, name: str, callback_group: ReentrantCallbackGroup):
        self.name = name
        self._state: Optional[LifecycleState] = None
        self._observed_at = ''
        self._client = node.create_client(
            TransitionManagedComponent, f'/lifecycle/{name}/transition',
            callback_group=callback_group,
        )
        self._subscription = node.create_subscription(
            ManagedLifecycleState, f'/lifecycle/{name}/state',
            self._on_state, STATE_QOS, callback_group=callback_group,
        )

    @property
    def state(self) -> Optional[LifecycleState]:
        return self._state

    def _on_state(self, snapshot: ManagedLifecycleState) -> None:
        if snapshot.component != self.name:
            return
        try:
            observed = datetime.fromisoformat(snapshot.observed_at)
            if observed.tzinfo is None:
                return
            state = LifecycleState(snapshot.state)
            if self._observed_at and observed < datetime.fromisoformat(self._observed_at):
                return
        except (ValueError, TypeError):
            return
        self._state = state
        self._observed_at = snapshot.observed_at

    def transition(self, operation: LifecycleTransition, **kwargs) -> TransitionResult:
        started_at = utc_now()
        request = TransitionManagedComponent.Request()
        request.transition = operation.value
        request.orchestration_id = kwargs.get('orchestration_id', '')
        try:
            if not self._client.wait_for_service(timeout_sec=2.0):
                raise TimeoutError('manager lifecycle service is unavailable')
            # Service and client use a reentrant group and a multithreaded
            # executor, so the response can complete while this call waits.
            response = self._client.call(request, timeout_sec=30.0)
            if response is None:
                raise TimeoutError('manager lifecycle service timed out')
            event = response.result
            if event.component != self.name or event.transition != operation.value:
                raise ValueError('manager response identity does not match request')
            if event.orchestration_id != request.orchestration_id:
                raise ValueError('manager response orchestration ID does not match request')
            if not event.transition_id:
                raise ValueError('manager response has no transition ID')
            if event.success and event.code != 'SUCCESS':
                raise ValueError('manager response has inconsistent success code')
            source = LifecycleState(event.source_state)
            destination = LifecycleState(event.destination_state)
            allowed, expected = LEGAL_TRANSITIONS[operation]
            if event.success and (source not in allowed or destination != expected):
                raise ValueError('manager reported an illegal successful transition')
            report = TransitionResult(
                success=event.success, transition_id=event.transition_id,
                component=event.component, transition=operation,
                source_state=source, destination_state=destination,
                code=event.code, reason=event.reason,
                failed_dependency=event.failed_dependency,
                started_at=event.started_at, completed_at=event.completed_at,
                recovery_guidance=event.recovery_guidance,
                rollback_performed=event.rollback_performed,
                rollback_result=event.rollback_result, attempts=event.attempts,
                orchestration_id=event.orchestration_id,
            )
            self._state = destination
            self._observed_at = event.completed_at
            return report
        except Exception as error:
            state = self._state or LifecycleState.UNCONFIGURED
            # The remote operation may have completed after a timeout. Do not
            # accept another platform request until a fresh state arrives.
            self._state = None
            return TransitionResult(
                success=False, transition_id=str(uuid4()), component=self.name,
                transition=operation, source_state=state, destination_state=state,
                code='TRANSPORT_FAILED', reason=f'{type(error).__name__}: {error}',
                failed_dependency=self.name, started_at=started_at,
                completed_at=utc_now(),
                recovery_guidance='Inspect manager lifecycle service and state.',
            )


class PlatformLifecycleOrchestratorNode(Node):
    def __init__(self) -> None:
        super().__init__('platform_lifecycle_orchestrator')
        callback_group = ReentrantCallbackGroup()
        components = {
            name: RemoteComponent(self, name, callback_group)
            for name in COMPONENT_ORDER
        }
        self.core = PlatformLifecycleOrchestrator(components)
        self.event_publisher = self.create_publisher(
            LifecycleTransitionEvent, '/platform/lifecycle/transition_events', 10,
        )
        self.transition_service = self.create_service(
            TransitionManagedComponent, '/platform/lifecycle/transition',
            self._transition_callback, callback_group=callback_group,
        )

    def _transition_callback(self, request, response):
        try:
            operation = LifecycleTransition(request.transition)
        except ValueError:
            event = LifecycleTransitionEvent()
            event.component = 'platform'
            event.transition_id = str(uuid4())
            event.transition = request.transition
            event.code = 'INVALID_TRANSITION'
            event.reason = f'unknown lifecycle transition: {request.transition}'
            event.started_at = event.completed_at = utc_now()
            event.recovery_guidance = 'Use configure, activate, deactivate, cleanup, or shutdown.'
            response.result = event
            self.event_publisher.publish(event)
            return response

        report = self.core.transition(operation)
        for item in (*report.results, *report.rollback_results):
            self.event_publisher.publish(event_from_result(item))
        response.component_results = [event_from_result(item) for item in report.results]
        response.rollback_results = [event_from_result(item) for item in report.rollback_results]
        response.rollback_failures = [event_from_result(item) for item in report.rollback_failures]
        response.rollback_unavailable = list(report.rollback_unavailable)
        response.result = self._platform_event(report)
        self.event_publisher.publish(response.result)
        return response

    @staticmethod
    def _platform_event(report: OrchestrationResult) -> LifecycleTransitionEvent:
        event = LifecycleTransitionEvent()
        event.success = report.success
        event.transition_id = report.transition_id
        event.orchestration_id = report.transition_id
        event.component = 'platform'
        event.transition = report.transition.value
        event.code = report.code
        event.reason = report.reason
        event.failed_dependency = report.failed_dependency
        event.started_at = report.started_at
        event.completed_at = report.completed_at
        event.recovery_guidance = (
            '' if report.success else
            'Inspect failed dependency and rollback results; recover ERROR components.'
        )
        event.rollback_performed = bool(report.rollback_results or report.rollback_unavailable)
        event.rollback_result = (
            'UNAVAILABLE' if report.rollback_unavailable else
            'FAILED' if report.rollback_failures else
            'SUCCESS' if report.rollback_results else ''
        )
        event.attempts = len(report.results)
        return event


def main(args=None) -> None:
    rclpy.init(args=args)
    node = PlatformLifecycleOrchestratorNode()
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        executor.shutdown()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
