# v0.1.3 readiness contracts

Readiness is a dependency observation, separate from the manager lifecycle.
Lifecycle reports whether a manager is operationally managed; readiness reports
whether the dependencies for a particular operation currently satisfy their
conditions. A readiness failure does not change `ManagedLifecycleState`.

## Public report

Simulation and mode managers publish a transient-local JSON `std_msgs/msg/String`
on `/platform/readiness`. The JSON object contains:

```json
{
  "ready": false,
  "state": "blocked",
  "profile": "simulation_ready",
  "runtime_id": "unique id for this probe session",
  "observed_monotonic": 12345.67,
  "lease_seconds": 2.0,
  "blocked_dependencies": ["/clock"],
  "checks": [
    {
      "name": "/clock",
      "kind": "clock",
      "state": "blocked",
      "ready": false,
      "reason": "clock_stopped",
      "guidance": "Enable simulated time and verify the Gazebo clock bridge.",
      "runtime_id": "unique id for this probe session",
      "observed_monotonic": 12345.67,
      "lease_seconds": 2.0,
      "observed": {"sample_count": 2, "advance_seconds": 0.0}
    }
  ]
}
```

Consumers must require the expected `profile`, reject a different `runtime_id`,
and consider evidence expired when its monotonic lease has elapsed. The runtime
ID identifies one readiness-probe evidence session; it is not a simulation
generation or map-publisher generation. Each new probe starts its own map
observation empty, but can immediately receive the current retained map from a
still-live transient-local publisher. All failed dependencies are reported
together, with a reason and recovery guidance. Monotonic values are local
elapsed-time evidence; they must not be interpreted as wall-clock dates.

## Declared profiles

The dependency sets below bind the v0.1.3 checks to this repository's existing
simulation and autonomy interfaces. The tracker defines the dependency check
categories; the names below come from the accepted launch/configuration
contracts. These profiles are contracts for later mode-admission consumers;
v0.1.3 uses them to gate successful simulation/mode startup reports.

| Profile | Required report children |
| --- | --- |
| `simulation_ready` | `/clock`, `/scan`, `/diff_drive_controller/odom`, `/joint_states`, `odom <- base_link`, `/controller_manager/list_controllers`, `controllers` |
| `mapping_ready` | `/clock`, `/scan`, `/diff_drive_controller/odom`, `odom <- base_link` |
| `localization_ready` | `/clock`, `/scan`, `/map`, `/amcl_pose`, `map <- odom`, `odom <- base_link` |
| `navigation_ready` | `/clock`, `/scan`, `/diff_drive_controller/odom`, `/map`, `/amcl_pose`, `map <- odom`, `odom <- base_link`, `/navigate_to_pose`, `/controller_manager/list_controllers`, `controllers` |

An omitted required child is added as a blocked result. The caller cannot make
an incomplete report ready by supplying only the checks it happened to collect.
Navigation action readiness requires `/navigate_to_pose` discovery and an
`active` state from `/bt_navigator/get_state`; the checker does not send an
operational navigation goal as a readiness probe. Service readiness requires
explicit response evidence.

## Check rules

- `/clock`: simulated time must be enabled; a fresh contiguous ROS-time
  advancing run must independently span the required monotonic interval and
  ROS-time advance. A no-progress interval equal to or longer than that required receive
  span resets the run, so stopped samples cannot lend their duration to a
  recovery tick. A run starts at the first positive advance and requires a
  later positive advance at least the receive-span threshold later. Short
  duplicate ticks are tolerated. The READY check's
  observation time is the newest advancing source sample, and its one-second
  lease matches the source freshness bound.
- Topics: receive samples must be recent and meet the configured minimum rate.
  Runtime defaults are 1 Hz for `/scan` and 5 Hz for odometry/joint states,
  with one-second freshness bounds and a five-second rate window.
- TF: lookup must resolve within its timeout and its transform timestamp must
  be nonnegative and within the freshness bound.
- Services: discovery and a responsive result are separate conditions. Unknown
  response state and timeouts are blocked. Navigation requires its action server
  and active navigator lifecycle state without sending an operational goal.
- Controllers: the controller-manager list response must identify every
  required controller as `active`.
- Map/localization: `/map` is a validated transient-local artifact. Once a valid
  map is received, it remains available to that probe instance. A probe created
  after its publisher has disappeared receives no old sample; a new publisher
  must publish its map before that probe becomes ready. If a publisher disappears
  after the probe received a valid map, the probe retains that artifact and does
  not independently monitor source liveness. An invalid replacement clears
  availability. This does not renew localization freshness: `/amcl_pose` and
  `map <- odom` remain independently time-bounded. REQ-028 requires map
  availability and valid localization evidence; it does not define publisher
  liveness or application-level map-generation identity.

The common implementation lives in `scripts/readiness_contract.py`; ROS
observations live in `scripts/ros_runtime_readiness.py`. `ReadinessReport`
and `CheckResult` are immutable structured values that also serialize to JSON.
Simulation/mode manager status and lifecycle interfaces remain separate.

## Lifecycle state authority

Transient-local lifecycle topics retain the last snapshot after a manager
exits, so they are not authoritative by themselves. Managers also publish a
one-second heartbeat. The orchestrator applies a three-second monotonic lease,
checks activation provenance, and calls
`/lifecycle/<component>/state_snapshot` before making target-satisfaction and
final-success decisions. The read-only `GetManagedComponentState` service
returns current lifecycle state, last transition name/ID, and UTC observation
time. Platform success requires two complete authoritative reads in dependency
order. Every required component must satisfy the requested target on both reads,
and its state and last transition name/ID must be unchanged between them. This
state/version vector provides a stable interval for the aggregate success
decision; a failed read, changed version, missing manager, or invalid ACTIVE
provenance fails closed without changing lifecycle/readiness semantics.
