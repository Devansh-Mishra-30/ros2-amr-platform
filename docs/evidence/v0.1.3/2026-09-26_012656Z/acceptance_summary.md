# v0.1.3 Release-Candidate Acceptance — 2026-09-26 01:26:56 UTC

**Decision: ACCEPTED by the existing v0.1.3 oracle.**

## Validation

- Focused regression checks: 2 passed, including the goal cancellation terminal-state contract and readiness probe identity regression.
- `./scripts/build.sh`: passed. The installed workspace contains the corrected probe construction.
- `./scripts/test.sh`: passed; 563 package tests, 0 errors/failures/skips, plus launch regression, headless dashboard, and public launcher lifecycle integrations.
- `git diff --check`: passed.

## Runtime acceptance

One fresh full acceptance on the corrected install completed with **34/34 checks passing** and no remaining blockers. It exercised simulation, mapping, localization, and navigation readiness; dependency blocking and recovery; lifecycle/readiness separation; profile completeness; rollback and reactivation; mapping save and localization pose workflows; a real accepted navigation goal and cancellation by deactivation; cleanup; process registry emptiness; and critical node uniqueness. Each REQ-021..REQ-030 and TC-0026..TC-0042 has an evidence mapping in `metadata.json`. MET-005 measured 0 against a target of 0. The tracker workbook was not modified.

## Process and graph evidence

The process registry was empty after cleanup; the post-acceptance process scan found no managed ROS/Gazebo processes. The required manager counts were exactly one each, and no duplicate critical nodes were observed. The graph report does show five `/simulation_readiness_probe` entries, which are noncritical internal probe nodes and are excluded by the existing critical-node oracle. This bundle records that limitation explicitly; it does not claim all graph names are unique.

## Identity and environment

Branch `feature/v0.1.3-readiness-contracts`; HEAD/base `7764c3683387c966873e00195d0417810624f33c`; dirty working tree; Ubuntu 24.04.4 LTS, ROS 2 Jazzy, `rmw_fastrtps_cpp`, ROS domain 86, WSL2 kernel 6.6.87.2. The tracked source patch and untracked source archive are hashed in `metadata.json`. No commit, push, or tag was made.
