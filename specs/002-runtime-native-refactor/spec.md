# Feature Specification: Runtime Native Refactor

**Feature Branch**: `002-runtime-native-refactor`  
**Created**: 2026-04-24
**Status**: Draft
**Input**: User description: "下一阶段不应该继续扩 skill，而是开始拆 legacy_scripts： 优先级建议： 把 session_engine.py 的核心状态机迁到 src/gh_address_cr/core/session.py / workflow.py 把 GitHub reply/resolve/list threads 迁到 src/gh_address_cr/github/ 把 intake/findings 迁到 src/gh_address_cr/intake/ 把 final-gate 完全切到 src/gh_address_cr/core/gate.py 最后删除 runtime 对 legacy_scripts 的依赖，只保留 skill shim 一句话：现在主迁移已经跑完，review remediation 也补上了；接下来是“去 legacy_scripts 化”的 runtime-native 重构阶段。"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Native Session State Management (Priority: P1)

As a maintainer of the control plane, I want the session state machine logic to reside in the `core` package so that the runtime is deterministic and free from legacy script coupling.

**Why this priority**: The session engine is the heart of the control plane. Its location dictates the clean separation of concerns.

**Independent Test**: Can be verified by running unit tests against `gh_address_cr.core.session` and `gh_address_cr.core.workflow` without importing any code from `legacy_scripts`.

**Acceptance Scenarios**:

1. **Given** a legacy `session_engine.py` with complex state transitions, **When** the logic is migrated to `src/gh_address_cr/core/`, **Then** the new native implementation produces bit-for-bit identical session files for the same inputs.
2. **Given** a new PR session, **When** handled by the native workflow, **Then** all state transitions are recorded in the evidence ledger using the new internal API.

---

### User Story 2 - Encapsulated GitHub IO (Priority: P1)

As a developer, I want the GitHub interaction logic to be encapsulated in a dedicated `github` package so that the control plane's side-effect boundary is explicit and mockable.

**Why this priority**: GitHub API calls are the primary side effects. Centralizing them is crucial for stability and testing.

**Independent Test**: Can be verified by running `gh_address_cr.github` tests using a local mock server or recorded fixtures, confirming `reply`, `resolve`, and `list threads` function correctly.

**Acceptance Scenarios**:

1. **Given** the need to reply to a thread, **When** the native `github` package is invoked, **Then** it correctly formats the GraphQL/REST request without calling `legacy_scripts`.
2. **Given** a request to list threads, **When** the native package is used, **Then** it returns a normalized list of threads compatible with the `intake` package.

---

### User Story 3 - Native Intake & Findings Normalization (Priority: P1)

As a maintainer, I want the findings intake logic to be a native package so that it can be reused by different producers without legacy script overhead.

**Why this priority**: Findings ingestion is the primary input to the session engine. Native implementation ensures type safety and performance.

**Independent Test**: `gh_address_cr.intake` tests verify parity with legacy normalization and support for multiple input formats.

**Acceptance Scenarios**:

1. **Given** a raw NDJSON finding, **When** processed by the native intake, **Then** it correctly maps to the internal `Finding` model.

---

### User Story 4 - Native Final Gate (Priority: P2)

As a maintainer, I want the Final Gate logic to be moved to `core.gate` so that the completion check is a first-class citizen of the native runtime.

**Why this priority**: The final gate ensures PR safety. It must be reliable and independent of legacy structures.

**Acceptance Scenarios**:

1. **Given** a PR session with unresolved threads, **When** `gh_address_cr.core.gate` is executed, **Then** it correctly identifies the blocking items and exits with the defined error code.

---

### User Story 5 - Clean Runtime Boundary (Priority: P1)

As a project architect, I want the runtime package to have zero dependencies on `legacy_scripts` so that the legacy code can eventually be deleted, leaving only shims for backwards compatibility.

**Why this priority**: This is the primary goal of the refactor. Eliminating coupling ensures long-term maintainability.

**Acceptance Scenarios**:

1. **Given** a complete build of the `gh_address_cr` package, **When** `legacy_scripts` is removed from the search path, **Then** all core runtime commands (`review`, `agent submit`, etc.) continue to function perfectly.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST migrate the core session state machine from `legacy_scripts/session_engine.py` to `src/gh_address_cr/core/session.py`.
- **FR-002**: System MUST migrate GitHub interaction logic (reply, resolve, list threads) to `src/gh_address_cr/github/`.
- **FR-003**: System MUST migrate intake and findings normalization logic to `src/gh_address_cr/intake/`.
- **FR-004**: System MUST migrate the final gate logic to `src/gh_address_cr/core/gate.py`.
- **FR-005**: The `src/gh_address_cr/` runtime package MUST NOT import or depend on any code within `src/gh_address_cr/legacy_scripts/`.
- **FR-006**: Existing skill shims in `src/gh_address_cr/legacy_scripts/` MAY remain but MUST delegate to the new native implementation.
- **FR-007**: All migrated logic MUST maintain 100% behavioral parity with the legacy implementation. Verification MUST include byte-for-bit comparison of `session.json` snapshots produced by legacy vs native runtimes for identical inputs.
- **FR-008**: System MUST update the CLI entrypoints in `src/gh_address_cr/cli.py` to use the new native packages instead of legacy internal modules.

### Constitution Alignment *(mandatory)*

- **Control Plane Impact**: Direct alignment with Principle I. Moves authoritative state and side-effect ownership from legacy scripts to the deterministic core package.
- **CLI / Agent Contract Impact**: No change to public CLI semantics (Principle II). Internal implementation detail only.
- **Evidence Requirements**: Preserves Principle III by ensuring the evidence ledger remains the source of truth during and after migration.
- **Packaged Skill Boundary**: Solidifies Principle IV by clearly separating runtime logic (`src/gh_address_cr/core`) from legacy/shim code.

### Key Entities

- **SessionManager**: The new native orchestrator for session state.
- **GitHubClient**: The encapsulated interface for GitHub IO.
- **IntakeEngine**: The normalized findings producer.
- **Gatekeeper**: The logic for final PR session validation.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Zero `import` statements in `src/gh_address_cr/core/`, `github/`, or `intake/` point to `legacy_scripts`.
- **SC-002**: 100% of existing unit tests in `tests/` pass using the new native implementation.
- **SC-003**: The `gh-address-cr` package size remains stable or decreases after removing legacy duplication.
- **SC-004**: Execution time for core commands (`review`, `final-gate`) remains within ±5% of legacy performance.

## Assumptions

- `legacy_scripts` currently contains all logic needed for the migration; no new external APIs are required.
- The existing test suite provides sufficient coverage to ensure behavioral parity during the refactor.
- Skill shims can be updated to delegate to the new internal structure without breaking the packaged skill contract.
