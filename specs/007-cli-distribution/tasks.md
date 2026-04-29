# Tasks: CLI Distribution Packaging & Publishing

**Input**: Design documents from `specs/007-cli-distribution/`
**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `checklists/requirements.md`

## Phase 1: Setup & Release Readiness

**Purpose**: Resolve release assumptions before changing workflows.

- [ ] T001 [US3] Verify PyPI package-name availability or ownership for `gh-address-cr`; record the result in `specs/007-cli-distribution/research.md` under a dated "Package Name Verification" note and stop for a naming decision if unavailable. Covers FR-006, SC-003, CHK003.
- [ ] T002 [US3] Decide whether `.github/workflows/release.yml` should use a protected `pypi` GitHub environment for Trusted Publishing approval. Covers FR-008, CHK004.
- [ ] T003 [US1] Define the installed smoke command result contract in tests/docs: dependency/import success required; missing-session domain failures allowed only as structured/documented CLI output. Covers FR-003, FR-004, CHK007, CHK011.
- [ ] T004 [US3] Define the package version synchronization mechanism for semantic-release and Python artifacts, including where the release version is injected or derived before build. Covers FR-013, SC-006, CHK015.
- [ ] T005 [US3] Define the dry-run/TestPyPI/staging publishing validation path and its success criteria before production PyPI publishing is enabled. Covers SC-003, CHK019.

---

## Phase 2: Package Metadata & Dependency Closure (P1)

**Goal**: Ensure the runtime CLI package installs with all dependencies and enough metadata for PyPI.

**Independent Test**: Build the package, install the wheel into a clean venv, and run installed CLI smoke commands without missing imports or tracebacks.

- [ ] T006 [US1] Add all runtime dependencies to `pyproject.toml`, including `packaging`, and verify no installed command imports undeclared third-party modules. Covers FR-001, SC-001, CHK002.
- [ ] T007 [US1] Add PyPI-ready package metadata to `pyproject.toml` (`readme`, `license`, Python classifiers, project URLs, and maintainer/author fields where available). Supports FR-005, FR-008, CHK024.
- [ ] T008 [US1] Add or extend packaging tests to prove installed runtime commands expose required modules and console entrypoints. Covers FR-002, FR-003, SC-001.

**Checkpoint**: A clean wheel install can run `gh-address-cr --help`, `python -m gh_address_cr --help`, and `gh-address-cr agent manifest`.

---

## Phase 3: CI Package Gate (P1)

**Goal**: Make PR validation catch packaging, dependency, and installed-entrypoint regressions.

**Independent Test**: CI build logs show separate build, install, and installed-smoke stages.

- [ ] T009 [P] [US2] Update `.github/workflows/ci.yml` to build wheel and sdist artifacts using the standard Python build flow. Covers FR-002, SC-002, CHK005, CHK017.
- [ ] T010 [P] [US2] Add a clean-environment wheel install step in CI after artifact build. Covers FR-002, SC-002.
- [ ] T011 [P] [US2] Add installed CLI smoke commands in CI: `gh-address-cr --help`, `python -m gh_address_cr --help`, `gh-address-cr agent manifest`, `gh-address-cr agent orchestrate status owner/repo 123`, and `gh-address-cr final-gate owner/repo 123`. Covers FR-003, FR-004, SC-001, CHK016, CHK029.
- [ ] T012 [US2] Ensure CI output labels or step names distinguish build, install, and installed-smoke failures. Covers SC-002, CHK017.

**Checkpoint**: Pull requests fail fast when wheel build, wheel install, or installed CLI smoke fails.

---

## Phase 4: Release Workflow & PyPI Publishing (P1)

**Goal**: Publish the runtime CLI package to PyPI through Trusted Publishing while preserving semantic-release for versioning and release notes.

**Independent Test**: Release workflow can build dist artifacts and reach a Trusted Publishing dry-run/staging validation path before production enablement.

- [ ] T013 [US3] Update `.github/workflows/release.yml` permissions for PyPI Trusted Publishing (`id-token: write`) and keep semantic-release release-note/tag behavior intact. Covers FR-005, FR-007, CHK012.
- [ ] T014 [US3] Add release workflow version synchronization before artifact build and fail if wheel/sdist metadata does not match the semantic-release version. Covers FR-013, SC-006, CHK015.
- [ ] T015 [US3] Add release workflow steps to build wheel/sdist artifacts after version synchronization and before any publish step. Covers FR-005, FR-013, CHK005.
- [ ] T016 [US3] Add `pypa/gh-action-pypi-publish` production publishing step using Trusted Publishing, with no long-lived PyPI API token fallback. Covers FR-005, FR-008, CHK004.
- [ ] T017 [US3] Implement the release workflow dry-run/TestPyPI/staging validation path before production publishing is enabled, ensuring the validation path builds artifacts, resolves OIDC credentials, and does not modify production PyPI. Covers SC-003, CHK019.
- [ ] T018 [US3] Gate or document production publishing until PyPI project ownership and Trusted Publishing configuration are verified. Covers FR-006, FR-008, CHK019.
- [ ] T019 [US3] Document release recovery policy for failed or partially completed PyPI publishes, including immutable artifact names and follow-up version guidance. Covers FR-009, CHK021, CHK022.
- [ ] T020 [US3] Clarify in release docs/comments that GitHub Releases are release-note/source-archive surfaces, while PyPI is the only stable package registry. Covers FR-007, CHK008, CHK009.

**Checkpoint**: Release workflow has explicit build-before-publish and Trusted Publishing semantics.

---

## Phase 5: Installation Documentation (P2)

**Goal**: Give users separated, copy-pasteable installation paths for runtime CLI, validation, development, and packaged skill usage.

**Independent Test**: README installation commands can be followed verbatim and include post-install smoke commands.

- [ ] T021 [US4] Add README section for released runtime CLI installation via `pipx install gh-address-cr`, including Python `>=3.10` expectation and `gh-address-cr --help` smoke. Covers FR-010, FR-011, SC-004, CHK010.
- [ ] T022 [US4] Add README section for released runtime CLI installation via `uv tool install gh-address-cr`, including post-install smoke. Covers FR-010, FR-011, SC-004, CHK010.
- [ ] T023 [US4] Add README section for GitHub-direct runtime validation install, clearly marked as pre-release/manual validation rather than the stable channel. Covers FR-010, SC-004, CHK006, CHK020.
- [ ] T024 [US4] Add README section for local editable development install (`python3 -m pip install -e .`) and keep it separate from end-user install paths. Covers FR-010, CHK006, CHK020.
- [ ] T025 [US4] Keep packaged skill installation documented separately with `npx skills add ... --skill gh-address-cr`, state that it does not replace the runtime CLI package, and include upgrade/reinstall guidance for users moving from skill-shim usage to `pipx` or `uv tool` runtime installation. Covers FR-010, FR-014, SC-005, SC-007, CHK001, CHK013, CHK018, CHK023.
- [ ] T026 [US4] Add README troubleshooting notes for unsupported Python versions, missing PyPI package, missing Trusted Publishing, stale artifact versions, skill-shim migration confusion, and users confusing skill install with CLI install. Covers FR-012, FR-013, FR-014, CHK021, CHK025, CHK026.

**Checkpoint**: README distinguishes runtime CLI distribution from packaged skill installation and local development setup.

---

## Phase 6: Verification & Closure

**Purpose**: Prove implementation and docs match the 007 contract.

- [ ] T027 Run `ruff check src tests` and fix any introduced issues.
- [ ] T028 Run `python3 -m unittest discover -s tests`.
- [ ] T029 Run local package build (`python3 -m build` or CI-equivalent build command).
- [ ] T030 Verify built wheel/sdist metadata version matches the semantic-release version source used for release validation, then install the built wheel into a clean venv and run the installed smoke command set from FR-003. Covers SC-001, SC-006, CHK015, CHK016.
- [ ] T031 Re-run or manually evaluate `specs/007-cli-distribution/checklists/requirements.md` and check off satisfied CHK items. Covers CHK027, CHK028, CHK029.
- [ ] T032 Record any production-only remaining action, such as enabling PyPI Trusted Publishing in the PyPI UI, as explicit release notes rather than hidden tribal knowledge. Covers FR-008, FR-009.

## Dependencies & Execution Order

- T001 must be completed before enabling production PyPI publishing.
- T003 must be completed before CI smoke assertions are finalized.
- T004 must be completed before T014/T015 can safely publish release artifacts.
- T005 must be completed before T017 can claim staging or dry-run coverage.
- T006 must be completed before T010/T011 can pass.
- T009, T010, T011, and T012 form the PR package gate and should land together.
- T013 through T020 form the release workflow and should land together.
- README tasks T021 through T026 can run in parallel with workflow work, but must be reconciled before verification.
- T027 through T032 are final closure tasks and depend on all implementation tasks.

## Parallel Opportunities

- Package metadata work (T006/T007/T008), CI gate work (T009/T010/T011/T012), release workflow work (T013~T020), and README work (T021~T026) can be assigned to separate agents with disjoint file ownership.
- File ownership split:
  - Package agent: `pyproject.toml`, `tests/test_runtime_packaging.py`
  - CI agent: `.github/workflows/ci.yml`
  - Release agent: `.github/workflows/release.yml`
  - Docs agent: `README.md`
  - Verification agent: final commands and checklist closure

## Implementation Strategy

### MVP First

1. Complete T001, T003, T004, and T006.
2. Validate clean wheel install locally.

### Release-Ready Increment

1. Add CI build/install/installed-smoke gates.
2. Add semantic-release package-version synchronization and Trusted Publishing workflow.
3. Add dry-run/TestPyPI/staging validation path.
4. Update README install sections.
5. Run final verification and close checklist.
