# Installation Guide

## C++ / ROS 2 Robotics Simulation Foundation

**Release:** `v0.1.0`
**Release commit:** `28a080e72ee6e31baa25bcd2fdaa249706520361`
**Supported host:** Ubuntu 24.04
**ROS distribution:** ROS 2 Jazzy
**Simulator:** Gazebo Harmonic

---

## 1. Purpose

This guide covers installation, first build, validation, and first launch of
`ros2-amr-platform` release `v0.1.0`.

The supported native setup is:

```text
Ubuntu 24.04
ROS 2 Jazzy
Gazebo Harmonic
colcon
rosdep
Docker optional
```

The project setup script supports Ubuntu 24.04 only and expects ROS 2 Jazzy
to already be installed.

---

## 2. Supported Environments

### Native Ubuntu 24.04

This is the primary supported environment.

### WSL2 with Ubuntu 24.04

WSL2 is supported for development when the Windows graphics and networking
environment can run Gazebo and open the dashboard.

The launcher detects the WSL network address and prints the dashboard URL.

### Docker

Docker is supported primarily for:

```text
build validation
syntax and lint validation
automated tests
reproducibility
```

The container is not the primary GUI Gazebo runtime entry point.

### Unsupported by the v0.1.0 setup script

```text
Ubuntu versions other than 24.04
non-Ubuntu Linux distributions
macOS native runtime
Windows native runtime without WSL2
ROS distributions other than Jazzy unless manually adapted
```

---

## 3. Hardware Guidance

Minimum practical development system:

```text
64-bit CPU
8 GB RAM
20 GB free disk space
graphics support capable of running Gazebo
internet access for initial dependency installation
```

Recommended:

```text
4 or more CPU cores
16 GB RAM
dedicated or modern integrated GPU
30 GB or more free disk space
```

GUI simulation performance depends on the host graphics stack, especially
under virtualization or WSL2.

---

## 4. Install Base Tools

Update the package index:

```bash
sudo apt update
```

Install common development tools:

```bash
sudo apt install -y \
  git \
  curl \
  wget \
  build-essential \
  cmake \
  python3 \
  python3-pip \
  python3-venv
```

The project setup script installs `python3-rosdep` when it is missing.

---

## 5. Install ROS 2 Jazzy

Install ROS 2 Jazzy for Ubuntu 24.04 using the official ROS 2 installation
instructions.

The project requires this setup file:

```text
/opt/ros/jazzy/setup.bash
```

Verify it:

```bash
test -f /opt/ros/jazzy/setup.bash \
  && printf 'ROS 2 Jazzy setup found.\n'
```

Source ROS 2:

```bash
source /opt/ros/jazzy/setup.bash
```

Verify the CLI:

```bash
ros2 --help >/dev/null
printf 'ROS 2 CLI available.\n'
```

The project setup script stops with an error when the Jazzy setup file is
missing.

---

## 6. Clone the Repository

```bash
git clone \
  https://github.com/Devansh-Mishra-30/ros2-amr-platform.git

cd ros2-amr-platform
```

For exact release reproduction:

```bash
git checkout v0.1.0
```

Verify:

```bash
git rev-parse HEAD
git describe --tags --always
```

Expected release commit:

```text
28a080e72ee6e31baa25bcd2fdaa249706520361
```

---

## 7. Run Project Setup

From the repository root:

```bash
./scripts/setup.sh
```

The setup script:

```text
verifies Ubuntu 24.04
verifies the configured ROS 2 setup file
installs python3-rosdep when missing
initializes rosdep when needed
updates the rosdep database
installs dependencies from ros2_ws/src
verifies colcon
verifies ros2
```

The script may request administrator privileges.

The configured ROS distribution can be overridden through:

```bash
ROS_DISTRO=<distribution> ./scripts/setup.sh
```

For the validated release, use:

```text
jazzy
```

A successful setup ends with:

```text
Setup completed successfully.
```

---

## 8. Build the Project

Use the project build script:

```bash
./scripts/build.sh
```

The script:

```text
runs source syntax validation
sources /opt/ros/jazzy/setup.bash
builds cpp_robotics_sim_ros
enables BUILD_TESTING
uses console_direct+ output
```

A successful build creates:

```text
ros2_ws/install/setup.bash
```

Verify:

```bash
test -f ros2_ws/install/setup.bash \
  && printf 'Workspace build available.\n'
```

Manual equivalent:

```bash
source /opt/ros/jazzy/setup.bash

cd ros2_ws

colcon build \
  --packages-select cpp_robotics_sim_ros \
  --cmake-args -DBUILD_TESTING=ON \
  --event-handlers console_direct+
```

Return to the repository root:

```bash
cd ..
```

---

## 9. Source the Workspace

For a new terminal:

```bash
source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash
```

Verify package discovery:

```bash
ros2 pkg prefix cpp_robotics_sim_ros
```

Optional shell convenience:

```bash
printf '\nsource /opt/ros/jazzy/setup.bash\n' >> ~/.bashrc
```

Avoid automatically sourcing a development workspace in `.bashrc` when you
regularly work with multiple ROS workspaces. Source the project workspace
explicitly instead.

---

## 10. Run the Full Validation Gate

After the workspace is built:

```bash
./scripts/test.sh
```

The release gate includes:

```text
Python syntax checks
JavaScript syntax checks
Bash syntax checks
registered ROS 2 tests
ament lint checks
GoogleTest
simulator launch regression
headless dashboard integration
public launcher lifecycle validation
```

The validated `v0.1.0` baseline is:

```text
357 tests
0 errors
0 failures
0 skipped
```

`test.sh` exits with an error when:

```text
ros2_ws/install/setup.bash
```

is missing.

Build before testing:

```bash
./scripts/build.sh
./scripts/test.sh
```

---

## 11. Run the Platform

From the repository root:

```bash
./scripts/run.sh
```

The launcher starts:

```text
dashboard HTTP server
rosbridge WebSocket
simulation manager
mode manager
mapping manager
localization manager
navigation goal manager
```

Default endpoints:

```text
Dashboard: http://localhost:8080
rosbridge: ws://localhost:9090
```

The dashboard launcher does not automatically start Gazebo.

From the dashboard:

```text
select Warehouse or Hospital
select Start
choose Manual, Mapping, Localization, or Navigation
```

---

## 12. First-Run Workflow

### Start the launcher

```bash
./scripts/run.sh
```

### Open the dashboard

```text
http://localhost:8080
```

Expected initial indicators:

```text
ROS connected
Safety state: READY
Simulation: stopped
```

### Select an environment

Choose:

```text
Warehouse
Hospital
```

### Start simulation

Select **Start**.

Expected runtime components include:

```text
Gazebo
robot_state_publisher
controller_manager
joint_state_broadcaster
diff_drive_controller
LiDAR bridge
command routing
```

### Select a mode

```text
Manual
Mapping
Localization
Navigation
```

Only one high-level operating mode is managed at a time.

---

## 13. Clean Shutdown

Use this order:

```text
stop the active mode
stop the simulation
wait for stopped status
exit the dashboard launcher with Ctrl+C
```

Do not close terminals or kill Gazebo as the normal shutdown method.

After shutdown, inspect:

```bash
ss -ltnp | grep -E ':8080|:9090' || true

pgrep -af \
  'ros2 launch|gz sim|gzserver|gzclient|ruby.*gz' \
  || true
```

After the launcher has exited, project-owned ports and processes should be
released.

---

## 14. Docker Installation and Validation

Build the image:

```bash
docker build \
  --tag cpp-robotics-sim:v0.1.0 \
  .
```

Run the full test gate:

```bash
docker run --rm \
  --name cpp-robotics-sim-v010-test \
  cpp-robotics-sim:v0.1.0 \
  bash -lc './scripts/test.sh'
```

Open an interactive shell:

```bash
docker run --rm -it \
  cpp-robotics-sim:v0.1.0 \
  bash
```

The Docker image is intended for development and test validation rather than
as a complete GUI launcher.

---

## 15. WSL2 Notes

### Dashboard URL

Under WSL2, `run.sh` detects the WSL network address and prints the complete
dashboard URL.

Use the printed URL when:

```text
http://localhost:8080
```

does not open from Windows.

### Graphics

Gazebo requires a functioning WSL graphics environment.

Check:

```bash
printf 'DISPLAY=%s\n' "${DISPLAY:-unset}"
printf 'WAYLAND_DISPLAY=%s\n' "${WAYLAND_DISPLAY:-unset}"
```

### Browser launch

The script can open the dashboard in the Windows browser when browser
launching is enabled.

### Network ports

Inspect:

```bash
ss -ltnp | grep -E ':8080|:9090' || true
```

### WSL restart

When the graphics or networking layer is corrupted, close project processes
cleanly, then restart WSL from Windows:

```powershell
wsl --shutdown
```

This is a host recovery step, not a normal project shutdown step.

---

## 16. Installation Verification

Run:

```bash
source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

printf '\n===== PACKAGE =====\n'
ros2 pkg prefix cpp_robotics_sim_ros

printf '\n===== EXECUTABLES =====\n'
ros2 pkg executables cpp_robotics_sim_ros | sort

printf '\n===== WORKSPACE =====\n'
test -f ros2_ws/install/setup.bash \
  && printf 'PASS  install/setup.bash\n'

printf '\n===== SYNTAX =====\n'
./scripts/check_syntax.sh
```

Then run:

```bash
./scripts/test.sh
```

A successful installation must support:

```text
package discovery
source syntax validation
workspace build
registered tests
launcher startup
dashboard connection
clean shutdown
```

---

## 17. Common Installation Failures

### Ubuntu version rejected

The setup script requires:

```text
Ubuntu 24.04
```

Check:

```bash
cat /etc/os-release
```

### ROS 2 setup file missing

Error condition:

```text
/opt/ros/jazzy/setup.bash not found
```

Install ROS 2 Jazzy before running project setup.

### `rosdep` initialization error

Inspect:

```bash
ls -l /etc/ros/rosdep/sources.list.d/
```

Then update:

```bash
rosdep update
```

Do not repeatedly run `sudo rosdep init` when the default source file already
exists.

### `colcon` missing

Check:

```bash
command -v colcon
```

The setup script verifies `colcon` after dependency installation.

### Package not found after build

Source both environments:

```bash
source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash
```

Then verify:

```bash
ros2 pkg prefix cpp_robotics_sim_ros
```

### Test script reports missing workspace

Run:

```bash
./scripts/build.sh
./scripts/test.sh
```

### Dashboard page opens but ROS is disconnected

Check:

```bash
ss -ltnp | grep -E ':8080|:9090'
ros2 node list
```

Confirm rosbridge and manager nodes are running.

### Port already occupied

Inspect:

```bash
ss -ltnp | grep -E ':8080|:9090' || true
```

Identify the owning process before terminating anything.

### Gazebo does not open

Check:

```text
graphics support
DISPLAY or WAYLAND_DISPLAY
Gazebo installation
WSL graphics integration
simulation logs
```

### Build state is stale

Run:

```bash
./scripts/clean.sh
./scripts/build.sh
```

The cleanup script removes generated workspace state but does not terminate
active runtime processes.

---

## 18. Updating an Existing Clone

Inspect current state:

```bash
git branch --show-current
git status --short
```

Do not pull over uncommitted work.

After preserving or committing local work:

```bash
git fetch origin
git pull --ff-only
```

Reinstall dependencies when package declarations change:

```bash
./scripts/setup.sh
```

Rebuild and retest:

```bash
./scripts/build.sh
./scripts/test.sh
```

---

## 19. Uninstall and Cleanup

Remove generated build products:

```bash
./scripts/clean.sh
```

Remove saved maps separately:

```bash
rm -rf ~/.ros/cpp_robotics_sim/maps
```

This permanently deletes user-generated maps.

Remove the local repository only after preserving any desired maps, logs, or
media:

```bash
cd ..
rm -rf ros2-amr-platform
```

Project setup installs system packages through `apt` and `rosdep`. Those
packages may be shared by other ROS projects and should not be removed
blindly.

---

## 20. Security and Safety Notes

The dashboard and rosbridge are intended for local development.

Do not expose ports:

```text
8080
9090
```

to an untrusted network without additional security controls.

The release does not provide:

```text
authentication
authorization
TLS termination
production network hardening
real-robot safety certification
```

Always stop the active mode and simulation before ending a runtime session.

---

## 21. Installation Checklist

```text
[ ] Ubuntu 24.04 confirmed
[ ] ROS 2 Jazzy installed
[ ] /opt/ros/jazzy/setup.bash exists
[ ] repository cloned
[ ] correct tag or branch selected
[ ] scripts/setup.sh passed
[ ] scripts/build.sh passed
[ ] ros2_ws/install/setup.bash exists
[ ] package is discoverable
[ ] scripts/test.sh passed
[ ] dashboard starts
[ ] ports 8080 and 9090 are available
[ ] simulation starts
[ ] launcher shuts down cleanly
```

---

## 22. Quick Reference

First installation:

```bash
git clone \
  https://github.com/Devansh-Mishra-30/ros2-amr-platform.git

cd ros2-amr-platform

git checkout v0.1.0

./scripts/setup.sh
./scripts/build.sh
./scripts/test.sh
./scripts/run.sh
```

Daily use:

```bash
source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash
./scripts/run.sh
```

Rebuild after source changes:

```bash
./scripts/build.sh
./scripts/test.sh
```

Clean generated state:

```bash
./scripts/clean.sh
./scripts/build.sh
```

---

## 23. Related Documentation

```text
README.md
docs/system_architecture.md
docs/topic_interface_reference.md
docs/debugging_and_validation.md
```

The README contains the user workflow, capabilities, media, and release
overview.

The architecture document describes runtime composition and ownership.

The interface reference defines topics, services, actions, payloads, and TF.

The debugging guide defines validation and failure-recovery procedures.

---

<!-- RELEASE_MEDIA_START -->
## Release Media

- [Installation and first-launch walkthrough](https://www.youtube.com/watch?v=_x2Z7jXXnWw)
- [Project teaser](https://www.youtube.com/watch?v=zKf_hjIYtlk)
- [Complete v0.1.0 demonstration playlist](https://www.youtube.com/playlist?list=PLP_aJnUqSRf8)

Release screenshots are stored in [`docs/media/v0.1.0`](media/v0.1.0).
<!-- RELEASE_MEDIA_END -->
