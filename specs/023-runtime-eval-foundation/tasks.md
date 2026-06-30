# Tasks: Read-Only Evaluation Plane

**Input**: Design documents from `/specs/023-runtime-eval-foundation/`
**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/`, `quickstart.md`

**Tests**: This feature requires fixture-driven TDD, deterministic replay, executable public-contract tests, performance budgets, and zero-mutation verification.

**Organization**: Tasks are grouped by user story. Each implementation task changes one behavior in one file unless an executable contract requires a narrowly coupled two-file change.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Create the package and fixture boundaries used by every later phase.

- [X] T001 [P] Create the evaluation package scaffold in `src/gh_address_cr/core/evaluation/__init__.py`
- [X] T002 [P] Create the evaluation fixture root marker in `tests/fixtures/evaluation/.gitkeep`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Establish versioned models, paths, measured-span preservation, and final-gate manifest plumbing.

**Critical ordering**: Complete each test immediately before its corresponding implementation task. Tasks that touch the same file are intentionally sequential and have no `[P]` marker.

- [X] T003 Add failing `run-manifest.v1` and complexity-profile model contract tests in `tests/core/test_evaluation.py`
- [X] T004 Implement `ComplexityProfile` validation and bucket derivation in `src/gh_address_cr/core/evaluation/models.py`
- [X] T005 Implement `RunManifestV1` validation and serialization in `src/gh_address_cr/core/evaluation/models.py`
- [X] T006 Add failing evidence-pointer and observation fingerprint model tests in `tests/core/test_evaluation.py`
- [X] T007 Implement `EvidencePointer` and deterministic fingerprint helpers in `src/gh_address_cr/core/evaluation/models.py`
- [X] T008 Implement `EvaluationObservationV1` validation in `src/gh_address_cr/core/evaluation/models.py`
- [X] T009 Add failing evaluation path and `SessionPaths` accessor tests in `tests/test_native_foundation.py`
- [X] T010 Implement run-manifest, observation-ledger, and catalog path helpers in `src/gh_address_cr/core/paths.py`
- [X] T011 Add failing execution-span timestamp preservation tests in `tests/core/test_telemetry.py`
- [X] T012 Preserve normalized start and end timestamps on execution metrics in `src/gh_address_cr/core/telemetry_models.py`
- [X] T013 Preserve execution metric timestamps during telemetry event normalization in `src/gh_address_cr/core/telemetry.py`
- [X] T014 Add failing attributable GitHub command-span tests in `tests/test_native_github.py`
- [X] T015 Emit measured operation spans from the centralized runner in `src/gh_address_cr/core/command_runner.py`
- [X] T016 Route GitHub CLI execution through the measured runner boundary in `src/gh_address_cr/github/client.py`
- [X] T017 Add failing stable-target manifest and fail-open diagnostic tests in `tests/test_final_gate_kernel.py`
- [X] T018 Implement final-target manifest construction without self-digesting in `src/gh_address_cr/commands/final_gate.py`
- [X] T019 Add failing post-rewrite digest and auto-clean archive tests in `tests/test_final_gate.py`
- [X] T020 Finalize `run-manifest.v1.json` after archive path rewriting in `src/gh_address_cr/commands/final_gate.py`

**Checkpoint**: Shared model, path, timing, and manifest contracts pass before story implementation begins.

---

## Phase 3: User Story 1 - Evaluate Review Outcomes With Hybrid Verification (Priority: P1)

**Goal**: Report provisional and durable verification separately with attributable evidence and deterministic replay.

**Independent Test**: Replay the same archived evidence twice and confirm provisional, durable, unknown, and negative states plus semantic fingerprints are identical and correctly attributed.

### Fixtures for User Story 1

- [X] T021 [P] [US1] Add a provisional-success archive fixture in `tests/fixtures/evaluation/hybrid_verification/provisional_success.json`
- [X] T022 [P] [US1] Add a later-supported approval fixture in `tests/fixtures/evaluation/hybrid_verification/durable_approval.json`
- [X] T023 [P] [US1] Add a correlated reopen fixture in `tests/fixtures/evaluation/hybrid_verification/reopened.json`
- [X] T024 [P] [US1] Add an equivalent-recurrence fixture in `tests/fixtures/evaluation/hybrid_verification/equivalent_recurrence.json`

### Tests for User Story 1

- [X] T025 [US1] Add failing provisional verification and missing-evidence deficit tests in `tests/core/test_evaluation.py`
- [X] T026 [US1] Add failing durable approval and unknown-observation tests in `tests/core/test_evaluation.py`
- [X] T027 [US1] Add failing reopen and equivalent-recurrence outcome tests in `tests/core/test_evaluation.py`
- [X] T028 [US1] Add failing archive integrity and evidence-pointer normalization tests in `tests/core/test_evaluation.py`
- [X] T029 [US1] Add failing identical-input concern replay tests for SC-009 in `tests/core/test_evaluation.py`

### Implementation for User Story 1

- [X] T030 [US1] Implement read-only archive artifact loading and digest validation in `src/gh_address_cr/core/evaluation/archive.py`
- [X] T031 [US1] Implement evidence-pointer normalization in `src/gh_address_cr/core/evaluation/archive.py`
- [X] T032 [US1] Implement later-observation correlation normalization in `src/gh_address_cr/core/evaluation/observations.py`
- [X] T033 [US1] Implement provisional verification policy and deficit reason codes in `src/gh_address_cr/core/evaluation/projector.py`
- [X] T034 [US1] Implement durable verification, unknown, and negative outcome policy in `src/gh_address_cr/core/evaluation/projector.py`
- [X] T035 [US1] Implement generation-time-independent concern projection fingerprints in `src/gh_address_cr/core/evaluation/projector.py`

**Checkpoint**: US1 independently proves hybrid verification and deterministic concern replay.

---

## Phase 4: User Story 2 - Compare Quality And Cost Without False Precision (Priority: P1)

**Goal**: Compare matched cohorts across quality, economics, and operational health with explicit insufficiency, distribution, uncertainty, and overhead semantics.

**Independent Test**: Compare supported and unsupported cohorts, then verify dimensional coverage, quality guardrails, deterministic distributions, replay identity, rejection taxonomy, and declared performance budgets.

### Fixtures for User Story 2

- [X] T036 [P] [US2] Add a ten-run matched-cohort fixture in `tests/fixtures/evaluation/comparison/matched_cohorts.json`
- [X] T037 [P] [US2] Add an incomplete-coverage cohort fixture in `tests/fixtures/evaluation/comparison/incomplete_coverage.json`
- [X] T038 [P] [US2] Add a lower-cost quality-regression fixture in `tests/fixtures/evaluation/comparison/quality_regression.json`

### Tests for User Story 2

- [X] T039 [US2] Add failing independent workflow, timing, token, and outcome coverage tests in `tests/core/test_evaluation.py`
- [X] T040 [US2] Add failing interval-union and separately labeled resource-time tests in `tests/core/test_evaluation.py`
- [X] T041 [US2] Add failing expected-versus-actionable rejection taxonomy tests for FR-021 in `tests/core/test_evaluation.py`
- [X] T042 [US2] Add failing cohort matching and exact evidence-deficit tests in `tests/core/test_evaluation.py`
- [X] T043 [US2] Add failing sample-size, median, p90, and uncertainty tests for FR-022 and SC-011 in `tests/core/test_evaluation.py`
- [X] T044 [US2] Add failing quality-regression guardrail tests in `tests/core/test_evaluation.py`
- [X] T045 [US2] Add failing separate overhead accounting and 250 ms budget tests for FR-023 and SC-012 in `tests/core/test_evaluation.py`
- [X] T046 [US2] Add failing duplicate archive, manifest, evidence, and comparison replay tests for FR-019 and SC-009 in `tests/core/test_evaluation.py`
- [X] T047 [US2] Add a 10,000-run catalog query budget test with a two-second ceiling in `tests/core/test_evaluation_performance.py`
- [X] T048 [US2] Add an interval-union span-scaling regression test in `tests/core/test_evaluation_performance.py`

### Implementation for User Story 2

- [X] T049 [US2] Implement dimensional coverage statuses and exact deficit codes in `src/gh_address_cr/core/evaluation/coverage.py`
- [X] T050 [US2] Implement expected, actionable, and unknown rejection classification in `src/gh_address_cr/core/evaluation/coverage.py`
- [X] T051 [US2] Implement linearithmic interval-union active-time calculation in `src/gh_address_cr/core/evaluation/timing.py`
- [X] T052 [US2] Implement separately labeled resource-time aggregation in `src/gh_address_cr/core/evaluation/timing.py`
- [X] T053 [US2] Implement non-self-referential evaluation overhead measurement in `src/gh_address_cr/core/evaluation/timing.py`
- [X] T054 [US2] Create catalog metadata, run, and concern tables in `src/gh_address_cr/core/evaluation/catalog.py`
- [X] T055 [US2] Create coverage, cost, observation, and evidence-pointer tables in `src/gh_address_cr/core/evaluation/catalog.py`
- [X] T056 [US2] Add fingerprint uniqueness constraints and duplicate-safe inserts in `src/gh_address_cr/core/evaluation/catalog.py`
- [X] T057 [US2] Build catalog data into a validated temporary SQLite file in `src/gh_address_cr/core/evaluation/catalog.py`
- [X] T058 [US2] Atomically replace the catalog while preserving the prior catalog on failure in `src/gh_address_cr/core/evaluation/catalog.py`
- [X] T059 [US2] Add cohort indexes and bounded matched-cohort queries in `src/gh_address_cr/core/evaluation/catalog.py`
- [X] T060 [US2] Implement cohort compatibility and minimum-sample policy in `src/gh_address_cr/core/evaluation/comparison.py`
- [X] T061 [US2] Implement dimensional `INSUFFICIENT_EVIDENCE` results with exact deficits in `src/gh_address_cr/core/evaluation/comparison.py`
- [X] T062 [US2] Implement sample size, median, p90, and deterministic quality bounds in `src/gh_address_cr/core/evaluation/comparison.py`
- [X] T063 [US2] Implement independent quality, economics, and operational-health vectors in `src/gh_address_cr/core/evaluation/comparison.py`
- [X] T064 [US2] Implement quality-regression guardrails that cannot be overridden by lower cost in `src/gh_address_cr/core/evaluation/comparison.py`
- [X] T065 [US2] Implement overhead-budget degradation without review-resolution failure in `src/gh_address_cr/core/evaluation/comparison.py`
- [X] T066 [US2] Implement generation-time-independent comparison fingerprints in `src/gh_address_cr/core/evaluation/comparison.py`

**Checkpoint**: US2 independently proves supported comparison, honest insufficiency, replay identity, and the declared performance budgets.

---

## Phase 5: User Story 3 - Preserve Runtime And Privacy Boundaries (Priority: P2)

**Goal**: Expose the evaluation CLI while preserving read-only GitHub/runtime behavior, privacy boundaries, stable exit codes, and fail-open/fail-loud separation.

**Independent Test**: Exercise all four evaluation commands against valid, duplicate, malformed, and unsafe fixtures; verify stable machine output and zero mutation of runtime, final-gate, and GitHub state.

### Tests for User Story 3

- [X] T067 [US3] Add failing observation deduplication and privacy rejection tests in `tests/core/test_evaluation.py`
- [X] T068 [US3] Add failing runtime-state and archive zero-mutation tests in `tests/core/test_evaluation.py`
- [X] T069 [US3] Add failing final-gate fail-open evaluation diagnostic tests in `tests/test_final_gate.py`
- [X] T070 [US3] Add failing `evaluation observe` output and exit-code tests in `tests/test_evaluation_cli.py`
- [X] T071 [US3] Add failing `evaluation rebuild` atomicity and exit-code tests in `tests/test_evaluation_cli.py`
- [X] T072 [US3] Add failing `evaluation show` JSON/Markdown and missing-catalog tests in `tests/test_evaluation_cli.py`
- [X] T073 [US3] Add failing `evaluation compare` supported/insufficient output tests in `tests/test_evaluation_cli.py`
- [X] T074 [US3] Add failing malformed, unsafe, ambiguous, and unsupported-schema CLI tests in `tests/test_evaluation_cli.py`

### Implementation for User Story 3

- [X] T075 [US3] Implement append-only observation writes with duplicate accounting in `src/gh_address_cr/core/evaluation/observations.py`
- [X] T076 [US3] Implement evaluation input privacy rejection and sanitization in `src/gh_address_cr/core/telemetry_safety.py`
- [X] T077 [US3] Implement read-only review-round and thread queries without mutation commands in `src/gh_address_cr/github/client.py`
- [X] T078 [US3] Convert read-only GitHub results into evaluation observation inputs in `src/gh_address_cr/core/evaluation/archive.py`
- [X] T079 [US3] Implement the `evaluation` argument parser and stable exit-code adapter in `src/gh_address_cr/commands/evaluation.py`
- [X] T080 [US3] Register the additive `evaluation` command family in `src/gh_address_cr/cli.py`
- [X] T081 [US3] Implement `evaluation observe` command execution in `src/gh_address_cr/commands/evaluation.py`
- [X] T082 [US3] Implement `evaluation rebuild` command execution in `src/gh_address_cr/commands/evaluation.py`
- [X] T083 [US3] Implement `evaluation show` command execution in `src/gh_address_cr/commands/evaluation.py`
- [X] T084 [US3] Implement `evaluation compare` command execution in `src/gh_address_cr/commands/evaluation.py`

**Checkpoint**: US3 independently proves the public CLI contract, privacy protection, and zero authority over runtime truth.

---

## Phase 6: Polish & Cross-Cutting Verification

**Purpose**: Align documentation and execute both focused and repository-wide completion gates.

- [X] T085 [P] Update evaluation examples, failure boundaries, and acceptance commands in `specs/023-runtime-eval-foundation/quickstart.md`
- [X] T086 [P] Document the advanced evaluation command family and read-only boundary in `README.md`
- [X] T087 Run focused evaluation, final-gate, CLI, deterministic replay, and performance tests listed in `specs/023-runtime-eval-foundation/quickstart.md`
- [X] T088 Run install, Ruff, mypy ratchet, full unittest, CLI manifest, and plugin payload checks listed in `specs/023-runtime-eval-foundation/quickstart.md`

---

## Dependencies & Execution Order

### Phase Dependencies

- Phase 1 has no dependencies.
- Phase 2 depends on Phase 1 and blocks all user stories.
- US1, US2, and US3 each depend on Phase 2.
- US2 may begin after Phase 2, but its deterministic comparison checks reuse the stable projection contracts completed by US1.
- US3 may begin after Phase 2; command-level `show` and `compare` validation requires the corresponding US1/US2 internals.
- Phase 6 begins after the selected story phases are complete.

### Within-Phase Ordering

- Execute tests before their corresponding implementation tasks and confirm the expected failure.
- Execute tasks that touch `tests/core/test_evaluation.py`, `models.py`, `catalog.py`, `comparison.py`, or `commands/evaluation.py` sequentially in listed order.
- Do not parallelize tasks merely because they are in the same phase; `[P]` is the only authorization for parallel execution.

### Parallel Opportunities

- T001 and T002 can run in parallel because they create different paths.
- T021 through T024 can run in parallel because each creates a distinct fixture file.
- T036 through T038 can run in parallel because each creates a distinct fixture file.
- T085 and T086 can run in parallel because they update different documentation files.

## Implementation Strategy

### MVP First

1. Complete Phase 1 and Phase 2.
2. Complete US1 through T035.
3. Run the US1 fixture and replay contracts before expanding into cohort comparison.

### Incremental Delivery

1. Ship versioned models, manifest finalization, and measured-span preservation.
2. Ship deterministic hybrid verification.
3. Ship dimensional economics, catalog rebuild, comparison policy, and performance budgets.
4. Ship the additive read-only CLI with privacy and zero-mutation contracts.
5. Complete documentation and both verification gates.

## Phase 7: Convergence

- [X] T089 Review the unrequested default process-level OTLP exporter, added runtime dependencies, and console-entrypoint change; remove or split them into a separately specified feature unless a versioned public contract and architecture ownership justify retaining them per plan: Technical Context / Project Structure / unchanged public runtime contract (unrequested)
