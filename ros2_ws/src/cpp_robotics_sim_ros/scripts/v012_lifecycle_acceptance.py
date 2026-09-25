#!/usr/bin/env python3
# Copyright 2026 Devansh Mishra
#
# Use of this source code is governed by an MIT-style
# license that can be found in the LICENSE file or at
# https://opensource.org/licenses/MIT.

"""Runtime lifecycle acceptance driver; evidence is kept outside the repo."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import threading
import time

from ament_index_python.packages import get_package_share_directory
from cpp_robotics_sim_ros.msg import LifecycleTransitionEvent, ManagedLifecycleState
from cpp_robotics_sim_ros.srv import TransitionManagedComponent
from geometry_msgs.msg import PoseWithCovarianceStamped
from lifecycle_msgs.srv import GetState
from nav2_msgs.action import NavigateToPose
from nav_msgs.msg import OccupancyGrid
import rclpy
from rclpy.action import ActionClient
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from rclpy.time import Time
from std_msgs.msg import String
from std_srvs.srv import Trigger
from tf2_ros import Buffer, TransformListener

sys.path.insert(0, str(Path(__file__).resolve().parent))
from managed_component import LifecycleState, LifecycleTransition  # noqa: E402,I100
from platform_lifecycle_orchestrator import COMPONENT_ORDER  # noqa: E402,I100
from process_registry import ProcessRegistry  # noqa: E402,I100
from runtime_verification import (  # noqa: E402,I100
    count_ros_nodes,
    CRITICAL_ROS_NODES,
    find_duplicate_ros_nodes,
)


STATE_QOS = QoSProfile(
    depth=1,
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
)
REQUIRED_LIFECYCLE_MANAGERS = (
    '/simulation_manager', '/mapping_manager',
    '/localization_manager', '/navigation_goal_manager',
)


def ros_mapping(message):
    return {
        name: getattr(message, name)
        for name in message.get_fields_and_field_types()
    }


class AcceptanceObserver(Node):
    def __init__(self):
        super().__init__('v012_lifecycle_acceptance')
        self.states = {}
        self.events = []
        self.domain_status = {}
        self.domain_update_count = 0
        self.map_messages = 0
        self.map_received_at = []
        self.initial_pose_messages = 0
        self.initial_pose_messages = 0
        self.domain_events = []
        self.create_subscription(
            OccupancyGrid, '/map',
            self.map_callback,
            10,
        )
        self.create_subscription(
            PoseWithCovarianceStamped, '/initialpose',
            lambda _value: setattr(
                self, 'initial_pose_messages', self.initial_pose_messages + 1,
            ), 10,
        )
        self.create_subscription(
            PoseWithCovarianceStamped, '/initialpose',
            lambda _value: setattr(
                self, 'initial_pose_messages', self.initial_pose_messages + 1,
            ), 10,
        )
        self.create_subscription(
            ManagedLifecycleState, '/lifecycle/simulation/state',
            lambda value: self.states.__setitem__('simulation', ros_mapping(value)),
            STATE_QOS,
        )
        for name in COMPONENT_ORDER[1:]:
            self.create_subscription(
                ManagedLifecycleState, f'/lifecycle/{name}/state',
                lambda value, component=name: self.states.__setitem__(
                    component, ros_mapping(value),
                ), STATE_QOS,
            )
        self.create_subscription(
            LifecycleTransitionEvent, '/platform/lifecycle/transition_events',
            lambda value: self.events.append(ros_mapping(value)), 100,
        )
        for topic in (
            '/simulation/status', '/mapping/save_status',
            '/localization/status', '/navigation/status', '/mode/status',
        ):
            self.create_subscription(
                String, topic,
                lambda value, name=topic: self.domain_callback(name, value.data),
                10,
            )
        self.platform_client = self.create_client(
            TransitionManagedComponent, '/platform/lifecycle/transition',
        )
        self.component_clients = {
            name: self.create_client(
                TransitionManagedComponent, f'/lifecycle/{name}/transition',
            ) for name in COMPONENT_ORDER
        }
        self.trigger_clients = {
            name: self.create_client(Trigger, name)
            for name in ('/simulation/start', '/simulation/stop')
        }
        self.mode_clients = {
            name: self.create_client(Trigger, f'/mode/{name}')
            for name in ('mapping', 'localization', 'navigation', 'stop')
        }
        self.command_publishers = {
            topic: self.create_publisher(String, topic, 10)
            for topic in (
                '/mapping/save_request', '/localization/select_map_request',
                '/localization/initial_pose_request', '/navigation/goal_request',
                '/navigation/cancel_request',
            )
        }
        self.navigation_action_client = ActionClient(
            self, NavigateToPose, '/navigate_to_pose',
        )

    def map_callback(self, _value):
        now = datetime.now(timezone.utc).isoformat()
        self.map_messages += 1
        self.map_received_at.append(now)

    def domain_callback(self, topic, value):
        now = datetime.now(timezone.utc).isoformat()
        self.domain_status[topic] = value
        self.domain_events.append({'at': now, 'topic': topic, 'value': value})
        self.domain_update_count += 1


def main(args=None):
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    evidence = Path.home() / '.ros' / 'cpp_robotics_sim' / 'evidence' / 'v0.1.2' / stamp
    evidence.mkdir(parents=True, exist_ok=False)
    report = {
        'started_at': datetime.now(timezone.utc).isoformat(),
        'checks': {}, 'state_snapshots': [], 'transition_events': [],
        'orchestrator_results': [], 'injected_failure_results': [],
        'rollback_results': [], 'active_provenance': {},
    }
    launch = None
    node = None
    executor = None
    executor_thread = None
    late = None
    launch_log = None
    launch_log_path = evidence / 'web_interface_launch.log'

    def record(name, passed, detail=''):
        report['checks'][name] = {'passed': bool(passed), 'detail': str(detail)}

    def wait_until(predicate, timeout=30.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.05)
        return bool(predicate())

    def call(client, request, timeout=35.0):
        if not client.wait_for_service(timeout_sec=timeout):
            raise TimeoutError(f'service unavailable: {client.srv_name}')
        future = client.call_async(request)
        if not wait_until(future.done, timeout):
            raise TimeoutError(f'service timed out: {client.srv_name}')
        return future.result()

    def transition(name, operation, is_platform=False):
        client = node.platform_client if is_platform else node.component_clients[name]
        request = TransitionManagedComponent.Request()
        request.transition = operation
        response = call(client, request)
        result = ros_mapping(response.result)
        target = (
            report['orchestrator_results'] if is_platform
            else report['injected_failure_results']
        )
        target.append(result)
        if is_platform:
            report['rollback_results'].extend(
                ros_mapping(item) for item in response.rollback_results
            )
        return response

    def platform_state_subscriptions_ready():
        for component in COMPONENT_ORDER:
            endpoints = node.get_subscriptions_info_by_topic(
                f'/lifecycle/{component}/state',
            )
            if not any(
                endpoint.node_name == 'platform_lifecycle_orchestrator'
                for endpoint in endpoints
            ):
                return False
        return True

    def platform_transition_when_state_ready(operation, timeout=10.0):
        deadline = time.monotonic() + timeout
        last_response = None
        while time.monotonic() < deadline:
            last_response = transition('', operation, True)
            if last_response.result.success or last_response.result.code != 'STATE_UNAVAILABLE':
                return last_response
            time.sleep(0.1)
        return last_response

    def runtime_graph_clean():
        names = [
            namespace.rstrip('/') + '/' + name
            for name, namespace in node.get_node_names_and_namespaces()
        ]
        counts = count_ros_nodes(names)
        clean = (
            all(counts.get(name, 0) == 1
                for name in REQUIRED_LIFECYCLE_MANAGERS)
            and not find_duplicate_ros_nodes(names, CRITICAL_ROS_NODES)
        )
        if clean:
            runtime_graph_clean.consecutive_clean_samples += 1
        else:
            runtime_graph_clean.consecutive_clean_samples = 0
        return runtime_graph_clean.consecutive_clean_samples >= 3

    runtime_graph_clean.consecutive_clean_samples = 0

    def trigger(name, required=True):
        response = call(node.trigger_clients[name], Trigger.Request())
        if required and not response.success:
            raise RuntimeError(f'{name} failed: {response.message}')
        return response

    def mode_trigger(name, required=True):
        response = call(node.mode_clients[name], Trigger.Request())
        if required and not response.success:
            raise RuntimeError(f'mode {name} failed: {response.message}')
        return response

    def publish(topic, value):
        message = String()
        message.data = value
        node.command_publishers[topic].publish(message)

    def endpoint_data(endpoints):
        output = []
        for endpoint in endpoints:
            qos = endpoint.qos_profile
            reliability = {
                1: 'RELIABLE', 2: 'BEST_EFFORT',
            }.get(int(qos.reliability), str(qos.reliability))
            durability = {
                1: 'TRANSIENT_LOCAL', 2: 'VOLATILE',
            }.get(int(qos.durability), str(qos.durability))
            output.append({
                'node_name': endpoint.node_name,
                'node_namespace': endpoint.node_namespace,
                'topic_type': endpoint.topic_type,
                'reliability': reliability,
                'durability': durability,
                'history': str(qos.history),
                'depth': qos.depth,
            })
        return output

    def capture_mapping_diagnostics(stage, map_name, query_slam=True):
        publishers = node.get_publishers_info_by_topic('/map')
        subscribers = node.get_subscriptions_info_by_topic('/map')
        graph_nodes = [
            namespace.rstrip('/') + '/' + name
            for name, namespace in node.get_node_names_and_namespaces()
        ]
        slam_lifecycle = None
        if query_slam:
            client = node.create_client(GetState, '/slam_toolbox/get_state')
            try:
                response = call(client, GetState.Request(), timeout=3.0)
                slam_lifecycle = {
                    'state_id': response.current_state.id,
                    'state_label': response.current_state.label,
                }
            except Exception as error:
                slam_lifecycle = {'error': f'{type(error).__name__}: {error}'}
            finally:
                node.destroy_client(client)
        prefix = Path.home() / '.ros' / 'cpp_robotics_sim' / 'maps' / 'warehouse' / map_name
        exact_command = [
            'ros2', 'run', 'nav2_map_server', 'map_saver_cli', '-f', str(prefix),
            '--free', '0.25', '--occ', '0.65',
        ]
        report.setdefault('mapping_diagnostics', []).append({
            'stage': stage,
            'captured_at': datetime.now(timezone.utc).isoformat(),
            'simulation_lifecycle': node.states.get('simulation'),
            'mapping_lifecycle': node.states.get('mapping'),
            'simulation_domain_state': node.domain_status.get('/simulation/status'),
            'mode_state': node.domain_status.get('/mode/status'),
            'slam_node_present': any(name.endswith('/slam_toolbox') for name in graph_nodes),
            'slam_lifecycle_state': (
                slam_lifecycle if slam_lifecycle else
                'not queried at this stage to preserve timing'
            ),
            'map_publishers': endpoint_data(publishers),
            'map_publisher_count': len(publishers),
            'map_subscribers': endpoint_data(subscribers),
            'map_subscriber_count': len(subscribers),
            'map_message_count': node.map_messages,
            'occupancy_grid_received': node.map_messages > 0,
            'map_receive_timestamps': list(node.map_received_at),
            'graph_nodes': graph_nodes,
            'exact_map_saver_command': exact_command,
        })

    try:
        rclpy.init(args=args)
        node = AcceptanceObserver()
        executor = MultiThreadedExecutor(num_threads=6)
        executor.add_node(node)
        executor_thread = threading.Thread(target=executor.spin, daemon=True)
        executor_thread.start()

        launch_log = launch_log_path.open('w', encoding='utf-8')
        launch = subprocess.Popen(
            ['ros2', 'launch', 'cpp_robotics_sim_ros', 'web_interface.launch.py',
             'open_browser:=false', 'mode_startup_grace_period:=8.0'],
            stdout=launch_log, stderr=subprocess.STDOUT, start_new_session=True,
        )
        if not wait_until(lambda: set(node.states) == set(COMPONENT_ORDER)):
            raise TimeoutError('manager lifecycle snapshots did not arrive')
        report['state_snapshots'].append(dict(node.states))
        initial_ok = all(
            value['state'] == LifecycleState.UNCONFIGURED.value
            for value in node.states.values()
        )
        record('1_initial_unconfigured', initial_ok, node.states)

        illegal = transition('localization', LifecycleTransition.ACTIVATE.value)
        before = node.states['localization']['state']
        record('illegal_transition_unchanged',
               not illegal.result.success and before == 'unconfigured',
               ros_mapping(illegal.result))

        sim_pre = trigger('/simulation/start', required=False)
        domain_baseline = node.domain_update_count
        publish('/mapping/save_request', 'lifecycle_preflight_map')
        publish('/localization/select_map_request', '{"map_name":"default_diffbot_map"}')
        publish('/navigation/goal_request', '{"x":0,"y":0,"yaw":0}')
        wait_until(lambda: node.domain_update_count >= domain_baseline + 3, timeout=3.0)
        inactive_messages = [
            sim_pre.message,
            node.domain_status.get('/mapping/save_status', ''),
            node.domain_status.get('/localization/status', ''),
            node.domain_status.get('/navigation/status', ''),
        ]
        record('5_inactive_operational_rejection',
               not sim_pre.success and all('ACTIVE' in text for text in inactive_messages),
               inactive_messages)

        graph_ready = wait_until(platform_state_subscriptions_ready, timeout=10.0)
        record('orchestrator_subscribed_to_all_component_states', graph_ready)
        if not graph_ready:
            raise TimeoutError(
                'platform orchestrator did not subscribe to every lifecycle state'
            )
        configured = platform_transition_when_state_ready(
            LifecycleTransition.CONFIGURE.value,
        )
        wait_until(lambda: all(
            node.states[name]['state'] == 'inactive' for name in COMPONENT_ORDER
        ))
        configured_ok = configured.result.success and all(
            node.states[name]['state'] == 'inactive' for name in COMPONENT_ORDER
        )
        record('2_configure_inactive', configured_ok, ros_mapping(configured.result))
        record(
            'configure_dependency_order',
            [item.component for item in configured.component_results]
            == list(COMPONENT_ORDER),
            [item.component for item in configured.component_results],
        )
        report['state_snapshots'].append(dict(node.states))
        activated = transition('', LifecycleTransition.ACTIVATE.value, True)
        wait_until(lambda: all(node.states[name]['state'] == 'active'
                               for name in COMPONENT_ORDER))
        active_ok = activated.result.success and all(
            node.states[name]['state'] == 'active' for name in COMPONENT_ORDER
        )
        record('3_dependency_order_activation', active_ok, ros_mapping(activated.result))
        record(
            'activate_dependency_order',
            [item.component for item in activated.component_results]
            == list(COMPONENT_ORDER),
            [item.component for item in activated.component_results],
        )
        activation_id = activated.result.transition_id
        correlated = all(
            item.orchestration_id == activation_id
            and any(
                event['transition_id'] == item.transition_id
                and event['orchestration_id'] == activation_id
                for event in node.events
            )
            for item in activated.component_results
        )
        record('transition_event_order_and_correlation', correlated)
        provenance = {}
        for name in COMPONENT_ORDER:
            snapshot = node.states[name]
            activate_event = next((event for event in reversed(node.events)
                                   if event['component'] == name
                                   and event['transition'] == 'activate'
                                   and event['success']), None)
            valid = bool(activate_event and snapshot['last_transition_id']
                         == activate_event['transition_id'])
            provenance[name] = {
                'valid': valid, 'snapshot': snapshot,
                'activate_event': activate_event,
            }
        report['active_provenance'] = provenance
        provenance_valid = all(item['valid'] for item in provenance.values())
        record('4_active_provenance', provenance_valid, provenance)
        record('18_active_only_via_activate', provenance_valid, provenance)
        report['state_snapshots'].append(dict(node.states))

        simulation_status = node.domain_status.get('/simulation/status', '')
        record(
            '6_lifecycle_active_simulation_stopped',
            'running' not in simulation_status,
            simulation_status or 'no status received',
        )
        # Exercise the established simulation lifecycle without equating ACTIVE
        # with the domain RUNNING state.
        sim_started = trigger('/simulation/start', required=False)
        if sim_started.success:
            reached_running = wait_until(
                lambda: 'running' in node.domain_status.get(
                    '/simulation/status', '',
                ),
            )
            record(
                '6_simulation_active_distinct_from_running',
                reached_running, sim_started.message,
            )
            trigger('/simulation/stop', required=True)
        else:
            record('6_simulation_active_distinct_from_running', False, sim_started.message)
        record(
            '7_simulation_operations_after_activation',
            sim_started.success, sim_started.message,
        )

        # Try the public mapping, localization, and navigation workflow using
        # the manager's existing mode and domain interfaces.
        mapping_workflow = False
        localization_workflow = False
        navigation_workflow = False
        report['manager_workflows'] = {}
        map_name = 'v012_' + stamp.replace('T', '_').replace('Z', '').replace('.', '')
        try:
            sim_started = trigger('/simulation/start')
            map_baseline = node.map_messages
            mapping_activated_at = datetime.now(timezone.utc).isoformat()
            mode_trigger('mapping')
            capture_mapping_diagnostics(
                'mapping_activated', map_name, query_slam=False,
            )
            early_probe_name = map_name + '_early'
            early_probe_baseline = len(node.domain_events)
            early_probe_at = datetime.now(timezone.utc).isoformat()
            publish('/mapping/save_request', early_probe_name)
            early_probe_completed = wait_until(
                lambda: any(
                    event['topic'] == '/mapping/save_status'
                    and event['value'].startswith('{')
                    and json.loads(event['value']).get('status')
                    in ('success', 'error')
                    for event in node.domain_events[early_probe_baseline:]
                ),
                timeout=25.0,
            )
            early_probe_status = node.domain_status.get('/mapping/save_status', '')
            report['mapping_early_probe'] = {
                'request_at': early_probe_at,
                'map_messages_at_request': map_baseline,
                'status_received': early_probe_completed,
                'status': early_probe_status,
            }
            if (
                early_probe_completed
                and 'failed to spin map subscription'
                in early_probe_status.lower()
            ):
                probe_prefix = (
                    Path.home() / '.ros' / 'cpp_robotics_sim' / 'maps'
                    / 'warehouse' / early_probe_name
                )
                probe_command = [
                    'ros2', 'run', 'nav2_map_server', 'map_saver_cli',
                    '-f', str(probe_prefix), '--free', '0.25', '--occ', '0.65',
                ]
                probe_result = subprocess.run(
                    probe_command, capture_output=True, text=True,
                    timeout=25.0, check=False,
                )
                report['mapping_early_probe']['exact_command'] = probe_command
                report['mapping_early_probe']['direct_cli_result'] = {
                    'returncode': probe_result.returncode,
                    'stdout': probe_result.stdout,
                    'stderr': probe_result.stderr,
                    'started_at': early_probe_at,
                    'completed_at': datetime.now(timezone.utc).isoformat(),
                }
                launch_log.flush()
                report['mapping_early_probe']['relevant_manager_logs'] = [
                    line for line in launch_log_path.read_text(
                        encoding='utf-8', errors='replace',
                    ).splitlines()
                    if any(token in line.lower() for token in (
                        'mapping_manager', 'map_saver', 'slam_toolbox',
                    ))
                ]
            map_topic_ready = wait_until(
                lambda: (
                    node.map_messages >= map_baseline + 1
                    and node.domain_status.get('/mode/status') == 'mapping'
                ), timeout=35.0,
            )
            if not map_topic_ready:
                raise RuntimeError(
                    'mapping mode started but no /map OccupancyGrid arrived'
                )
            # Perform slow graph and SLAM lifecycle inspection before the final
            # observable message precondition, not between it and the request.
            capture_mapping_diagnostics('map_observed', map_name)
            prior_map_count = node.map_messages
            fresh_map_ready = wait_until(
                lambda: node.map_messages > prior_map_count
                and node.domain_status.get('/mode/status') == 'mapping',
                timeout=10.0,
            )
            if not fresh_map_ready:
                raise TimeoutError(
                    'no fresh /map OccupancyGrid arrived after diagnostics; '
                    f'messages={node.map_messages}, last_at='
                    f'{node.map_received_at[-1] if node.map_received_at else "none"}'
                )
            mapping_status_baseline = len(node.domain_events)
            save_requested_at = datetime.now(timezone.utc).isoformat()
            report['mapping_save_precondition'] = {
                'map_messages_at_request': node.map_messages,
                'latest_map_received_at': node.map_received_at[-1],
                'save_request_at': save_requested_at,
                'map_received_immediately_before_request': True,
            }
            publish('/mapping/save_request', map_name)
            saver_endpoint_samples = []
            mapping_terminal_status = ''
            mapping_deadline = time.monotonic() + 25.0
            while time.monotonic() < mapping_deadline:
                for event in node.domain_events[mapping_status_baseline:]:
                    if (
                        event['topic'] != '/mapping/save_status'
                        or not event['value'].startswith('{')
                    ):
                        continue
                    payload = json.loads(event['value'])
                    if (
                        payload.get('map_name') == map_name
                        and payload.get('status') in ('success', 'error')
                    ):
                        mapping_terminal_status = event['value']
                        break
                if mapping_terminal_status:
                    break
                live_subscribers = endpoint_data(
                    node.get_subscriptions_info_by_topic('/map'),
                )
                saver_endpoint_samples.append({
                    'at': datetime.now(timezone.utc).isoformat(),
                    'subscribers': live_subscribers,
                })
                time.sleep(0.05)
            if mapping_terminal_status:
                mapping_workflow = (
                    json.loads(mapping_terminal_status).get('status') == 'success'
                )
            report['mapping_saver_endpoint_samples'] = saver_endpoint_samples
            report['mapping_diagnostics'][-1]['mapping_activation_at'] = mapping_activated_at
            report['mapping_diagnostics'][-1]['save_request_at'] = save_requested_at
            report['mapping_diagnostics'][-1]['map_manager_status'] = mapping_terminal_status
            if not mapping_workflow:
                direct_result = subprocess.run(
                    report['mapping_diagnostics'][-1]['exact_map_saver_command'],
                    capture_output=True, text=True, timeout=25.0, check=False,
                )
                report['mapping_diagnostics'][-1]['direct_map_saver_result'] = {
                    'returncode': direct_result.returncode,
                    'stdout': direct_result.stdout,
                    'stderr': direct_result.stderr,
                }
                launch_log.flush()
                report['mapping_diagnostics'][-1]['relevant_manager_logs'] = [
                    line for line in launch_log_path.read_text(
                        encoding='utf-8', errors='replace',
                    ).splitlines()
                    if any(token in line.lower() for token in (
                        'mapping_manager', 'map_saver', 'slam_toolbox',
                    ))
                ]
            else:
                report['mapping_diagnostics'][-1]['map_manager_status'] = (
                    node.domain_status.get('/mapping/save_status', '')
                )
            report['manager_workflows']['mapping'] = {
                'lifecycle_active_at_start': node.states['mapping']['state'] == 'active',
                'map_messages_received': node.map_messages - map_baseline,
                'map_save_succeeded': mapping_workflow,
                'save_status': mapping_terminal_status,
            }
            mode_trigger('stop', required=False)
            mapping_deactivated = transition(
                'mapping', LifecycleTransition.DEACTIVATE.value,
            )
            inactive_baseline = len(node.domain_events)
            publish('/mapping/save_request', map_name + '_inactive')
            mapping_inactive_rejected = wait_until(
                lambda: any(
                    event['topic'] == '/mapping/save_status'
                    and 'not ACTIVE' in event['value']
                    for event in node.domain_events[inactive_baseline:]
                ), timeout=3.0,
            )
            mapping_reactivated = transition(
                'mapping', LifecycleTransition.ACTIVATE.value,
            )
            record('mapping_deactivate_and_inactive_rejection',
                   mapping_deactivated.result.success
                   and mapping_inactive_rejected
                   and mapping_reactivated.result.success,
                   {'deactivate': ros_mapping(mapping_deactivated.result),
                    'inactive_rejection': node.domain_status.get('/mapping/save_status'),
                    'reactivate': ros_mapping(mapping_reactivated.result)})
        except Exception as error:
            report['manager_workflows'] = {
                'mapping_error': f'{type(error).__name__}: {error}',
            }

        # Localization uses a copied, known-valid package fixture so it does
        # not depend on the mapping save above succeeding.
        fixture_directory = (
            Path.home() / '.ros' / 'cpp_robotics_sim' / 'maps' / 'warehouse'
        )
        fixture_name = 'v012_fixture_' + stamp.replace('T', '_').replace('Z', '').replace('.', '')
        fixture_source = (
            Path(get_package_share_directory('cpp_robotics_sim_ros'))
            / 'maps' / 'default_diffbot_map'
        )
        fixture_target = fixture_directory / fixture_name
        fixture_directory.mkdir(parents=True, exist_ok=True)
        for extension in ('.yaml', '.pgm'):
            shutil.copy2(
                fixture_source.with_suffix(extension),
                fixture_target.with_suffix(extension),
            )
        fixture_yaml = fixture_target.with_suffix('.yaml')
        fixture_yaml.write_text(
            fixture_yaml.read_text(encoding='utf-8').replace(
                'image: default_diffbot_map.pgm',
                f'image: {fixture_name}.pgm',
            ),
            encoding='utf-8',
        )
        report['fixture_map'] = {
            'name': fixture_name,
            'environment': 'warehouse',
            'source': str(fixture_source),
            'yaml': str(fixture_target.with_suffix('.yaml')),
            'image': str(fixture_target.with_suffix('.pgm')),
        }
        try:
            mode_trigger('stop', required=False)
            localization_baseline = len(node.domain_events)
            publish('/localization/select_map_request', json.dumps({
                'name': fixture_name, 'environment': 'warehouse',
            }))
            fixture_selected = wait_until(
                lambda: any(
                    event['topic'] == '/localization/status'
                    and 'success' in event['value'].lower()
                    for event in node.domain_events[localization_baseline:]
                ), timeout=5.0,
            )
            mode_trigger('localization')
            pose_baseline = node.initial_pose_messages
            publish('/localization/initial_pose_request',
                    json.dumps({'x': 0.0, 'y': 0.0, 'yaw': 0.0}))
            pose_published = wait_until(
                lambda: node.initial_pose_messages > pose_baseline, timeout=5.0,
            )
            localization_workflow = fixture_selected and pose_published
            report['manager_workflows']['localization'] = {
                'lifecycle_active_at_start': node.states['localization']['state'] == 'active',
                'fixture_selected': fixture_selected,
                'initial_pose_published': pose_published,
                'status': node.domain_status.get('/localization/status', ''),
            }
            record('localization_real_fixture_and_pose_workflow',
                   localization_workflow,
                   report['manager_workflows']['localization'])
            mode_trigger('stop', required=False)
            localization_deactivated = transition(
                'localization', LifecycleTransition.DEACTIVATE.value,
            )
            inactive_baseline = len(node.domain_events)
            publish('/localization/initial_pose_request',
                    json.dumps({'x': 1.0, 'y': 1.0, 'yaw': 0.0}))
            localization_inactive_rejected = wait_until(
                lambda: any(
                    event['topic'] == '/localization/status'
                    and 'not ACTIVE' in event['value']
                    for event in node.domain_events[inactive_baseline:]
                ), timeout=3.0,
            )
            localization_reactivated = transition(
                'localization', LifecycleTransition.ACTIVATE.value,
            )
            record('localization_deactivate_and_inactive_rejection',
                   localization_deactivated.result.success
                   and localization_inactive_rejected
                   and localization_reactivated.result.success,
                   {'deactivate': ros_mapping(localization_deactivated.result),
                    'inactive_rejection': node.domain_status.get('/localization/status'),
                    'reactivate': ros_mapping(localization_reactivated.result)})
        except Exception as error:
            report.setdefault('manager_workflows', {})['localization_error'] = (
                f'{type(error).__name__}: {error}'
            )

        try:
            mode_trigger('stop', required=False)
            report['navigation_launch_configuration'] = {
                'launch_argument': 'mode_startup_grace_period:=8.0',
                'rationale': (
                    'nav2_navigation.launch.py contains a 4.0 s TimerAction; '
                    'the mode manager default descendant-capture grace is 3.0 s'
                ),
            }
            mode_trigger('navigation')
            action_server_ready = wait_until(
                lambda: node.navigation_action_client.wait_for_server(
                    timeout_sec=0.2,
                ), timeout=30.0,
            )
            if not action_server_ready:
                raise TimeoutError(
                    '/navigate_to_pose action server did not become available'
                )
            tf_buffer = Buffer()
            node._tf_listener = TransformListener(
                tf_buffer,
                node,
                spin_thread=False,
            )
            navigation_pose_baseline = node.initial_pose_messages
            navigation_pose_status_baseline = len(node.domain_events)
            publish(
                '/localization/initial_pose_request',
                json.dumps({'x': 0.0, 'y': 0.0, 'yaw': 0.0}),
            )
            navigation_pose_published = wait_until(
                lambda: node.initial_pose_messages > navigation_pose_baseline
                and any(
                    event['topic'] == '/localization/status'
                    and 'Initial pose published' in event['value']
                    for event in node.domain_events[
                        navigation_pose_status_baseline:
                    ]
                ),
                timeout=5.0,
            )
            navigation_localization_ready = navigation_pose_published and wait_until(
                lambda: tf_buffer.can_transform('map', 'odom', Time()),
                timeout=10.0,
            )
            record(
                'navigation_localization_transform_ready',
                navigation_localization_ready,
                {
                    'initial_pose_published': navigation_pose_published,
                    'map_to_odom_available': navigation_localization_ready,
                },
            )
            if not navigation_localization_ready:
                raise TimeoutError(
                    'navigation AMCL did not establish map -> odom after '
                    'the initial pose was published'
                )
            navigation_baseline = len(node.domain_events)
            publish('/navigation/goal_request', '{"x":1.0,"y":0.0,"yaw":0.0}')
            accepted = wait_until(
                lambda: any(
                    event['topic'] == '/navigation/status'
                    and json.loads(event['value']).get('state')
                    in ('accepted', 'navigating')
                    for event in node.domain_events[navigation_baseline:]
                    if event['value'].startswith('{')
                ), timeout=20.0,
            )
            report.setdefault('manager_workflows', {})[
                'navigation_goal_accepted'
            ] = accepted
            if accepted:
                navigation_deactivated = transition(
                    'navigation', LifecycleTransition.DEACTIVATE.value,
                )
                navigation_workflow = wait_until(
                    lambda: any(
                        event['topic'] == '/navigation/status'
                        and json.loads(event['value']).get('state') == 'canceled'
                        for event in node.domain_events[navigation_baseline:]
                        if event['value'].startswith('{')
                    ), timeout=10.0,
                )
                inactive_baseline = len(node.domain_events)
                publish('/navigation/goal_request', '{"x":0,"y":0,"yaw":0}')
                inactive_rejected = wait_until(
                    lambda: any(
                        event['topic'] == '/navigation/status'
                        and 'not ACTIVE' in event['value']
                        for event in node.domain_events[inactive_baseline:]
                    ), timeout=3.0,
                )
                navigation_reactivated = transition(
                    'navigation', LifecycleTransition.ACTIVATE.value,
                )
                record('navigation_deactivation_cancels_goal',
                       navigation_deactivated.result.success and navigation_workflow
                       and inactive_rejected and navigation_reactivated.result.success,
                       {'deactivate': ros_mapping(navigation_deactivated.result),
                        'goal_canceled': navigation_workflow,
                        'inactive_rejection': node.domain_status.get('/navigation/status'),
                        'reactivate': ros_mapping(navigation_reactivated.result)})
            report['manager_workflows']['navigation'] = {
                'lifecycle_active_at_start': node.states['navigation']['state'] == 'active',
                'goal_accepted': accepted,
                'goal_canceled_by_deactivation': navigation_workflow,
                'status': node.domain_status.get('/navigation/status', ''),
            }
            record('navigation_real_goal_and_deactivation_workflow',
                   accepted and navigation_workflow,
                   report['manager_workflows']['navigation'])
        except Exception as error:
            report.setdefault('manager_workflows', {})['navigation_error'] = (
                f'{type(error).__name__}: {error}'
            )
        mode_trigger('stop', required=False)
        trigger('/simulation/stop', required=False)
        record(
            '8_mapping_workflow', mapping_workflow,
            node.domain_status.get('/mapping/save_status', ''),
        )
        record(
            '9_localization_workflow', localization_workflow,
            node.domain_status.get('/localization/status', ''),
        )
        record(
            'navigation_goal_cancel_workflow', navigation_workflow,
            node.domain_status.get('/navigation/status', ''),
        )

        # A manager fault from INACTIVE is a deterministic middle-component
        # activation failure. The aggregate service must rollback only the two
        # completed upstream managers and suppress navigation activation.
        inactive_platform = transition('', LifecycleTransition.DEACTIVATE.value, True)
        if not inactive_platform.result.success:
            raise RuntimeError('pre-injection platform deactivation failed')
        transition('localization', LifecycleTransition.ERROR.value)
        failed_activate = transition('', LifecycleTransition.ACTIVATE.value, True)
        wait_until(lambda: any(
            event['component'] == 'localization'
            and event['transition'] == 'activate'
            and not event['success']
            and event['orchestration_id'] == failed_activate.result.transition_id
            for event in node.events
        ), timeout=3.0)
        rollback_components = [item['component'] for item in report['rollback_results']]
        downstream_suppressed = not any(
            event['component'] == 'navigation' and event['transition'] == 'activate'
            and event['orchestration_id'] == failed_activate.result.transition_id
            for event in node.events
        )
        record('11_middle_activation_failure_suppresses_downstream',
               not failed_activate.result.success and downstream_suppressed,
               ros_mapping(failed_activate.result))
        record('12_reverse_upstream_rollback',
               rollback_components[-2:] == ['mapping', 'simulation'], rollback_components)
        recovered = transition('localization', LifecycleTransition.RECOVER.value)
        wait_until(lambda: node.states['localization']['state'] == 'unconfigured')
        record('13_error_recovery_to_unconfigured',
               recovered.result.success and node.states['localization']['state'] == 'unconfigured',
               ros_mapping(recovered.result))
        report['state_snapshots'].append(dict(node.states))

        reconfigured = transition('', LifecycleTransition.CONFIGURE.value, True)
        reactivated = transition('', LifecycleTransition.ACTIVATE.value, True)
        record('14_reconfigure_reactivate_after_recovery',
               reconfigured.result.success and reactivated.result.success,
               [ros_mapping(reconfigured.result), ros_mapping(reactivated.result)])
        report['state_snapshots'].append(dict(node.states))

        # Late subscriber verifies transient-local lifecycle state replay.
        late = Node('v012_late_lifecycle_subscriber')
        late_states = {}
        for name in COMPONENT_ORDER:
            late.create_subscription(
                ManagedLifecycleState, f'/lifecycle/{name}/state',
                lambda value, component=name: late_states.__setitem__(component, value.state),
                STATE_QOS,
            )
        executor.add_node(late)
        replayed = wait_until(lambda: set(late_states) == set(COMPONENT_ORDER))
        record('late_subscriber_state_replay', replayed, late_states)

        deactivated = transition('', LifecycleTransition.DEACTIVATE.value, True)
        wait_until(lambda: all(
            node.states[name]['state'] == 'inactive' for name in COMPONENT_ORDER
        ))
        deactivation_order = [
            event.component for event in deactivated.component_results
        ]
        record(
            '15_reverse_deactivation',
            deactivated.result.success
            and deactivation_order == list(reversed(COMPONENT_ORDER)),
            deactivation_order,
        )
        cleaned = transition('', LifecycleTransition.CLEANUP.value, True)
        wait_until(lambda: all(
            node.states[name]['state'] == 'unconfigured' for name in COMPONENT_ORDER
        ))
        record('16_cleanup_unconfigured', cleaned.result.success and all(
            node.states[name]['state'] == 'unconfigured' for name in COMPONENT_ORDER
        ), ros_mapping(cleaned.result))
        shut = transition('', LifecycleTransition.SHUTDOWN.value, True)
        wait_until(lambda: all(
            node.states[name]['state'] == 'finalized' for name in COMPONENT_ORDER
        ))
        record('17_shutdown_finalized', shut.result.success and all(
            node.states[name]['state'] == 'finalized' for name in COMPONENT_ORDER
        ), ros_mapping(shut.result))

        time.sleep(1.0)
        report['transition_events'] = list(node.events)
        report['state_snapshots'].append(dict(node.states))
        registry_records = [
            record.__dict__ for record in ProcessRegistry().list_records()
        ]
        report['registry_final_state'] = registry_records
        record('19_process_registry_clean', not registry_records, registry_records)
        node_lines = sorted(
            namespace.rstrip('/') + '/' + name
            for name, namespace in node.get_node_names_and_namespaces()
        )
        graph_complete = wait_until(runtime_graph_clean, timeout=8.0)
        node_lines = sorted(
            namespace.rstrip('/') + '/' + name
            for name, namespace in node.get_node_names_and_namespaces()
        )
        report['runtime_nodes'] = node_lines
        node_counts = count_ros_nodes(node_lines)
        duplicate_critical_nodes = find_duplicate_ros_nodes(
            node_lines, CRITICAL_ROS_NODES,
        )
        lifecycle_manager_counts = {
            name: node_counts.get(name, 0)
            for name in REQUIRED_LIFECYCLE_MANAGERS
        }
        record(
            '20_no_duplicate_critical_nodes',
            graph_complete and not duplicate_critical_nodes,
            {
                'duplicate_critical_nodes': duplicate_critical_nodes,
                'critical_node_source': 'runtime_verification.CRITICAL_ROS_NODES',
                'graph_nodes': node_lines,
            },
        )
        record(
            '21_required_lifecycle_managers_present_once',
            graph_complete and all(
                count == 1 for count in lifecycle_manager_counts.values()
            ),
            {'manager_counts': lifecycle_manager_counts},
        )
    except Exception as error:
        report['fatal_error'] = f'{type(error).__name__}: {error}'
    finally:
        if node is not None:
            report['transition_events'] = list(node.events)
            report['state_snapshots'].append(dict(node.states))
        if launch is not None and launch.poll() is None:
            try:
                os.killpg(launch.pid, signal.SIGINT)
                launch.wait(timeout=15.0)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(launch.pid, signal.SIGTERM)
                    launch.wait(timeout=5.0)
                except (ProcessLookupError, subprocess.TimeoutExpired):
                    os.killpg(launch.pid, signal.SIGKILL)
        if executor is not None:
            executor.shutdown(timeout_sec=3.0)
        if late is not None:
            late.destroy_node()
        if node is not None:
            node.destroy_node()
        if executor_thread is not None:
            executor_thread.join(timeout=3.0)
        if rclpy.ok():
            rclpy.shutdown()
        if launch_log is not None:
            launch_log.close()
        report['completed_at'] = datetime.now(timezone.utc).isoformat()
        failed = [
            name for name, item in report['checks'].items()
            if not item['passed']
        ]
        if report.get('fatal_error'):
            failed.append(f"fatal_error: {report['fatal_error']}")
        report['release_decision'] = (
            'ACCEPTED'
            if not failed and not report.get('fatal_error')
            else 'NOT_ACCEPTED'
        )
        report['remaining_blockers'] = failed

        def write_json(filename, value):
            payload = json.dumps(value, indent=2, default=str) + '\n'
            (evidence / filename).write_text(payload, encoding='utf-8')

        write_json('summary.json', report)
        write_json('state_snapshots.json', report['state_snapshots'])
        write_json('transition_events.json', report['transition_events'])
        write_json('orchestrator_results.json', report['orchestrator_results'])
        write_json('injected_failure_results.json', report['injected_failure_results'])
        write_json('rollback_results.json', report['rollback_results'])
        write_json('active_provenance.json', report['active_provenance'])
        final_states = report['state_snapshots'][-1] if report['state_snapshots'] else {}
        report['final_lifecycle_states'] = final_states
        write_json(
            'final_lifecycle_states.json',
            final_states,
        )
        write_json('registry_final_state.json', report.get('registry_final_state', []))
        (evidence / 'release_decision.txt').write_text(
            report['release_decision'] + '\n', encoding='utf-8',
        )
        print(f'Evidence: {evidence}')
        print(f"Release decision: {report['release_decision']}")
    return 0 if report['release_decision'] == 'ACCEPTED' else 1


if __name__ == '__main__':
    raise SystemExit(main())
