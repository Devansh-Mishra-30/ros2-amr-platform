# v0.1.3 Final Candidate Acceptance — 2026-11-06 17:14:45 UTC

This bundle records fresh verification of the final local v0.1.3 candidate on Ubuntu 24.04, ROS 2 Jazzy, Gazebo Harmonic, ROS domain 90, and `rmw_fastrtps_cpp`.

- Syntax: 48 Python, 1 JavaScript, and 13 Bash files passed.
- Build: passed.
- Test suite: 565 tests across 26 CTest targets; 0 failures, errors, or skips.
- Launch regression, headless dashboard integration, and public launcher lifecycle: passed.
- Runtime acceptance: 34/34 checks passed; decision `ACCEPTED`.
- Final process registry and post-run managed-process scan: empty.

`source_candidate.patch` binds the staged candidate before this evidence directory was added. `metadata.json` records its SHA-256 and the exact reconciliation rule for the future release commit. Raw runtime files are preserved without modification under `runtime_acceptance/`.

The acceptance driver writes to a historical `v0.1.2` runtime path; that directory label is retained as raw provenance and does not change the tested package version (`0.1.3`). This bundle does not claim physical-hardware validation.
