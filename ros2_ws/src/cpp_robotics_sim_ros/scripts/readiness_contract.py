#!/usr/bin/env python3
# Copyright 2026 Devansh Mishra
#
# Use of this source code is governed by an MIT-style
# license that can be found in the LICENSE file or at
# https://opensource.org/licenses/MIT.

"""
Dependency-based readiness contracts, independent of lifecycle state.

Adapters collect observations from ROS and pass them to these evaluators. The
pure evaluation layer makes reports deterministic and straightforward to test.
"""

from dataclasses import dataclass
from enum import Enum
import math
import time
from typing import Any, Mapping, Sequence


class ReadinessState(str, Enum):
    READY = 'ready'
    BLOCKED = 'blocked'


class ReadinessProfile(str, Enum):
    """Declared readiness dependency sets used by runtime consumers."""

    SIMULATION_READY = 'simulation_ready'
    MAPPING_READY = 'mapping_ready'
    LOCALIZATION_READY = 'localization_ready'
    NAVIGATION_READY = 'navigation_ready'


PROFILE_REQUIREMENTS = {
    ReadinessProfile.SIMULATION_READY: frozenset({
        '/clock', '/scan', '/diff_drive_controller/odom', '/joint_states',
        'odom <- base_link', '/controller_manager/list_controllers', 'controllers',
    }),
    ReadinessProfile.MAPPING_READY: frozenset({
        '/clock', '/scan', '/diff_drive_controller/odom',
        'odom <- base_link',
    }),
    ReadinessProfile.LOCALIZATION_READY: frozenset({
        '/clock', '/scan', '/map', '/amcl_pose', 'map <- odom',
        'odom <- base_link',
    }),
    ReadinessProfile.NAVIGATION_READY: frozenset({
        '/clock', '/scan', '/diff_drive_controller/odom', '/map', '/amcl_pose',
        'map <- odom', 'odom <- base_link', '/navigate_to_pose',
        '/controller_manager/list_controllers', 'controllers',
    }),
}


def select_profile_checks(profile: ReadinessProfile,
                          observations: Sequence['CheckResult']) -> tuple['CheckResult', ...]:
    """Return exactly the declared blocking observations for this profile."""
    required = PROFILE_REQUIREMENTS[profile]
    return tuple(item for item in observations if item.name in required)


class LatchedMapObservation:
    """Validity of a transient-local map artifact within one probe session."""

    def __init__(self, runtime_id: str):
        self.runtime_id = runtime_id
        self._valid = False

    def observe(self, *, valid: bool, runtime_id: str) -> None:
        if runtime_id != self.runtime_id:
            return
        self._valid = bool(valid)

    def available_for(self, runtime_id: str) -> bool:
        return runtime_id == self.runtime_id and self._valid


@dataclass(frozen=True)
class CheckResult:
    """Machine-readable result for one named dependency condition."""

    name: str
    kind: str
    state: ReadinessState
    reason: str = ''
    guidance: str = ''
    observed: Mapping[str, Any] | None = None
    runtime_id: str = ''
    observed_monotonic: float = 0.0
    lease_seconds: float = 2.0

    def current_for(self, runtime_id: str, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else now
        return (bool(self.runtime_id) and self.runtime_id == runtime_id
                and self.observed_monotonic <= current
                and current - self.observed_monotonic <= self.lease_seconds)

    def to_mapping(self) -> dict[str, Any]:
        return {
            'name': self.name,
            'kind': self.kind,
            'state': self.state.value,
            'ready': self.state == ReadinessState.READY,
            'reason': self.reason,
            'guidance': self.guidance,
            'observed': dict(self.observed or {}),
            'runtime_id': self.runtime_id,
            'observed_monotonic': self.observed_monotonic,
            'lease_seconds': self.lease_seconds,
        }


@dataclass(frozen=True)
class ReadinessReport:
    """Aggregate that retains every dependency result, including failures."""

    checks: tuple[CheckResult, ...]
    profile: ReadinessProfile
    runtime_id: str
    observed_monotonic: float
    lease_seconds: float = 2.0

    @property
    def ready(self) -> bool:
        now = time.monotonic()
        return (bool(self.checks)
                and PROFILE_REQUIREMENTS[self.profile].issubset(
                    {item.name for item in self.checks}
                )
                and now - self.observed_monotonic <= self.lease_seconds
                and all(item.current_for(self.runtime_id, now) for item in self.checks)
                and all(
            item.state == ReadinessState.READY for item in self.checks
                ))

    def current_for(self, runtime_id: str, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else now
        return (runtime_id == self.runtime_id
                and self.observed_monotonic <= current
                and current - self.observed_monotonic <= self.lease_seconds
                and all(item.current_for(runtime_id, current) for item in self.checks))

    @property
    def blocked(self) -> tuple[CheckResult, ...]:
        return tuple(item for item in self.checks
                     if (item.state == ReadinessState.BLOCKED
                         or not item.current_for(self.runtime_id)))

    @property
    def missing_dependencies(self) -> tuple[str, ...]:
        present = {item.name for item in self.checks}
        return tuple(sorted(PROFILE_REQUIREMENTS[self.profile] - present))

    def to_mapping(self) -> dict[str, Any]:
        return {
            'ready': self.ready,
            'state': 'ready' if self.ready else 'blocked',
            'checks': [item.to_mapping() for item in self.checks],
            'blocked_dependencies': sorted(
                {item.name for item in self.blocked}
                | set(self.missing_dependencies)
            ),
            'profile': self.profile.value,
            'runtime_id': self.runtime_id,
            'observed_monotonic': self.observed_monotonic,
            'lease_seconds': self.lease_seconds,
        }


def _result(name: str, kind: str, ready: bool, *, runtime_id: str,
            reason: str = '', guidance: str = '',
            observed: Mapping[str, Any] | None = None,
            observed_monotonic: float | None = None, lease_seconds: float = 2.0):
    return CheckResult(name, kind,
                       ReadinessState.READY if ready else ReadinessState.BLOCKED,
                       reason, guidance, observed, runtime_id,
                       time.monotonic() if observed_monotonic is None else observed_monotonic,
                       lease_seconds)


def check_clock(samples: Sequence[tuple[float, float]], *, use_sim_time: bool,
                min_advance: float = 0.001, now: float | None = None,
                max_age: float = 1.0, min_receive_span: float = 0.05,
                runtime_id: str) -> CheckResult:
    """Check ROS /clock samples as (ROS seconds, monotonic receive seconds)."""
    current = time.monotonic() if now is None else now

    def reaches(value: float, threshold: float) -> bool:
        """Compare clock boundaries inclusively despite float roundoff."""
        return (value >= threshold
                or math.isclose(value, threshold, rel_tol=1e-12, abs_tol=1e-12))

    original_count = len(samples)
    samples = tuple((t, received) for t, received in samples
                    if math.isfinite(t) and math.isfinite(received)
                    and 0.0 <= current - received <= max_age)
    # Build a fresh run from ROS-time advances. Duplicate ticks are tolerated,
    # but cannot extend a stopped interval indefinitely: if no ROS progress
    # occurs for the required observation span, the next advance starts a new
    # run and the stopped receive-time span is discarded.
    run_start = None
    last_progress = None
    latest_progress = None
    for previous, sample in zip(samples, samples[1:]):
        ros_delta = sample[0] - previous[0]
        receive_delta = sample[1] - previous[1]
        if ros_delta < 0.0 or receive_delta <= 0.0:
            run_start = None
            last_progress = None
            latest_progress = None
            continue
        if (ros_delta == 0.0 and last_progress is not None
                and reaches(sample[1] - last_progress, min_receive_span)):
            run_start = None
            last_progress = None
            latest_progress = None
        if ros_delta > 0.0:
            if run_start is None:
                # Start at the first advancing observation, never at the
                # preceding sample whose receive gap may include a pause.
                run_start = sample
            last_progress = sample[1]
            latest_progress = sample

    advance = (latest_progress[0] - run_start[0]
               if run_start is not None and latest_progress is not None else 0.0)
    receive_span = (latest_progress[1] - run_start[1]
                    if run_start is not None and latest_progress is not None else 0.0)
    any_ros_advance = (len(samples) >= 2
                       and any(right[0] > left[0]
                               for left, right in zip(samples, samples[1:])))
    advancing = (use_sim_time and latest_progress is not None
                 and reaches(advance, min_advance)
                 and reaches(receive_span, min_receive_span))
    reason = '' if advancing else (
        'use_sim_time is false' if not use_sim_time else
        'clock_samples_stale' if original_count < 2 or len(samples) < 2 else
        'clock_samples_batched' if any_ros_advance and receive_span < min_receive_span else
        'clock_stopped' if latest_progress is None or advance < min_advance else
        'clock_stopped'
    )
    source_observed = (latest_progress[1] if latest_progress is not None else
                       samples[-1][1] if samples else current)
    return _result('/clock', 'clock', advancing, runtime_id=runtime_id, reason=reason,
                   guidance='Enable simulated time and verify the Gazebo clock bridge.',
                   observed={'sample_count': len(samples), 'advance_seconds': advance,
                             'receive_span_seconds': receive_span},
                   observed_monotonic=source_observed, lease_seconds=max_age)


def check_topic(name: str, receive_times: Sequence[float], *, now: float,
                min_rate_hz: float, max_age: float,
                runtime_id: str, window: float = 5.0) -> CheckResult:
    """Check that a topic has recent samples at its configured minimum rate."""
    recent = [t for t in receive_times if math.isfinite(t) and now - window <= t <= now]
    age = now - max(recent) if recent else math.inf
    rate = max(0, len(recent) - 1) / window
    ready = bool(recent) and age <= max_age and rate >= min_rate_hz
    reason = '' if ready else ('no recent messages' if not recent else
                               'message freshness threshold exceeded' if age > max_age else
                               'message rate below configured minimum')
    return _result(name, 'topic', ready, runtime_id=runtime_id, reason=reason,
                   guidance='Verify the publisher, bridge, and configured topic rate.',
                   observed={'sample_count': len(recent), 'age_seconds': age,
                             'rate_hz': rate, 'minimum_rate_hz': min_rate_hz},
                   observed_monotonic=now)


def check_tf(target_frame: str, source_frame: str, *, available: bool,
             age_seconds: float | None, max_age: float,
             lookup_seconds: float, timeout: float, runtime_id: str) -> CheckResult:
    ready = (available and age_seconds is not None and math.isfinite(age_seconds)
             and 0.0 <= age_seconds <= max_age
             and math.isfinite(lookup_seconds)
             and 0.0 <= lookup_seconds <= timeout)
    reason = '' if ready else (
        'transform lookup failed' if not available else
        'transform timestamp is missing or invalid'
        if age_seconds is None or not math.isfinite(age_seconds) else
        'transform is stale' if age_seconds < 0.0 or age_seconds > max_age else
        'transform lookup exceeded timeout'
    )
    name = f'{target_frame} <- {source_frame}'
    return _result(name, 'tf', ready, runtime_id=runtime_id, reason=reason,
                   guidance='Verify the expected TF publisher, frame IDs, and simulation time.',
                   observed={'age_seconds': age_seconds, 'lookup_seconds': lookup_seconds,
                             'timeout_seconds': timeout})


def check_endpoint(name: str, kind: str, *, available: bool,
                   responsive: bool | None = None,
                   require_responsive: bool = True,
                   runtime_id: str) -> CheckResult:
    ready = available and (not require_responsive or responsive is True)
    reason = '' if ready else ('endpoint is not discoverable' if not available else
                               'endpoint responsiveness is unknown' if responsive is None else
                               'endpoint did not respond before timeout')
    return _result(name, kind, ready, runtime_id=runtime_id, reason=reason,
                   guidance=f'Verify that {name} is running and responsive.',
                   observed={'available': available, 'responsive': responsive})


def check_navigation_action_server(*, available: bool,
                                   lifecycle_state: str | None,
                                   runtime_id: str) -> CheckResult:
    """Require a discoverable NavigateToPose server whose navigator is active."""
    active = lifecycle_state == 'active'
    ready = available and active
    reason = '' if ready else (
        'action server is not discoverable' if not available else
        'bt_navigator lifecycle state is unavailable'
        if lifecycle_state is None else
        f'bt_navigator is not active (state={lifecycle_state})'
    )
    return _result(
        '/navigate_to_pose', 'action', ready, runtime_id=runtime_id,
        reason=reason,
        guidance=('Verify the NavigateToPose server and active bt_navigator '
                  'lifecycle state.'),
        observed={
            'available': available,
            'bt_navigator_state': lifecycle_state,
        },
    )


def check_controllers(active: Sequence[str], required: Sequence[str], *,
                      response_received: bool = True, runtime_id: str) -> CheckResult:
    missing = sorted(set(required) - set(active))
    ready = response_received and not missing
    reason = '' if ready else ('controller state is unavailable' if not response_received else
                               'required controllers are not active: ' + ', '.join(missing))
    return _result(
        'controllers', 'controllers', ready, runtime_id=runtime_id,
        reason=reason,
        guidance=('Load and activate required controllers, then inspect their '
                  'state.'),
        observed={'required': list(required), 'active': list(active),
                  'missing': missing},
    )


def check_map(path: str, *, available: bool, runtime_id: str) -> CheckResult:
    return _result('/map', 'map', available, runtime_id=runtime_id,
                   reason='' if available else 'configured map is unavailable',
                   guidance='Select an existing readable map YAML and image.',
                   observed={'path': path})


def check_localization(*, valid: bool, age_seconds: float | None,
                       max_age: float, runtime_id: str) -> CheckResult:
    ready = (valid and age_seconds is not None and math.isfinite(age_seconds)
             and 0.0 <= age_seconds <= max_age)
    reason = '' if ready else ('localization estimate is invalid' if not valid else
                               'localization estimate is missing or invalid'
                               if age_seconds is None or not math.isfinite(age_seconds) else
                               'localization estimate is stale')
    return _result('/amcl_pose', 'localization', ready, runtime_id=runtime_id,
                   reason=reason,
                   guidance=('Verify map server, localization pose publication, '
                             'and map-to-odom TF.'),
                   observed={'age_seconds': age_seconds})


def aggregate(checks: Sequence[CheckResult], *, profile: ReadinessProfile,
              runtime_id: str, now: float | None = None) -> ReadinessReport:
    """Build a report without short-circuiting or suppressing failed checks."""
    names = [item.name for item in checks]
    if len(names) != len(set(names)):
        raise ValueError('readiness check names must be unique')
    current = time.monotonic() if now is None else now
    by_name = {item.name: item for item in checks}
    required = PROFILE_REQUIREMENTS[profile]
    complete = list(checks)
    for missing in sorted(required - set(by_name)):
        complete.append(_result(
            missing, 'dependency', False, runtime_id=runtime_id,
            reason='required readiness dependency was not evaluated',
            guidance='Collect and include evidence for this profile dependency.',
            observed_monotonic=current,
        ))
    for index, item in enumerate(complete):
        if not item.current_for(runtime_id, current):
            complete[index] = _result(
                item.name, item.kind, False, runtime_id=runtime_id,
                reason='readiness evidence is stale or belongs to another runtime',
                guidance='Re-probe dependencies for the current runtime session.',
                observed_monotonic=current,
            )
    return ReadinessReport(tuple(complete), profile, runtime_id, current)


def wait_for_readiness(probe, *, timeout: float, process_alive,
                       poll_interval: float = 0.1, monotonic=None,
                       sleep=None) -> ReadinessReport:
    """Poll evidence until ready, process exit, or a bounded deadline."""
    import time

    now = monotonic or time.monotonic
    pause = sleep or time.sleep
    if not math.isfinite(timeout) or timeout <= 0.0:
        raise ValueError('readiness timeout must be finite and positive')
    if not math.isfinite(poll_interval) or poll_interval <= 0.0:
        raise ValueError('readiness poll interval must be finite and positive')
    deadline = now() + timeout
    report = probe()
    while not report.ready and process_alive() and now() < deadline:
        pause(min(poll_interval, max(0.0, deadline - now())))
        report = probe()
    if report.ready and not process_alive():
        extra = _result(
            'simulation_process', 'process', False, runtime_id=report.runtime_id,
            reason='simulation launch process exited as readiness completed',
            guidance='Inspect launch output and restart the simulation.',
        )
        return aggregate((*report.checks, extra), profile=report.profile,
                         runtime_id=report.runtime_id)
    if not report.ready and not process_alive():
        extra = _result(
            'simulation_process', 'process', False, runtime_id=report.runtime_id,
            reason='simulation launch process exited before runtime readiness',
            guidance='Inspect launch output and resolve the reported startup failure.',
        )
        return aggregate((*report.checks, extra), profile=report.profile,
                         runtime_id=report.runtime_id)
    if not report.ready and now() >= deadline:
        extra = _result(
            'readiness_deadline', 'deadline', False, runtime_id=report.runtime_id,
            reason=f'no complete readiness evidence within {timeout:.3f} seconds',
            guidance='Resolve blocked dependencies in the report and retry startup.',
        )
        return aggregate((*report.checks, extra), profile=report.profile,
                         runtime_id=report.runtime_id)
    return report
