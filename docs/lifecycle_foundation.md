# v0.1.2 lifecycle foundation

This foundation defines the lifecycle of a **manager component**. It does not
replace simulation `running/stopped`, robot operating modes, map save status,
or navigation goal status. Existing domain topics and services remain intact.
The orchestrator is started after the four manager nodes in
`web_interface.launch.py`; operating modes remain owned by `mode_manager`.

## Component contract

| Operation | Source | Destination after verified success |
|---|---|---|
| configure | UNCONFIGURED | INACTIVE |
| activate | INACTIVE | ACTIVE |
| deactivate | ACTIVE | INACTIVE |
| cleanup | INACTIVE | UNCONFIGURED |
| shutdown | UNCONFIGURED, INACTIVE, ACTIVE, ERROR | FINALIZED |
| error | UNCONFIGURED, INACTIVE, ACTIVE | ERROR |
| recover | ERROR | UNCONFIGURED |

Only `ManagedComponent.transition()` changes lifecycle state. An `on_activate`
hook must finish successfully before ACTIVE is assigned. `on_recover` must
return `True` only after cleanup has been verified. An illegal transition
returns `ILLEGAL_TRANSITION` without calling a hook or changing state.
FINALIZED has no outgoing transitions. A second attempt while a transition
holds the lock returns `BUSY` immediately.

`TransitionResult` is immutable and includes a UUID, component and operation,
source and destination states, code, reason, failed dependency, UTC start and
completion timestamps, recovery guidance, attempt count, and rollback fields.
Hook exceptions become structured failures with the exception type and message
preserved in `reason`.

Automatic retries default to zero. A caller may explicitly mark one of
configure, activate, deactivate, or cleanup as retry-safe and request at most
three retries. Before another attempt, `on_rollback(operation, source_state)`
must verify restoration to the source state by returning `True`. A failed
rollback returns `ROLLBACK_FAILED` and enters ERROR. An exhausted retry returns
`RETRY_EXHAUSTED` and enters ERROR. Any unhandled hook failure enters ERROR;
recovery requires an explicit verified recover transition. This policy does
not alter the v0.1.1 OS process registry or process recovery.

## Platform order

`platform_lifecycle_orchestrator.py` defines the dependency order once:
simulation, mapping, localization, navigation. Configure and activate run in
that order. Deactivate, cleanup, and shutdown run in reverse order. A failed
component stops downstream transitions; completed components from that same
request are rolled back in reverse completion order. The original failure and
rollback failures are separate result fields. Shutdown is irreversible:
completed shutdowns are reported as `rollback_unavailable` after a later
failure. The orchestrator does not select or launch robot operating modes;
`mode_manager` remains their owner.

When every component already has the requested target state, an identical
request returns `ALREADY_APPLIED` without invoking hooks. A partial request
continues in dependency order, skipping components already at target; invalid
edges are rejected by their components. Requests received before all component
state snapshots exist return `STATE_UNAVAILABLE` without invoking any manager.
Concurrent platform requests return `BUSY` immediately.

## Additive ROS contract

Each manager adapter publishes a transient-local
`ManagedLifecycleState` on `/lifecycle/<component>/state` and offers
`TransitionManagedComponent` on `/lifecycle/<component>/transition`.
Component transition events and aggregate orchestration events are published
on `/platform/lifecycle/transition_events`. Manager service requests carry an
`orchestration_id`; the manager event repeats it, allowing the orchestrator to
correlate each result with its aggregate request. The orchestrator offers the
same service type at
`/platform/lifecycle/transition` and publishes typed
`LifecycleTransitionEvent` messages. Service responses include the
original component failure, all component results, rollback results, and
rollback failures. Component state topics must report ACTIVE only with the
ID of a successful activate transition.

The manager adapters compose `ManagedComponent`; lifecycle ACTIVE indicates
permission to accept manager operations, not simulation RUNNING, a map-save
state, AMCL state, or an active navigation goal. Simulation deactivation uses
the v0.1.1 owned-process cleanup. Mapping deactivation closes request
admission and waits for an in-flight save worker. Localization cleanup clears
the manager's selected-map runtime reference but does not delete map files.
Navigation deactivation requests Nav2 cancellation and waits for a terminal
goal result; a refused cancellation or timeout is a lifecycle failure.

The focused runtime driver is `scripts/v012_lifecycle_acceptance.py`. It
stores timestamped evidence under
`~/.ros/cpp_robotics_sim/evidence/v0.1.2/` and emits a fail-closed
`release_decision.txt` plus machine-readable snapshots, events, rollback, and
registry results. Its domain workflow checks require the normal Gazebo, SLAM,
AMCL, and Nav2 runtime dependencies to be available.
