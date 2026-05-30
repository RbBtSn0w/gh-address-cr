# Feature Specification: CLI and Skill Synchronization

**Feature Branch**: `011-agent-efficiency-metrics`
**Created**: 2026-05-30
**Status**: Verified
**Input**: User description: "开发CLI，同时维护skill，毕竟他们的代码分离，一不小心丢失就出错，非常低下。从系统化思考，第一性原理给出复盘和修复方案。短期修复（阶段一）：建立兼容脚本的单一可信源、实现同步逻辑与集成校验以防漂移。"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Script Single Source of Truth and Sync (Priority: P1)

As a developer of `gh-address-cr`, I want to maintain compatibility scripts in a single directory (`src/gh_address_cr/legacy_scripts/`) and have a tool copy them to `skill/scripts/` while automatically injecting required local-development bootstrap path logic, so that I do not have to maintain duplicate, formatted-drifted files manually.

**Why this priority**: Eliminates redundancy and manual synchronization overhead, preventing typos/formatting drifts from breaking packaging checks.

**Independent Test**: Modifying a script in the source folder, running the sync tool, and asserting that the script in `skill/scripts/` is updated and executable.

**Acceptance Scenarios**:
1. **Given** a script is modified or added in `src/gh_address_cr/legacy_scripts/`, **When** I run `python3 scripts/sync_scripts.py`, **Then** the corresponding file in `skill/scripts/` is written with an injected `bootstrap_runtime_path()` helper.
2. **Given** a file in `skill/scripts/` has drifted or a file is missing, **When** I run `python3 scripts/sync_scripts.py --check`, **Then** the script reports a failure and returns a non-zero exit code.

---

### User Story 2 - CI Integration and Guardrails (Priority: P1)

As a repository maintainer, I want CI workflows to verify that the packaged skill scripts are perfectly synchronized with the source scripts, so that no unsynchronized changes can be merged into `main` or released to users.

**Why this priority**: Crucial gatekeeper to prevent regressions and keep the release payload consistent.

**Independent Test**: Running the CI action on a branch with drifted scripts and asserting that the build fails.

**Acceptance Scenarios**:
1. **Given** a PR branch with unsynchronized script files, **When** CI runs the test suite or workflow steps, **Then** the `Script sync check` step fails.
2. **Given** a PR branch with fully synchronized script files, **When** CI runs the test suite or workflow steps, **Then** the `Script sync check` step succeeds.

---

### Edge Cases

- **__init__.py presence**: The package initialization file `__init__.py` must not be copied to `skill/scripts/` because the skill scripts are run individually, not imported as a python package in that directory.
- **Imports without gh_address_cr**: If a script does not import `gh_address_cr`, the sync tool must not inject the bootstrap header (e.g. `audit_report.py`).
- **Formatting differences**: The formatting (whitespaces, line wrapping) of the source file must be preserved in the target, except for the injected bootstrap block and its associated `# noqa: E402` rules.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST establish `src/gh_address_cr/legacy_scripts/` as the single source of truth for python compatibility scripts.
- **FR-002**: System MUST provide a synchronization command `python3 scripts/sync_scripts.py` that copies scripts from the source directory to `skill/scripts/`.
- **FR-003**: Synchronization MUST automatically inject the path-bootstrapping helper `bootstrap_runtime_path()` before any imports of `gh_address_cr` in the destination files (except `cli.py`).
- **FR-004**: System MUST append `  # noqa: E402` to any import lines of `gh_address_cr` that follow the injected bootstrapping helper to comply with Ruff linting.
- **FR-005**: Synchronization MUST support a `--check` flag that performs a dry-run check, returning exit code `1` if any file in `skill/scripts/` is missing, orphaned, or has content/formatting drift.
- **FR-006**: The synchronization check MUST be integrated into unit tests and CI workflow suites to enforce a zero-drift guardrail.

### Constitution Alignment *(mandatory)*

- **Control Plane Impact**: Preserves the deterministic nature of compatibility scripts by making sure they only delegate to `src/gh_address_cr/` core code.
- **CLI / Agent Contract Impact**: No impact on the CLI command contract.
- **Evidence Requirements**: The `--check` command output and exit code serve as evidence of packaging consistency.
- **Packaged Skill Boundary**: Synchronization copies the clean, formatted python source files into the packaged skill's `scripts/` directory, maintaining clean boundaries.
- **External Intake Replaceability**: No impact.
- **Fail-Fast Behavior**: The check script and CI steps fail loudly on any synchronization drift.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of python files in `skill/scripts/` (except `__init__.py`) are generated and updated automatically by the synchronization tool.
- **SC-002**: CI workflow run time overhead for the sync check is less than 5 seconds.
- **SC-003**: The unit test suite detects any manual modification to `skill/scripts/` files and fails.

## Assumptions

- We assume that `sys.path` injection in `bootstrap_runtime_path()` is sufficient to resolve `src/` when the skill scripts are executed locally.
- We assume that developers will write scripts in `src/gh_address_cr/legacy_scripts/` and run the sync tool prior to pushing code.
