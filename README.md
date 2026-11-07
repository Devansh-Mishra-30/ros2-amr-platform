# ROS 2 AMR Platform

[![ROS 2 Jazzy CI](https://github.com/Devansh-Mishra-30/ros2-amr-platform/actions/workflows/ros2_jazzy_ci.yml/badge.svg)](https://github.com/Devansh-Mishra-30/ros2-amr-platform/actions/workflows/ros2_jazzy_ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A browser-controlled autonomous mobile robot (AMR) simulation, orchestration,
and verification platform built with ROS 2 Jazzy and Gazebo Harmonic.

The current published release is **v0.1.3 — Readiness Contracts**. Its annotated
tag points to merge commit `16d3f0dc28b1cd7ab0f90a095fd531a694b06b7b`,
and the package version is `0.1.3`.

This is a simulation and engineering-verification platform. It is not a
certified safety system or a production-hardware deployment.

## Platform Preview & Demonstrations

A browser-controlled ROS 2 simulation platform for autonomous navigation,
mapping, localization, and managed robot-system operation.

<p align="center">
  <a href="https://www.youtube.com/watch?v=zKf_hjIYtlk">
    <img src="docs/media/v0.1.0/dashboard.png"
         alt="ROS 2 AMR browser dashboard and simulation controls"
         width="900">
  </a>
</p>

<p align="center">
  <strong>Browser Dashboard · ROS 2 Jazzy · Gazebo Harmonic · Nav2</strong>
</p>

### Simulation Environments

<table>
<tr>
<td width="50%" align="center">
  <img src="docs/media/v0.1.0/warehouse_gazebo.png"
       alt="ROS 2 AMR Warehouse Gazebo environment"
       width="100%">
  <br>
  <strong>Warehouse Environment</strong>
</td>
<td width="50%" align="center">
  <img src="docs/media/v0.1.0/hospital_gazebo.png"
       alt="ROS 2 AMR Hospital Gazebo environment"
       width="100%">
  <br>
  <strong>Hospital Environment</strong>
</td>
</tr>
</table>

### Explore the Project

**[Watch 32-Second Demo](https://www.youtube.com/watch?v=zKf_hjIYtlk)**
&nbsp; | &nbsp;
**[YouTube Demonstration Playlist](https://www.youtube.com/playlist?list=PLP_aJnUqSRf8)**
&nbsp; | &nbsp;
**[Portfolio Case Study](https://devanshportfolio.bubbleapps.io/version-test/project-12)**
&nbsp; | &nbsp;
**[Latest Release — v0.1.3](https://github.com/Devansh-Mishra-30/ros2-amr-platform/releases/tag/v0.1.3)**

> **Demo version:** The screenshots and linked demonstration videos show
> the original v0.1.0 platform workflows. The current v0.1.3 release
> additionally includes managed lifecycle and fail-closed readiness
> contracts. Refer to the release evidence below for their verification.

### Engineering Highlights

| Area | Published v0.1.3 evidence |
| --- | --- |
| **Autonomous navigation** | SLAM Toolbox, AMCL, Nav2 |
| **Robot simulation** | ROS 2 Jazzy, Gazebo Harmonic, ros2_control |
| **System orchestration** | Managed lifecycle and readiness contracts |
| **Automated acceptance** | 565 tests across 26 CTest targets |
| **Runtime acceptance** | 34/34 checks passed |
| **Continuous integration** | Native ROS 2 and Docker CI passed at the release commit |

The test counts above are from the documented v0.1.3 acceptance run,
not a new execution of the suite.

### Video Walkthroughs

The following recordings demonstrate the original v0.1.0 workflows.

| Demonstration | What it covers |
| --- | --- |
| [Project Teaser](https://www.youtube.com/watch?v=zKf_hjIYtlk) | Complete platform overview |
| [Manual Robot Control](https://www.youtube.com/watch?v=eXRZwrg_8eY) | Dashboard and keyboard-based control |
| [SLAM Mapping](https://www.youtube.com/watch?v=gJ5ggf250xE) | LiDAR-based occupancy mapping |
| [AMCL Localization](https://www.youtube.com/watch?v=HJZlihnV8Ko) | Robot localization using a saved map |
| [Nav2 Navigation](https://www.youtube.com/watch?v=O9wMdFE_PvU) | Autonomous navigation goals and cancellation |
| [Installation and First Launch](https://www.youtube.com/watch?v=_x2Z7jXXnWw) | Build, launch, and environment setup |
| [Docker Validation](https://www.youtube.com/watch?v=4M628CFYiz8) | Original v0.1.0 container validation |

---

## Implemented capabilities

- Browser dashboard served over HTTP with rosbridge connectivity.
- Warehouse and hospital Gazebo environments.
- Differential-drive robot with LiDAR, odometry, joint states, and simulated
  clock.
- Manual velocity control, command arbitration, and emergency stop.
- SLAM mapping with validated map saving and saved-map inventory.
- AMCL localization with map selection and initial-pose workflows.
- Nav2 single-goal navigation, feedback, cancellation, and safe terminal stop.
- Managed simulation and operating-mode process lifecycles.
- Dependency-ordered component lifecycle transitions with structured failures,
  rollback evidence, and explicit recovery.
- Fail-closed readiness profiles for simulation, mapping, localization, and
  navigation.
- Syntax, unit, integration, launch, lifecycle, runtime-acceptance, native CI,
  and Docker CI validation.

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

The dashboard publishes requests and displays ROS 2 state; it does not
implement robotics algorithms. Operating modes remain mutually exclusive, and
supported velocity sources pass through the command multiplexer before reaching
the drive controller.

TF ownership depends on the operating mode:

- Mapping: SLAM Toolbox owns `map -> odom`.
- Localization and navigation: AMCL owns `map -> odom`.
- ros2_control owns `odom -> base_link`.
- `robot_state_publisher` owns robot-link and sensor transforms.

The [system architecture](docs/system_architecture.md) records the v0.1.0
baseline. The [lifecycle foundation](docs/lifecycle_foundation.md) and
[readiness contracts](docs/readiness_contracts.md) describe the additive
v0.1.2 and v0.1.3 contracts.

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
├── .github/                         # CI and contribution templates
├── docs/                            # architecture, contracts, evidence, plans
├── ros2_ws/src/cpp_robotics_sim_ros/
│   ├── config/ and nav2/            # manager, controller, and Nav2 parameters
│   ├── include/ and src/            # C++ implementation and public headers
│   ├── launch/                      # simulation and web launch descriptions
│   ├── scripts/                     # installed Python manager/contract nodes
│   ├── test/                        # Python, launch, contract, and C++ tests
│   ├── urdf/, xacro/, worlds/       # robot and simulation assets
│   └── web/dashboard/               # browser dashboard
├── scripts/                         # setup, build, run, cleanup, validation
├── Dockerfile
└── README.md
```

Generated `build/`, `install/`, `log/`, and cache directories are not source.

## Supported environment

The verified primary environment is Ubuntu 24.04, including WSL2, with ROS 2
Jazzy and Gazebo Harmonic. Interactive Gazebo requires a working graphics stack.

The project setup script expects `/opt/ros/jazzy/setup.bash` to exist. It
initializes rosdep when needed and installs dependencies declared by the ROS
workspace:

```bash
./scripts/setup.sh
```

See the [installation guide](docs/installation.md) for the detailed v0.1.0
baseline procedure. Its version-specific counts and commit references are
historical; the commands remain the foundation of the current workflow.

## Clone and reproduce v0.1.3

```bash
git clone https://github.com/Devansh-Mishra-30/ros2-amr-platform.git
cd ros2-amr-platform
git checkout v0.1.3
./scripts/setup.sh
./scripts/build.sh
./scripts/test.sh
```

`build.sh` runs source syntax checks, sources ROS 2, and builds
`cpp_robotics_sim_ros` with tests enabled. To source the result manually:

```bash
source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash
```

## Run

```bash
./scripts/run.sh
```

The launcher starts the dashboard HTTP server, rosbridge, manager layer, and
supporting ROS 2 nodes. The default endpoints are HTTP port 8080 and rosbridge
port 9090. Ctrl+C invokes verified owned-process cleanup.

Useful overrides:

```bash
OPEN_BROWSER=false ./scripts/run.sh
DASHBOARD_PORT=8081 ROSBRIDGE_PORT=9091 ./scripts/run.sh
```

## Operator workflows

### Simulation and manual control

Select an environment, start simulation, and wait for both the simulation state
and `simulation_ready` profile. Manual mode publishes `TwistStamped` commands on
`/cmd_vel/gui`; the command multiplexer controls admission to the drive
controller. Stop the mode or engage emergency stop before leaving manual
operation.

### Mapping

Start Mapping only after simulation readiness succeeds. Drive the environment,
save with a valid map name, and confirm both the reported result and saved-map
inventory. Runtime map paths are validated and default outside the repository.

### Localization and navigation

Select a saved map, start Localization, and provide an initial pose. Readiness
requires clock, scan, map, AMCL pose, and the necessary TF chain. After
localization is valid, Navigation accepts a map-frame goal and reports Nav2
feedback and terminal state. Deactivation requests cancellation and waits for a
terminal result before reporting success.

## Lifecycle and readiness

Lifecycle and readiness answer different questions:

- Lifecycle records whether a manager component is unconfigured, inactive,
  active, in error, or finalized.
- Readiness records whether the runtime dependencies for a specific operation
  are currently satisfied.

The orchestrator exposes `/platform/lifecycle/transition` and orders simulation,
mapping, localization, and navigation transitions by dependency. Manager
adapters publish transient-local state and heartbeat data and provide an
authoritative read-only snapshot service. Aggregate success requires two
complete, stable authoritative reads; missing, expired, or changed evidence
fails closed.

Simulation and mode managers publish transient-local JSON reports on
`/platform/readiness`. Reports identify the profile, runtime ID, observation and
lease, all blocked dependencies, reasons, guidance, and individual checks.

| Profile | Principal dependencies |
| --- | --- |
| `simulation_ready` | clock, scan, odometry, joint states, TF, controller service and states |
| `mapping_ready` | clock, scan, odometry, TF |
| `localization_ready` | clock, scan, map, AMCL pose, map/odom/base TF |
| `navigation_ready` | localization inputs, Nav2 action/lifecycle, controller state |

See [readiness contracts](docs/readiness_contracts.md) for exact schemas,
freshness rules, and fail-closed behavior.

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

Simulation and mode control services use `std_srvs/srv/Trigger`. The
[topic and interface reference](docs/topic_interface_reference.md) is the full
v0.1.3 contract.

## Validation and release evidence

Run the native gate from the repository root:

```bash
./scripts/build.sh
./scripts/test.sh
git diff --check
```

`test.sh` repeats syntax validation, executes the colcon suite, reports results,
then runs simulator launch regression, headless dashboard integration, and
public-launcher lifecycle integration.

Final v0.1.3 local acceptance recorded:

- 565 tests across 26 CTest targets, with no failures, errors, or skips;
- simulator launch, headless dashboard, and launcher lifecycle integrations
  passed;
- 34/34 runtime acceptance checks passed;
- final managed process registry and managed-process scan were empty.

The [final acceptance summary](docs/evidence/v0.1.3/2026-11-06_171445Z/acceptance_summary.md)
is source-bound to the reviewed candidate. The annotated tag and published
release identify the accepted commit, and the
[release-commit GitHub Actions run](https://github.com/Devansh-Mishra-30/ros2-amr-platform/actions/runs/42301211782)
passed both native ROS 2 and Docker jobs.

The earlier [2026-09-26 evidence](docs/evidence/v0.1.3/2026-09-26_012656Z/acceptance_summary.md)
remains immutable historical candidate evidence. Its source bindings and scope
must not be interpreted as evidence for a different commit.

### Docker validation

```bash
docker build --tag cpp-robotics-sim:local .
docker run --rm --init --network host \
  cpp-robotics-sim:local \
  bash -lc 'cd /workspace && ./scripts/test.sh'
```

Hosted CI does not exercise interactive Gazebo GUI scenarios.

## Known limitations

- **Network exposure:** The current v0.1.3 dashboard HTTP server and
  rosbridge WebSocket bind to `0.0.0.0`. Depending on firewall and network
  configuration, these interfaces can be accessible from other machines.
  They do not provide an application-level authentication boundary.
  Operate the platform only in a trusted, isolated development environment.
  Do not expose these interfaces directly to the public internet or
  untrusted networks.
- **Emergency-stop scope:** Dashboard emergency-stop functionality is
  software-level command handling, not a safety-rated physical emergency
  stop or certified safety mechanism.
- Validation is simulation-only; physical hardware, hardware-in-the-loop,
  safety certification, and production deployment are not claimed.
- Hosted CI does not exercise interactive Gazebo GUI scenarios.
- Five internal `/simulation_readiness_probe` graph entries may appear; the
  accepted oracle excludes these noncritical probes from manager uniqueness.
- The platform supports the configured robot, environments, maps, and autonomy
  algorithms; arbitrary dashboard-driven imports and tuning are not provided.
- Runtime maps default to user data outside the repository.
- Final lifecycle verification reports external irreversible effects but cannot
  reverse effects that already completed.

## Release history

| Version | GitHub publication status | Engineering milestone |
| --- | --- | --- |
| **v0.1.0** | Published GitHub release | Browser-controlled simulation, mapping, localization, navigation, and initial validation |
| **v0.1.1** | Git tag; no separate GitHub release | Deterministic process ownership and runtime cleanup |
| **v0.1.2** | Git tag; no separate GitHub release | Managed component lifecycle foundation |
| **v0.1.3** | Published GitHub release | Fail-closed readiness contracts and authoritative lifecycle verification |

The intermediate v0.1.1 and v0.1.2 milestones are preserved as Git
tags. They should not be confused with separately published GitHub
releases. The latest published release is v0.1.3.

See the [v0.1.3 release notes](docs/v0.1.3_release_notes.md) and
[published GitHub release](https://github.com/Devansh-Mishra-30/ros2-amr-platform/releases/tag/v0.1.3).

## Roadmap boundary

Post-v0.1.3 work is planning-only. The
[v0.1.4–v0.1.6 engineering plan](docs/v0.1.4-v0.1.6_forward_engineering_plan.md)
and [v0.1.4 handoff](docs/v0.1.4_handoff.md) are not implemented behavior and do
not authorize feature work.

## Documentation navigation

- [Installation guide](docs/installation.md) — detailed v0.1.0 baseline setup.
- [System architecture](docs/system_architecture.md) — v0.1.0 architectural
  baseline and ownership model.
- [Lifecycle foundation](docs/lifecycle_foundation.md) — v0.1.2 component and
  orchestration contracts.
- [Readiness contracts](docs/readiness_contracts.md) — v0.1.3 profiles and
  fail-closed rules.
- [Topic and interface reference](docs/topic_interface_reference.md) — current
  public and internal v0.1.3 contract.
- [Debugging and validation](docs/debugging_and_validation.md) — detailed
  v0.1.0 validation baseline; use repository scripts for the current gate.
- [Release verification tracker](docs/AMR_Release_Verification_Tracker.xlsx) —
  planning, traceability, release gates, and supported evidence index.
- [v0.1.3 release notes](docs/v0.1.3_release_notes.md) — release scope,
  validation, and limitations.

## Development and contribution

Keep changes bounded, preserve established interfaces unless intentionally
versioned, and run validation proportional to the affected subsystem. Before a
merge proposal:

```bash
./scripts/test.sh
git diff --check
git status --short
```

Use the issue and pull-request templates to record scope, architecture and
interface impact, commands executed, results, risks, and limitations. Do not
commit generated workspace artifacts, runtime maps, bags, logs, caches, or
local environment files.

## License

Licensed under the [MIT License](LICENSE).

## Author

Devansh Mishra — [GitHub](https://github.com/Devansh-Mishra-30)
