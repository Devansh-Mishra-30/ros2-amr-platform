#!/usr/bin/env python3
# Copyright 2026 Devansh Mishra
#
# Use of this source code is governed by an MIT-style
# license that can be found in the LICENSE file or at
# https://opensource.org/licenses/MIT.

"""Tests for independent, structured dependency readiness contracts."""

from collections import deque
import importlib.util
from pathlib import Path
import sys
import threading


MODULE_PATH = (
    Path(__file__).resolve().parents[1] / 'scripts'
    / 'readiness_contract.py'
)
spec = importlib.util.spec_from_file_location('readiness_contract', MODULE_PATH)
readiness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(readiness)

SCRIPT_DIRECTORY = str(MODULE_PATH.parent)
if SCRIPT_DIRECTORY not in sys.path:
    sys.path.insert(0, SCRIPT_DIRECTORY)
import ros_runtime_readiness as runtime_probe  # noqa: E402
from rosgraph_msgs.msg import Clock  # noqa: E402


def test_runtime_probe_ignores_global_manager_node_remap(monkeypatch):
    captured = {}

    class FakeNode:
        def __init__(self, name, **kwargs):
            captured['name'] = name
            captured['kwargs'] = kwargs

        def set_parameters(self, _parameters):
            pass

        def create_subscription(self, *_args, **_kwargs):
            return object()

        def create_client(self, *_args, **_kwargs):
            return object()

        def destroy_node(self):
            pass

    class FakeBuffer:
        def __init__(self, **_kwargs):
            pass

    class FakeExecutor:
        def add_node(self, _node):
            pass

        def spin(self):
            pass

        def shutdown(self, **_kwargs):
            pass

    monkeypatch.setattr(runtime_probe, 'Node', FakeNode)
    monkeypatch.setattr(runtime_probe, 'Buffer', FakeBuffer)
    monkeypatch.setattr(runtime_probe, 'TransformListener', lambda *_a, **_k: object())
    monkeypatch.setattr(runtime_probe, 'ActionClient', lambda *_a, **_k: object())
    monkeypatch.setattr(runtime_probe, 'SingleThreadedExecutor', FakeExecutor)

    probe = runtime_probe.SimulationReadinessProbe(use_sim_time=True)
    probe.close()

    assert captured['name'] == 'simulation_readiness_probe'
    assert captured['kwargs']['use_global_arguments'] is False


def _clock_probe():
    probe = object.__new__(runtime_probe.SimulationReadinessProbe)
    probe._lock = threading.Lock()
    probe._clock_samples = deque(
        maxlen=runtime_probe.CLOCK_SAMPLE_BUFFER_SIZE
    )
    return probe


def _append_clock(probe, ros_seconds, received, monkeypatch):
    nanoseconds = round(ros_seconds * 1_000_000_000)
    message = Clock()
    message.clock.sec = nanoseconds // 1_000_000_000
    message.clock.nanosec = nanoseconds % 1_000_000_000
    monkeypatch.setattr(runtime_probe.time, 'monotonic', lambda: received)
    probe._clock(message)


def _check_probe_clock(probe, *, now, runtime_id='run'):
    return readiness.check_clock(
        tuple(probe._clock_samples), use_sim_time=True,
        now=now, runtime_id=runtime_id,
    )


def test_clock_requires_fresh_advancing_ros_and_receive_time():
    good = readiness.check_clock(
        [(1.0, 5.0), (1.5, 5.1), (2.0, 5.2)],
        use_sim_time=True, now=5.2, runtime_id='run',
    )
    assert good.state.value == 'ready'

    batched = readiness.check_clock(
        [(1.0, 5.0), (2.0, 5.0)],
        use_sim_time=True, now=5.0, runtime_id='run',
    )
    assert batched.state.value == 'blocked'
    assert batched.reason == 'clock_samples_batched'

    old = readiness.check_clock(
        [(1.0, 5.0), (2.0, 5.2)],
        use_sim_time=True, now=10.0, runtime_id='run',
    )
    assert old.state.value == 'blocked'
    assert old.reason == 'clock_samples_stale'

    stopped = readiness.check_clock(
        [(2.0, 5.0), (2.0, 5.2)],
        use_sim_time=True, now=5.2, runtime_id='run',
    )
    assert stopped.state.value == 'blocked'
    assert stopped.reason == 'clock_stopped'

    recovered = readiness.check_clock(
        [(2.0, 10.0), (2.25, 10.1), (2.5, 10.2)],
        use_sim_time=True, now=10.2, runtime_id='new-run',
    )
    assert recovered.state.value == 'ready'


def test_clock_stopped_plateau_does_not_lend_span_to_one_recovery_tick():
    samples = [(2.0, 10.0 + index * 0.001) for index in range(900)]
    samples.append((2.001, 10.900))
    result = readiness.check_clock(samples, use_sim_time=True, now=10.900,
                                   runtime_id='run')
    assert result.state.value == 'blocked'

    isolated = readiness.check_clock(
        [(1.0, 10.0), (1.001, 10.9)],
        use_sim_time=True, now=10.9, runtime_id='run',
    )
    assert isolated.state.value == 'blocked'


def test_clock_plateau_reset_uses_inclusive_receive_span_boundary():
    shorter = readiness.check_clock(
        [(1.0, 0.0), (1.001, 0.001), (1.001, 0.050),
         (1.002, 0.051), (1.003, 0.052)],
        use_sim_time=True, now=0.052, runtime_id='run',
    )
    assert shorter.state.value == 'ready'

    for plateau_time in (0.051, 0.052):
        samples = [
            (1.0, 0.0), (1.001, 0.001), (1.001, plateau_time),
            (1.002, plateau_time + 0.001),
        ]
        one_tick = readiness.check_clock(
            samples, use_sim_time=True, now=plateau_time + 0.001,
            runtime_id='run',
        )
        assert one_tick.state.value == 'blocked'

    sustained_samples = [
        (1.0, 0.0), (1.001, 0.001), (1.001, 0.051),
        (1.002, 0.052),
    ]
    sustained_samples.extend(
        (1.002 + index * 0.001, 0.052 + index * 0.001)
        for index in range(1, 53)
    )
    sustained = readiness.check_clock(
        sustained_samples, use_sim_time=True, now=0.104, runtime_id='run',
    )
    assert sustained.state.value == 'ready'


def test_clock_recovery_requires_fresh_contiguous_advancing_run():
    samples = [(2.0, 10.0 + index * 0.001) for index in range(900)]
    samples.extend((2.001 + index * 0.001, 10.900 + index * 0.001)
                   for index in range(1, 71))
    result = readiness.check_clock(samples, use_sim_time=True, now=10.970,
                                   runtime_id='run')
    assert result.state.value == 'ready'
    assert result.observed['receive_span_seconds'] >= 0.05
    assert result.observed['advance_seconds'] >= 0.001


def test_clock_ignores_batched_prefix_before_sustained_live_advancement():
    samples = [(1.0 + index * 0.001, 5.0) for index in range(20)]
    samples.extend((1.020 + index * 0.001, 5.0 + index * 0.001)
                   for index in range(1, 71))
    result = readiness.check_clock(samples, use_sim_time=True, now=5.070,
                                   runtime_id='run')
    assert result.state.value == 'ready'


def test_clock_tolerates_isolated_duplicate_ticks_inside_live_run():
    samples = []
    ros_time = 1.0
    for index in range(101):
        received = 20.0 + index * 0.001
        if index % 10:
            ros_time += 0.001
        samples.append((ros_time, received))
    result = readiness.check_clock(samples, use_sim_time=True, now=20.100,
                                   runtime_id='run')
    assert result.state.value == 'ready'


def test_clock_result_expires_from_qualifying_source_sample_time():
    samples = [(3.0 + index * 0.001, 30.0 + index * 0.001)
               for index in range(70)]
    result = readiness.check_clock(samples, use_sim_time=True, now=30.069,
                                   runtime_id='run')
    assert result.state.value == 'ready'
    assert result.observed_monotonic == samples[-1][1]
    assert result.lease_seconds == 1.0
    assert result.current_for('run', 30.5)
    # Evaluating a new result later cannot reset the source observation age.
    evaluated_late = readiness.check_clock(samples, use_sim_time=True, now=30.8,
                                           runtime_id='run')
    assert evaluated_late.state.value == 'ready'
    assert evaluated_late.observed_monotonic == samples[-1][1]
    assert evaluated_late.current_for('run', 30.9)
    assert not result.current_for('run', 31.0701)
    fresh = readiness.check_clock(
        [(4.0 + index * 0.001, 31.01 + index * 0.001) for index in range(70)],
        use_sim_time=True, now=31.079, runtime_id='run',
    )
    assert fresh.state.value == 'ready'
    assert fresh.current_for('run', 31.08)


def test_probe_clock_burst_then_live_advancement_eventually_becomes_ready(
    monkeypatch,
):
    probe = _clock_probe()
    for index in range(20):
        _append_clock(probe, 1.0 + index * 0.001, 5.0, monkeypatch)
    burst = _check_probe_clock(probe, now=5.0)
    assert burst.state.value == 'blocked'
    assert burst.reason == 'clock_samples_batched'

    for index in range(1, 71):
        _append_clock(probe, 1.020 + index * 0.001,
                      5.0 + index * 0.001, monkeypatch)

    live = _check_probe_clock(probe, now=5.070)
    assert live.state.value == 'ready'
    assert live.observed['receive_span_seconds'] >= 0.05
    assert live.observed['advance_seconds'] >= 0.001


def test_probe_clock_only_burst_then_silence_expires():
    probe = _clock_probe()
    probe._clock_samples.extend((1.0 + index * 0.001, 5.0) for index in range(20))

    initial = _check_probe_clock(probe, now=5.0)
    later = _check_probe_clock(probe, now=6.01)

    assert initial.state.value == 'blocked'
    assert initial.reason == 'clock_samples_batched'
    assert later.state.value == 'blocked'
    assert later.reason == 'clock_samples_stale'


def test_probe_clock_high_rate_live_window_is_ready_and_stales_when_stopped(
    monkeypatch,
):
    probe = _clock_probe()
    for index in range(100):
        _append_clock(probe, 2.0 + index * 0.001,
                      10.0 + index * 0.001, monkeypatch)

    ready = _check_probe_clock(probe, now=10.099)
    stopped = _check_probe_clock(probe, now=11.101)

    assert ready.state.value == 'ready'
    assert stopped.state.value == 'blocked'
    assert stopped.reason == 'clock_samples_stale'


def test_probe_clock_zero_blocks_and_fresh_advancement_recovers(monkeypatch):
    probe = _clock_probe()
    for index in range(70):
        _append_clock(probe, 0.0, 20.0 + index * 0.001, monkeypatch)

    zero = _check_probe_clock(probe, now=20.069)
    assert zero.state.value == 'blocked'
    assert zero.reason == 'clock_stopped'

    probe._clock_samples.clear()
    for index in range(70):
        _append_clock(probe, 3.0 + index * 0.001,
                      21.0 + index * 0.001, monkeypatch)
    recovered = _check_probe_clock(probe, now=21.069, runtime_id='recovered')
    assert recovered.state.value == 'ready'


def test_topic_checks_freshness_and_rate():
    assert readiness.check_topic('/scan', [8.0, 9.0, 10.0], now=10.0,
                                 min_rate_hz=0.4, max_age=0.5,
                                 runtime_id='run').state.value == 'ready'
    result = readiness.check_topic('/scan', [1.0, 2.0], now=10.0,
                                   min_rate_hz=0.4, max_age=0.5,
                                   runtime_id='run')
    assert result.state.value == 'blocked'
    assert result.reason == 'no recent messages'


def test_tf_checks_resolution_freshness_and_timeout():
    assert readiness.check_tf('odom', 'base_link', available=True,
                              age_seconds=0.1, max_age=0.5,
                              lookup_seconds=0.01, timeout=0.1,
                              runtime_id='run').state.value == 'ready'
    stale = readiness.check_tf('odom', 'base_link', available=True,
                               age_seconds=1.0, max_age=0.5,
                               lookup_seconds=0.01, timeout=0.1,
                               runtime_id='run')
    assert stale.reason == 'transform is stale'


def test_endpoint_discovery_requires_explicit_responsiveness_by_default():
    assert readiness.check_endpoint('/clear', 'service', available=False,
                                    runtime_id='run').state.value == 'blocked'
    unknown = readiness.check_endpoint('/clear', 'service', available=True,
                                       runtime_id='run')
    assert unknown.state.value == 'blocked'
    assert unknown.reason == 'endpoint responsiveness is unknown'
    timeout = readiness.check_endpoint('/clear', 'service', available=True,
                                       responsive=False, runtime_id='run')
    assert timeout.state.value == 'blocked'
    recovered = readiness.check_endpoint('/clear', 'service', available=True,
                                         responsive=True, runtime_id='run')
    assert recovered.state.value == 'ready'
    unavailable_action = readiness.check_navigation_action_server(
        available=True, lifecycle_state='inactive', runtime_id='run',
    )
    assert unavailable_action.state.value == 'blocked'
    assert unavailable_action.reason == 'bt_navigator is not active (state=inactive)'
    active_action = readiness.check_navigation_action_server(
        available=True, lifecycle_state='active', runtime_id='run',
    )
    assert active_action.state.value == 'ready'


class PendingControllerFuture:
    def __init__(self, result=None):
        self.value = result
        self.completed = False
        self.cancelled = False

    def done(self):
        return self.completed

    def result(self):
        return self.value

    def cancel(self):
        self.cancelled = True
        self.completed = True


class ControllerServiceClient:
    def __init__(self, futures):
        self.futures = list(futures)
        self.calls = 0
        self.removed = []

    def service_is_ready(self):
        return True

    def call_async(self, _request):
        future = self.futures[self.calls]
        self.calls += 1
        return future

    def remove_pending_request(self, future):
        self.removed.append(future)


def test_controller_state_probe_retries_after_unanswered_request(monkeypatch):
    first = PendingControllerFuture()
    recovered_response = object()
    second = PendingControllerFuture(recovered_response)
    third = PendingControllerFuture()
    client = ControllerServiceClient([first, second, third])
    probe = object.__new__(runtime_probe.SimulationReadinessProbe)
    probe._controller_client = client
    probe._controller_future = None
    probe._controller_request_started = None
    probe._controller_response = None
    probe._controller_response_at = 0.0
    clock = [10.0]
    monkeypatch.setattr(runtime_probe.time, 'monotonic', lambda: clock[0])

    available, response = probe._request_controller_state()
    assert available is True
    assert response is None
    assert client.calls == 1

    clock[0] += runtime_probe.CONTROLLER_REQUEST_TIMEOUT_SECONDS - 0.01
    _available, response = probe._request_controller_state()
    assert response is None
    assert client.calls == 1

    clock[0] += 0.01
    _available, response = probe._request_controller_state()
    assert response is None
    assert first.cancelled is True
    assert client.removed == [first]
    assert client.calls == 2

    second.completed = True
    clock[0] += 0.1
    _available, response = probe._request_controller_state()
    assert response is recovered_response
    assert client.calls == 3
    assert probe._controller_future is third


def test_controllers_map_and_localization():
    assert readiness.check_controllers(['joint_state_broadcaster'],
                                       ['joint_state_broadcaster'],
                                       runtime_id='run').state.value == 'ready'
    assert readiness.check_controllers([], ['diff_drive_controller'],
                                       runtime_id='run').state.value == 'blocked'
    assert readiness.check_map('/maps/site.yaml', available=False,
                               runtime_id='run').state.value == 'blocked'
    assert readiness.check_localization(valid=True, age_seconds=0.1,
                                        max_age=0.5,
                                        runtime_id='run').state.value == 'ready'
    assert readiness.check_localization(valid=False, age_seconds=None,
                                        max_age=0.5,
                                        runtime_id='run').state.value == 'blocked'


def test_latched_map_persists_for_runtime_and_invalidates_independently():
    map_state = readiness.LatchedMapObservation('run-1')
    assert not map_state.available_for('run-1')
    map_state.observe(valid=True, runtime_id='run-1')
    assert map_state.available_for('run-1')
    # No time/freshness lease applies to this transient-local artifact.
    assert map_state.available_for('run-1')
    assert not map_state.available_for('run-2')

    map_state.observe(valid=False, runtime_id='run-1')
    assert not map_state.available_for('run-1')
    map_state.observe(valid=True, runtime_id='run-1')
    assert map_state.available_for('run-1')

    stale_pose = readiness.check_localization(
        valid=False, age_seconds=2.0, max_age=1.0, runtime_id='run-1'
    )
    assert stale_pose.state.value == 'blocked'
    assert readiness.check_map('/maps/site.yaml', available=True,
                               runtime_id='run-1').state.value == 'ready'


def test_aggregate_retains_all_simultaneous_failures_and_is_actionable():
    first = readiness.check_endpoint('/controller_manager/list_controllers',
                                     'service', available=False,
                                     runtime_id='run')
    second = readiness.check_map('/maps/missing.yaml', available=False,
                                 runtime_id='run')
    report = readiness.aggregate(
        [first, second], profile=readiness.ReadinessProfile.SIMULATION_READY,
        runtime_id='run',
    ).to_mapping()
    assert report['ready'] is False
    assert first.name in report['blocked_dependencies']
    assert second.name in report['blocked_dependencies']
    assert set(readiness.PROFILE_REQUIREMENTS[
        readiness.ReadinessProfile.SIMULATION_READY
    ]).issubset(report['blocked_dependencies'])
    assert len(report['checks']) > 2
    assert all(check['guidance'] for check in report['checks'])


def test_aggregate_rejects_duplicate_dependency_names():
    result = readiness.check_endpoint('/x', 'service', available=True,
                                      responsive=True, runtime_id='run')
    try:
        readiness.aggregate([result, result],
                            profile=readiness.ReadinessProfile.SIMULATION_READY,
                            runtime_id='run')
    except ValueError as error:
        assert 'unique' in str(error)
    else:
        raise AssertionError('duplicate names were accepted')


def test_every_profile_dependency_is_required():
    for profile, required in readiness.PROFILE_REQUIREMENTS.items():
        for omitted in required:
            runtime_id = f'{profile.value}-{omitted}'
            supplied = [readiness._result(
                name, 'fixture', True, runtime_id=runtime_id
            ) for name in required if name != omitted]
            report = readiness.aggregate(supplied, profile=profile,
                                         runtime_id=runtime_id)
            assert not report.ready
            assert omitted in report.to_mapping()['blocked_dependencies']


def test_profile_blocking_selection_matches_declared_dependencies():
    for profile, required in readiness.PROFILE_REQUIREMENTS.items():
        runtime_id = profile.value
        observations = [readiness._result(name, 'fixture', True,
                                          runtime_id=runtime_id)
                        for name in required]
        observations.append(readiness._result('/diagnostic_only', 'topic', False,
                                              runtime_id=runtime_id))
        blocking = readiness.select_profile_checks(profile, observations)
        assert {item.name for item in blocking} == set(required)
        if '/joint_states' not in required:
            assert '/joint_states' not in {item.name for item in blocking}
        assert '/diagnostic_only' not in {item.name for item in blocking}
        assert readiness.aggregate(blocking, profile=profile,
                                   runtime_id=runtime_id).ready

    docs = (Path(__file__).resolve().parents[4]
            / 'docs' / 'readiness_contracts.md').read_text()
    for profile, required in readiness.PROFILE_REQUIREMENTS.items():
        row = next(line for line in docs.splitlines()
                   if f'`{profile.value}`' in line)
        assert all(f'`{name}`' in row for name in required)


def test_evidence_is_bound_to_runtime_identity_and_lease():
    profile = readiness.ReadinessProfile.SIMULATION_READY
    old_id = 'simulation-generation-1'
    checks = [readiness._result(name, 'fixture', True, runtime_id=old_id)
              for name in readiness.PROFILE_REQUIREMENTS[profile]]
    old = readiness.aggregate(checks, profile=profile, runtime_id=old_id)
    assert old.ready

    after_restart = readiness.aggregate(checks, profile=profile,
                                        runtime_id='simulation-generation-2')
    assert not after_restart.ready
    assert all(item.state.value == 'blocked' for item in after_restart.checks)
    assert not old.current_for(old_id, old.observed_monotonic + 3.0)


def test_readiness_wait_times_out_when_process_lives_but_dependency_is_missing():
    runtime_id = 'live-but-not-ready'
    blocked = readiness.aggregate(
        [], profile=readiness.ReadinessProfile.SIMULATION_READY,
        runtime_id=runtime_id,
    )
    now = [0.0]

    def sleep(duration):
        now[0] += duration

    report = readiness.wait_for_readiness(
        lambda: blocked, timeout=0.2, poll_interval=0.1,
        process_alive=lambda: True,
        monotonic=lambda: now[0], sleep=sleep,
    )
    assert not report.ready
    assert 'readiness_deadline' in report.to_mapping()['blocked_dependencies']
    assert '/clock' in report.to_mapping()['blocked_dependencies']
