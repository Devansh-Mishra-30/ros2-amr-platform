# Copyright 2026 Devansh Mishra
#
# Use of this source code is governed by an MIT-style
# license that can be found in the LICENSE file or at
# https://opensource.org/licenses/MIT.

"""Focused contract tests for each existing manager's lifecycle hooks."""

from pathlib import Path
import sys
import threading
from types import SimpleNamespace

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))

from localization_manager_node import LocalizationManagerNode  # noqa: E402
from managed_component import LifecycleState, LifecycleTransition, ManagedComponent  # noqa: E402
from mapping_manager_node import MappingManagerNode  # noqa: E402
from navigation_goal_manager_node import NavigationGoalManagerNode  # noqa: E402
from simulation_manager_node import SimulationManagerNode  # noqa: E402


def install_hooks(node, manager_type):
    for name in (
        'on_configure', 'on_activate', 'on_deactivate', 'on_cleanup',
        'on_shutdown', 'on_error', 'on_recover', 'on_rollback',
        '_clear_transient_localization_state', '_cancel_and_wait_for_goal',
    ):
        if not hasattr(manager_type, name):
            continue
        method = getattr(manager_type, name)
        setattr(node, name, method.__get__(node, manager_type))
    return node


def test_simulation_lifecycle_is_distinct_from_domain_running_and_stops_on_deactivate():
    node = SimpleNamespace(
        lifecycle_component=SimpleNamespace(state=LifecycleState.UNCONFIGURED),
        simulation_state='stopped',
        stop_simulation=lambda: (True, 'already stopped'),
    )
    install_hooks(node, SimulationManagerNode)
    component = ManagedComponent('simulation', node)
    node.lifecycle_component = component
    assert component.transition(LifecycleTransition.CONFIGURE).success
    assert component.transition(LifecycleTransition.ACTIVATE).success
    # The lifecycle hook does not start a simulation; a stopped domain is valid.
    assert node.simulation_state == 'stopped'
    node.stop_simulation = lambda: (True, 'stopped')
    assert SimulationManagerNode.on_deactivate(node) is None
    assert component.state == LifecycleState.ACTIVE  # only the engine changes state
    assert component.transition(LifecycleTransition.DEACTIVATE).success


def test_simulation_stop_failure_enters_error_and_verified_recovery_is_required():
    node = SimpleNamespace(
        stop_simulation=lambda: (False, 'owned process remains'),
        process_record=None,
        process_registry=SimpleNamespace(list_records=lambda: []),
    )
    install_hooks(node, SimulationManagerNode)
    component = ManagedComponent('simulation', node)
    node.lifecycle_component = component
    assert component.transition('configure').success
    assert component.transition('activate').success
    failed = component.transition('deactivate')
    assert not failed.success and component.state == LifecycleState.ERROR
    node.stop_simulation = lambda: (True, 'verified stopped')
    assert component.transition('recover').success
    assert component.state == LifecycleState.UNCONFIGURED


def test_simulation_domain_service_is_rejected_before_activation():
    response = SimpleNamespace(success=True, message='')
    node = SimpleNamespace(
        lifecycle_component=SimpleNamespace(state=LifecycleState.INACTIVE),
        lifecycle_accepts_operations=lambda: False,
        lifecycle_rejection_reason=lambda: 'Simulation lifecycle is not ACTIVE',
    )
    assert not SimulationManagerNode.start_callback(node, None, response).success
    assert 'not ACTIVE' in response.message


def test_mapping_deactivation_waits_for_in_progress_save_and_recovery_checks_idle():
    node = SimpleNamespace(
        lifecycle_accepting=True,
        save_timeout=0.2,
        save_completed=threading.Event(),
        save_lock=threading.Lock(),
        save_in_progress=True,
    )
    install_hooks(node, MappingManagerNode)

    def finish_save():
        node.save_in_progress = False
        node.save_completed.set()
    timer = threading.Timer(0.02, finish_save)
    timer.start()
    MappingManagerNode.on_deactivate(node)
    timer.join()
    assert not node.lifecycle_accepting
    assert MappingManagerNode.on_recover(node) is True


def test_mapping_deactivation_failure_is_not_reported_as_success():
    node = SimpleNamespace(
        lifecycle_accepting=True,
        save_timeout=0.001,
        save_completed=threading.Event(),
    )
    install_hooks(node, MappingManagerNode)
    component = ManagedComponent('mapping', node)
    assert component.transition('configure').success
    assert component.transition('activate').success
    result = component.transition('deactivate')
    assert not result.success and result.code == 'HOOK_FAILED'
    assert component.state == LifecycleState.ERROR


def test_mapping_save_request_is_rejected_before_activation():
    messages = []
    node = SimpleNamespace(
        lifecycle_accepting=False,
        lifecycle_component=SimpleNamespace(state=LifecycleState.UNCONFIGURED),
        publish_status=lambda **kwargs: messages.append(kwargs),
    )
    MappingManagerNode.save_request_callback(node, SimpleNamespace(data='fixture'))
    assert 'not ACTIVE' in messages[-1]['message']


def test_localization_cleanup_clears_only_manager_selected_map_transient_state():
    node = SimpleNamespace(
        lifecycle_accepting=True,
        selected_map_name='warehouse',
        selected_map_path='/maps/warehouse.yaml',
        selected_map_environment='warehouse',
        publish_selected_map=lambda: None,
        publish_status=lambda **kwargs: None,
    )
    install_hooks(node, LocalizationManagerNode)
    component = ManagedComponent('localization', node)
    assert component.transition('configure').success
    assert component.transition('activate').success
    assert component.transition('deactivate').success
    assert component.transition('cleanup').success
    LocalizationManagerNode.on_cleanup(node)
    assert node.selected_map_name == ''
    assert node.selected_map_path == ''
    assert node.selected_map_environment == ''
    assert not node.lifecycle_accepting


def test_localization_map_selection_is_rejected_before_activation():
    messages = []
    node = SimpleNamespace(
        lifecycle_accepting=False,
        lifecycle_component=SimpleNamespace(state=LifecycleState.UNCONFIGURED),
        publish_status=lambda **kwargs: messages.append(kwargs),
    )
    LocalizationManagerNode.select_map_callback(node, SimpleNamespace(data='{}'))
    assert 'not ACTIVE' in messages[-1]['message']


def test_navigation_cleanup_requires_goal_terminal_state():
    node = SimpleNamespace(
        lifecycle_accepting=True,
        goal_finished=SimpleNamespace(wait=lambda timeout: True),
        cancel_response_event=SimpleNamespace(wait=lambda timeout: True, clear=lambda: None),
        cancel_response_accepted=True,
        goal_is_active=lambda: True,
        request_cancel=lambda reason: setattr(node, 'cancel_response_accepted', True),
    )
    install_hooks(node, NavigationGoalManagerNode)
    NavigationGoalManagerNode.on_deactivate(node)
    assert not node.lifecycle_accepting
    node.goal_is_active = lambda: False
    NavigationGoalManagerNode.on_cleanup(node)


def test_navigation_goal_is_rejected_before_activation():
    messages = []
    node = SimpleNamespace(
        lifecycle_accepting=False,
        lifecycle_component=SimpleNamespace(state=LifecycleState.UNCONFIGURED),
        publish_status=lambda **kwargs: messages.append(kwargs),
    )
    NavigationGoalManagerNode.goal_request_callback(node, SimpleNamespace(data='{}'))
    assert messages[-1]['state'] == 'rejected'
    assert 'not ACTIVE' in messages[-1]['message']


def test_navigation_cancellation_timeout_becomes_lifecycle_error_then_recovers():
    node = SimpleNamespace(
        lifecycle_accepting=True,
        goal_finished=SimpleNamespace(wait=lambda timeout: False),
        cancel_response_event=SimpleNamespace(wait=lambda timeout: False, clear=lambda: None),
        cancel_response_accepted=False,
        goal_is_active=lambda: True,
        request_cancel=lambda reason: None,
    )
    install_hooks(node, NavigationGoalManagerNode)
    component = ManagedComponent('navigation', node)
    assert component.transition('configure').success
    assert component.transition('activate').success
    result = component.transition('deactivate')
    assert not result.success and result.code == 'HOOK_FAILED'
    assert component.state == LifecycleState.ERROR
    node.goal_is_active = lambda: False
    assert component.transition('recover').success
    assert component.state == LifecycleState.UNCONFIGURED
