# System Architecture

## C++ / ROS 2 Robotics Simulation Foundation

**Release:** `v0.1.0`
**Release commit:** `28a080e72ee6e31baa25bcd2fdaa249706520361`
**Primary platform:** Ubuntu 24.04, ROS 2 Jazzy, Gazebo Harmonic
**Robot type:** Differential-drive autonomous mobile robot
**Primary user interface:** Browser dashboard connected to ROS 2 through rosbridge

---

## 1. Document Purpose

This document defines the software architecture of
`cpp_robotics_sim_foundation` at release `v0.1.0`.

It explains:

- the responsibilities of the browser dashboard;
- how the dashboard communicates with ROS 2;
- how simulation and operating-mode processes are launched and supervised;
- how manual, mapping, localization, and navigation modes are separated;
- how velocity commands are prioritized and sent to the robot;
- how environments and saved maps are managed;
- how SLAM Toolbox, AMCL, and Nav2 are integrated;
- which nodes own the principal TF transforms;
- how process cleanup, safety behavior, testing, and release validation work;
- the explicit limitations of the first public release.

---

## 2. System Overview

`cpp_robotics_sim_foundation` is a browser-controlled ROS 2 mobile-robot
simulation platform.

Release `v0.1.0` supports:

```text
Warehouse and Hospital environment selection
Managed simulation startup, stop, reset, and recovery
Browser-based manual driving
Browser-keyboard driving
Optional terminal-keyboard command input
Priority-based velocity-command arbitration
Emergency-stop override
SLAM Toolbox mapping
Environment-aware map saving and map inventory
Saved-map selection
AMCL localization
Map-frame Nav2 goal requests
Goal feedback, completion, rejection, and cancellation
Managed process-group shutdown
Native validation
Docker build-and-test validation
GitHub Actions CI
```

The normal user workflow is operated from the browser dashboard. The
dashboard does not implement robotics algorithms itself. It publishes
requests and commands to ROS 2 and displays state reported by ROS 2 nodes.

---

## 3. Architectural Principles

### 3.1 Reproducible public workflow

The supported repository workflow is:

```text
./scripts/setup.sh
./scripts/build.sh
./scripts/test.sh
./scripts/run.sh
```

### 3.2 Explicit lifecycle ownership

Simulation processes, operating-mode processes, dashboard infrastructure,
and stale-process cleanup have separate owners.

### 3.3 Mutually exclusive operating modes

The mode manager exposes:

```text
manual
mapping
localization
navigation
```

Only one operating mode is active at a time.

### 3.4 Centralized velocity arbitration

All supported velocity sources converge at one command multiplexer before
reaching `diff_drive_controller`.

### 3.5 Environment-aware map handling

Saved maps are organized by environment and validated before use.

### 3.6 Observable status

The dashboard receives explicit status for simulation, environment,
operating mode, maps, localization, navigation, active command source, and
emergency-stop state.

### 3.7 Layered validation

The release is checked through syntax checks, unit tests, ROS 2 package
tests, launch regression, dashboard integration, launcher lifecycle tests,
Docker validation, and CI.

---

## 4. System Context

```text
User
  |
  v
Browser Dashboard
  |
  | HTTP
  | rosbridge WebSocket
  v
ROS 2 Management Nodes
  |
  | services, request topics, status topics
  | managed launch processes
  v
ROS 2 Robotics Runtime
  |
  | robot description
  | ros2_control
  | mapping
  | localization
  | navigation
  | command arbitration
  v
Gazebo Harmonic
  |
  v
Differential-Drive Robot in Warehouse or Hospital
```

Primary dependencies include:

```text
Ubuntu 24.04
ROS 2 Jazzy
Gazebo Harmonic
ros2_control
gz_ros2_control
ros_gz_bridge
SLAM Toolbox
Nav2
AMCL
rosbridge_server
Python 3
C++17
colcon
Docker
```

---

## 5. High-Level Runtime Architecture

```text
+---------------------------------------------------------------+
|                        Browser Dashboard                      |
|                                                               |
| Environment | Start/Stop | Modes | Drive | Maps | Nav Goals  |
+-------------------------------+-------------------------------+
                                |
                                | HTTP :8080
                                | rosbridge WebSocket :9090
                                v
+---------------------------------------------------------------+
|                    Dashboard Infrastructure                   |
|                                                               |
| web_interface.launch.py                                       |
| Python HTTP server                                            |
| rosbridge_websocket                                           |
| single-instance lock                                          |
| stale-project-process cleanup                                 |
+-------------------------------+-------------------------------+
                                |
                                v
+---------------------------------------------------------------+
|                       Management Layer                        |
|                                                               |
| simulation_manager                                            |
| mode_manager                                                  |
| mapping_manager                                               |
| localization_manager                                          |
| navigation_goal_manager                                       |
+----------+------------------+--------------------+-------------+
           |                  |                    |
           v                  v                    v
+----------------+  +-------------------+  +--------------------+
| Core Simulation|  | Mapping / Maps    |  | Localization / Nav |
|                |  |                   |  |                    |
| Gazebo         |  | SLAM Toolbox      |  | map_server         |
| robot model    |  | map_saver_cli     |  | AMCL               |
| ros2_control   |  | map inventory     |  | Nav2 servers       |
| LiDAR bridge   |  | safe map paths    |  | NavigateToPose     |
+-------+--------+  +---------+---------+  +----------+---------+
        |                     |                       |
        +---------------------+-----------------------+
                              |
                              v
+---------------------------------------------------------------+
|                    Command and Robot Layer                    |
|                                                               |
| cmd_vel_twist_bridge                                          |
| command_mux                                                   |
| diff_drive_controller                                         |
| joint_state_broadcaster                                       |
| robot_state_publisher                                         |
| ros_gz_bridge                                                 |
+-------------------------------+-------------------------------+
                                |
                                v
+---------------------------------------------------------------+
|                        Gazebo Harmonic                         |
|                                                               |
| differential-drive robot                                      |
| wheel joints                                                  |
| LiDAR                                                         |
| Warehouse or Hospital world                                   |
+---------------------------------------------------------------+
```

---

## 6. Repository Architecture

The tagged `v0.1.0` repository contains:

```text
cpp_robotics_sim_foundation/
├── .github/
│   └── workflows/
│       └── ros2_jazzy_ci.yml
├── docs/
├── ros2_ws/
│   └── src/
│       └── cpp_robotics_sim_ros/
│           ├── config/
│           ├── include/
│           ├── launch/
│           ├── maps/
│           ├── nav2/
│           ├── rviz/
│           ├── scripts/
│           ├── src/
│           ├── test/
│           ├── urdf/
│           ├── web/
│           ├── worlds/
│           ├── xacro/
│           ├── CMakeLists.txt
│           └── package.xml
├── scripts/
├── Dockerfile
├── LICENSE
└── README.md
```

---

## 7. Public Repository Scripts

### `scripts/setup.sh`

Performs host and dependency setup checks for the supported Ubuntu and ROS 2
environment.

### `scripts/build.sh`

Runs source syntax checks and builds the ROS 2 package with testing enabled.

### `scripts/test.sh`

Runs the complete native release test gate, including:

```text
source syntax checks
colcon test
colcon test-result
launch regression
headless dashboard integration
public launcher lifecycle validation
```

### `scripts/run.sh`

Starts the public browser-controlled platform.

It resolves dashboard and rosbridge ports, sources the ROS 2 workspace, and
launches `web_interface.launch.py`.

Default ports:

```text
Dashboard HTTP: 8080
rosbridge WebSocket: 9090
```

### `scripts/clean.sh`

Removes generated workspace state and caches. It is not the primary runtime
shutdown mechanism.

Runtime processes should be stopped through the dashboard and launcher
lifecycle paths.

---

## 8. Dashboard Infrastructure

`web_interface.launch.py` launches:

```text
simulation_manager
mode_manager
mapping_manager
localization_manager
navigation_goal_manager
rosbridge_websocket
Python HTTP server
```

It also implements two important infrastructure protections.

### 8.1 Single-instance lock

A lock file under:

```text
~/.ros/cpp_robotics_sim/web_interface.lock
```

prevents multiple dashboard launch instances from running simultaneously.

### 8.2 Stale-process cleanup

Before launching, the web interface reconciles the file-backed ownership
registry under `~/.ros/cpp_robotics_sim/`. It never authorizes cleanup from a
process-name match. A registered group is signaled only while its saved Linux
identity still matches, using PID, PGID, session ID, `/proc` start time,
executable, and command-line fingerprint. Persisted descendant identities
allow a surviving session to be recovered after its launch leader dies.

Recovery stops mode groups before the simulation group and uses bounded
`SIGINT`, `SIGTERM`, then `SIGKILL` stages. An ambiguous identity is retained
and reported instead of being signaled. The same reconciliation runs before
the single-instance lock is released at launcher shutdown.

---

## 9. Browser Communication

### 9.1 Dashboard transport

The dashboard is served through HTTP and communicates with ROS 2 through
rosbridge.

Default endpoints:

```text
http://localhost:8080
ws://localhost:9090
```

Under WSL2, `run.sh` handles the host-accessible dashboard address and
browser launch behavior.

### 9.2 Browser responsibilities

The dashboard can:

```text
select an environment
start, stop, or reset the simulation
activate or stop a mode
publish manual velocity commands
publish browser-keyboard velocity commands
engage or release emergency stop
request a map save
select a saved map
publish an initial-pose request
send a navigation goal
cancel a navigation goal
display system status and feedback
```

Browser buttons and browser keyboard events both use the dashboard GUI
velocity topic:

```text
/cmd_vel/gui
geometry_msgs/msg/TwistStamped
```

The browser does not publish to `/cmd_vel/keyboard`.

---

## 10. Simulation Manager

The simulation manager owns high-level simulation lifecycle and environment
selection.

### 10.1 States

```text
stopped
starting
running
stopping
error
```

### 10.2 Interfaces

Publishes:

```text
/simulation/status
/simulation/environment_status
```

Subscribes:

```text
/simulation/environment_request
```

Provides:

```text
/simulation/start
/simulation/stop
/simulation/reset
```

### 10.3 Environment registry

Supported environment identifiers:

```text
warehouse
hospital
```

Associated world files:

```text
warehouse_world.sdf
hospital_world.sdf
```

### 10.4 Selection lock

Environment changes are rejected while the simulation is:

```text
starting
running
stopping
```

or while the managed simulation process is still running.

### 10.5 Managed simulation launch

The simulation manager launches:

```text
interactive_control.launch.py
```

with the selected world path and simulation-time setting.

### 10.6 Process lifecycle

The managed simulation launch is started in a new operating-system session.

The manager:

```text
registers the launch leader and stable descendant identities
verifies PID, process group, session, start time, executable, and command line
cancels navigation and commands zero velocity
waits for the active operating mode to stop
sends SIGINT to the verified simulation process group
uses bounded SIGTERM and SIGKILL escalation if required
persists structured shutdown diagnostics outside ROS
publishes stopped or error state
detects unexpected process exit
```

---

## 11. Core Simulation Launch

`interactive_control.launch.py` starts:

```text
ros2_control.launch.py
command_mux_node.py
```

The command multiplexer is delayed to allow the simulator and controller
stack to initialize first.

The core runtime includes:

```text
Gazebo Harmonic
selected world
robot description
robot_state_publisher
gz_ros2_control
controller_manager
joint_state_broadcaster
diff_drive_controller
LiDAR bridge
simulation-time bridge
command_mux
```

The dashboard launcher remains available while the simulation itself is
stopped.

---

## 12. Mode Manager

The mode manager owns the active high-level operating mode and each
mode-specific launch process.

### 12.1 Modes

```text
stopped
starting
manual
mapping
localization
navigation
error
```

### 12.2 Interfaces

Provides:

```text
/mode/manual
/mode/mapping
/mode/localization
/mode/navigation
/mode/stop
```

Publishes:

```text
/mode/status
```

Subscribes to simulation status and selected-map state.

### 12.3 Transition rules

A mode cannot be activated unless the simulation state is `running`.

Localization and Navigation modes additionally require a selected map path.

The code does not require proof that an initial pose has already been
published before Navigation mode starts or before a goal is sent.

Setting an initial pose remains operationally necessary for meaningful AMCL
localization, but it is not an enforced navigation-goal invariant in
`v0.1.0`.

### 12.4 Mutual exclusion

When a new mode is requested, the manager first stops the current mode.

Manual mode does not launch a separate ROS 2 process.

The other modes launch:

```text
Mapping      -> slam_mapping.launch.py
Localization -> amcl_localization.launch.py
Navigation   -> nav2_navigation.launch.py
```

### 12.5 Mode-process shutdown

Mode-specific launches run in their own process groups.

The mode manager registers each launch group immediately, verifies its saved
identity before every signal, and uses bounded `SIGINT`, `SIGTERM`, then
`SIGKILL` escalation. Registration failure rolls back the newly created group
so a long-lived child cannot continue unowned.

This process ownership is separate from the simulation manager's core
simulation process group.

---

## 13. Command Multiplexer

`command_mux_node.py` is the authority that selects and forwards velocity
commands to the robot controller.

### 13.1 Configured command sources

| Source | Topic | Priority | Freshness timeout |
|---|---|---:|---:|
| Gamepad | `/cmd_vel/gamepad` | 100 | 0.50 s |
| Terminal keyboard | `/cmd_vel/keyboard` | 90 | 0.50 s |
| Browser GUI and browser keyboard | `/cmd_vel/gui` | 80 | 0.75 s |
| Navigation | `/cmd_vel/navigation` | 50 | 0.50 s |

The gamepad source is configured in the multiplexer, but PS4/gamepad support
is not part of the completed `v0.1.0` public feature scope.

### 13.2 Output

```text
/diff_drive_controller/cmd_vel
geometry_msgs/msg/TwistStamped
```

### 13.3 Selection algorithm

At 20 Hz, the multiplexer:

1. checks emergency-stop state;
2. removes expired or invalid sources from consideration;
3. selects the highest-priority fresh source;
4. clamps supported velocity components;
5. clears unsupported Twist components;
6. publishes the selected command;
7. publishes the active source.

If no source is fresh, it publishes zero velocity and reports:

```text
/control/active_source = none
```

### 13.4 Input validation

A command is rejected when any Twist component is non-finite.

### 13.5 Velocity limits

```text
maximum linear velocity: 0.30 m/s
maximum angular velocity: 1.00 rad/s
```

### 13.6 Emergency stop

The multiplexer subscribes to:

```text
/control/emergency_stop
std_msgs/msg/Bool
```

When active, emergency stop overrides every command source, publishes zero
velocity, and reports:

```text
/control/active_source = emergency_stop
```

### 13.7 Safe-stop ownership

The primary continuous safe-stop behavior belongs to the command
multiplexer.

When an active source stops publishing and its freshness timeout expires,
the multiplexer selects no source and publishes zero velocity.

The navigation goal manager reports action completion and resets its goal
state, but it does not directly publish a zero-velocity command in the
tagged `v0.1.0` implementation.

---

## 14. Manual Control Architecture

### 14.1 Browser controls

Dashboard buttons and browser keyboard events publish:

```text
/cmd_vel/gui
geometry_msgs/msg/TwistStamped
```

Flow:

```text
Dashboard button or browser key
        |
        v
/cmd_vel/gui
        |
        v
command_mux
        |
        v
/diff_drive_controller/cmd_vel
        |
        v
diff_drive_controller
        |
        v
Gazebo robot
```

Releasing browser controls publishes zero commands, and the GUI source also
expires after 0.75 seconds if updates stop unexpectedly.

### 14.2 Terminal keyboard control

`keyboard_teleop_node.py` is a separate optional terminal interface.

It publishes:

```text
/cmd_vel/keyboard
geometry_msgs/msg/TwistStamped
```

The terminal keyboard source has higher priority than the browser GUI source.

It is not the same as browser-keyboard control.

---

## 15. Mapping Manager

The mapping manager owns map-save requests and saved-map inventory.

### 15.1 Interfaces

Subscribes:

```text
/mapping/save_request
/mode/status
/simulation/status
/simulation/environment_status
```

Publishes:

```text
/mapping/save_status
/mapping/saved_maps
```

### 15.2 Map root

```text
~/.ros/cpp_robotics_sim/maps
```

### 15.3 Environment-aware storage

Maps are saved under:

```text
~/.ros/cpp_robotics_sim/maps/<environment>/<map_name>.yaml
~/.ros/cpp_robotics_sim/maps/<environment>/<map_name>.pgm
```

### 15.4 Save implementation

The manager validates the request, resolves the environment directory, and
invokes:

```text
nav2_map_server map_saver_cli
```

A save is treated as successful only when both YAML and PGM files exist.

### 15.5 Inventory

The manager recursively scans the managed map root, derives environment
metadata from each relative path, checks whether the matching image exists,
and publishes a JSON map inventory.

---

## 16. Mapping Mode

Mapping mode launches:

```text
slam_mapping.launch.py
```

SLAM Toolbox consumes LiDAR and TF data and publishes the occupancy grid and
map correction transform.

### 16.1 Data flow

```text
Gazebo LiDAR
    |
    v
/scan -----------------------+
                             |
diff_drive_controller        |
    |                        |
    v                        |
odom -> base_link            |
                             v
                       SLAM Toolbox
                             |
                  +----------+----------+
                  |                     |
                  v                     v
                /map                map -> odom
```

### 16.2 TF ownership during mapping

```text
SLAM Toolbox:
  map -> odom

diff_drive_controller:
  odom -> base_link

robot_state_publisher:
  base_link -> robot links and sensors
```

SLAM Toolbox and AMCL must not simultaneously own `map -> odom`.

Mode mutual exclusion prevents Mapping and Localization/Navigation from being
active together.

---

## 17. Localization Manager

The localization manager validates map selection and publishes initial-pose
messages.

### 17.1 Interfaces

Subscribes:

```text
/localization/select_map_request
/localization/initial_pose_request
/mode/status
/simulation/status
/simulation/environment_status
```

Publishes:

```text
/localization/selected_map
/localization/status
/initialpose
```

### 17.2 Selected-map state

The manager stores:

```text
selected map name
selected map YAML path
selected map environment
selected simulation environment
```

### 17.3 Map resolution

For environment `<environment>` and map `<name>`, the preferred path is:

```text
~/.ros/cpp_robotics_sim/maps/<environment>/<name>.yaml
```

A legacy root-level map location is also recognized by the `v0.1.0`
implementation.

### 17.4 Environment switching

When the simulation environment changes, a selected map belonging to another
environment is cleared and the updated empty selection is published.

### 17.5 Initial pose

The manager publishes:

```text
geometry_msgs/msg/PoseWithCovarianceStamped
```

to:

```text
/initialpose
```

A selected map is required before an initial-pose request is accepted.

---

## 18. Localization Mode

Localization mode launches:

```text
amcl_localization.launch.py
```

The launch contains:

```text
scan-frame compatibility transform
nav2_map_server map_server
nav2_amcl amcl
localization lifecycle manager
```

The lifecycle manager automatically activates:

```text
map_server
amcl
```

### 18.1 Data flow

```text
Saved YAML and PGM map
        |
        v
    map_server
        |
        v
       /map ----------------------+
                                  |
Gazebo LiDAR                      |
    |                             |
    v                             |
  /scan --------------------------+
                                  |
diff_drive_controller             |
    |                             |
    v                             |
odom -> base_link                 |
                                  v
                                AMCL
                                  |
                       +----------+----------+
                       |                     |
                       v                     v
                  /amcl_pose            map -> odom
```

### 18.2 TF ownership during localization

```text
AMCL:
  map -> odom

diff_drive_controller:
  odom -> base_link

robot_state_publisher:
  base_link -> robot links and sensors
```

Expected transform chain:

```text
map -> odom -> base_link
```

---

## 19. Navigation Goal Manager

The navigation goal manager provides dashboard and CLI clients with a JSON
interface to Nav2's `NavigateToPose` action.

### 19.1 Interfaces

Subscribes:

```text
/navigation/goal_request
/navigation/cancel_request
/mode/status
/simulation/status
```

Publishes:

```text
/navigation/status
/navigation/feedback
```

Uses action:

```text
/navigate_to_pose
nav2_msgs/action/NavigateToPose
```

### 19.2 Goal frame

Every action goal is created in:

```text
map
```

### 19.3 Goal acceptance rules

A goal is rejected unless:

```text
the JSON request is valid
x, y, and yaw are present and valid
the simulation state is running
the active mode is navigation
no other navigation goal is active
the NavigateToPose server is available
```

The goal manager does not check whether `/initialpose` has already been
published.

### 19.4 Goal state

The manager tracks:

```text
request identifier
current goal
active goal handle
goal request in progress
cancel requested
last feedback
```

### 19.5 Completion

The manager converts ROS action status into:

```text
succeeded
canceled
aborted
```

It publishes the final status and resets internal goal state.

### 19.6 Cancellation

A cancellation request must contain:

```json
{"cancel": true}
```

The manager requests asynchronous cancellation and publishes cancellation
progress and result state.

---

## 20. Navigation Mode

Navigation mode launches:

```text
nav2_navigation.launch.py
```

### 20.1 Localization portion

The launch includes Nav2's localization launch with:

```text
selected saved map
shared Nav2 parameter file
autostart enabled
composition disabled
```

This provides map-server and AMCL functionality for navigation.

### 20.2 Navigation servers

The launch starts:

```text
controller_server
planner_server
behavior_server
bt_navigator
waypoint_follower
velocity_smoother
navigation lifecycle manager
```

### 20.3 Command path

The exact `v0.1.0` navigation command path is:

```text
controller_server or behavior_server
        |
        | remapped output
        v
/cmd_vel_nav_raw
        |
        v
velocity_smoother
        |
        v
/cmd_vel
geometry_msgs/msg/Twist
        |
        v
cmd_vel_twist_bridge
        |
        v
/cmd_vel/navigation
geometry_msgs/msg/TwistStamped
        |
        v
command_mux
        |
        v
/diff_drive_controller/cmd_vel
geometry_msgs/msg/TwistStamped
        |
        v
diff_drive_controller
        |
        v
Gazebo wheel joints
```

Navigation has the lowest configured command-source priority:

```text
navigation priority: 50
```

Therefore fresh gamepad, terminal-keyboard, or GUI commands take priority
over navigation commands.

### 20.4 Navigation stop behavior

After Nav2 stops publishing fresh commands, the navigation source expires
after 0.50 seconds. The command multiplexer then publishes zero velocity and
sets the active source to `none`, unless another valid higher-priority source
is active.

The goal manager itself does not directly publish the stop command.

---

## 21. Nav2 Frame Architecture

The `v0.1.0` navigation configuration is intentionally described precisely
because it is not a conventional all-map-frame Nav2 configuration.

### 21.1 Global localization

AMCL uses:

```text
global_frame_id: map
odom_frame_id: odom
base_frame_id: base_link
```

Navigation goals are sent in:

```text
map
```

### 21.2 Costmap and controller frames

The tagged Nav2 parameter file configures the relevant Nav2 costmaps and
controller-side global-frame settings as:

```text
global_frame: odom
robot_base_frame: base_link
```

### 21.3 Hybrid frame design

The release therefore combines:

```text
map-frame AMCL localization
map-frame NavigateToPose goals
map -> odom correction from AMCL
odom-frame Nav2 costmaps and controller configuration
```

This is a hybrid `v0.1.0` design, not a conventional fully map-frame global
costmap architecture.

The system was validated operationally, but further frame and navigation
parameter refinement is appropriate for later releases.

---

## 22. Principal TF Ownership

```text
map
  |
  v
odom
  |
  v
base_link
  |
  +-- left_wheel_link
  +-- right_wheel_link
  +-- caster_link
  +-- lidar_link
```

| TF edge | Manual | Mapping | Localization | Navigation |
|---|---|---|---|---|
| `map -> odom` | not required | SLAM Toolbox | AMCL | AMCL |
| `odom -> base_link` | `diff_drive_controller` | `diff_drive_controller` | `diff_drive_controller` | `diff_drive_controller` |
| `base_link -> robot links` | `robot_state_publisher` | `robot_state_publisher` | `robot_state_publisher` | `robot_state_publisher` |

The scan launch paths also publish a compatibility transform between
`lidar_link` and the Gazebo-generated LiDAR frame.

Duplicate publishers for one TF edge must be avoided.

---

## 23. Safety Architecture

### 23.1 Environment validation

Only configured environment names and world files are accepted.

### 23.2 Mode transition validation

Modes require a running simulation. Localization and Navigation additionally
require a selected map.

### 23.3 Map-path validation

Map names and resolved paths are constrained to the managed map root.

### 23.4 Navigation request validation

Navigation JSON, numeric fields, active state, and action-server readiness
are validated before a goal is sent.

### 23.5 Finite-command validation

The command mux rejects non-finite velocity commands.

### 23.6 Velocity clamping

The command mux limits supported linear and angular velocities.

### 23.7 Source freshness

Each command source must continue publishing within its configured timeout.

### 23.8 Priority arbitration

Only the highest-priority fresh source is forwarded.

### 23.9 Emergency-stop override

Emergency stop forces zero output regardless of source state.

### 23.10 No-source stop

When no fresh source exists, the command mux continuously publishes zero
velocity.

---

## 24. Process-Lifecycle Architecture

There are three distinct process-management layers.

### 24.1 Dashboard-launch layer

`web_interface.launch.py`:

```text
enforces one dashboard instance
removes stale project processes at startup
owns dashboard server, rosbridge, and manager-node launch
```

### 24.2 Simulation layer

`simulation_manager_node.py`:

```text
owns interactive_control.launch.py
owns the selected Gazebo world and core robot runtime
tracks a simulation process group
handles stop, reset, unexpected exit, SIGTERM, and SIGKILL
```

### 24.3 Mode layer

`mode_manager_node.py`:

```text
owns SLAM, localization, or navigation launch process groups
stops the previous mode before activating another
terminates remaining descendant processes when required
```

These layers should not be collapsed into one generic “process manager”
because they have different scopes and responsibilities.

---

## 25. Build, Docker, and CI Architecture

### 25.1 Native build

The native build uses ROS 2 Jazzy and `colcon` from `ros2_ws`.

### 25.2 Docker image

The Dockerfile creates an Ubuntu 24.04 / ROS 2 Jazzy development and test
image.

During image creation it:

```text
installs ROS 2 and build dependencies
resolves package dependencies with rosdep
creates a non-root development user
copies the repository
runs source syntax checks
builds the ROS 2 package with testing enabled
sources ROS and the workspace in interactive shells
```

The default container command is:

```text
/bin/bash
```

The Docker image is the supported clean build-and-test environment for
`v0.1.0`.

It is not packaged as a complete graphical Gazebo runtime entrypoint.
Graphical simulation is normally run natively on the host.

### 25.3 GitHub Actions

The ROS 2 Jazzy workflow performs native validation and a separate Docker
build-and-test job.

---

## 26. Validation Architecture

The tagged package registers:

```text
test_navigation_goal_validation
test_map_name_validation
test_environment_validation
test_localization_environment_switch
test_mode_transition_rules
test_command_mux_safety
test_safe_map_path_resolution
test_core_math
ament lint tests
```

Repository-level integration validation additionally includes:

```text
source syntax checks
simulator launch regression
headless dashboard integration
public launcher lifecycle validation
Docker full test execution
Docker cleanup verification
```

The validated `v0.1.0` release gate reported:

```text
357 tests
0 errors
0 failures
0 skipped
```

The test-count statement is a release-gate result tied to release commit:

```text
28a080e72ee6e31baa25bcd2fdaa249706520361
```

It should not be interpreted as a guarantee that every future branch will
always register the same number of tests.

---

## 27. Observability

The platform exposes state through:

```text
dashboard status panels
manager status topics
navigation feedback topics
active command-source topic
ROS 2 node, topic, service, and action inspection
TF inspection
controller inspection
lifecycle inspection
process and port checks
test output
GitHub Actions
```

Representative commands:

```bash
ros2 node list
ros2 topic list
ros2 service list
ros2 action list
ros2 control list_controllers
ros2 lifecycle get /amcl
ros2 lifecycle get /planner_server
ros2 run tf2_ros tf2_echo map base_link
ss -ltnp | grep -E ':8080|:9090'
```

Operational troubleshooting belongs in
`docs/debugging_and_validation.md`.

---

## 28. Data and Generated State

### Saved maps

```text
~/.ros/cpp_robotics_sim/maps/<environment>/
```

### ROS 2 workspace output

```text
ros2_ws/build/
ros2_ws/install/
ros2_ws/log/
```

### Other generated evidence

Depending on the workflow:

```text
bags/
data/
plots/
screenshots/
videos/
```

Generated artifacts remain outside version control unless deliberately
selected as small documentation evidence.

---

## 29. Known Limitations

Release `v0.1.0` is a validated simulation platform, not a production robot
fleet or hardware deployment system.

Current limitations include:

```text
RViz is not embedded in the browser dashboard
Nav2 costmaps use odom-frame configuration
navigation tuning is not final
initial-pose completion is not enforced as a goal-submission invariant
gamepad input is configured but not part of the completed public feature set
planner and controller selection is configuration-file based
parameter tuning is configuration-file based
custom robots are not dynamically imported through the dashboard
custom worlds require configuration changes
hosted CI does not run full graphical Gazebo scenarios
automatic kidnapped-robot recovery is not implemented
hardware deployment is outside scope
multi-robot operation is outside scope
```

These are explicit release boundaries.

---

## 30. Planned Architectural Direction

Post-`v0.1.0` work may include:

```text
navigation controller and costmap tuning
cleaner map-frame Nav2 configuration
dashboard parameter editing
selectable planners and controllers
richer visualization integration
custom robot and world selection
scenario orchestration
repeatable navigation benchmarks
automated parameter sweeps
rosbag replay regression
dynamic-obstacle scenarios
sensor and physics noise sweeps
simulation-to-hardware workflows
gamepad integration
```

Future work should preserve:

```text
clear component ownership
safe command arbitration
mode mutual exclusion
environment-aware data
validated paths
managed shutdown
reproducible tests
observable state
```

---

## 31. Architecture Summary

```text
Browser dashboard
    |
    | /cmd_vel/gui, services, request topics
    v
rosbridge and manager nodes
    |
    +--> simulation_manager
    |      -> interactive_control.launch.py
    |      -> Gazebo + ros2_control + command_mux
    |
    +--> mode_manager
    |      -> SLAM, AMCL, or Nav2 launch process
    |
    +--> mapping_manager
    |      -> safe environment-aware map persistence
    |
    +--> localization_manager
    |      -> map selection and /initialpose
    |
    +--> navigation_goal_manager
           -> NavigateToPose action

Velocity sources
    |
    +--> /cmd_vel/gamepad
    +--> /cmd_vel/keyboard
    +--> /cmd_vel/gui
    +--> /cmd_vel/navigation
           |
           v
       command_mux
           |
           v
/diff_drive_controller/cmd_vel
           |
           v
diff_drive_controller
           |
           v
Gazebo differential-drive robot
```

Localization TF chain:

```text
map -> odom -> base_link
```

Navigation frame design:

```text
map-frame AMCL and goals
odom-frame Nav2 costmaps and controller configuration
```

---

## 32. Interview-Level Explanation

This project is a browser-controlled ROS 2 mobile-robot simulation platform
built on Gazebo Harmonic.

The dashboard is served over HTTP and communicates with ROS 2 through
rosbridge. A simulation manager launches and supervises the selected
Warehouse or Hospital environment. A separate mode manager enforces mutual
exclusion between Manual, Mapping, Localization, and Navigation modes and
owns the process group for each mode-specific launch.

The robot is modeled with Xacro and controlled through `gz_ros2_control`,
`controller_manager`, and `diff_drive_controller`. A command multiplexer
receives gamepad, terminal-keyboard, browser GUI, and navigation velocity
sources, checks freshness and finite values, applies priorities and velocity
limits, implements emergency-stop override, and publishes the final
`TwistStamped` command to the differential-drive controller.

SLAM Toolbox owns `map -> odom` during mapping. AMCL owns `map -> odom`
during localization and navigation. The differential-drive controller owns
`odom -> base_link`, and `robot_state_publisher` owns transforms below
`base_link`.

Navigation goals are created in the map frame. The `v0.1.0` Nav2
configuration uses AMCL for global map localization while keeping Nav2
costmaps and controller-side global-frame settings in `odom`, making it a
hybrid first-release navigation architecture.

The release includes environment-aware map storage, safe map-path
resolution, managed process-group shutdown, action-goal validation,
command-source arbitration, emergency stop, native and Docker validation,
GitHub Actions CI, and a release gate that reported 357 passing tests with
no failures, errors, or skipped tests.

---

<!-- RELEASE_MEDIA_START -->
## Release Media

- [Project teaser](https://www.youtube.com/watch?v=zKf_hjIYtlk)
- [Complete v0.1.0 demonstration playlist](https://www.youtube.com/playlist?list=PLP_aJnUqSRf8)
- [Installation and first launch](https://www.youtube.com/watch?v=_x2Z7jXXnWw)
- [Docker build and 357-test validation](https://www.youtube.com/watch?v=4M628CFYiz8)

Release screenshots are stored in [`docs/media/v0.1.0`](media/v0.1.0).
<!-- RELEASE_MEDIA_END -->
