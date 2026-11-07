# GitHub Consolidation Report

Audit date: 2026-11-06

## Release consistency

- `master` and `origin/master` were at merge commit
  `16d3f0dc28b1cd7ab0f90a095fd531a694b06b7b` when this branch was created.
- Annotated tag `v0.1.3` points to that commit. The tag object was not modified.
- GitHub release `AMR Platform v0.1.3 — Readiness Contracts` is published and
  is neither a draft nor a prerelease.
- `package.xml` reports version `0.1.3`.
- GitHub Actions run `42301211782` passed the native ROS 2 and Docker jobs for
  the release commit.
- Historical evidence directories and their captured metadata were not edited.

## Documentation consolidation

- README release status, commands, architecture, lifecycle/readiness summary,
  validation evidence, limitations, release history, roadmap boundary, and
  documentation navigation were reconciled.
- The nonexistent local Docker helper commands were replaced with the actual
  `docker build` and `docker run` commands used by CI.
- The topic/interface reference now identifies the published v0.1.3 commit.
- Release notes now distinguish local acceptance from release-commit CI.
- The manual release checklist is clearly labeled as a completed historical
  procedure, and the v0.1.4 handoff records that v0.1.3 is published.
- v0.1.0 installation, architecture, and debugging documents remain explicitly
  historical; their evidence and media references were not rewritten.

## Tracker reconciliation

- The owner review copy differed from the canonical workbook in two cached
  status values and one additional `v013_Closure` worksheet. No existing
  formula differed.
- The canonical workbook now records v0.1.3 as Released on `Release_Plan` and
  Dashboard.
- All existing feature, requirement, test, defect, metric, risk, and gate IDs
  were preserved.
- v0.1.3 records remain: 10/10 features Done, 10/10 requirements Verified,
  17/17 catalog tests Passed, 4/4 gates Passed, and zero open Critical defects.
- Six release-level Evidence records index the published release, final
  candidate metadata and acceptance, release-commit CI, defect disposition,
  and release notes.
- `Test_Executions` remains empty. Existing evidence is aggregate and does not
  support truthful one-row-per-test execution reconstruction.
- The dashboard labels feature progress separately from catalog test pass and
  release-gate progress.
- Saved-workbook checks found no broken v0.1.3 traceability and no formula-error
  values. The three existing dashboard charts remain present.

## Repository hygiene

- `.gitignore` covers generated ROS/colcon output, caches, bags, logs, local
  data, IDE files, secrets, and Windows download metadata.
- `.dockerignore` excludes generated and documentation content while retaining
  `docs/readiness_contracts.md`, which is required by a Docker test.
- `.gitattributes` normalizes text to LF and marks binary engineering artifacts,
  including `.xlsx`, as binary.
- The MIT license, package metadata, contribution templates, and CI workflow are
  present.
- No generated build, install, log, cache, bytecode, or Zone.Identifier file is
  tracked.
- Generated build/install/log directories exist locally but are ignored and
  were not modified.
- The owner review workbook remains untracked and preserved for comparison.

## CI timing investigation

The successful pull-request native job `128056103833` took 3 h 49 min. Its
`rosdep install` step consumed 3 h 27 min (18:12:07–21:39:07 UTC). The
release-commit native job `128179195097` completed in 4 min 36 s, with the same
step taking 2 min 11 s. The Docker job independently built the image and ran the
complete test suite.

This points to a transient package-resolution or mirror delay rather than a
stable workflow cost. The smallest safe recommendation is to retain both jobs,
monitor recurrence, and if it repeats add a bounded timeout plus one retry to
the native `rosdep install` step. Do not remove native dependency resolution or
tests: Docker is equivalent for much of build/test coverage, but it does not
replace native-host setup validation. `master` currently has no GitHub branch
protection rule, so required-check enforcement should be configured before any
future reduction or restructuring of CI.

## Validation performed

- Git tag/object and release-commit comparison.
- GitHub release, tag, Actions runs, job timings, and branch protection query.
- Package version and repository hygiene inspection.
- Workbook formula, ID, traceability, gate, defect, evidence, chart, and visual
  checks.
- Markdown local-link validation.
- `git diff --check` and documentation/source syntax checks.

Runtime robotics tests were not rerun because this branch changes documentation
and the engineering tracker only; no runtime source, launch, configuration,
interface, or CI workflow file changed.

## Owner-reviewed commit and PR commands

Review the untracked owner workbook before using `git add`; the commands below
stage only the intended consolidation files.

```bash
cd /home/devansh/robotics_projects/ros2-amr-platform
git branch --show-current
git status --short --branch
git diff --check
git diff -- README.md docs

git add README.md \
  docs/AMR_Release_Verification_Tracker.xlsx \
  docs/github_consolidation_report.md \
  docs/worktree_integration_manifest.md \
  docs/topic_interface_reference.md \
  docs/v0.1.3_release_notes.md \
  docs/v0.1.3_manual_release_checklist.md \
  docs/v0.1.4_handoff.md

git diff --cached --check
git diff --cached --stat
git status --short --branch
git commit -m "docs: consolidate v0.1.3 repository state"
git push -u origin docs/v0.1.3-final-consolidation

gh pr create \
  --base master \
  --head docs/v0.1.3-final-consolidation \
  --title "Consolidate published v0.1.3 repository state" \
  --body-file .github/PULL_REQUEST_TEMPLATE.md
gh pr checks --watch
```

Replace the pull-request template prompts with the actual summary, validation,
limitations, and tracker reconciliation before submitting it.
