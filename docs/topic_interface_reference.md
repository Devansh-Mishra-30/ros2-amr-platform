# Topic and Interface Reference

## C++ / ROS 2 Robotics Simulation Foundation

**Release:** `v0.1.0`
**Release commit:** `28a080e72ee6e31baa25bcd2fdaa249706520361`
**Primary package:** `cpp_robotics_sim_ros`
**Primary platform:** Ubuntu 24.04, ROS 2 Jazzy, Gazebo Harmonic

---

## 1. Document Purpose

This document defines the public runtime interface contract for
`cpp_robotics_sim_foundation` at release `v0.1.0`.

It covers:

- dashboard-facing ROS 2 topics and services;
- simulation, mode, mapping, localization, and navigation manager interfaces;
- command-source topics and arbitration rules;
- Nav2 actions and internal command topics;
- robot, sensor, controller, map, localization, and TF interfaces;
- message types;
- payload formats;
- ownership rules;
- state values;
- validation commands;
- important implementation constraints.

This document describes the tagged `v0.1.0` implementation. It does not
describe uncommitted `v0.2.0` changes.

---

## 2. Interface Conventions

### 2.1 Naming

Manager-facing interfaces use namespaces such as:

```text
/simulation/*
/mode/*
/mapping/*
/localization/*
/navigation/*
/control/*
```

Robot and autonomy interfaces use standard ROS 2 names such as:

```text
/scan
/map
/amcl_pose
/initialpose
/tf
/tf_static
/navigate_to_pose
/diff_drive_controller/*
```

### 2.2 Dashboard transport

The browser communicates with ROS 2 through rosbridge.

Default endpoints:

```text
Dashboard HTTP: http://localhost:8080
rosbridge WebSocket: ws://localhost:9090
```

### 2.3 JSON-over-String interfaces

Several manager interfaces use:

```text
std_msgs/msg/String
```

with JSON encoded in the `data` field.

Unless stated otherwise:

- JSON payloads must be valid JSON;
- request payloads must contain the required fields;
- state and status payloads are published as compact JSON objects;
- malformed payloads are rejected or ignored without crashing the manager.

### 2.4 Service type

All public simulation and mode services use:

```text
std_srvs/srv/Trigger
```

The service response contains:

```text
bool success
string message
```

---

## 3. High-Level Interface Map

```text
Browser Dashboard
    |
    +--> /simulation/environment_request
    +--> /simulation/start
    +--> /simulation/stop
    +--> /simulation/reset
    |
    +--> /mode/manual
    +--> /mode/mapping
    +--> /mode/localization
    +--> /mode/navigation
    +--> /mode/stop
    |
    +--> /cmd_vel/gui
    +--> /control/emergency_stop
    |
    +--> /mapping/save_request
    |
    +--> /localization/select_map_request
    +--> /localization/initial_pose_request
    |
    +--> /navigation/goal_request
    +--> /navigation/cancel_request
    |
    v
ROS 2 Managers and Command Mux
    |
    +--> status topics
    +--> mode-specific launch files
    +--> /navigate_to_pose action
    +--> /diff_drive_controller/cmd_vel
```

---

## 4. Dashboard-Facing Interface Summary

### 4.1 Topics

| Interface | Type | Direction relative to dashboard | Purpose |
|---|---|---|---|
| `/simulation/status` | `std_msgs/msg/String` | Subscribe | High-level simulation state |
| `/simulation/environment_status` | `std_msgs/msg/String` | Subscribe | Selected environment, world, lock state, and message |
| `/simulation/environment_request` | `std_msgs/msg/String` | Publish | Request `warehouse` or `hospital` |
| `/mode/status` | `std_msgs/msg/String` | Subscribe | Active operating-mode state |
| `/cmd_vel/gui` | `geometry_msgs/msg/TwistStamped` | Publish | Browser buttons and browser-keyboard velocity commands |
| `/control/emergency_stop` | `std_msgs/msg/Bool` | Publish | Engage or release emergency stop |
| `/control/active_source` | `std_msgs/msg/String` | Subscribe | Current command source selected by command mux |
| `/mapping/save_request` | `std_msgs/msg/String` | Publish | Request map save by map name |
| `/mapping/save_status` | `std_msgs/msg/String` | Subscribe | JSON map-save result |
| `/mapping/saved_maps` | `std_msgs/msg/String` | Subscribe | JSON saved-map inventory |
| `/localization/select_map_request` | `std_msgs/msg/String` | Publish | Select a saved map |
| `/localization/initial_pose_request` | `std_msgs/msg/String` | Publish | Request publication of `/initialpose` |
| `/localization/selected_map` | `std_msgs/msg/String` | Subscribe | JSON selected-map metadata |
| `/localization/status` | `std_msgs/msg/String` | Subscribe | JSON localization-manager status |
| `/navigation/goal_request` | `std_msgs/msg/String` | Publish | JSON map-frame goal request |
| `/navigation/cancel_request` | `std_msgs/msg/String` | Publish | JSON goal-cancellation request |
| `/navigation/status` | `std_msgs/msg/String` | Subscribe | JSON goal state and final result |
| `/navigation/feedback` | `std_msgs/msg/String` | Subscribe | JSON navigation-progress feedback |

### 4.2 Services

| Interface | Type | Purpose |
|---|---|---|
| `/simulation/start` | `std_srvs/srv/Trigger` | Start selected environment |
| `/simulation/stop` | `std_srvs/srv/Trigger` | Stop managed simulation |
| `/simulation/reset` | `std_srvs/srv/Trigger` | Stop and restart selected environment |
| `/mode/manual` | `std_srvs/srv/Trigger` | Activate Manual mode |
| `/mode/mapping` | `std_srvs/srv/Trigger` | Start Mapping mode |
| `/mode/localization` | `std_srvs/srv/Trigger` | Start Localization mode |
| `/mode/navigation` | `std_srvs/srv/Trigger` | Start Navigation mode |
| `/mode/stop` | `std_srvs/srv/Trigger` | Stop active mode |

---

## 5. Simulation Manager Interfaces

Node:

```text
/simulation_manager
```

### 5.1 `/simulation/status`

Type:

```text
std_msgs/msg/String
```

Producer:

```text
simulation_manager
```

Purpose:

```text
Publish the current simulation lifecycle state.
```

Defined state values:

```text
stopped
starting
running
stopping
error
```

Example:

```text
running
```

Validation:

```bash
ros2 topic echo /simulation/status
```

### 5.2 `/simulation/environment_status`

Type:

```text
std_msgs/msg/String
```

Producer:

```text
simulation_manager
```

Payload:

```json
{
  "state": "selected",
  "message": "Selected environment: hospital",
  "selected_environment": "hospital",
  "available_environments": [
    "warehouse",
    "hospital"
  ],
  "world_file": "hospital_world.sdf",
  "selection_locked": false
}
```

Defined `state` values used by the environment-status publisher are:

```text
ready
selected
locked
invalid_request
running
error
```

Fields:

| Field | Type | Meaning |
|---|---|---|
| `state` | string | Environment-status category |
| `message` | string | Human-readable status |
| `selected_environment` | string | Current environment identifier |
| `available_environments` | array[string] | Supported environment identifiers |
| `world_file` | string | SDF filename associated with selection |
| `selection_locked` | boolean | Whether selection changes are currently blocked |

Validation:

```bash
ros2 topic echo /simulation/environment_status
```

### 5.3 `/simulation/environment_request`

Type:

```text
std_msgs/msg/String
```

Consumer:

```text
simulation_manager
```

Accepted values:

```text
warehouse
hospital
```

Example:

```bash
ros2 topic pub --once \
  /simulation/environment_request \
  std_msgs/msg/String \
  "{data: hospital}"
```

Rejection rules:

```text
empty request
unsupported environment
simulation starting
simulation running
simulation stopping
managed simulation process still alive
```

### 5.4 `/simulation/start`

Type:

```text
std_srvs/srv/Trigger
```

Behavior:

```text
Resolve the selected world.
Launch interactive_control.launch.py.
Start the process in a new operating-system session.
Publish starting, then running or error.
```

Command:

```bash
ros2 service call \
  /simulation/start \
  std_srvs/srv/Trigger \
  "{}"
```

### 5.5 `/simulation/stop`

Type:

```text
std_srvs/srv/Trigger
```

Behavior:

```text
Stop the managed simulation process group.
Verify its persisted process and session identity before signaling.
Attempt SIGINT first.
Use bounded SIGTERM, then SIGKILL escalation if required.
Publish stopping, then stopped or error.
Persist a structured shutdown report even if ROS publishing is unavailable.
```

Command:

```bash
ros2 service call \
  /simulation/stop \
  std_srvs/srv/Trigger \
  "{}"
```

### 5.6 `/simulation/reset`

Type:

```text
std_srvs/srv/Trigger
```

Behavior:

```text
Stop the current simulation.
Wait briefly.
Start the currently selected environment again.
```

Command:

```bash
ros2 service call \
  /simulation/reset \
  std_srvs/srv/Trigger \
  "{}"
```

---

## 6. Mode Manager Interfaces

Node:

```text
/mode_manager
```

### 6.1 `/mode/status`

Type:

```text
std_msgs/msg/String
```

Producer:

```text
mode_manager
```

Defined mode values:

```text
stopped
starting
manual
mapping
localization
navigation
error
```

Validation:

```bash
ros2 topic echo /mode/status
```

### 6.2 Mode services

All mode services use:

```text
std_srvs/srv/Trigger
```

Commands:

```bash
ros2 service call /mode/manual std_srvs/srv/Trigger "{}"
ros2 service call /mode/mapping std_srvs/srv/Trigger "{}"
ros2 service call /mode/localization std_srvs/srv/Trigger "{}"
ros2 service call /mode/navigation std_srvs/srv/Trigger "{}"
ros2 service call /mode/stop std_srvs/srv/Trigger "{}"
```

### 6.3 Mode prerequisites

All operating modes require:

```text
/simulation/status == running
```

Localization and Navigation additionally require:

```text
a non-empty selected map YAML path
```

The mode manager does not enforce proof that an initial pose has already been
published.

### 6.4 Mode launch ownership

```text
Manual:
  no separate launch process

Mapping:
  slam_mapping.launch.py

Localization:
  amcl_localization.launch.py

Navigation:
  nav2_navigation.launch.py
```

---

## 7. Command Source Interfaces

Node:

```text
/command_mux
```

### 7.1 Source summary

| Source | Topic | Type | Priority | Timeout |
|---|---|---|---:|---:|
| Gamepad | `/cmd_vel/gamepad` | `geometry_msgs/msg/TwistStamped` | 100 | 0.50 s |
| Terminal keyboard | `/cmd_vel/keyboard` | `geometry_msgs/msg/TwistStamped` | 90 | 0.50 s |
| Browser GUI and browser keyboard | `/cmd_vel/gui` | `geometry_msgs/msg/TwistStamped` | 80 | 0.75 s |
| Navigation | `/cmd_vel/navigation` | `geometry_msgs/msg/TwistStamped` | 50 | 0.50 s |

Configured publish rate:

```text
20 Hz
```

Configured limits:

```text
max linear.x: 0.30 m/s
max angular.z: 1.00 rad/s
```

### 7.2 `/cmd_vel/gui`

Type:

```text
geometry_msgs/msg/TwistStamped
```

Producers:

```text
browser drive buttons
browser keyboard handlers
```

Consumer:

```text
command_mux
```

Used components:

```text
twist.linear.x
twist.angular.z
```

Example:

```bash
ros2 topic pub -r 10 \
  /cmd_vel/gui \
  geometry_msgs/msg/TwistStamped \
  "{
    header: {frame_id: base_link},
    twist: {
      linear: {x: 0.15},
      angular: {z: 0.0}
    }
  }"
```

### 7.3 `/cmd_vel/keyboard`

Type:

```text
geometry_msgs/msg/TwistStamped
```

Producer:

```text
keyboard_teleop_node.py
```

Consumer:

```text
command_mux
```

This topic is for the optional terminal keyboard node. Browser keyboard
events do not publish here.

### 7.4 `/cmd_vel/gamepad`

Type:

```text
geometry_msgs/msg/TwistStamped
```

Consumer:

```text
command_mux
```

The source is configured in `v0.1.0`, but completed PS4/gamepad support is
outside the public release feature scope.

### 7.5 `/cmd_vel/navigation`

Type:

```text
geometry_msgs/msg/TwistStamped
```

Producer:

```text
cmd_vel_twist_bridge
```

Consumer:

```text
command_mux
```

The bridge converts Nav2's unstamped `Twist` output into this stamped command
source.

### 7.6 `/diff_drive_controller/cmd_vel`

Type:

```text
geometry_msgs/msg/TwistStamped
```

Producer:

```text
command_mux
```

Consumer:

```text
diff_drive_controller
```

This is the final velocity-command interface to the robot controller.

### 7.7 `/control/active_source`

Type:

```text
std_msgs/msg/String
```

Producer:

```text
command_mux
```

Known values:

```text
gamepad
keyboard
gui
navigation
emergency_stop
none
```

Validation:

```bash
ros2 topic echo /control/active_source
```

### 7.8 `/control/emergency_stop`

Type:

```text
std_msgs/msg/Bool
```

Producer:

```text
dashboard or another safety client
```

Consumer:

```text
command_mux
```

Behavior:

```text
true:
  publish zero velocity
  ignore all command sources
  publish active source emergency_stop

false:
  release emergency-stop override
  resume normal source arbitration
```

Commands:

```bash
ros2 topic pub --once \
  /control/emergency_stop \
  std_msgs/msg/Bool \
  "{data: true}"

ros2 topic pub --once \
  /control/emergency_stop \
  std_msgs/msg/Bool \
  "{data: false}"
```

### 7.9 Command validity

The mux rejects a command if any Twist component is non-finite.

When a valid source is selected, the mux:

```text
clamps linear.x
clamps angular.z
clears unsupported linear and angular components
re-stamps the outgoing command
uses frame_id base_link
```

If no source remains fresh, the mux publishes zero velocity and reports
`none`.

---

## 8. Mapping Manager Interfaces

Node:

```text
/mapping_manager
```

### 8.1 `/mapping/save_request`

Type:

```text
std_msgs/msg/String
```

Consumer:

```text
mapping_manager
```

Payload:

```text
A requested map name in message.data.
```

Example:

```bash
ros2 topic pub --once \
  /mapping/save_request \
  std_msgs/msg/String \
  "{data: hospital_main}"
```

Prerequisites:

```text
simulation environment selected
mapping mode active
non-empty valid map name
```

### 8.2 `/mapping/save_status`

Type:

```text
std_msgs/msg/String
```

Producer:

```text
mapping_manager
```

Representative payload:

```json
{
  "status": "success",
  "message": "Map 'hospital_main' saved successfully for hospital",
  "map_name": "hospital_main",
  "environment": "hospital",
  "yaml_path": "/home/user/.ros/cpp_robotics_sim/maps/hospital/hospital_main.yaml",
  "image_path": "/home/user/.ros/cpp_robotics_sim/maps/hospital/hospital_main.pgm"
}
```

Important fields:

| Field | Type | Meaning |
|---|---|---|
| `status` | string | Save lifecycle or result |
| `message` | string | Human-readable result |
| `map_name` | string | Requested map name |
| `environment` | string | Associated simulation environment |
| `yaml_path` | string | Resolved YAML path |
| `image_path` | string | Resolved PGM path |

### 8.3 `/mapping/saved_maps`

Type:

```text
std_msgs/msg/String
```

Producer:

```text
mapping_manager
```

Payload:

```text
A JSON array of saved-map objects under the managed map root.
```

Representative map entry:

```json
{
  "name": "hospital_main",
  "environment": "hospital",
  "legacy": false,
  "yaml_path": "/home/user/.ros/cpp_robotics_sim/maps/hospital/hospital_main.yaml",
  "image_path": "/home/user/.ros/cpp_robotics_sim/maps/hospital/hospital_main.pgm",
  "complete": true
}
```

The outer payload is a JSON array. Each entry includes `name`,
`environment`, `legacy`, `yaml_path`, `image_path`, and `complete`.

### 8.4 Map storage

Managed root:

```text
~/.ros/cpp_robotics_sim/maps
```

Environment-aware layout:

```text
~/.ros/cpp_robotics_sim/maps/<environment>/<map_name>.yaml
~/.ros/cpp_robotics_sim/maps/<environment>/<map_name>.pgm
```

The mapping manager invokes:

```text
nav2_map_server map_saver_cli
```

A map is considered complete only when both files exist.

---

## 9. SLAM Toolbox Interfaces

Primary node:

```text
/slam_toolbox
```

Launch:

```text
slam_mapping.launch.py
```

### 9.1 Inputs

```text
/scan
/tf
/tf_static
```

Supporting odometry and TF:

```text
/diff_drive_controller/odom
odom -> base_link
```

### 9.2 Outputs

```text
/map
/map_metadata
map -> odom
```

### 9.3 Core types

| Interface | Type |
|---|---|
| `/scan` | `sensor_msgs/msg/LaserScan` |
| `/map` | `nav_msgs/msg/OccupancyGrid` |
| `/map_metadata` | `nav_msgs/msg/MapMetaData` |
| `/tf` | `tf2_msgs/msg/TFMessage` |
| `/tf_static` | `tf2_msgs/msg/TFMessage` |

### 9.4 TF ownership in Mapping mode

```text
SLAM Toolbox:
  map -> odom

diff_drive_controller:
  odom -> base_link

robot_state_publisher:
  base_link -> robot links and sensors
```

---

## 10. Localization Manager Interfaces

Node:

```text
/localization_manager
```

### 10.1 `/localization/select_map_request`

Type:

```text
std_msgs/msg/String
```

Consumer:

```text
localization_manager
```

Accepted request forms include a plain map name or a JSON object.

Plain-name example:

```text
hospital_main
```

JSON example:

```json
{
  "name": "hospital_main",
  "environment": "hospital"
}
```

The manager prefers:

```text
~/.ros/cpp_robotics_sim/maps/<environment>/<name>.yaml
```

It also recognizes the legacy root-level map location supported by
`v0.1.0`.

### 10.2 `/localization/selected_map`

Type:

```text
std_msgs/msg/String
```

Producer:

```text
localization_manager
```

Payload:

```json
{
  "name": "hospital_main",
  "environment": "hospital",
  "yaml_path": "/home/user/.ros/cpp_robotics_sim/maps/hospital/hospital_main.yaml"
}
```

An empty selection is represented through empty field values.

Environment changes clear a selected map when it belongs to a different
environment.

### 10.3 `/localization/initial_pose_request`

Type:

```text
std_msgs/msg/String
```

Consumer:

```text
localization_manager
```

Required pose fields:

```text
x
y
yaw
```

Representative request:

```json
{
  "x": 0.0,
  "y": 0.0,
  "yaw": 0.0
}
```

A selected map is required before the request is accepted.

### 10.4 `/initialpose`

Type:

```text
geometry_msgs/msg/PoseWithCovarianceStamped
```

Producer:

```text
localization_manager
```

Consumer:

```text
AMCL
```

Frame:

```text
map
```

The manager converts yaw into a quaternion and publishes a covariance-bearing
initial hypothesis.

### 10.5 `/localization/status`

Type:

```text
std_msgs/msg/String
```

Producer:

```text
localization_manager
```

Payload fields are:

```text
status
message
map_name
environment
yaml_path
```

---

## 11. AMCL and Map Server Interfaces

Localization launch:

```text
amcl_localization.launch.py
```

Navigation localization is included through Nav2's localization launch.

### 11.1 `/map`

Type:

```text
nav_msgs/msg/OccupancyGrid
```

Producer:

```text
map_server
```

Consumers:

```text
AMCL
Nav2 planning and costmap components
dashboard visualization
```

### 11.2 `/amcl_pose`

Type:

```text
geometry_msgs/msg/PoseWithCovarianceStamped
```

Producer:

```text
AMCL
```

Purpose:

```text
Current map-frame AMCL pose estimate.
```

### 11.3 `/particle_cloud`

Producer:

```text
AMCL
```

Purpose:

```text
Particle-filter hypothesis visualization and inspection.
```

On ROS 2 Jazzy, confirm the active type at runtime with:

```bash
ros2 topic type /particle_cloud
```

The project does not define a custom particle-cloud message type.

### 11.4 AMCL inputs

```text
/map
/scan
/tf
/tf_static
/initialpose
```

### 11.5 AMCL transform

AMCL owns:

```text
map -> odom
```

during Localization and Navigation modes.

---

## 12. Navigation Manager Interfaces

Node:

```text
/navigation_goal_manager
```

### 12.1 `/navigation/goal_request`

Type:

```text
std_msgs/msg/String
```

Consumer:

```text
navigation_goal_manager
```

Required JSON:

```json
{
  "x": 1.0,
  "y": 0.0,
  "yaw": 0.0
}
```

Fields:

| Field | Type | Meaning |
|---|---|---|
| `x` | finite number | Goal x coordinate |
| `y` | finite number | Goal y coordinate |
| `yaw` | finite number | Goal heading in radians |

Action goal frame:

```text
map
```

Rejection conditions:

```text
invalid JSON
non-object JSON
missing x, y, or yaw
non-numeric or non-finite value
simulation not running
mode not navigation
another goal active
NavigateToPose server unavailable
action server rejects goal
```

### 12.2 `/navigation/cancel_request`

Type:

```text
std_msgs/msg/String
```

Consumer:

```text
navigation_goal_manager
```

Required payload:

```json
{
  "cancel": true
}
```

Any other value is rejected.

### 12.3 `/navigation/status`

Type:

```text
std_msgs/msg/String
```

Producer:

```text
navigation_goal_manager
```

Payload structure:

```json
{
  "state": "succeeded",
  "message": "Navigation goal succeeded",
  "result": "succeeded",
  "goal_active": false,
  "goal": {
    "x": 1.0,
    "y": 0.0,
    "yaw": 0.0
  },
  "feedback": {},
  "nav2_error_code": 0,
  "nav2_error_message": ""
}
```

Defined state values used by the navigation manager include:

```text
ready
idle
inactive
invalid_request
rejected
waiting_for_server
server_unavailable
sending
accepted
navigating
cancel_pending
canceling
succeeded
canceled
aborted
```

### 12.4 `/navigation/feedback`

Type:

```text
std_msgs/msg/String
```

Producer:

```text
navigation_goal_manager
```

Representative feedback fields:

```text
state
message
goal
distance_remaining
estimated_time_remaining
navigation_time
recovery_count
```

Not every field is guaranteed to be present in every message.

### 12.5 Goal state ownership

The manager tracks one goal at a time.

Internal state includes:

```text
request sequence
current request identifier
current goal
active action goal handle
goal request in progress
cancel requested
last feedback
```

---

## 13. Nav2 Action Interface

### 13.1 `/navigate_to_pose`

Type:

```text
nav2_msgs/action/NavigateToPose
```

Action server owner:

```text
bt_navigator
```

Action client:

```text
navigation_goal_manager
```

Goal frame:

```text
map
```

Validation:

```bash
ros2 action info /navigate_to_pose
```

Direct CLI example:

```bash
ros2 action send_goal --feedback \
  /navigate_to_pose \
  nav2_msgs/action/NavigateToPose \
  "{
    pose: {
      header: {frame_id: map},
      pose: {
        position: {x: 1.0, y: 0.0, z: 0.0},
        orientation: {z: 0.0, w: 1.0}
      }
    },
    behavior_tree: ''
  }"
```

The dashboard should normally use `/navigation/goal_request` rather than
constructing the action directly.

---

## 14. Nav2 Internal Command Interfaces

Navigation launch:

```text
nav2_navigation.launch.py
```

### 14.1 `/cmd_vel_nav_raw`

Type:

```text
geometry_msgs/msg/Twist
```

Producers:

```text
controller_server
behavior_server
```

Consumer:

```text
velocity_smoother
```

The servers remap their standard `/cmd_vel` output to this topic.

### 14.2 `/cmd_vel`

Type:

```text
geometry_msgs/msg/Twist
```

Producer:

```text
velocity_smoother
```

Consumer:

```text
cmd_vel_twist_bridge
```

The velocity smoother remaps:

```text
/cmd_vel_smoothed -> /cmd_vel
```

### 14.3 Bridge conversion

Node:

```text
/cmd_vel_twist_bridge
```

Input:

```text
/cmd_vel
geometry_msgs/msg/Twist
```

Output:

```text
/cmd_vel/navigation
geometry_msgs/msg/TwistStamped
```

Frame:

```text
base_link
```

### 14.4 Exact navigation command path

```text
controller_server or behavior_server
  -> /cmd_vel_nav_raw
  -> velocity_smoother
  -> /cmd_vel
  -> cmd_vel_twist_bridge
  -> /cmd_vel/navigation
  -> command_mux
  -> /diff_drive_controller/cmd_vel
  -> diff_drive_controller
```

---

## 15. Nav2 Planning and Costmap Interfaces

### 15.1 Actions

The active Nav2 stack exposes actions according to the launched Nav2 servers. Verify the exact runtime set with:

```text
/compute_path_to_pose
/compute_path_through_poses
/follow_path
/navigate_to_pose
/navigate_through_poses
```

Confirm the active set at runtime:

```bash
ros2 action list -t | sort
```

### 15.2 Costmap topics

Representative interfaces:

```text
/local_costmap/costmap
/local_costmap/costmap_updates
/local_costmap/published_footprint
/global_costmap/costmap
/global_costmap/costmap_updates
/global_costmap/published_footprint
```

Common types:

| Interface | Type |
|---|---|
| `*/costmap` | `nav_msgs/msg/OccupancyGrid` |
| `*/costmap_updates` | `map_msgs/msg/OccupancyGridUpdate` |
| `*/published_footprint` | `geometry_msgs/msg/PolygonStamped` |

### 15.3 Frame configuration

AMCL:

```text
global_frame_id: map
odom_frame_id: odom
base_frame_id: base_link
```

Tagged Nav2 costmap/controller configuration:

```text
global_frame: odom
robot_base_frame: base_link
odom_topic: /diff_drive_controller/odom
```

Therefore `v0.1.0` uses:

```text
map-frame AMCL localization
map-frame NavigateToPose goals
odom-frame Nav2 costmaps and controller-side global-frame settings
```

This hybrid frame design is intentional documentation of the actual release.

---

## 16. Robot and Controller Interfaces

### 16.1 `/diff_drive_controller/odom`

Type:

```text
nav_msgs/msg/Odometry
```

Producer:

```text
diff_drive_controller
```

Expected frames:

```text
header.frame_id: odom
child_frame_id: base_link
```

Consumers include:

```text
Nav2
validation tools
debugging tools
optional localization experiments
```

### 16.2 Controller-limited command output

The controller configuration enables:

```text
publish_limited_velocity: true
```

Confirm the exact runtime topic name and type with:

```bash
ros2 topic list | grep diff_drive_controller
ros2 topic type /diff_drive_controller/cmd_vel_out
```

The project configuration enables this output, but the topic name should be
validated at runtime rather than treated as a dashboard-facing contract.

### 16.3 `/joint_states`

Type:

```text
sensor_msgs/msg/JointState
```

Producer:

```text
joint_state_broadcaster
```

Consumer:

```text
robot_state_publisher
```

### 16.4 Dynamic joint-state output

`joint_state_broadcaster` can expose detailed joint-interface state depending
on its runtime configuration. Confirm the exact topic name and type with:

```bash
ros2 topic list | grep joint
```

`/joint_states` is the required project interface. Any dynamic joint-state
topic is diagnostic rather than part of the public dashboard contract.

### 16.5 Controller inspection

```bash
ros2 control list_controllers
ros2 control list_hardware_interfaces
```

Expected active controllers:

```text
joint_state_broadcaster
diff_drive_controller
```

---

## 17. Sensor and Simulation-Time Interfaces

### 17.1 `/scan`

Type:

```text
sensor_msgs/msg/LaserScan
```

Producer:

```text
Gazebo LiDAR through ros_gz_bridge
```

Consumers:

```text
SLAM Toolbox
AMCL
Nav2 costmaps
dashboard visualization
RViz and debugging tools
```

Validation:

```bash
ros2 topic type /scan
ros2 topic echo /scan --once
```

### 17.2 `/clock`

Type:

```text
rosgraph_msgs/msg/Clock
```

Producer:

```text
Gazebo through ros_gz_bridge
```

Consumers:

```text
nodes configured with use_sim_time: true
```

Validation:

```bash
ros2 topic echo /clock --once
```

### 17.3 LiDAR frame compatibility

The mapping, localization, and navigation launches include a static
compatibility transform between:

```text
lidar_link
diffbot/base_link/diffbot_lidar
```

This connects the Gazebo-generated scan frame to the robot TF tree.

---

## 18. TF Interface Contract

### 18.1 Principal chain

```text
map -> odom -> base_link -> robot links and sensors
```

### 18.2 Ownership

| Transform | Owner |
|---|---|
| `map -> odom` in Mapping | SLAM Toolbox |
| `map -> odom` in Localization | AMCL |
| `map -> odom` in Navigation | AMCL |
| `odom -> base_link` | `diff_drive_controller` |
| `base_link -> robot links` | `robot_state_publisher` |
| `lidar_link -> Gazebo scan frame` | static transform publisher |

### 18.3 TF topics

```text
/tf
/tf_static
```

Type:

```text
tf2_msgs/msg/TFMessage
```

### 18.4 Validation

```bash
ros2 run tf2_ros tf2_echo map odom
ros2 run tf2_ros tf2_echo odom base_link
ros2 run tf2_ros tf2_echo map base_link
ros2 run tf2_ros tf2_echo base_link lidar_link
```

### 18.5 Duplicate ownership rule

Do not run simultaneous owners of the same edge.

Examples:

```text
SLAM Toolbox and AMCL must not both publish map -> odom.
The custom kinematic simulator and diff_drive_controller must not both
publish odom -> base_link.
```

---

## 19. Node Summary

| Node | Main responsibility | Principal interfaces |
|---|---|---|
| `/simulation_manager` | Simulation and environment lifecycle | `/simulation/*` |
| `/mode_manager` | Mutually exclusive operating modes | `/mode/*`, selected-map and simulation status |
| `/mapping_manager` | Map save and inventory | `/mapping/*` |
| `/localization_manager` | Map selection and initial pose | `/localization/*`, `/initialpose` |
| `/navigation_goal_manager` | JSON-to-Nav2 action bridge | `/navigation/*`, `/navigate_to_pose` |
| `/command_mux` | Velocity arbitration and emergency stop | `/cmd_vel/*`, `/control/*` |
| `/cmd_vel_twist_bridge` | Nav2 Twist to TwistStamped conversion | `/cmd_vel`, `/cmd_vel/navigation` |
| `/robot_state_publisher` | Robot-link TF | `/joint_states`, `/tf`, `/tf_static` |
| `/controller_manager` | ros2_control lifecycle | controller services and hardware interfaces |
| `/joint_state_broadcaster` | Joint-state publication | `/joint_states` and optional diagnostic joint-state interfaces |
| `/diff_drive_controller` | Wheel control and odometry | command, odometry, TF |
| `/slam_toolbox` | Mapping | `/scan`, `/map`, `map -> odom` |
| `/map_server` | Saved occupancy-grid publication | `/map` |
| `/amcl` | Known-map localization | `/amcl_pose`, `map -> odom` |
| `/planner_server` | Nav2 path planning | planning actions and plan topics |
| `/controller_server` | Nav2 path following | `/follow_path`, velocity output |
| `/behavior_server` | Recovery behaviors | behavior actions and velocity output |
| `/bt_navigator` | Nav2 task execution | `/navigate_to_pose`, `/navigate_through_poses` |
| `/waypoint_follower` | Multi-pose missions | waypoint interfaces |
| `/velocity_smoother` | Command smoothing | `/cmd_vel_nav_raw`, `/cmd_vel` |
| `/rosbridge_websocket` | Browser-to-ROS transport | WebSocket port 9090 |

---

## 20. Lifecycle Interfaces

Lifecycle-managed nodes include:

```text
slam_toolbox
map_server
amcl
controller_server
planner_server
behavior_server
bt_navigator
waypoint_follower
velocity_smoother
```

Representative commands:

```bash
ros2 lifecycle get /slam_toolbox
ros2 lifecycle get /map_server
ros2 lifecycle get /amcl
ros2 lifecycle get /planner_server
ros2 lifecycle get /controller_server
ros2 lifecycle get /bt_navigator
```

Expected lifecycle state after successful autostart:

```text
active
```

Lifecycle managers are launched with autostart enabled. The release
configuration uses:

```text
bond_timeout: 0.0
```

for the relevant managed stacks.

---

## 21. File and Configuration Interfaces

### 21.1 Environment registry

```text
ros2_ws/src/cpp_robotics_sim_ros/config/environment_registry.yaml
```

Defines:

```text
default environment
supported environment identifiers
world filenames
```

### 21.2 Command mux configuration

```text
ros2_ws/src/cpp_robotics_sim_ros/config/command_mux.yaml
```

Defines:

```text
source topics
priorities
timeouts
publish rate
velocity limits
output topic
active-source topic
emergency-stop topic
```

### 21.3 Mapping and localization manager configuration

```text
ros2_ws/src/cpp_robotics_sim_ros/config/mapping_manager.yaml
ros2_ws/src/cpp_robotics_sim_ros/config/localization_manager.yaml
```

Both use:

```text
~/.ros/cpp_robotics_sim/maps
```

as the managed map root.

### 21.4 SLAM configuration

```text
ros2_ws/src/cpp_robotics_sim_ros/config/slam_toolbox.yaml
```

Important frames:

```text
map
odom
base_link
```

### 21.5 AMCL configuration

```text
ros2_ws/src/cpp_robotics_sim_ros/config/amcl_params.yaml
```

Important frames:

```text
global_frame_id: map
odom_frame_id: odom
base_frame_id: base_link
```

### 21.6 Nav2 configuration

```text
ros2_ws/src/cpp_robotics_sim_ros/nav2/diffbot_nav2_params.yaml
```

Important release-specific behavior:

```text
AMCL uses map as global frame.
Nav2 costmaps use odom as global_frame.
Controller odometry topic is /diff_drive_controller/odom.
```

---

## 22. Runtime Validation Checklist

### 22.1 Dashboard managers

```bash
ros2 node list | grep -E \
  'simulation_manager|mode_manager|mapping_manager|localization_manager|navigation_goal_manager|rosbridge'
```

### 22.2 Public services

```bash
ros2 service list | grep -E \
  '^/(simulation|mode)/'
```

### 22.3 Public status topics

```bash
ros2 topic list | grep -E \
  '^/(simulation|mode|mapping|localization|navigation|control)/'
```

### 22.4 Command path

```bash
ros2 topic info /cmd_vel/gui
ros2 topic info /cmd_vel/navigation
ros2 topic info /diff_drive_controller/cmd_vel
ros2 topic echo /control/active_source
```

### 22.5 Mapping

```bash
ros2 lifecycle get /slam_toolbox
ros2 topic echo /map --once
ros2 run tf2_ros tf2_echo map odom
```

### 22.6 Localization

```bash
ros2 lifecycle get /map_server
ros2 lifecycle get /amcl
ros2 topic echo /amcl_pose --once
ros2 run tf2_ros tf2_echo map base_link
```

### 22.7 Navigation

```bash
ros2 action info /navigate_to_pose
ros2 lifecycle get /planner_server
ros2 lifecycle get /controller_server
ros2 topic echo /navigation/status
ros2 topic echo /navigation/feedback
```

### 22.8 Controller and sensor

```bash
ros2 control list_controllers
ros2 topic echo /diff_drive_controller/odom --once
ros2 topic echo /scan --once
ros2 topic echo /clock --once
```

---

## 23. Interface Safety Rules

```text
1. Only configured environments are accepted.
2. Environment changes are blocked while simulation is active.
3. Only one high-level mode is active at a time.
4. Localization and Navigation require a selected map.
5. Initial pose is operationally necessary but not enforced before goal submission.
6. Map names and paths must remain within the managed map root.
7. Navigation goals require valid finite x, y, and yaw values.
8. Only one navigation goal may be active at a time.
9. Every velocity source has a freshness timeout.
10. Non-finite velocity commands are rejected.
11. The highest-priority fresh source wins.
12. Emergency stop overrides every source.
13. No fresh source results in zero output.
14. Only one node should own each principal TF edge.
15. Browser keyboard commands use /cmd_vel/gui.
16. Terminal keyboard commands use /cmd_vel/keyboard.
17. Nav2 commands reach the controller only through the bridge and command mux.
```

---

## 24. Known Interface Limitations

```text
The gamepad command source is configured but not a completed public v0.1.0 feature.
Initial-pose completion is not enforced as a navigation-goal prerequisite.
Nav2 uses a hybrid map-goal and odom-costmap frame configuration.
Some manager payloads use JSON inside std_msgs/msg/String rather than custom messages.
The browser interface depends on rosbridge and has no authentication layer.
RViz is not embedded in the dashboard.
Custom robots, worlds, planners, and controllers are configuration-driven.
```

---

## 25. Interface Summary

The central public control interfaces are:

```text
/simulation/*
/mode/*
/mapping/*
/localization/*
/navigation/*
/control/*
```

The central velocity path is:

```text
/cmd_vel/gamepad
/cmd_vel/keyboard
/cmd_vel/gui
/cmd_vel/navigation
        |
        v
command_mux
        |
        v
/diff_drive_controller/cmd_vel
```

The Nav2 command path is:

```text
/cmd_vel_nav_raw
  -> velocity_smoother
  -> /cmd_vel
  -> cmd_vel_twist_bridge
  -> /cmd_vel/navigation
  -> command_mux
  -> /diff_drive_controller/cmd_vel
```

The localization transform chain is:

```text
map -> odom -> base_link
```

The primary autonomous action is:

```text
/navigate_to_pose
nav2_msgs/action/NavigateToPose
```

The release interface contract is designed so the browser remains a thin
client while ROS 2 nodes retain ownership of lifecycle management, safety,
mapping, localization, planning, control, and robot state.

---

<!-- RELEASE_MEDIA_START -->
## Release Media

- [Project teaser](https://www.youtube.com/watch?v=zKf_hjIYtlk)
- [Complete v0.1.0 demonstration playlist](https://www.youtube.com/playlist?list=PLP_aJnUqSRf8)
- [Installation and first launch](https://www.youtube.com/watch?v=_x2Z7jXXnWw)
- [Docker build and 357-test validation](https://www.youtube.com/watch?v=4M628CFYiz8)

Release screenshots are stored in [`docs/media/v0.1.0`](media/v0.1.0).
<!-- RELEASE_MEDIA_END -->
