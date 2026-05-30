# Feature Specification: CLI and Skill Synchronization

**Feature Branch**: `011-agent-efficiency-metrics`
**Created**: 2026-05-30
**Status**: In Progress
**Input**: User description: "开发CLI，同时维护skill，毕竟他们的代码分离，一不小心丢失就出错，非常低下。从系统化思考，第一性原理给出复盘和修复方案。短期修复（阶段一）：建立兼容脚本的单一可信源、实现同步逻辑与集成校验以防漂移。中期重构（阶段二）：脚本“极简代理化”（彻底下沉逻辑）。长期重构（阶段三）：彻底消除 skill/scripts/ 脚本，全量使用 CLI 代理。"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Script Single Source of Truth and Sync (Phase 1 - Complete)

As a developer of `gh-address-cr`, I want to maintain compatibility scripts in a single directory (`src/gh_address_cr/legacy_scripts/`) and have a tool copy them to `skill/scripts/` while automatically injecting required local-development bootstrap path logic, so that I do not have to maintain duplicate, formatted-drifted files manually.

**Acceptance Scenarios**:
1. **Given** a script is modified or added in `src/gh_address_cr/legacy_scripts/`, **When** I run `python3 scripts/sync_scripts.py`, **Then** the corresponding file in `skill/scripts/` is written with an injected `bootstrap_runtime_path()` helper.
2. **Given** a file in `skill/scripts/` has drifted or a file is missing, **When** I run `python3 scripts/sync_scripts.py --check`, **Then** the script reports a failure and returns a non-zero exit code.

---

### User Story 2 - Minimalist Delegation of Legacy Scripts (Phase 2 - Complete)

As a developer, I want all compatibility scripts in the packaged skill payload to be thin proxies/shims that contain no business logic and delegate entirely to the core `gh_address_cr` Python package. This eliminates duplication, ensures logic is fully packaged and testable, and prevents bulky shared utilities (like `python_common.py`) from bloat-loading the skill's script payload.

**Acceptance Scenarios**:
1. **Given** a command (e.g., `post-reply`) is run via the CLI or a legacy script wrapper, **When** it executes, **Then** the execution flows through a minimalist shim script that delegates to a handler inside the package, maintaining exact original behavior.
2. **Given** the sync script is run, **When** it maps files, **Then** only the thin proxies are synced to `skill/scripts/`, and bulky helper files like `python_common.py` are cleaned up/removed from `skill/scripts/`.

---

### User Story 3 - Complete Elimination of Skill Scripts in Payload (Phase 3 - Active)

As a developer/maintainer, I want to completely remove compatibility shim python scripts from the packaged skill's `scripts/` directory and configure the Codex plugin and agent instructions to execute the installed `gh-address-cr` CLI directly. This eliminates python shims entirely from the skill packaging boundary and routes all agent execution directly to the installed python package runtime.

**Acceptance Scenarios**:
1. **Given** the plugin payload is built, **When** I inspect the `skill/scripts/` directory, **Then** it contains no python scripts (the directory can be deleted).
2. **Given** the Codex plugin configuration (`plugin/gh-address-cr/plugin.json`), `skill/SKILL.md`, and `skill/agents/openai.yaml` are compiled, **When** they instruct the agent on command execution, **Then** all instructions point directly to `gh-address-cr` CLI instead of `python3 scripts/cli.py` or other python shim scripts.
3. **Given** the unit tests and CI workflows run, **When** they execute, **Then** all checks pass successfully without expecting local python wrapper scripts under the skill payload.

---

### Edge Cases

- **__init__.py presence**: The package initialization file `__init__.py` must not be copied to `skill/scripts/`.
- **Imports without gh_address_cr**: If a script does not import `gh_address_cr`, the sync tool must not inject the bootstrap header.
- **Ruff compliance**: Sync script must append `# noqa: E402` to imports of `gh_address_cr` that follow path injection.
- **Circular Imports**: Package handlers must load cleanly without module-level circular dependencies.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST establish `src/gh_address_cr/legacy_scripts/` as the single source of truth for python compatibility scripts.
- **FR-002**: System MUST provide a synchronization command `python3 scripts/sync_scripts.py` that copies scripts from the source directory to `skill/scripts/`.
- **FR-003**: Synchronization MUST automatically inject the path-bootstrapping helper `bootstrap_runtime_path()` before any imports of `gh_address_cr` in the destination files (except `cli.py`).
- **FR-004**: System MUST append `  # noqa: E402` to any import lines of `gh_address_cr` that follow the injected bootstrapping helper to comply with Ruff linting.
- **FR-005**: System MUST support a `--check` flag that performs a dry-run check, returning exit code `1` if any file in `skill/scripts/` is missing, orphaned, or has content/formatting drift.
- **FR-006**: The synchronization check MUST be integrated into unit tests and CI workflow suites to enforce a zero-drift guardrail.
- **FR-007**: System MUST move all business logic from `src/gh_address_cr/legacy_scripts/` scripts to `src/gh_address_cr/legacy_handlers/` internal package directory.
- **FR-008**: System MUST make each script in `src/gh_address_cr/legacy_scripts/` (except `__init__.py` and `cli.py`) a minimal shim that only imports its entry point from `gh_address_cr.legacy_handlers` and calls it.
- **FR-009**: The sync tool (`sync_scripts.py`) MUST delete `python_common.py` from `skill/scripts/` during synchronization as it is no longer present in `legacy_scripts/`.
- **FR-010**: System MUST completely eliminate python compatibility scripts from the packaged skill's `scripts/` directory.
- **FR-011**: All packaged skill documentation (`skill/SKILL.md`) and agent instructions (`skill/agents/openai.yaml`) MUST reference `gh-address-cr` CLI directly for execution, instead of `python3 scripts/cli.py` or other python shim scripts.
- **FR-012**: System MUST remove the synchronization command `sync_scripts.py` and clean up all CI and unit test suites that verify local compatibility shims.

### Constitution Alignment *(mandatory)*

- **Control Plane Impact**: Preserves the deterministic nature of compatibility scripts by making sure they only delegate to `src/gh_address_cr/` core code.
- **CLI / Agent Contract Impact**: No impact on the CLI command contract.
- **Evidence Requirements**: The `--check` command output and exit code serve as evidence of packaging consistency.
- **Packaged Skill Boundary**: Synchronization copies the clean, formatted python source files into the packaged skill's `scripts/` directory, maintaining clean boundaries.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of python files in `skill/scripts/` (except `__init__.py`) are generated and updated automatically by the synchronization tool. (Obsoleted in Phase 3)
- **SC-002**: All compatibility scripts under `skill/scripts/` are minimal proxies with zero business logic. (Obsoleted in Phase 3)
- **SC-003**: The unit test suite detects any manual modification to `skill/scripts/` files and fails. (Obsoleted in Phase 3)
- **SC-004**: All 544 unit tests pass successfully after the refactor.
- **SC-005**: The `skill/scripts/` directory is completely removed from the packaged skill payload.
- **SC-006**: All CI checks and semantic release configurations pass successfully without requiring or running script synchronization.
- **SC-007**: 100% of references in `SKILL.md` and `openai.yaml` target `gh-address-cr` CLI directly.
