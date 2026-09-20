# Project

This repository is an autonomous mobile robot (AMR) simulation, orchestration, and verification platform. The verified primary environment is Ubuntu 24.04 with ROS 2 Jazzy and Gazebo Harmonic.

The current stack includes ROS 2 Jazzy with `ament_cmake`/colcon, Gazebo Harmonic through `ros_gz_sim` and `ros_gz_bridge`, `ros2_control` and `gz_ros2_control`, SLAM Toolbox, AMCL, Nav2, rosbridge, a browser dashboard, C++17, Python, Bash, Docker, and GitHub Actions on Ubuntu 24.04.

# Repository Layout

- `ros2_ws/`: ROS 2 workspace. Generated `build/`, `install/`, and `log/` contents are not source.
- `ros2_ws/src/cpp_robotics_sim_ros/`: primary and currently sole ROS 2 package.
  - `src/` and `include/`: C++ simulation implementation and public headers.
  - `scripts/`: installed Python manager nodes and package-level diagnostic shell tools.
  - `launch/`: simulation, dashboard, visualization, mapping, localization, and navigation launch files.
  - `config/` and `nav2/`: manager, controller, localization, mapping, environment, and Nav2 configuration.
  - `urdf/`, `xacro/`, `worlds/`, `maps/`, and `rviz/`: robot and simulation assets.
  - `web/dashboard/`: browser dashboard HTML, CSS, and JavaScript.
  - `test/`: Python behavior tests and C++ GoogleTest coverage.
- `scripts/`: repository-level setup, build, run, cleanup, and validation entry points.
- `docs/`: installation, architecture, interface, debugging, validation, media, and release-planning material.
- `.github/workflows/ros2_jazzy_ci.yml`: native ROS 2 and Docker CI workflow.

# Architecture

Use `docs/system_architecture.md` and `docs/topic_interface_reference.md` as the architectural and interface sources of truth for the established v0.1.0 system. Do not redesign the system while performing a scoped task.

The normal runtime path is `./scripts/run.sh`, which sources ROS 2 and the built workspace, then launches `cpp_robotics_sim_ros/web_interface.launch.py`. The web launch owns the dashboard HTTP server, rosbridge WebSocket endpoint, and the simulation, mode, mapping, localization, and navigation manager layer. The dashboard publishes requests and commands and presents ROS 2 state; it does not implement the robotics algorithms.

The mode manager keeps manual, mapping, localization, and navigation modes mutually exclusive. Supported velocity sources pass through the command multiplexer before reaching `diff_drive_controller`. Simulation, mode, and dashboard processes have explicit lifecycle owners. Environment-specific maps live outside the repository by default. Preserve the documented TF ownership model, especially ownership of `map -> odom` and `odom -> base_link` in each operating mode.

# Engineering Principles

- Inspect the existing implementation before changing it.
- Make the smallest change that satisfies the requirement.
- Preserve the established architecture unless a change is justified by the requirement.
- Avoid unrelated refactors and opportunistic cleanup.
- Preserve existing behavior unless the requirement intentionally changes it.
- Preserve ROS topics, services, actions, frames, message types, QoS, and configuration contracts unless intentionally changing them.
- Preserve TF ownership assumptions unless intentionally changing them.
- Never silently remove functionality or hide failures.
- Never fabricate validation results or claim a test passed when it was not run.
- Never weaken, disable, or bypass a test merely to make CI pass.
- Add or update tests when behavior changes.
- Update documentation when interfaces, runtime behavior, or architecture change.

# Git Workflow

- Before editing, verify the current branch and working-tree state.
- If unrelated pre-existing changes are present, do not overwrite, revert, stage, or incorporate them without explicit instruction.
- `master` represents stable, integrated work. Do not implement features directly on `master`.
- Use focused feature, fix, chore, or test branches.
- Keep one bounded scope per branch where practical.
- Do not force push unless explicitly instructed.
- Do not merge automatically.
- Inspect `git status` and `git diff` before concluding work.
- Report every modified file.
- Do not commit generated build, install, log, cache, coverage, bag, or local-map artifacts.
- Do not commit or push changes unless explicitly instructed.

# Agent Task Workflow

For each coding task, generally:

1. Inspect the repository and relevant implementation.
2. Understand and state current behavior.
3. State the proposed change and its boundaries.
4. Identify affected files and interfaces.
5. Implement the minimal change.
6. Add or update appropriate tests.
7. Run targeted validation first.
8. Run broader validation when the scope or risk warrants it.
9. Inspect `git status` and the complete relevant diff.
10. Summarize changes and validation honestly.
11. Report risks, limitations, and remaining questions.

# Validation Ladder

Choose validation in proportion to the change:

fast local or targeted validation -> relevant package tests -> build -> integration/regression -> full release validation

- `./scripts/check_syntax.sh`: fast source gate. Runs Python byte-compilation, Node JavaScript syntax checks, and `bash -n` over discovered source files.
- `./scripts/build.sh`: runs `check_syntax.sh`, sources ROS 2, and performs a package-selective colcon build for `cpp_robotics_sim_ros`.
- `./scripts/test.sh`: full native automated gate. It reruns `check_syntax.sh`, runs the package's registered colcon/ament tests and `colcon test-result --verbose`, then calls `launch_regression.sh`, `headless_smoke_test.sh`, and `run_lifecycle_test.sh`. Do not run those scripts again after a successful `test.sh` unless isolating a failure or collecting specific evidence.
- `./scripts/launch_regression.sh`: launches `sim.launch.py` and verifies expected nodes/topics, default and overridden parameters, published state, command response, diagnostics, and process handling.
- `./scripts/headless_smoke_test.sh`: launches `web_interface.launch.py` without opening a browser and verifies the dashboard HTTP server, rosbridge port, and manager status topics.
- `./scripts/run_lifecycle_test.sh`: exercises the public `scripts/run.sh` entry point, verifies HTTP, rosbridge, and topics, sends SIGINT, and checks process-group cleanup and port release.

Use targeted tests for small validation-rule or core-math changes. Use `build.sh` for C++, CMake, package metadata, install rules, or install-space changes. Launch, lifecycle, command-routing, dashboard, mapping, localization, navigation, or TF changes warrant the matching integration gate; use `test.sh` when a change crosses subsystems or is release-relevant. Docker, dependency, or CI changes require the affected native path and relevant Docker/CI-equivalent validation. Documentation-only changes normally require document and link inspection, not runtime gates.

Consult `docs/debugging_and_validation.md` for exact commands, failure triage, change-specific regression requirements, and release validation. Do not run the entire expensive validation stack after every small edit.

# Definition of Done

A task is not complete merely because code exists. Depending on scope, completion includes:

- the required implementation with no unrelated changes;
- appropriate automated tests or a clear reason tests were not applicable;
- successful relevant validation, reported with exact commands and outcomes;
- no unexplained regressions or hidden failures;
- documentation updates when interfaces, architecture, or operator behavior change;
- review of git status and the final diff;
- a concise engineering report covering changes, evidence, risks, and limitations.

# Safety / Do Not

Do not:

- delete large subsystems without explicit instruction;
- rewrite the architecture because another design seems preferable;
- modify generated `build/`, `install/`, `log/`, cache, or coverage directories as source;
- commit generated artifacts;
- bypass CI failures or conceal failing output;
- disable or weaken failing tests without documented technical justification;
- claim tests passed when they were skipped, unavailable, or failed;
- perform large opportunistic cleanups during a scoped task;
- casually change ROS topic, service, action, message, QoS, or frame contracts;
- introduce duplicate TF publishers or violate documented transform ownership;
- write saved runtime maps into the repository unless the task explicitly requires a reviewed fixture.

# Roadmap Discipline

`docs/AMR_Release_Verification_Tracker.xlsx` is project-level roadmap and release-verification planning information. Treat it as planning context, not authorization to implement listed work.

Do not attempt to implement an entire release or the complete roadmap in one agent task. Break future work into bounded requirements or features. One coding task should normally address one focused engineering objective with its own acceptance criteria and validation.

Do not modify `docs/AMR_Release_Verification_Tracker.xlsx` unless explicitly instructed. Do not mark requirements, tests, or releases complete solely because implementation code exists; completion requires the defined verification evidence.

# Learning Handoff

After significant implementation work, summarize:

- what changed and why;
- key files, classes, functions, nodes, and launch/config entries;
- ROS 2 concepts involved;
- software engineering concepts involved;
- important runtime behavior and interface effects;
- tests and validation performed, including anything not run;
- risks, limitations, and remaining questions.

The repository owner intends to review and learn the code after agentic implementation. Explanations should support code review and understanding rather than replace inspection of the implementation.
