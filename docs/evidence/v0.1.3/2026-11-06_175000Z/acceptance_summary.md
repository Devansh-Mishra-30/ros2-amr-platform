# v0.1.3 Docker CI correction

GitHub Actions run `42262268075`, job `128044996204`, built the Docker image successfully and failed while executing the complete test suite inside the container.

The failing workflow command was:

```bash
docker run --rm --init --network host \
  --name cpp-robotics-sim-ci-test \
  cpp-robotics-sim:ci \
  bash -lc 'cd /workspace && ./scripts/test.sh'
```

CTest target `test_readiness_contract` failed at `test_profile_blocking_selection_matches_declared_dependencies` with `FileNotFoundError: /workspace/docs/readiness_contracts.md`. The readiness contract test introduced in v0.1.3 validates that documented profile dependencies match the implementation. The existing `.dockerignore` excluded all of `docs/`, so the file was absent only in the Docker build context.

The correction keeps documentation excluded by default while including only `docs/readiness_contracts.md`. No lifecycle, readiness, process-ownership, production, test, Dockerfile, dependency, or workflow behavior changed.

Local verification after the correction:

- Affected readiness test: 24 passed.
- Complete suite: 565 tests, 0 errors, 0 failures, 0 skipped.
- CTest: 26/26 targets passed.
- Syntax checks: 48 Python, 1 JavaScript, and 13 Bash files passed.
- Launch regression, headless dashboard integration, and public launcher lifecycle: passed.
- Local Docker execution was unavailable because Docker Desktop WSL integration was not enabled; the pushed GitHub Actions Docker job is the authoritative container verification.

The original `2026-11-06_171445Z` runtime evidence remains immutable because this correction does not change runtime code or acceptance behavior. `correction.patch` binds this supplemental record to the exact source change relative to commit `d7cf27bfb0d1af7b8d38da44b7fdea9b49e68e65`.
