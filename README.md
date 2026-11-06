# ROS 2 AMR Platform

[![ROS 2 Jazzy CI](https://github.com/Devansh-Mishra-30/ros2-amr-platform/actions/workflows/ros2_jazzy_ci.yml/badge.svg)](https://github.com/Devansh-Mishra-30/ros2-amr-platform/actions/workflows/ros2_jazzy_ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A browser-controlled autonomous mobile robot (AMR) simulation and verification
platform built with ROS 2 Jazzy, Gazebo Harmonic, ros2_control, SLAM Toolbox,
AMCL, Nav2, and rosbridge.

The repository is preparing the **v0.1.3 release candidate**. No v0.1.3 tag
exists yet. The last published tag is v0.1.2; the candidate adds fail-closed
readiness contracts and authoritative lifecycle-state verification while
preserving the established simulation, mapping, localization, navigation, and
dashboard interfaces.

## Implemented capabilities

- Browser dashboard served with rosbridge connectivity.
- Warehouse and hospital Gazebo environments.
- Differential-drive robot with LiDAR, odometry, joint states, and simulated
  clock.
- Manual velocity control with command arbitration and emergency stop.
- SLAM mapping and validated map saving.
- AMCL localization with map selection and initial-pose workflows.
- Nav2 single-goal navigation, feedback, cancellation, and safe terminal stop.
- Managed simulation and operating-mode process lifecycles.
- Component lifecycle orchestration with dependency-ordered transitions,
  structured failures, rollback evidence, and explicit recovery.
- Fail-closed runtime readiness profiles for simulation, mapping, localization,
  and navigation.
- Automated syntax, unit, integration, launch, lifecycle, and runtime
  acceptance checks.

This is a simulation and engineering-verification platform. It is not a
certified safety system or a production-hardware deployment.

## Architecture

```text
Browser dashboard
    |
    +-- HTTP server :8080
    +-- rosbridge WebSocket :9090
             |
             v
simulation_manager ---- environment selection / Gazebo / ros2_control
mode_manager ---------- manual / mapping / localization / navigation
mapping_manager ------- map-save workflow and saved-map inventory
localization_manager -- map selection and initial pose
navigation_manager --- Nav2 goal, feedback, cancel, and terminal state
             |
             +-- command multiplexer --> diff_drive_controller
             +-- lifecycle adapters --> platform_lifecycle_orchestrator
             +-- readiness probes --> /platform/readiness
```

The dashboard publishes requests and presents ROS 2 state; it does not
implement the robotics algorithms. Operating modes remain mutually exclusive.
Velocity sources pass through the command multiplexer before reaching the
drive controller. Mapping and localization/navigation retain distinct TF
ownership:

- Mapping: SLAM Toolbox owns `map -> odom`.
- Localization/navigation: AMCL owns `map -> odom`.
- ros2_control owns `odom -> base_link`.
- robot_state_publisher owns the robot link and sensor transforms.

See [system architecture](docs/system_architecture.md) for the original v0.1.0
baseline, [lifecycle foundation](docs/lifecycle_foundation.md) for v0.1.2, and
[readiness contracts](docs/readiness_contracts.md) for v0.1.3.

## Technology stack

| Area | Technology |
| --- | --- |
| Platform | Ubuntu 24.04, ROS 2 Jazzy |
| Simulation | Gazebo Harmonic, `ros_gz_sim`, `ros_gz_bridge` |
| Robot control | ros2_control, `gz_ros2_control`, differential-drive controller |
| Autonomy | SLAM Toolbox, AMCL, Nav2 |
| Application | C++17, Python 3, Bash |
| Browser interface | HTML, CSS, JavaScript, rosbridge |
| Build and test | ament_cmake, colcon, pytest, GoogleTest |
| Automation | Docker, GitHub Actions on Ubuntu 24.04 |

## Repository layout

```text
ros2-amr-platform/
├── .github/
│   ├── ISSUE_TEMPLATE/
│   ├── PULL_REQUEST_TEMPLATE.md
│   └── workflows/ros2_jazzy_ci.yml
├── docs/
│   ├── evidence/v0.1.3/
│   ├── lifecycle_foundation.md
│   ├── readiness_contracts.md
│   ├── topic_interface_reference.md
│   └── AMR_Release_Verification_Tracker.xlsx
├── ros2_ws/src/cpp_robotics_sim_ros/
│   ├── config/      # managers, controllers, environments, and Nav2
│   ├── include/     # public C++ headers
│   ├── launch/      # simulation and dashboard launch descriptions
│   ├── maps/        # repository map assets
│   ├── msg/         # lifecycle messages
│   ├── nav2/        # Nav2 parameter sets
│   ├── scripts/     # installed Python manager and contract nodes
│   ├── src/         # C++ robot and simulation implementation
│   ├── srv/         # lifecycle services
│   ├── test/        # C++, Python, launch, and contract tests
│   ├── urdf/ and xacro/
│   ├── web/dashboard/
│   └── worlds/
└── scripts/         # setup, build, run, cleanup, and validation entry points
```

Generated `build/`, `install/`, and `log/` directories are workspace
artifacts and are not source.

## Supported environment and prerequisites

The verified primary environment is:

- Ubuntu 24.04 LTS, including WSL2;
- ROS 2 Jazzy;
- Gazebo Harmonic;
- an OpenGL-capable desktop for interactive Gazebo;
- Bash, Python 3, CMake, colcon, and a C++17 compiler.

The setup helper installs the repository's supported Ubuntu/ROS dependencies:

```bash
./scripts/setup.sh
```

Review the script before running it on an existing development machine. The
long-form [installation guide](docs/installation.md) records the v0.1.0
baseline and should be read as historical release documentation where it names
that version.

## Clone and build

```bash
git clone https://github.com/Devansh-Mishra-30/ros2-amr-platform.git
cd ros2-amr-platform
./scripts/build.sh
```

`build.sh` validates source syntax, sources ROS 2, and builds
`cpp_robotics_sim_ros` with tests enabled.

To source the built workspace manually:

```bash
source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash
```

## Run

```bash
./scripts/run.sh
```

The launcher starts the dashboard HTTP server, rosbridge, manager layer, and
supporting ROS 2 nodes. By default it prints and opens the dashboard URL, uses
port 8080 for HTTP and 9090 for rosbridge, and performs verified owned-process
cleanup when stopped with Ctrl+C.

Useful overrides:

```bash
OPEN_BROWSER=false ./scripts/run.sh
DASHBOARD_PORT=8081 ROSBRIDGE_PORT=9091 ./scripts/run.sh
```

## Operator workflows

### Simulation

1. Open the dashboard and confirm the rosbridge connection.
2. Select the warehouse or hospital environment.
3. Start the simulation.
4. Wait for the manager to report the simulation running and the
   `simulation_ready` profile ready.
5. Stop or reset through the dashboard; do not treat a button click alone as
   proof of completion.

### Manual control

Activate Manual mode, then use the dashboard controls to publish
`TwistStamped` commands on `/cmd_vel/gui`. The command multiplexer owns the
controller input selection. Stop the mode or use emergency stop before leaving
manual operation.

### Mapping

Start Mapping mode only after simulation readiness succeeds. Drive the robot to
cover the environment, enter a valid map name, save the map, and confirm the
reported result and saved-map inventory. Map names and filesystem paths are
validated.

### Localization

Select a saved map, start Localization mode, and provide an initial pose. A
successful mode request is not reported until clock, scan, map, AMCL pose, and
the required TF chain satisfy the localization readiness contract.

### Navigation

After localization is valid, start Navigation mode and send a map-frame goal.
The manager reports Nav2 feedback and terminal result. Deactivation requests
goal cancellation and waits for a terminal state; success and cancellation
both command a safe stop.

## Lifecycle and readiness contracts

Lifecycle and readiness answer different questions:

- Lifecycle records whether a manager component is unconfigured, inactive,
  active, in error, or finalized.
- Readiness records whether the runtime dependencies for an operation are
  presently satisfied.

The orchestrator exposes `/platform/lifecycle/transition` and orders
simulation, mapping, localization, and navigation transitions by dependency.
Rollback results and failures are kept separate from the originating failure.
Manager adapters publish transient-local state plus a heartbeat and provide an
authoritative read-only snapshot service. Aggregate success requires two
complete, stable authoritative reads; missing, expired, or changed evidence
fails closed.

Simulation and mode managers publish transient-local JSON readiness reports on
`/platform/readiness`. Reports include the profile, runtime ID, monotonic
observation and lease, all blocked dependencies, reasons, guidance, and
per-dependency checks. Consumers must reject the wrong profile, an earlier
runtime ID, or an expired lease.

| Profile | Principal dependencies |
| --- | --- |
| `simulation_ready` | clock, scan, odometry, joint states, TF, controller service and controller states |
| `mapping_ready` | clock, scan, odometry, TF |
| `localization_ready` | clock, scan, map, AMCL pose, map/odom/base TF |
| `navigation_ready` | localization inputs plus Nav2 action/lifecycle and controller state |

The exact schemas, rates, freshness limits, and fail-closed rules are in
[readiness_contracts.md](docs/readiness_contracts.md).

## Principal ROS 2 interfaces

| Interface | Type | Purpose |
| --- | --- | --- |
| `/simulation/status` | `std_msgs/msg/String` | Simulation state |
| `/simulation/environment_request` | `std_msgs/msg/String` | Environment selection |
| `/mode/status` | `std_msgs/msg/String` | Active mode state |
| `/platform/readiness` | `std_msgs/msg/String` | Structured readiness report |
| `/cmd_vel/gui` | `geometry_msgs/msg/TwistStamped` | Manual velocity command |
| `/control/emergency_stop` | `std_msgs/msg/Bool` | Emergency-stop state |
| `/mapping/save_request` | `std_msgs/msg/String` | Map-save request |
| `/localization/initial_pose_request` | `std_msgs/msg/String` | Initial-pose request |
| `/navigation/goal_request` | `std_msgs/msg/String` | Map-frame navigation goal |
| `/navigate_to_pose` | `nav2_msgs/action/NavigateToPose` | Nav2 goal action |
| `/platform/lifecycle/transition` | custom service | Aggregate lifecycle transition |

Simulation and mode control services use `std_srvs/srv/Trigger`. See the
[topic and interface reference](docs/topic_interface_reference.md) for the
complete public and internal contract.

## Validation

Run the native release gate from the repository root:

```bash
./scripts/build.sh
./scripts/test.sh
git diff --check
```

`test.sh` repeats syntax validation, executes the colcon suite, reports
individual results, and runs simulator launch regression, headless dashboard
integration, and public-launcher lifecycle integration.

The accepted historical v0.1.3 candidate evidence from 2026-09-26 records:

- `./scripts/build.sh`: passed;
- `./scripts/test.sh`: 563 package tests, 0 failures, errors, or skips;
- launch regression, headless dashboard, and launcher lifecycle integrations:
  passed;
- full runtime acceptance: 34/34 checks passed;
- final managed process registry: empty;
- critical manager-node multiplicity: exactly one each.

The evidence was captured from a dirty candidate based on commit
`7764c3683387c966873e00195d0417810624f33c`. It is bound to that source by a
hashed tracked patch and untracked-source archive; it is not evidence for a
v0.1.3 tag or commit. See the
[acceptance summary](docs/evidence/v0.1.3/2026-09-26_012656Z/acceptance_summary.md),
[metadata](docs/evidence/v0.1.3/2026-09-26_012656Z/metadata.json), and
[checksums](docs/evidence/v0.1.3/2026-09-26_012656Z/SHA256SUMS).

The recorded graph contains five noncritical
`/simulation_readiness_probe` entries; the accepted oracle excludes those
internal probe nodes from its critical-node uniqueness check. The evidence
does not claim that every graph name is unique.

Fresh final-candidate verification completed on 2026-11-06 against the staged
uncommitted release candidate:

- syntax validation and `./scripts/build.sh`: passed;
- `./scripts/test.sh`: 565 tests, 0 errors, failures, or skips;
- launch regression, headless dashboard, and public-launcher lifecycle:
  passed;
- isolated runtime acceptance: 34/34 checks passed with an empty final process
  registry and no remaining managed ROS/Gazebo processes.

The raw output, full build/test logs, source-candidate patch, metadata, tracker
reconciliation, and verified SHA-256 manifest are in the
[final-candidate evidence bundle](docs/evidence/v0.1.3/2026-11-06_171445Z/acceptance_summary.md).
The bundle is source-bound to the staged diff, not yet to a release commit or
tag; its metadata records the post-commit reconciliation rule.

## Continuous integration and Docker

The GitHub Actions workflow targets Ubuntu 24.04 and ROS 2 Jazzy. It runs the
native build/test path and Docker build/test coverage defined in
[ros2_jazzy_ci.yml](.github/workflows/ros2_jazzy_ci.yml). Hosted CI does not
exercise interactive Gazebo GUI scenarios.

For local container validation, use the repository's Docker scripts:

```bash
./scripts/docker_build.sh
./scripts/docker_test.sh
```

## Historical media

The screenshots and demonstration links under
[`docs/media/v0.1.0`](docs/media/v0.1.0) document the v0.1.0 user experience.
They are retained as historical media and are not presented as fresh v0.1.3
runtime evidence.

## v0.1.3 release materials

- [Release notes](docs/v0.1.3_release_notes.md)
- [Manual release checklist](docs/v0.1.3_manual_release_checklist.md)
- [Media capture plan](docs/v0.1.3_media_capture_plan.md)
- [LinkedIn publication package](docs/v0.1.3_linkedin_package.md)
- [v0.1.4 engineering handoff](docs/v0.1.4_handoff.md)

## Known limitations

- The candidate has not yet been committed or tagged as v0.1.3.
- The accepted evidence binds an uncommitted candidate with hashes rather than
  a release commit; final-source verification must remain distinct from that
  historical run.
- Five internal readiness-probe graph entries were observed; critical manager
  uniqueness still passed the accepted oracle.
- GUI Gazebo scenarios are not run in hosted CI.
- The platform supports the repository's configured robot, environments,
  maps, and autonomy algorithms; arbitrary dashboard-driven imports and tuning
  are not implemented.
- Runtime maps default to user data outside the repository.
- Hardware deployment, safety certification, performance benchmarking, and
  dynamic-obstacle qualification are outside v0.1.3 scope.
- A final authoritative lifecycle verification failure is reported but cannot
  undo already completed irreversible runtime effects.

## Roadmap

Future work is planning-only and is not part of v0.1.3. The current forward
plan is documented in
[`docs/v0.1.4-v0.1.6_forward_engineering_plan.md`](docs/v0.1.4-v0.1.6_forward_engineering_plan.md).
It must not be interpreted as implemented behavior.

## Development and contribution

Keep changes bounded, preserve established ROS interfaces unless intentionally
versioned, and include validation proportional to the affected subsystem.
Before proposing a merge:

```bash
./scripts/test.sh
git diff --check
git status --short
```

Use the issue and pull-request templates to record objective, scope,
architecture/interface impact, commands actually executed, results, risks,
and remaining limitations. Do not commit generated workspace artifacts,
runtime maps, bags, logs, or local environment files.

## Release information

| Item | Value |
| --- | --- |
| Candidate | v0.1.3 |
| Package | `cpp_robotics_sim_ros` |
| Package version | `0.1.3` |
| Primary environment | Ubuntu 24.04, ROS 2 Jazzy, Gazebo Harmonic |
| License | MIT |
| Published baseline tags | v0.1.0, v0.1.1, v0.1.2 |
| v0.1.3 tag | Not created |

Release publication requires a reviewed commit whose final tree has passed the
applicable release gates. This repository intentionally contains no claim that
the untagged candidate is already published.

## License

Licensed under the [MIT License](LICENSE).

## Author

Devansh Mishra — [GitHub](https://github.com/Devansh-Mishra-30)
