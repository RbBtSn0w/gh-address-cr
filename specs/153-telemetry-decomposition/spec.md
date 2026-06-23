# Feature Specification: Telemetry Module Decomposition

**Feature Branch**: `153-telemetry-decomposition`
**Created**: 2026-06-25
**Status**: In Review
**Input**: Issue #153: core/telemetry.py is a god module (1,839 lines); finish decomposition.

## User Scenarios & Testing

### User Story 1 - Stable Telemetry API

Maintainers and integrating agents can continue to use telemetry features (ingest, summary, report) with the same CLI and public-facing behavior, even as the internal implementation is decomposed into cohesive sub-modules.

**Why this priority**: Decomposition must not break the stable public contract of the tool.

**Acceptance Scenarios**:
1. **Given** a PR with existing telemetry artifacts, **When** `telemetry summary` or `final-gate` is run, **Then** the resulting report and coverage label are identical to the pre-decomposition state.
2. **Given** external agent telemetry, **When** `telemetry ingest` is run, **Then** the events are correctly imported, deduplicated, and attributed to the source.

---

### User Story 2 - Clean Codebase Architecture

Developers can easily locate and modify telemetry-related logic (importing, reporting, attribution) in dedicated modules without navigating a single 1.8k-line file or relying on hidden re-export shims.

**Why this priority**: Reducing technical debt and churn in the highest-churn area of the codebase.

**Acceptance Scenarios**:
1. **Given** the source tree, **When** looking for reporting logic, **Then** it is found in `telemetry_reporting.py` without unrelated import or safety logic.
2. **Given** the codebase, **When** running linting/type checks, **Then** no `noqa: F401` shims exist for telemetry safety helpers.

## Requirements

### Functional Requirements

- **FR-001**: System MUST decompose `core/telemetry.py` into at least three new sub-modules: `telemetry_import.py`, `telemetry_reporting.py`, and `telemetry_attribution.py`.
- **FR-002**: `telemetry_import.py` MUST own external telemetry ingestion, format adapters, and adapter registry.
- **FR-003**: `telemetry_reporting.py` MUST own efficiency report generation, metrics calculation, and Markdown formatting.
- **FR-004**: `telemetry_attribution.py` MUST own event fingerprinting, deduplication, and source attribution logic.
- **FR-005**: `telemetry.py` MUST be reduced to a high-level orchestration module and session context owner.
- **FR-006**: System MUST remove the re-export shim in `telemetry.py` and update all internal call sites to import from the authoritative sub-modules.
- **FR-007**: System MUST preserve existing public CLI contracts and machine-readable output formats.
- **FR-008**: System MUST update all tests to reflect the new module structure.

### Constitution Alignment

- **Control Plane State**: Telemetry state remains owned by the runtime. This refactor only changes the physical organization of the code.
- **CLI Stability**: CLI commands remain unchanged.
- **Evidence-First**: Telemetry remains observed evidence and does not mutate PR state.
- **Testable Contracts**: Refactor MUST pass all existing telemetry acceptance tests and matrix tests.

## Key Entities

- **Telemetry Import**: Logic for consuming external events and mapping them to the internal model.
- **Telemetry Reporting**: Logic for aggregating events into efficiency summaries.
- **Telemetry Attribution**: Logic for uniquely identifying events and preventing double-counting.
- **Telemetry Context**: The `SessionTelemetry` singleton managing the current PR scope.

## Success Criteria

- **SC-001**: `core/telemetry.py` size is significantly reduced (goal: < 400 lines).
- **SC-002**: Re-export shim (`noqa: F401`) is deleted.
- **SC-003**: All telemetry-related unit and acceptance tests pass.
- **SC-004**: No regressions in `final-gate` or `telemetry` CLI commands.
