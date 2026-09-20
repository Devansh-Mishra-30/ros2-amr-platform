# Debugging and Validation Guide

## C++ / ROS 2 Robotics Simulation Foundation

**Release:** `v0.1.0`
**Release commit:** `28a080e72ee6e31baa25bcd2fdaa249706520361`
**Primary package:** `cpp_robotics_sim_ros`
**Primary platform:** Ubuntu 24.04, ROS 2 Jazzy, Gazebo Harmonic

---

## 1. Document Purpose

This document defines the debugging, verification, and release-validation
workflow for `cpp_robotics_sim_foundation` at release `v0.1.0`.

It is intended for:

- contributors validating a local change;
- users diagnosing startup or runtime failures;
- maintainers reproducing release evidence;
- reviewers checking safety and lifecycle behavior;
- developers extending the platform after `v0.1.0`.

This document covers:

- clean environment preparation;
- build validation;
- syntax and lint validation;
- registered ROS 2 tests;
- GoogleTest execution;
- simulator launch regression;
- headless dashboard integration;
- public launcher lifecycle validation;
- Docker validation;
- runtime subsystem inspection;
- mapping, localization, and navigation diagnosis;
- TF ownership and frame debugging;
- command-routing and emergency-stop validation;
- process, port, and shutdown checks;
- failure recovery;
- evidence capture;
- release-gate interpretation.

This document describes the tagged `v0.1.0` behavior. Uncommitted work on
later branches must not be treated as release evidence for `v0.1.0`.

---

## 2. Validated Release Baseline

The validated native release gate for `v0.1.0` produced:

```text
357 tests
0 errors
0 failures
0 skipped
```

The complete release gate includes:

1. Python syntax checks;
2. JavaScript syntax checks;
3. Bash syntax checks;
4. ROS 2 package build;
5. registered ROS 2 tests;
6. ament lint checks;
7. GoogleTest;
8. simulator launch regression;
9. headless dashboard integration;
10. public launcher lifecycle validation.

The validated release scenarios also include:

- Warehouse startup and shutdown;
- Hospital startup and shutdown;
- manual drive and safe stop;
- mapping and map save;
- map selection;
- AMCL localization;
- Nav2 goal success;
- Nav2 goal cancellation;
- environment switching in both directions;
- stale-process cleanup;
- launcher port release;
- recovery after externally closing Gazebo;
- native full test gate;
- Docker full test gate.

A passing test count is necessary but not sufficient. Release approval also
requires clean process ownership, released ports, no stale nodes, correct TF
ownership, and reproducible runtime behavior.

---

## 3. Validation Principles

### 3.1 Validate the exact revision

Release evidence must be associated with an exact commit or tag.

Check the current revision:

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

git branch --show-current
git rev-parse HEAD
git describe --tags --always --dirty
git status --short
```

For the immutable release source:

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

git rev-parse v0.1.0
git show --no-patch --decorate --oneline v0.1.0
```

Expected release commit:

```text
28a080e72ee6e31baa25bcd2fdaa249706520361
```

### 3.2 Separate release evidence from development evidence

When the active branch contains `v0.2.0` changes:

- do not report those results as tagged `v0.1.0` results;
- use `git show v0.1.0:<path>` for source audits;
- use a detached worktree or clean clone for exact release reproduction;
- record the tested commit in every validation report.

### 3.3 Prefer controlled gates

Run validation in this order:

```text
repository hygiene
source syntax
build
registered tests
launch regression
headless integration
lifecycle validation
manual runtime workflows
shutdown and residue checks
Docker reproduction
```

Do not jump directly into a GUI workflow when the source tree does not first
pass syntax, build, and registered tests.

### 3.4 Stop on unexplained failures

Do not normalize:

- intermittent test failures;
- missing lifecycle nodes;
- duplicate TF publishers;
- stale Gazebo processes;
- occupied dashboard ports after shutdown;
- navigation success without a final zero command;
- map files written outside the managed root;
- unexplained changes in test count.

Every unexplained deviation must be investigated before release approval.

---

## 4. Repository and Environment Preflight

### 4.1 Working-tree inspection

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

git status --short
git diff --check
git diff --stat
```

Interpretation:

```text
git status --short:
  lists modified and untracked files

git diff --check:
  reports trailing whitespace and malformed conflict markers

git diff --stat:
  summarizes tracked changes
```

A clean `git diff --check` produces no output.

### 4.2 Required directory layout

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

test -d ros2_ws
test -d ros2_ws/src/cpp_robotics_sim_ros
test -d scripts
test -f README.md
test -f Dockerfile
test -f .github/workflows/ros2_jazzy_ci.yml

printf 'Repository layout preflight passed.\n'
```

### 4.3 ROS 2 installation

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

test -f /opt/ros/jazzy/setup.bash
source /opt/ros/jazzy/setup.bash
ros2 --help >/dev/null
printf 'ROS 2 Jazzy setup passed.\n'
```

### 4.4 Tool availability

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

for command_name in \
  bash \
  python3 \
  node \
  colcon \
  ros2 \
  git \
  grep \
  sed \
  awk \
  ss \
  ps
do
  command -v "$command_name" >/dev/null \
    && printf 'PASS  %s\n' "$command_name" \
    || printf 'FAIL  %s\n' "$command_name"
done
```

### 4.5 Disk space

Gazebo, colcon build products, Docker layers, maps, logs, and rosbag files can
consume substantial storage.

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

df -h .
du -sh ros2_ws/build ros2_ws/install ros2_ws/log 2>/dev/null || true
docker system df 2>/dev/null || true
```

---

## 5. Standard Native Release Gate

### 5.1 Build

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

./scripts/build.sh
```

The build script is the preferred project entry point.

A successful build must create:

```text
ros2_ws/install/setup.bash
```

Confirm:

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

test -f ros2_ws/install/setup.bash
printf 'Workspace setup exists.\n'
```

### 5.2 Full test gate

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

./scripts/test.sh
```

`test.sh` requires an existing built workspace. It fails early when:

```text
ros2_ws/install/setup.bash
```

does not exist.

The script runs:

```text
scripts/check_syntax.sh
colcon test
colcon test-result --verbose
scripts/launch_regression.sh
scripts/headless_smoke_test.sh
scripts/run_lifecycle_test.sh
```

It also enables slow-version cppcheck support:

```text
AMENT_CPPCHECK_ALLOW_SLOW_VERSIONS=1
```

The registered ROS 2 test command includes:

```text
--return-code-on-test-failure
```

so a failing registered test causes the gate to fail.

### 5.3 Expected conclusion

A successful gate ends with:

```text
All unit and integration tests completed successfully.
```

Do not accept that line alone. Also inspect the preceding test-result summary
and confirm that no earlier warning represents a skipped or bypassed gate.

---

## 6. Source Syntax Validation

### 6.1 Run the project syntax gate

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

./scripts/check_syntax.sh
```

The release syntax gate covers:

```text
Python
JavaScript
Bash
```

### 6.2 Python syntax

Targeted validation:

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

find ros2_ws/src/cpp_robotics_sim_ros \
  -type f -name '*.py' -print0 \
  | xargs -0 -n1 python3 -m py_compile
```

Failures usually indicate:

- indentation errors;
- malformed strings;
- unmatched brackets;
- invalid function definitions;
- accidental shell text pasted into Python.

### 6.3 JavaScript syntax

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

find ros2_ws/src/cpp_robotics_sim_ros/web \
  -type f -name '*.js' -print0 \
  | xargs -0 -n1 node --check
```

Failures usually indicate:

- missing braces;
- invalid object literals;
- malformed template strings;
- broken callback definitions;
- unfinished edits.

### 6.4 Bash syntax

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

find scripts \
  -type f -name '*.sh' -print0 \
  | xargs -0 -n1 bash -n
```

Failures usually indicate:

- unmatched `fi`, `done`, or `}`;
- malformed quoting;
- invalid heredoc termination;
- incomplete command continuation.

### 6.5 Executable permissions

ROS 2 Python executables and project shell scripts must retain executable
permissions where required.

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

find scripts \
  -maxdepth 1 \
  -type f \
  -name '*.sh' \
  ! -perm -u+x \
  -print

find ros2_ws/src/cpp_robotics_sim_ros/scripts \
  -maxdepth 1 \
  -type f \
  -name '*.py' \
  ! -perm -u+x \
  -print
```

No output is expected for scripts that are installed and launched as
executables.

---

## 7. Build Debugging

### 7.1 Clean rebuild

Use the repository cleanup script for generated build state:

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

./scripts/clean.sh
./scripts/build.sh
```

The cleanup script removes generated workspace artifacts and Python caches.
It does not terminate active ROS 2 or Gazebo processes.

### 7.2 Manual package build

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

source /opt/ros/jazzy/setup.bash

cd ros2_ws
colcon build \
  --packages-select cpp_robotics_sim_ros \
  --symlink-install \
  --event-handlers console_direct+
```

### 7.3 Verify package discovery

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

ros2 pkg prefix cpp_robotics_sim_ros
ros2 pkg executables cpp_robotics_sim_ros | sort
```

### 7.4 Common build failure: package not found

Check:

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

find ros2_ws/src -maxdepth 3 -name package.xml -print
grep -n '<name>' \
  ros2_ws/src/cpp_robotics_sim_ros/package.xml
```

Then clean and rebuild.

### 7.5 Common build failure: stale generated state

Symptoms:

```text
installed script differs from source
launch file changes not reflected
old parameter file still used
package import behavior inconsistent
```

Recovery:

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

./scripts/clean.sh
./scripts/build.sh
```

### 7.6 Common build failure: unsourced environment

Correct sequence:

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

ros2 pkg prefix cpp_robotics_sim_ros
```

---

## 8. Registered ROS 2 Tests

### 8.1 Run package tests directly

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

cd ros2_ws

colcon test \
  --packages-select cpp_robotics_sim_ros \
  --event-handlers console_direct+ \
  --return-code-on-test-failure

colcon test-result --verbose
```

### 8.2 Test-result inspection

Summary only:

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

cd ros2_ws
colcon test-result
```

Verbose:

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

cd ros2_ws
colcon test-result --verbose
```

### 8.3 Locate test logs

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

find ros2_ws/log/latest_test \
  -type f \
  | sort \
  | sed -n '1,200p'
```

Search failures:

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

grep -RniE \
  'fail|error|exception|traceback' \
  ros2_ws/log/latest_test \
  | head -n 200 || true
```

### 8.4 Run a specific CTest target

List tests:

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

cd ros2_ws/build/cpp_robotics_sim_ros
ctest -N
```

Run matching tests:

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

cd ros2_ws/build/cpp_robotics_sim_ros
ctest \
  --output-on-failure \
  -R '<TEST_NAME_PATTERN>'
```

Replace `<TEST_NAME_PATTERN>` with an exact or partial registered test name.

---

## 9. Test Categories and Intent

The release test suite validates several classes of behavior.

### 9.1 Input and path validation

Examples include:

- environment allowlisting;
- map-name validation;
- path traversal prevention;
- safe map-root resolution;
- finite numeric goal validation;
- malformed JSON rejection;
- boolean rejection where numeric values are required.

### 9.2 State-machine behavior

Examples include:

- simulation lifecycle transitions;
- mode mutual exclusion;
- mode prerequisites;
- environment lock rules;
- map selection clearing after environment change;
- navigation goal admission;
- navigation cancellation;
- shutdown idempotence.

### 9.3 Safety behavior

Examples include:

- velocity-source timeout;
- source priority;
- emergency-stop override;
- zero command when no source is fresh;
- zero command after stop paths;
- stale-process cleanup;
- bounded process termination.

### 9.4 ROS 2 integration behavior

Examples include:

- launch-file construction;
- manager startup;
- topic and service availability;
- action-client behavior;
- dashboard-to-ROS transport;
- lifecycle-managed node activation;
- clean launcher shutdown.

### 9.5 C++ core behavior

GoogleTest covers the C++ robotics foundation components registered by the
package.

A passing aggregate count must not be interpreted as proof of untested future
features.

---

## 10. Simulator Launch Regression

### 10.1 Run the regression gate

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

./scripts/launch_regression.sh
```

This gate belongs to `scripts/test.sh` and is not an optional manual extra.

### 10.2 Purpose

The launch regression checks that the project can construct and exercise the
simulator launch path without leaving unmanaged state.

It is intended to catch:

- broken launch imports;
- invalid launch arguments;
- missing package resources;
- incorrect executable installation;
- startup failures;
- early process exits;
- shutdown regressions;
- stale simulator processes.

### 10.3 Diagnose a failure

First inspect the script:

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

sed -n '1,260p' scripts/launch_regression.sh
```

Then inspect recent ROS logs:

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

find ~/.ros/log \
  -maxdepth 2 \
  -type f \
  -printf '%T@ %p\n' \
  2>/dev/null \
  | sort -nr \
  | head -n 30
```

Check residual processes:

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

ps -ef \
  | grep -E \
    'ros2 launch|gz sim|gzserver|gzclient|ruby.*gz|cpp_robotics_sim' \
  | grep -v grep || true
```

### 10.4 Do not hide a launch failure

Avoid validating by appending unconditional success:

```text
command || true
```

Use `|| true` only for diagnostic queries that are allowed to return no
matches, never for the actual release gate.

---

## 11. Headless Dashboard Integration

### 11.1 Run the integration gate

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

./scripts/headless_smoke_test.sh
```

### 11.2 Purpose

The headless integration gate validates the non-GUI operational surface of
the platform, including the dashboard launcher and ROS-facing manager layer.

It is intended to catch:

- dashboard HTTP server startup failure;
- rosbridge startup failure;
- missing manager nodes;
- unavailable topics or services;
- broken request routing;
- process cleanup failure;
- port-release regressions.

### 11.3 Dashboard ports

Default ports:

```text
HTTP:      8080
WebSocket: 9090
```

Inspect:

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

ss -ltnp | grep -E ':8080|:9090' || true
```

### 11.4 Dashboard nodes

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

ros2 node list \
  | grep -E \
    'simulation_manager|mode_manager|mapping_manager|localization_manager|navigation_goal_manager|rosbridge' \
  | sort
```

Expected manager nodes:

```text
/simulation_manager
/mode_manager
/mapping_manager
/localization_manager
/navigation_goal_manager
```

The exact rosbridge node name should be inspected at runtime.

### 11.5 Public services

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

ros2 service list \
  | grep -E '^/(simulation|mode)/' \
  | sort
```

### 11.6 Public topics

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

ros2 topic list \
  | grep -E \
    '^/(simulation|mode|mapping|localization|navigation|control)/' \
  | sort
```

### 11.7 Browser-level diagnosis

When the page loads but controls do not work:

1. confirm port 8080 is listening;
2. confirm port 9090 is listening;
3. confirm rosbridge exists;
4. confirm manager nodes exist;
5. inspect browser developer-console errors;
6. inspect WebSocket connection state;
7. confirm topic names and message types against
   `docs/topic_interface_reference.md`.

---

## 12. Public Launcher Lifecycle Validation

### 12.1 Run the lifecycle gate

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

./scripts/run_lifecycle_test.sh
```

### 12.2 Purpose

This test validates the user-facing launcher lifecycle rather than only an
individual ROS launch file.

It is intended to verify:

- launcher startup;
- dashboard availability;
- manager startup;
- controlled shutdown;
- process-group termination;
- no stale ROS/Gazebo children;
- port release;
- repeatable relaunch.

### 12.3 Post-test residue check

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

printf '\n===== PORTS =====\n'
ss -ltnp | grep -E ':8080|:9090' || true

printf '\n===== ROS AND GAZEBO PROCESSES =====\n'
ps -ef \
  | grep -E \
    'ros2 launch|gz sim|gzserver|gzclient|ruby.*gz|rosbridge|simulation_manager|mode_manager' \
  | grep -v grep || true
```

After the launcher has fully stopped, no project-owned listeners or managed
runtime processes should remain.

### 12.4 Repeatability

A lifecycle validation is stronger when run twice:

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

./scripts/run_lifecycle_test.sh
./scripts/run_lifecycle_test.sh
```

The second run catches residue that the first run may have left behind.

---

## 13. Docker Validation

### 13.1 Build image

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

docker build \
  --tag cpp-robotics-sim:v0.1.0 \
  .
```

### 13.2 Run the full gate

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

docker run --rm \
  --name cpp-robotics-sim-v010-test \
  cpp-robotics-sim:v0.1.0 \
  bash -lc './scripts/test.sh'
```

### 13.3 Docker validation intent

The container validates the same source tree in a clean:

```text
Ubuntu 24.04
ROS 2 Jazzy
```

environment.

The container is primarily a:

```text
build
lint
automated test
reproducibility
```

environment.

It is not the primary GUI Gazebo runtime entry point.

### 13.4 Diagnose image build failure

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

docker build \
  --no-cache \
  --progress=plain \
  --tag cpp-robotics-sim:v0.1.0-debug \
  .
```

### 13.5 Inspect the container

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

docker run --rm -it \
  cpp-robotics-sim:v0.1.0 \
  bash
```

Inside the container, inspect:

```text
/opt/ros/jazzy/setup.bash
workspace build products
dependency installation
test logs
script permissions
```

### 13.6 Remove stale named container

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

docker rm -f cpp-robotics-sim-v010-test 2>/dev/null || true
```

This cleanup command is diagnostic maintenance, not a substitute for fixing
a container that fails to exit normally.

---

## 14. Continuous Integration

Workflow:

```text
.github/workflows/ros2_jazzy_ci.yml
```

Inspect the tagged workflow:

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

git show v0.1.0:.github/workflows/ros2_jazzy_ci.yml \
  | sed -n '1,280p'
```

CI validates:

- source syntax;
- dependency installation;
- ROS 2 package build;
- unit and behavior tests;
- ament linting;
- test-result collection.

GUI-dependent Gazebo scenarios are validated locally because hosted CI does
not reproduce the full desktop and graphics environment.

A green hosted CI result does not replace the local GUI/runtime validation
required for the release.

---

## 15. Standard Runtime Startup Inspection

### 15.1 Source environment

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash
```

### 15.2 Node inventory

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

ros2 node list | sort
```

### 15.3 Topic inventory

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

ros2 topic list -t | sort
```

### 15.4 Service inventory

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

ros2 service list -t | sort
```

### 15.5 Action inventory

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

ros2 action list -t | sort
```

### 15.6 Parameters

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

ros2 param list | sort
```

---

## 16. Simulation Manager Debugging

Node:

```text
/simulation_manager
```

### 16.1 Status

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

ros2 topic echo /simulation/status
```

Expected lifecycle values:

```text
stopped
starting
running
stopping
error
```

### 16.2 Environment status

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

ros2 topic echo /simulation/environment_status
```

Inspect:

```text
state
message
selected_environment
available_environments
world_file
selection_locked
```

### 16.3 Select environment

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

ros2 topic pub --once \
  /simulation/environment_request \
  std_msgs/msg/String \
  "{data: hospital}"
```

Accepted environments:

```text
warehouse
hospital
```

### 16.4 Start, stop, and reset

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

ros2 service call \
  /simulation/start \
  std_srvs/srv/Trigger \
  "{}"
```

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

ros2 service call \
  /simulation/stop \
  std_srvs/srv/Trigger \
  "{}"
```

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

ros2 service call \
  /simulation/reset \
  std_srvs/srv/Trigger \
  "{}"
```

### 16.5 Environment selection locked

Selection is intentionally locked during:

```text
starting
running
stopping
```

Stop the simulation before changing environments.

### 16.6 Gazebo closes externally

An externally closed simulator is an unexpected process exit.

Expected manager behavior:

```text
simulation status -> error
environment selection -> unlocked
new environment selection -> allowed
simulation restart -> allowed
dashboard restart -> not required
```

Check:

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

ros2 topic echo /simulation/status --once
ros2 topic echo /simulation/environment_status --once
```

---

## 17. Mode Manager Debugging

Node:

```text
/mode_manager
```

### 17.1 Mode status

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

ros2 topic echo /mode/status
```

Expected values:

```text
stopped
starting
manual
mapping
localization
navigation
stopping
error
```

### 17.2 Activate modes

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

ros2 service call /mode/manual std_srvs/srv/Trigger "{}"
ros2 service call /mode/mapping std_srvs/srv/Trigger "{}"
ros2 service call /mode/localization std_srvs/srv/Trigger "{}"
ros2 service call /mode/navigation std_srvs/srv/Trigger "{}"
ros2 service call /mode/stop std_srvs/srv/Trigger "{}"
```

### 17.3 Mode rejected

Check:

```text
simulation is running
selected map exists for Localization
selected map exists for Navigation
no mode transition is already in progress
no stale managed mode process remains
```

Inspect:

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

ros2 topic echo /simulation/status --once
ros2 topic echo /localization/selected_map --once
ros2 topic echo /mode/status --once
```

---

## 18. Command Routing Debugging

Node:

```text
/command_mux
```

### 18.1 Configured sources

| Source | Topic | Priority | Timeout |
|---|---|---:|---:|
| Gamepad | `/cmd_vel/gamepad` | 100 | 0.50 s |
| Terminal keyboard | `/cmd_vel/keyboard` | 90 | 0.50 s |
| Browser GUI/keyboard | `/cmd_vel/gui` | 80 | 0.75 s |
| Navigation | `/cmd_vel/navigation` | 50 | 0.50 s |

Output:

```text
/diff_drive_controller/cmd_vel
```

### 18.2 Inspect active source

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

ros2 topic echo /control/active_source
```

Expected values include:

```text
gamepad
keyboard
gui
navigation
emergency_stop
none
```

### 18.3 Test GUI source

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

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

Stop the publisher with `Ctrl+C`.

The active source should return to:

```text
none
```

after the 0.75-second GUI timeout.

### 18.4 Inspect final controller command

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

ros2 topic echo /diff_drive_controller/cmd_vel
```

### 18.5 Emergency stop

Engage:

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

ros2 topic pub --once \
  /control/emergency_stop \
  std_msgs/msg/Bool \
  "{data: true}"
```

Release:

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

ros2 topic pub --once \
  /control/emergency_stop \
  std_msgs/msg/Bool \
  "{data: false}"
```

Expected engaged behavior:

```text
zero velocity output
active source emergency_stop
all normal sources ignored
```

### 18.6 Source arbitration test

Publish two sources at the same time and confirm the higher priority wins.

Do not command motion in an unsafe environment. Keep the simulated robot
clear of obstacles and use low velocities.

### 18.7 Non-finite commands

The command mux rejects non-finite Twist components.

A rejected message must not propagate to the controller.

---

## 19. Controller and Odometry Debugging

### 19.1 Controller state

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

ros2 control list_controllers
```

Expected active controllers:

```text
joint_state_broadcaster
diff_drive_controller
```

### 19.2 Hardware interfaces

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

ros2 control list_hardware_interfaces
```

### 19.3 Odometry

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

ros2 topic echo /diff_drive_controller/odom --once
```

Expected frames:

```text
header.frame_id: odom
child_frame_id: base_link
```

### 19.4 Joint state

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

ros2 topic echo /joint_states --once
```

### 19.5 Command received but robot does not move

Check:

```text
command mux active source
final controller command topic
controller active state
wheel interfaces
Gazebo paused state
simulation clock
joint state updates
```

Commands:

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

ros2 topic echo /control/active_source --once
ros2 topic echo /diff_drive_controller/cmd_vel --once
ros2 control list_controllers
ros2 topic echo /clock --once
ros2 topic echo /joint_states --once
```

---

## 20. LiDAR and Simulation-Time Debugging

### 20.1 LiDAR

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

ros2 topic type /scan
ros2 topic info /scan --verbose
ros2 topic echo /scan --once
```

Expected type:

```text
sensor_msgs/msg/LaserScan
```

### 20.2 Scan frequency

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

ros2 topic hz /scan
```

### 20.3 Clock

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

ros2 topic echo /clock --once
```

Expected type:

```text
rosgraph_msgs/msg/Clock
```

### 20.4 Nodes using simulation time

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

for node_name in $(ros2 node list); do
  value="$(
    ros2 param get "$node_name" use_sim_time 2>/dev/null \
      || true
  )"

  if [[ -n "$value" ]]; then
    printf '%-45s %s\n' "$node_name" "$value"
  fi
done
```

A missing or inconsistent `use_sim_time` setting can cause:

- stale transforms;
- extrapolation errors;
- navigation timeout;
- delayed map updates;
- inconsistent action timing.

---

## 21. TF Debugging

### 21.1 Principal transform chain

```text
map -> odom -> base_link -> robot links and sensors
```

### 21.2 Ownership

Mapping:

```text
SLAM Toolbox:
  map -> odom
```

Localization and Navigation:

```text
AMCL:
  map -> odom
```

All modes:

```text
diff_drive_controller:
  odom -> base_link

robot_state_publisher:
  base_link -> robot links and sensors
```

### 21.3 Inspect transforms

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

ros2 run tf2_ros tf2_echo map odom
```

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

ros2 run tf2_ros tf2_echo odom base_link
```

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

ros2 run tf2_ros tf2_echo map base_link
```

### 21.4 Generate frame graph

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

ros2 run tf2_tools view_frames
```

### 21.5 Duplicate `map -> odom`

Check active nodes:

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

ros2 node list \
  | grep -E 'slam_toolbox|amcl'
```

Do not run SLAM Toolbox and AMCL as simultaneous owners of `map -> odom`.

### 21.6 Duplicate `odom -> base_link`

The controller owns this edge in the public platform.

Do not start another odometry publisher that also broadcasts the same edge.

### 21.7 Extrapolation errors

Check:

```text
/clock is publishing
use_sim_time is consistent
TF timestamps advance
scan timestamps advance
odom timestamps advance
required static transforms exist
```

---

## 22. Mapping Debugging

Nodes and interfaces:

```text
/mapping_manager
/slam_toolbox
/mapping/save_request
/mapping/save_status
/mapping/saved_maps
/map
/map_metadata
```

### 22.1 Prerequisites

```text
simulation status == running
mode status == mapping
selected environment is non-empty
map name is valid
```

### 22.2 SLAM lifecycle

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

ros2 lifecycle get /slam_toolbox
```

Expected:

```text
active
```

### 22.3 Map publication

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

ros2 topic info /map --verbose
ros2 topic echo /map --once
ros2 topic echo /map_metadata --once
```

### 22.4 Save request

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

ros2 topic pub --once \
  /mapping/save_request \
  std_msgs/msg/String \
  "{data: hospital_main}"
```

### 22.5 Observe save result

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

ros2 topic echo /mapping/save_status
```

Status payload field:

```text
status
```

Typical values:

```text
ready
saving
success
error
```

### 22.6 Inspect inventory

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

ros2 topic echo /mapping/saved_maps --once
```

The payload is a JSON array.

Each entry includes:

```text
name
environment
legacy
yaml_path
image_path
complete
```

### 22.7 Inspect files

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

find ~/.ros/cpp_robotics_sim/maps \
  -maxdepth 3 \
  -type f \
  \( -name '*.yaml' -o -name '*.pgm' \) \
  -print \
  | sort
```

Expected environment-aware layout:

```text
~/.ros/cpp_robotics_sim/maps/<environment>/<map_name>.yaml
~/.ros/cpp_robotics_sim/maps/<environment>/<map_name>.pgm
```

### 22.8 Map save fails

Check:

```text
map mode active
/map exists
map name contains only allowed characters
target directory is writable
map_saver_cli is installed
free and occupied thresholds are valid
save timeout was not exceeded
both YAML and PGM were created
```

### 22.9 Incomplete map

A map is complete only when both files exist:

```text
<map_name>.yaml
<map_name>.pgm
```

An inventory entry with:

```json
{
  "complete": false
}
```

must not be treated as a valid localization map.

---

## 23. Localization Debugging

Nodes and interfaces:

```text
/localization_manager
/map_server
/amcl
/localization/select_map_request
/localization/selected_map
/localization/initial_pose_request
/localization/status
/initialpose
/amcl_pose
```

### 23.1 Select map

Plain request:

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

ros2 topic pub --once \
  /localization/select_map_request \
  std_msgs/msg/String \
  "{data: hospital_main}"
```

Environment-specific JSON:

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

ros2 topic pub --once \
  /localization/select_map_request \
  std_msgs/msg/String \
  '{data: "{\"name\":\"hospital_main\",\"environment\":\"hospital\"}"}'
```

### 23.2 Confirm selected map

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

ros2 topic echo /localization/selected_map --once
```

Expected fields:

```text
name
environment
yaml_path
```

### 23.3 Activate localization

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

ros2 service call \
  /mode/localization \
  std_srvs/srv/Trigger \
  "{}"
```

### 23.4 Lifecycle state

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

ros2 lifecycle get /map_server
ros2 lifecycle get /amcl
```

Expected:

```text
active
```

### 23.5 Publish initial pose

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

ros2 topic pub --once \
  /localization/initial_pose_request \
  std_msgs/msg/String \
  '{data: "{\"x\":0.0,\"y\":0.0,\"yaw\":0.0}"}'
```

Prerequisites:

```text
simulation running
mode is localization or navigation
map selected
x, y, yaw numeric
x, y, yaw finite
```

### 23.6 Observe AMCL

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

ros2 topic echo /amcl_pose --once
ros2 run tf2_ros tf2_echo map base_link
```

### 23.7 AMCL does not converge

Check:

```text
map matches selected environment
initial pose is near true robot pose
/scan publishes
scan frame connects to base_link
/map publishes
map -> odom exists
odom -> base_link exists
robot is moving slowly enough
AMCL is active
```

### 23.8 Selected map clears after environment change

This is expected when the selected map belongs to a different non-legacy
environment.

Select a compatible map after changing environments.

---

## 24. Navigation Debugging

Nodes and interfaces:

```text
/navigation_goal_manager
/planner_server
/controller_server
/behavior_server
/bt_navigator
/waypoint_follower
/velocity_smoother
/cmd_vel_twist_bridge
/navigate_to_pose
/navigation/goal_request
/navigation/cancel_request
/navigation/status
/navigation/feedback
```

### 24.1 Prerequisites

```text
simulation running
mode navigation
saved map selected
map server active
AMCL active
initial pose operationally established
/scan available
/map available
map -> odom available
odom -> base_link available
NavigateToPose action server available
```

The mode manager requires a selected map. It does not enforce proof that an
initial pose has already been published.

### 24.2 Lifecycle checks

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

for node_name in \
  map_server \
  amcl \
  planner_server \
  controller_server \
  behavior_server \
  bt_navigator \
  waypoint_follower \
  velocity_smoother
do
  printf '\n===== %s =====\n' "$node_name"
  ros2 lifecycle get "/$node_name" || true
done
```

### 24.3 Action server

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

ros2 action info /navigate_to_pose
```

### 24.4 Submit goal through manager

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

ros2 topic pub --once \
  /navigation/goal_request \
  std_msgs/msg/String \
  '{data: "{\"x\":1.0,\"y\":0.0,\"yaw\":0.0}"}'
```

### 24.5 Observe status and feedback

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

ros2 topic echo /navigation/status
```

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

ros2 topic echo /navigation/feedback
```

Navigation feedback fields:

```text
state
message
goal
distance_remaining
estimated_time_remaining
navigation_time
recovery_count
```

### 24.6 Cancel active goal

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

ros2 topic pub --once \
  /navigation/cancel_request \
  std_msgs/msg/String \
  '{data: "{\"cancel\":true}"}'
```

### 24.7 Inspect command path

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

ros2 topic info /cmd_vel_nav_raw --verbose
ros2 topic info /cmd_vel --verbose
ros2 topic info /cmd_vel/navigation --verbose
ros2 topic info /diff_drive_controller/cmd_vel --verbose
```

Exact path:

```text
controller_server or behavior_server
  -> /cmd_vel_nav_raw
  -> velocity_smoother
  -> /cmd_vel
  -> cmd_vel_twist_bridge
  -> /cmd_vel/navigation
  -> command_mux
  -> /diff_drive_controller/cmd_vel
```

### 24.8 Navigation does not start

Run:

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

ros2 topic info /map
ros2 topic info /scan
ros2 topic echo /amcl_pose --once
ros2 run tf2_ros tf2_echo map base_link
ros2 action list | grep navigate_to_pose
```

### 24.9 Goal rejected

Check:

```text
JSON is valid
payload is an object
x, y, yaw exist
values are numeric
values are not booleans
values are finite
x and y are within configured limits
simulation is running
mode is navigation
no other goal is active
action server is available
```

### 24.10 Robot plans but does not move

Check:

```text
controller_server active
velocity_smoother active
/cmd_vel_nav_raw has data
/cmd_vel has data
/cmd_vel/navigation has data
command mux active source is navigation
emergency stop is false
controller command has data
controller is active
```

### 24.11 Goal succeeds but velocity persists

This is a release-blocking safety failure.

Check:

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

ros2 topic echo /navigation/status
ros2 topic echo /control/active_source
ros2 topic echo /diff_drive_controller/cmd_vel
```

Expected:

```text
navigation status succeeded
navigation source expires
active source none
final output zero
```

### 24.12 Goal cancellation safety

After cancellation:

```text
status transitions through cancel_pending/canceling
final result is canceled or an explicit failure
navigation source expires
controller output becomes zero
```

---

## 25. Process and Port Debugging

### 25.1 Project process inventory

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

ps -eo pid,ppid,pgid,sid,stat,etime,cmd \
  | grep -E \
    'ros2 launch|gz sim|gzserver|gzclient|ruby.*gz|rosbridge|simulation_manager|mode_manager|mapping_manager|localization_manager|navigation_goal_manager' \
  | grep -v grep || true
```

### 25.2 Port inventory

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

ss -ltnp | grep -E ':8080|:9090' || true
```

### 25.3 Process tree

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

command -v pstree >/dev/null \
  && pstree -ap \
  || ps -ef --forest
```

### 25.4 Stale Gazebo process

A process whose parent is PID 1 may have survived its original launcher.

Inspect:

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

pgrep -af 'gz sim|gzserver|gzclient|ruby.*gz' || true
```

Do not use force-kill as the normal shutdown path. First use the dashboard or
manager stop workflow.

### 25.5 Emergency manual cleanup

Use only after normal project shutdown has failed and evidence has been
captured:

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

pkill -TERM -f 'ros2 launch' || true
pkill -TERM -f 'gz sim' || true
pkill -TERM -f 'gzserver' || true
pkill -TERM -f 'gzclient' || true
pkill -TERM -f 'ruby.*gz' || true

sleep 3

pgrep -af 'ros2 launch|gz sim|gzserver|gzclient|ruby.*gz' || true
```

Escalate only remaining confirmed project-owned processes:

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

pkill -KILL -f 'gz sim' || true
pkill -KILL -f 'gzserver' || true
pkill -KILL -f 'gzclient' || true
pkill -KILL -f 'ruby.*gz' || true
```

Record why escalation was required.

---

## 26. Shutdown Validation

### 26.1 High-level status

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

printf '\n===== MODE =====\n'
ros2 topic echo /mode/status --once || true

printf '\n===== SIMULATION =====\n'
ros2 topic echo /simulation/status --once || true
```

Expected before launcher shutdown:

```text
mode: stopped
simulation: stopped
```

### 26.2 Runtime-node cleanup

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

ros2 node list \
  | grep -E \
    'slam_toolbox|map_server|amcl|planner_server|controller_server|behavior_server|bt_navigator|waypoint_follower|velocity_smoother' \
  || true
```

After mode stop, mode-owned nodes should no longer remain.

### 26.3 Gazebo cleanup

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

pgrep -af 'gz sim|gzserver|gzclient|ruby.*gz' || true
```

After simulation stop, no project-owned Gazebo processes should remain.

### 26.4 Launcher cleanup

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

ss -ltnp | grep -E ':8080|:9090' || true
```

After the public launcher exits, both ports should be released.

### 26.5 Manager uniqueness

While the dashboard launcher is active:

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

for node_name in \
  /simulation_manager \
  /mode_manager \
  /mapping_manager \
  /localization_manager \
  /navigation_goal_manager
do
  count="$(
    ros2 node list \
      | grep -Fx "$node_name" \
      | wc -l
  )"

  printf '%-32s %s\n' "$node_name" "$count"
done
```

Expected count:

```text
1
```

for each active manager.

---

## 27. Logging and Evidence Capture

### 27.1 ROS logs

Default root:

```text
~/.ros/log
```

Recent files:

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

find ~/.ros/log \
  -type f \
  -printf '%T@ %p\n' \
  2>/dev/null \
  | sort -nr \
  | head -n 100
```

### 27.2 Colcon logs

```text
ros2_ws/log
```

Latest build:

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

find ros2_ws/log/latest_build \
  -type f \
  | sort \
  | sed -n '1,200p'
```

Latest tests:

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

find ros2_ws/log/latest_test \
  -type f \
  | sort \
  | sed -n '1,200p'
```

### 27.3 Capture validation transcript

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

mkdir -p validation_evidence

timestamp="$(date +%Y%m%d_%H%M%S)"

{
  printf 'Commit: '
  git rev-parse HEAD

  printf 'Description: '
  git describe --tags --always --dirty

  printf 'Date: '
  date --iso-8601=seconds

  ./scripts/test.sh
} 2>&1 \
  | tee "validation_evidence/full_gate_${timestamp}.log"
```

Generated evidence should be reviewed before publication. Do not commit large
or transient logs unless the repository intentionally tracks a curated
report.

### 27.4 Capture runtime inventory

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

mkdir -p validation_evidence

timestamp="$(date +%Y%m%d_%H%M%S)"

{
  printf '\n===== REVISION =====\n'
  git rev-parse HEAD
  git describe --tags --always --dirty

  printf '\n===== STATUS =====\n'
  git status --short

  printf '\n===== NODES =====\n'
  ros2 node list | sort

  printf '\n===== TOPICS =====\n'
  ros2 topic list -t | sort

  printf '\n===== SERVICES =====\n'
  ros2 service list -t | sort

  printf '\n===== ACTIONS =====\n'
  ros2 action list -t | sort

  printf '\n===== PORTS =====\n'
  ss -ltnp | grep -E ':8080|:9090' || true

  printf '\n===== PROCESSES =====\n'
  ps -eo pid,ppid,pgid,sid,stat,etime,cmd \
    | grep -E \
      'ros2|gz sim|gzserver|gzclient|rosbridge' \
    | grep -v grep || true
} > "validation_evidence/runtime_${timestamp}.txt"
```

---

## 28. Failure Triage Workflow

Use this order when a full gate fails.

### Step 1: Record revision

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

git branch --show-current
git rev-parse HEAD
git describe --tags --always --dirty
git status --short
```

### Step 2: Identify the first failing gate

```text
syntax
build
registered tests
launch regression
headless integration
lifecycle
manual runtime
Docker
```

The first failure often causes later failures. Fix it before interpreting
downstream noise.

### Step 3: Reproduce narrowly

Examples:

```text
one syntax checker
one CTest target
one launch regression script
one manager service
one topic contract
one lifecycle node
one command source
```

### Step 4: Capture logs

Store:

```text
exact command
complete output
commit SHA
environment
timestamp
reproduction frequency
expected behavior
actual behavior
```

### Step 5: Check residue

A failed integration test may leave processes or ports that corrupt the next
attempt.

### Step 6: Clean generated state only when justified

Use:

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

./scripts/clean.sh
./scripts/build.sh
```

Do not erase logs before reading them.

### Step 7: Rerun the narrow test

Confirm the fix is real.

### Step 8: Rerun the complete native gate

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

./scripts/test.sh
```

### Step 9: Rerun Docker gate when release-relevant

### Step 10: Repeat manual workflows affected by the change

---

## 29. Common Failure Patterns

### 29.1 `test.sh` reports missing workspace setup

Cause:

```text
workspace has not been built
generated install tree was cleaned
build failed before installation
```

Recovery:

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

./scripts/build.sh
./scripts/test.sh
```

### 29.2 Dashboard loads but ROS is disconnected

Check:

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

ss -ltnp | grep -E ':8080|:9090'
ros2 node list
```

Restart the launcher when rosbridge or manager nodes are missing.

### 29.3 Port already in use

Find owner:

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

ss -ltnp | grep -E ':8080|:9090' || true
```

Determine whether it is:

```text
a previous project launcher
another application
a stale test process
```

Do not blindly kill an unrelated process.

### 29.4 Map exists but cannot be selected

Check:

```text
YAML exists
PGM exists
name passes validation
environment matches
path remains inside managed root
YAML image field resolves correctly
```

### 29.5 Navigation action exists but goal fails

Check:

```text
AMCL pose
map-to-base transform
costmap lifecycle
controller lifecycle
goal bounds
obstacle placement
command mux source
emergency stop
```

### 29.6 ROS graph shows duplicate node names

Possible causes:

```text
launcher started twice
manager from previous run remains
mode process did not stop
manual launch overlaps dashboard launch
```

Stop through normal lifecycle paths, inspect process groups, and verify
residue before relaunch.

### 29.7 Tests pass locally but fail in Docker

Check:

```text
undeclared dependency
host-only environment variable
untracked generated file
permission difference
shell assumption
missing package.xml dependency
missing CMake installation rule
```

### 29.8 Tests pass in Docker but GUI fails locally

Check:

```text
display environment
Gazebo graphics support
WSL graphics integration
host GPU/driver
host network and ports
desktop session
Gazebo resources
```

Docker is not the primary GUI validation environment.

---

## 30. Change-Specific Regression Requirements

### 30.1 Lifecycle changes

Validate:

```text
start
stop
reset
unexpected child exit
SIGTERM path
SIGKILL escalation path
repeat launch
port release
no child residue
```

### 30.2 Command-routing changes

Validate:

```text
every configured source
priority ordering
source timeout
zero on no source
emergency stop
finite-value rejection
velocity clamping
final controller topic
```

### 30.3 Mapping changes

Validate:

```text
valid map name
invalid map name
concurrent save rejection
timeout
map-saver failure
YAML and PGM creation
inventory publication
environment filtering
legacy-map handling
path containment
```

### 30.4 Localization changes

Validate:

```text
plain map selection
JSON map selection
environment mismatch
legacy fallback
missing YAML
missing PGM
path traversal
initial pose mode prerequisite
finite values
boolean rejection
covariance
selected-map clearing
```

### 30.5 Navigation changes

Validate:

```text
malformed JSON
missing fields
boolean values
non-finite values
bounds
server unavailable
goal rejection
goal acceptance
feedback
success
cancel before acceptance
cancel after acceptance
abort
safe stop
second-goal rejection
```

### 30.6 Dashboard changes

Validate:

```text
JavaScript syntax
WebSocket connection
every advertised topic
every advertised service
button enable/disable state
mode transitions
error display
reconnect behavior
keyboard release
emergency stop
```

### 30.7 Filesystem changes

Validate:

```text
relative paths
absolute paths
symlink escape
parent traversal
missing directory
permission failure
existing file
partial file
environment-aware location
```

---

## 31. Release Approval Checklist

### 31.1 Source

```text
[ ] exact commit recorded
[ ] tag target confirmed
[ ] working tree understood
[ ] git diff --check clean
[ ] no conflict markers
[ ] executable permissions correct
```

### 31.2 Build and automated tests

```text
[ ] scripts/build.sh passed
[ ] scripts/test.sh passed
[ ] 357 tests reported for the validated baseline
[ ] 0 errors
[ ] 0 failures
[ ] 0 skipped
[ ] launch regression passed
[ ] headless integration passed
[ ] lifecycle validation passed
```

### 31.3 Native runtime

```text
[ ] Warehouse starts
[ ] Warehouse stops cleanly
[ ] Hospital starts
[ ] Hospital stops cleanly
[ ] manual control works
[ ] source timeout stops motion
[ ] emergency stop works
[ ] mapping works
[ ] map saves
[ ] saved map selects
[ ] AMCL localizes
[ ] Nav2 goal succeeds
[ ] Nav2 goal cancels
[ ] success ends in zero command
[ ] cancellation ends in zero command
```

### 31.4 Recovery

```text
[ ] environment switches Warehouse -> Hospital
[ ] environment switches Hospital -> Warehouse
[ ] externally closed Gazebo produces error state
[ ] environment unlocks after unexpected exit
[ ] simulation restarts without dashboard restart
[ ] stale-process cleanup verified
```

### 31.5 Shutdown

```text
[ ] mode status stopped
[ ] simulation status stopped
[ ] no mode-owned lifecycle nodes
[ ] no Gazebo process
[ ] no duplicate manager
[ ] ports 8080 and 9090 released after launcher exit
[ ] launcher can start again
```

### 31.6 Docker and CI

```text
[ ] Docker image builds
[ ] Docker full gate passes
[ ] CI passes
[ ] local GUI scenarios pass
```

### 31.7 Documentation

```text
[ ] README release status correct
[ ] system architecture current
[ ] topic interface reference current
[ ] debugging and validation guide current
[ ] installation instructions current
[ ] media references current
[ ] limitations honest
[ ] validation claims reproducible
```

---

## 32. Minimal Daily Development Gate

For a small, isolated documentation or implementation change:

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

git diff --check
./scripts/check_syntax.sh
./scripts/build.sh
./scripts/test.sh
git status --short
```

This is still a substantial gate because `scripts/test.sh` includes the
registered tests and integration/lifecycle scripts.

For changes affecting GUI Gazebo behavior, also repeat the relevant manual
workflow.

---

## 33. Final Release Reproduction Sequence

Run from a clean, controlled checkout of the intended release revision:

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

git status --short
git rev-parse HEAD
git describe --tags --always --dirty

./scripts/clean.sh
./scripts/build.sh
./scripts/test.sh

docker build \
  --tag cpp-robotics-sim:v0.1.0 \
  .

docker run --rm \
  --name cpp-robotics-sim-v010-test \
  cpp-robotics-sim:v0.1.0 \
  bash -lc './scripts/test.sh'

git diff --check
git status --short
```

Then perform the documented manual runtime scenarios and the final shutdown
residue check.

---

## 34. Validation Boundaries

The `v0.1.0` validation does not establish:

- production safety certification;
- real-robot deployment readiness;
- deterministic hard real-time behavior;
- cybersecurity hardening for untrusted networks;
- hosted-CI GUI Gazebo coverage;
- dynamic-obstacle benchmarking;
- PS4 controller completion;
- arbitrary custom robot support;
- arbitrary custom planner/controller selection;
- formal verification of all state transitions.

The release is a validated simulation and development baseline, not a
production deployment platform.

---

## 35. Summary

The authoritative native gate is:

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

./scripts/build.sh
./scripts/test.sh
```

The authoritative Docker reproduction is:

```bash
cd ~/robotics_projects/cpp_robotics_sim_foundation

docker build \
  --tag cpp-robotics-sim:v0.1.0 \
  .

docker run --rm \
  --name cpp-robotics-sim-v010-test \
  cpp-robotics-sim:v0.1.0 \
  bash -lc './scripts/test.sh'
```

The validated baseline is:

```text
357 tests
0 errors
0 failures
0 skipped
```

Release confidence comes from the combination of:

```text
syntax validation
build success
registered tests
ament lint
GoogleTest
launch regression
headless dashboard integration
public launcher lifecycle validation
manual robotics workflows
safe-stop behavior
process cleanup
port release
Docker reproduction
honest documentation
```

No single test count replaces complete lifecycle and runtime validation.

---

## 36. Dashboard Singleton Admission

The dashboard launch admits one active AMR platform per Linux user. It holds
an exclusive kernel lock at ~/.ros/cpp_robotics_sim/web_interface.lock.
Duplicate launches are rejected before stale-process cleanup begins. The
kernel releases flock ownership if the owning process dies, while the PID
stored in the lock file is informational and is not authoritative ownership.
The current stale-process cleanup still uses legacy pattern-based matching;
its ownership limitations are deferred to the process-registry work.

<!-- RELEASE_MEDIA_START -->
## Release Media

- [Docker build and 357-test validation](https://www.youtube.com/watch?v=4M628CFYiz8)
- [Installation and first launch](https://www.youtube.com/watch?v=_x2Z7jXXnWw)
- [Complete v0.1.0 demonstration playlist](https://www.youtube.com/playlist?list=PLP_aJnUqSRf8)

The validated `v0.1.0` baseline includes 357 automated tests, launch
regression, headless dashboard integration, lifecycle validation, and clean
container removal.
<!-- RELEASE_MEDIA_END -->
