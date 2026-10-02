# Tasks: CR Lifecycle Decision Metrics

## Phase 0 — Architecture and Contracts

- [x] T001 Reconcile the proposal with current `develop@907be6bc`.
- [x] T002 Record Architecture Preflight and the no-second-authority boundary.
- [x] T003 Define consumers and explicitly forbid runtime/final-gate verdict consumption.
- [x] T004 Accept ADR-001 and freeze the `cr-lifecycle.v1` schema.
- [x] T005 Audit every item kind and terminal producer event against real fixtures.
- [x] T006 Decide and document the `finding_observed` producer boundary.

## Phase 1 — Pure Lifecycle Projector

- [x] T007 Add RED golden tests for first-pass, rework, rejection, blocked publish, incomplete, duplicate, malformed, and mixed-session histories.
- [x] T008 Split ledger I/O from a pure ordered-event projector.
- [x] T009 Implement timestamp provenance, completeness, and exclusion reasons.
- [x] T010 Implement per-item stage durations and friction counts.
- [x] T011 Implement aggregate percentiles/rates with explicit denominators.
- [x] T012 Preserve or explicitly version existing `cr_metrics` fields.

## Phase 2 — Final-Gate Artifact Boundary

- [x] T013 Add RED tests proving metrics failure cannot alter gate verdict or exit code.
- [x] T014 Generate `cr-metrics.json` after gate evaluation.
- [x] T015 Archive the report and rewrite its artifact path.
- [x] T016 Surface projection diagnostics in human and machine output.
- [x] T017 Prove stack-gate behavior remains deterministic.

## Phase 3 — Advisory Output and Telemetry

- [x] T018 Add RED completion-summary contracts for bounded lifecycle output.
- [x] T019 Add the advisory lifecycle summary without changing pass/fail semantics.
- [x] T020 Instrument projection outcome, duration, and completeness.
- [x] T021 Prove OTel attributes are bounded and contain no repo, PR, item, path, content, or raw timestamp.

## Phase 4 — Verification and Dogfood

- [x] T022 Run editable install, ruff, mypy, full unit suite, CLI, manifest, and plugin payload gates.
- [x] T023 Rerun Spec 036 profile M/L and confirm no protected regression.
- [x] T024 Collect 10 controlled pre-merge completed PR sessions with version and eligibility counts.
- [x] T025 Record controlled baseline distributions and exclusions in `validation.md`.
- [x] T026 Decide whether a later advisory regression policy has sufficient evidence (no; exact eligible baseline is zero).

## Deferred

- [x] T027 Complete the separate preflight for GitHub review-stage metrics and external outcome correlation; keep implementation deferred.
