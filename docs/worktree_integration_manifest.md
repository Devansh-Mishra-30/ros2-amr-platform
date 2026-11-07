# AMR Worktree Integration Manifest

Audit date: 2026-11-06

This manifest records the seven worktrees registered for
`ros2-amr-platform`. The audit was read-only. No worktree content was merged,
copied, deleted, reset, rebased, or staged. All uncommitted files remain in
their original worktrees.

| Worktree | Branch and HEAD | Dirty state | Intended release | Reuse value | Integration dependencies |
| --- | --- | --- | --- | --- | --- |
| `/home/devansh/robotics_projects/ros2-amr-platform` | `docs/v0.1.3-final-consolidation` at `16d3f0d` | Consolidation edits plus owner review workbook left untracked | v0.1.3 repository consolidation | Canonical release documentation, tracker, and GitHub metadata reconciliation | Owner review, commit, push, and PR only; do not include the owner review copy unless explicitly approved |
| `/home/devansh/robotics_projects/ros2-amr-antigravity-v015` | `research/antigravity-v015-sensor-tf` at `7764c36`; 3 commits behind `master`, 0 ahead | Untracked sensor/TF execution package, static inventory, and five Python tool/test files | v0.1.5 | Static sensor/TF inventory and audit prototypes | Rebase or port from accepted v0.1.3 only after v0.1.4 contract decisions; validate tool assumptions against current TF ownership |
| `/home/devansh/robotics_projects/ros2-amr-forward-planning` | `planning/v0.1.4-v0.1.6` at `9f8072a`; 5 commits behind `master`, 0 ahead | Modified package `CMakeLists.txt`; untracked v0.1.4–v0.2 plans, harness, tests, and bootstrap tool | v0.1.4 primarily; later planning through v0.2 | Deterministic harness, test skeletons, staging and porting manifests | Preserve every uncommitted file; base production work on v0.1.3; port isolated harness files; resolve CMake test registration deliberately |
| `/home/devansh/robotics_projects/ros2-amr-review` | `review/v0.1.3` at `7764c36`; 3 commits behind `master`, 0 ahead | Untracked v0.1.3–v0.1.12 acceptance oracles, fault matrix, clock contract, and review tools | Cross-release verification | Acceptance-oracle drafts and evidence-analysis utilities | Review against the published v0.1.3 contracts; integrate per release, not wholesale; keep stale runtime source out |
| `/home/devansh/robotics_projects/ros2-amr-robotics-research` | `research/sensor-tf-ekf` at `7764c36`; 3 commits behind `master`, 0 ahead | Untracked v0.1.5–v0.1.12 research plans, metrics contracts, and 10 Python tool/test files | v0.1.5–v0.1.12 | Metrics, EKF ingestion/benchmarking, AMCL/Nav2 reliability research | Requires accepted v0.1.4 admission behavior, declared TF ownership, identified ground truth, and per-release scope review |
| `/home/devansh/robotics_projects/ros2-amr-tracker` | `release/tracker-maintenance` at `7764c36`; 3 commits behind `master`, 0 ahead | Untracked release-governance documents, evidence schemas/manifests, tracker patch utilities, and tests | Tracker and release governance across v0.1.3–v0.1.12 | Evidence schema, validation tools, artifact manifests, and tracker backfill proposals | Compare with the reconciled canonical tracker first; migrate only validated records and formulas; never overwrite historical evidence |
| `/home/devansh/robotics_projects/ros2-amr-v013` | `feature/v0.1.3-readiness-contracts` at `8d5f05a`; 1 merge commit behind `master`, 0 ahead | Four untracked failed-attempt evidence directories; branch otherwise matches its remote | v0.1.3 historical worktree | Historical failed-attempt evidence and original feature-branch context | Preserve in place; the published tag and `master` are authoritative; integrate nothing without a separate evidence review |

## Unique artifact inventory

### v0.1.5 sensor and TF research

- `docs/v0.1.5_sensor_tf_execution_package.md`
- `docs/v0.1.5_static_sensor_tf_inventory.md`
- `tools/sensor_health_analysis.py` and its tests
- `tools/tf_ownership_audit.py` and its tests

### v0.1.4 forward planning and harness

- Planning and staging documents for v0.1.4 through v0.2.
- `test/test_support/v014_harness.py`
- Harness utility and mode-transition skeleton tests.
- Modified `CMakeLists.txt` registration and `tools/bootstrap_v014.sh`.

### Verification worktree

- Acceptance-oracle drafts for v0.1.3 through v0.1.12.
- Clock readiness review contract and v0.1.11 fault matrix.
- Clock-evidence and fault-scenario analysis tools with tests.

### Robotics research worktree

- Cross-release integration, sensor, EKF, AMCL, Nav2, and CI research plans.
- Robotics metric, EKF, and AMCL analysis tools with tests.

### Tracker maintenance worktree

- Evidence provenance, schema, release-management, and artifact-integration documents.
- Evidence creation/finalization/validation tools and tests.
- Tracker patch and release-scope manifests.

### v0.1.3 historical worktree

- Four untracked failed-attempt evidence directories dated 2026-09-25 and
  2026-09-26. These are not part of the published release evidence set.

## Recommended integration order

1. Merge this consolidation after owner review.
2. Reconcile the forward-planning worktree against tag `v0.1.3` without
   overwriting its uncommitted files.
3. Port and validate the v0.1.4 harness separately from feature implementation.
4. Review acceptance-oracle and tracker-governance artifacts per release.
5. Defer sensor/TF/EKF/AMCL/Nav2 research integration until its prerequisite
   contracts and ground-truth sources are accepted.
