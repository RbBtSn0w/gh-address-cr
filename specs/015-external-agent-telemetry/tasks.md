# Tasks: External Agent Telemetry Ingestion

**Input**: Design documents from `/specs/015-external-agent-telemetry/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/telemetry-ingestion.md, quickstart.md

**Tests**: Required for every changed runtime report, CLI contract, final-gate evidence path, audit artifact, import parser, privacy guard, deduplication rule, and packaged-skill contract.

**Organization**: Tasks are grouped by independently testable user story. US3 is first because `research.md` defines `repair-telemetry-metrics` as the first implementation slice even though US1, US2, and US3 are all P1.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Confirm the existing telemetry and final-gate surfaces before changing public behavior.

- [ ] T001 Review existing runtime telemetry, final-gate, audit summary, and report paths in src/gh_address_cr/core/telemetry.py, src/gh_address_cr/cli.py, src/gh_address_cr/core/gate.py, src/gh_address_cr/core/paths.py, and tests/core/test_telemetry.py
- [ ] T002 [P] Add reusable telemetry fixture helpers for PR-scoped runtime and external events in tests/helpers.py
- [ ] T003 [P] Add generic JSONL telemetry fixture files for valid, malformed, duplicate, and unsafe feeds in tests/fixtures/telemetry/
- [ ] T004 [P] Document feature-specific validation scenarios from quickstart.md in specs/015-external-agent-telemetry/quickstart.md

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Define shared runtime-owned telemetry primitives that all user stories depend on.

**CRITICAL**: No user story work can begin until this phase is complete.

- [ ] T005 Add canonical ExternalTelemetryEvent, TelemetryImport, TelemetrySource, CoverageReport, and EfficiencyReport dataclasses or typed structures in src/gh_address_cr/core/telemetry.py
- [ ] T006 Add PR-scoped telemetry artifact path helpers for external events, import ledger, and efficiency report output in src/gh_address_cr/core/paths.py
- [ ] T007 Add shared coverage label calculation for complete, partial, runtime-only, and unavailable states in src/gh_address_cr/core/telemetry.py
- [ ] T008 Add shared report serialization helpers that emit public-safe JSON and Markdown summaries in src/gh_address_cr/core/telemetry.py
- [ ] T009 [P] Add foundational tests for telemetry models, coverage labels, and report serialization in tests/core/test_telemetry.py
- [ ] T010 [P] Add path helper tests for telemetry artifacts and report files in tests/test_native_foundation.py

**Checkpoint**: Foundation ready; each user story can now build on deterministic telemetry state and report primitives.

---

## Phase 3: User Story 3 - Repair Existing Metrics Summary Gap (Priority: P1) MVP

**Goal**: Runtime-only metrics appear in final-gate output, audit_summary.md, and a structured efficiency report artifact without requiring external telemetry.

**Independent Test**: Complete a PR-scoped workflow with runtime telemetry only and verify final-gate stdout, audit summary content, and structured report artifact all include current metrics and `runtime-only` coverage.

### Tests for User Story 3

- [ ] T011 [P] [US3] Add failing final-gate stdout contract test for runtime-only Agent Efficiency Summary and report artifact path in tests/test_python_wrappers.py
- [ ] T012 [P] [US3] Add failing audit_summary.md contract test for runtime-only coverage label, source summary, and inefficiency signals in tests/test_python_wrappers.py
- [ ] T013 [P] [US3] Add failing structured EfficiencyReport artifact test for runtime telemetry only in tests/core/test_telemetry.py
- [ ] T014 [P] [US3] Add failing no-telemetry coverage test that reports unavailable instead of omitting metrics in tests/test_python_wrappers.py

### Implementation for User Story 3

- [ ] T015 [US3] Implement runtime telemetry aggregation into EfficiencyReport in src/gh_address_cr/core/telemetry.py
- [ ] T016 [US3] Write structured efficiency report artifacts during final-gate execution in src/gh_address_cr/core/gate.py
- [ ] T017 [US3] Print Agent Efficiency Summary, coverage label, and report artifact path in final-gate output in src/gh_address_cr/cli.py
- [ ] T018 [US3] Append telemetry coverage, source summary, top inefficiency signals, and report artifact metadata to audit_summary.md in src/gh_address_cr/core/gate.py
- [ ] T019 [US3] Include efficiency report artifact metadata in submit-feedback context when available in src/gh_address_cr/commands/submit_feedback.py
- [ ] T020 [US3] Update packaged completion guidance to require final-gate telemetry coverage reporting in skill/SKILL.md and skill/agents/openai.yaml
- [ ] T021 [US3] Update completion contract reference with runtime-only and unavailable coverage evidence requirements in skill/references/completion-contract.md
- [ ] T022 [US3] Add packaged-skill documentation tests for telemetry coverage guidance in tests/test_skill_docs.py

**Checkpoint**: Runtime-only metrics repair is complete and independently verifiable.

---

## Phase 4: User Story 1 - Import Host Agent Telemetry (Priority: P1)

**Goal**: Import PR-scoped host-agent telemetry and combine it with runtime telemetry in the final efficiency report.

**Independent Test**: Complete a PR-scoped workflow with runtime telemetry plus an external host feed and verify the final report includes both sources, imported status, counts, success rate, duration, slowest operations, and inefficiency flags.

### Tests for User Story 1

- [ ] T023 [P] [US1] Add failing CLI contract tests for telemetry ingest machine-readable success fields in tests/test_python_wrappers.py
- [ ] T024 [P] [US1] Add failing CLI summary tests for combined runtime and external telemetry fields in tests/test_python_wrappers.py
- [ ] T025 [P] [US1] Add failing import validation tests for malformed feed diagnostics and unchanged review session state in tests/core/test_telemetry.py
- [ ] T026 [P] [US1] Add failing safety tests for token, raw prompt, username, machine id, and unnecessary absolute path rejection in tests/core/test_telemetry.py
- [ ] T027 [P] [US1] Add failing duplicate import tests proving counts, durations, retries, and slowest operations stay stable in tests/core/test_telemetry.py
- [ ] T028 [P] [US1] Add failing final-gate integration test for imported host telemetry status in tests/test_native_workflow.py

### Implementation for User Story 1

- [ ] T029 [US1] Implement agent-jsonl parser and per-record diagnostics for external telemetry feeds in src/gh_address_cr/core/telemetry.py
- [ ] T030 [US1] Implement unsafe metadata rejection and sanitization before storing imported telemetry in src/gh_address_cr/core/telemetry.py
- [ ] T031 [US1] Implement deterministic event identity and duplicate import handling in src/gh_address_cr/core/telemetry.py
- [ ] T032 [US1] Persist TelemetryImport ledger entries and accepted external events under PR workspace paths in src/gh_address_cr/core/telemetry.py
- [ ] T033 [US1] Add telemetry ingest and telemetry summary command routing in src/gh_address_cr/cli.py
- [ ] T034 [US1] Merge runtime and imported external events into one EfficiencyReport with source attribution in src/gh_address_cr/core/telemetry.py
- [ ] T035 [US1] Include external telemetry status and diagnostics in final-gate evidence and audit_summary.md in src/gh_address_cr/core/gate.py
- [ ] T036 [US1] Update quickstart commands and expected imported telemetry evidence in specs/015-external-agent-telemetry/quickstart.md

**Checkpoint**: Host-agent import works without mutating review item state and final-gate reports imported coverage.

---

## Phase 5: User Story 2 - Support Generic AI Agent Reporting (Priority: P1)

**Goal**: Accept a generic AI agent telemetry contract while allowing host-specific adapters to normalize into the same canonical model.

**Independent Test**: Import a generic agent feed and a host-specific adapter feed, then verify both normalize to the same report model with source attribution and no vendor-specific requirement.

### Tests for User Story 2

- [ ] T037 [P] [US2] Add failing generic agent feed normalization tests for required fields, duration alternatives, status values, and safe metadata in tests/core/test_telemetry.py
- [ ] T038 [P] [US2] Add failing host-adapter normalization tests for a codex-style source into canonical ExternalTelemetryEvent in tests/core/test_telemetry.py
- [ ] T039 [P] [US2] Add failing standard envelope adapter tests for preserving source and coverage information in tests/core/test_telemetry.py
- [ ] T040 [P] [US2] Add failing CLI tests for unsupported format and ambiguous telemetry session diagnostics in tests/test_python_wrappers.py

### Implementation for User Story 2

- [ ] T041 [US2] Implement generic agent event contract validation and normalization in src/gh_address_cr/core/telemetry.py
- [ ] T042 [US2] Implement adapter registry for generic-agent, codex, and standard envelope inputs in src/gh_address_cr/core/telemetry.py
- [ ] T043 [US2] Implement unsupported format and ambiguous session reason codes in telemetry CLI output in src/gh_address_cr/cli.py
- [ ] T044 [US2] Add agent-facing telemetry protocol reference with generic contract and adapter boundaries in skill/references/agent-protocol.md
- [ ] T045 [US2] Update OpenAI agent guidance to import host telemetry when available without requiring vendor-specific behavior in skill/agents/openai.yaml
- [ ] T046 [US2] Add packaged-skill tests for generic telemetry protocol guidance and skill-root-relative paths in tests/test_skill_docs.py

**Checkpoint**: Generic agents can report telemetry through the public contract and adapters remain optional enrichment.

---

## Phase 6: User Story 4 - Diagnose Workflow Inefficiencies (Priority: P2)

**Goal**: Convert runtime and external telemetry into optimization signals for slow, repeated, failed, or low-confidence workflow segments.

**Independent Test**: Import mixed telemetry with long operations, failures, retries, and successes; verify the report highlights top bottlenecks, error-prone operations, and coverage confidence.

### Tests for User Story 4

- [ ] T047 [P] [US4] Add failing report tests for top three slowest operations with source attribution in tests/core/test_telemetry.py
- [ ] T048 [P] [US4] Add failing report tests for retry-heavy and error-rate inefficiency flags in tests/core/test_telemetry.py
- [ ] T049 [P] [US4] Add failing Markdown summary tests for confidence and partial coverage wording in tests/test_python_wrappers.py

### Implementation for User Story 4

- [ ] T050 [US4] Implement slowest operation ranking and duration threshold flags in src/gh_address_cr/core/telemetry.py
- [ ] T051 [US4] Implement error-prone operation grouping for failures, retries, timeouts, and success rate in src/gh_address_cr/core/telemetry.py
- [ ] T052 [US4] Implement coverage confidence and partial-observation explanation in src/gh_address_cr/core/telemetry.py
- [ ] T053 [US4] Render inefficiency flags and confidence labels in JSON and Markdown telemetry summaries in src/gh_address_cr/core/telemetry.py

**Checkpoint**: Reports identify actionable workflow bottlenecks without overstating incomplete telemetry.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Keep contracts, docs, and verification aligned across runtime and packaged skill.

- [ ] T054 [P] Update public telemetry command contract examples and failure reason wording in specs/015-external-agent-telemetry/contracts/telemetry-ingestion.md
- [ ] T055 [P] Update repository README command overview for telemetry ingest and summary in README.md
- [ ] T056 [P] Update packaged skill README or references to avoid repo-root paths inside skill-owned docs in skill/references/agent-protocol.md and skill/SKILL.md
- [ ] T057 Run ruff check src tests
- [ ] T058 Run python3 -m unittest discover -s tests
- [ ] T059 Run python3 -m gh_address_cr --help
- [ ] T060 Run quickstart runtime-only, generic import, duplicate import, unsafe rejection, and final-gate scenarios from specs/015-external-agent-telemetry/quickstart.md

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 Setup**: No dependencies.
- **Phase 2 Foundational**: Depends on Phase 1 and blocks all user stories.
- **Phase 3 US3 Repair Existing Metrics Summary Gap**: Depends on Phase 2 and is the recommended MVP slice.
- **Phase 4 US1 Import Host Agent Telemetry**: Depends on Phase 2; final-gate integration tasks depend on US3 report surfaces.
- **Phase 5 US2 Support Generic AI Agent Reporting**: Depends on Phase 2 and can proceed after US1 parser boundaries are clear.
- **Phase 6 US4 Diagnose Workflow Inefficiencies**: Depends on US3 report artifacts and benefits from US1/US2 imported event coverage.
- **Phase 7 Polish**: Depends on the selected implementation scope.

### User Story Dependencies

- **US3 (P1)**: First implementation slice; no dependency on external telemetry.
- **US1 (P1)**: Can start after Phase 2, but final-gate evidence should integrate with US3 report output.
- **US2 (P1)**: Can start after Phase 2; adapter registry should reuse US1 import storage and diagnostics when available.
- **US4 (P2)**: Requires report aggregation from US3 and broader event variety from US1/US2.

### Within Each User Story

- Write failing tests before implementation tasks.
- Define or update models before command routing.
- Implement core telemetry behavior before final-gate and skill documentation integration.
- Validate each story independently before moving to the next story.

---

## Parallel Opportunities

- T002, T003, and T004 can run in parallel after T001.
- T009 and T010 can run in parallel once T005-T008 interfaces are sketched.
- US3 tests T011-T014 can run in parallel before implementation.
- US1 tests T023-T028 can run in parallel before implementation.
- US2 tests T037-T040 can run in parallel before implementation.
- US4 tests T047-T049 can run in parallel before implementation.
- Documentation polish tasks T054-T056 can run in parallel after relevant public contracts stabilize.

---

## Parallel Example: US3 Runtime Metrics Repair

```bash
# Start independent failing tests together:
Task: "T011 [US3] Add final-gate stdout contract test in tests/test_python_wrappers.py"
Task: "T012 [US3] Add audit_summary.md contract test in tests/test_python_wrappers.py"
Task: "T013 [US3] Add structured EfficiencyReport artifact test in tests/core/test_telemetry.py"
Task: "T014 [US3] Add unavailable coverage test in tests/test_python_wrappers.py"
```

## Parallel Example: US1 Host Telemetry Import

```bash
# Start independent failing tests together:
Task: "T023 [US1] Add telemetry ingest CLI success contract test in tests/test_python_wrappers.py"
Task: "T025 [US1] Add malformed feed diagnostics test in tests/core/test_telemetry.py"
Task: "T026 [US1] Add unsafe telemetry rejection test in tests/core/test_telemetry.py"
Task: "T027 [US1] Add duplicate import stability test in tests/core/test_telemetry.py"
```

## Parallel Example: US2 Generic Agent Contract

```bash
# Start independent failing tests together:
Task: "T037 [US2] Add generic agent normalization tests in tests/core/test_telemetry.py"
Task: "T038 [US2] Add host-adapter normalization tests in tests/core/test_telemetry.py"
Task: "T039 [US2] Add standard envelope adapter tests in tests/core/test_telemetry.py"
Task: "T046 [US2] Add packaged-skill protocol guidance tests in tests/test_skill_docs.py"
```

---

## Implementation Strategy

### MVP First: US3 Repair Existing Metrics Summary Gap

1. Complete Phase 1 and Phase 2.
2. Complete Phase 3 to make runtime-only metrics visible in final-gate output, audit_summary.md, and structured report artifacts.
3. Stop and validate US3 with targeted tests and the runtime-only quickstart scenario.

### Incremental Delivery

1. Deliver US3 runtime-only report repair.
2. Deliver US1 external host telemetry ingestion and combined reporting.
3. Deliver US2 generic agent contract and adapter normalization.
4. Deliver US4 bottleneck and confidence diagnostics.
5. Run Phase 7 verification before claiming the feature complete.

### Validation Commands

```bash
ruff check src tests
python3 -m unittest discover -s tests
python3 -m gh_address_cr --help
```

## Notes

- `[P]` tasks touch different files or independent test cases and can run concurrently after their prerequisites are clear.
- `[US3]` is intentionally first because the existing 011 metrics summary repair is required before external telemetry can be trusted.
- Imported telemetry must never mutate review item state; final-gate remains authoritative for review-thread and pending-review completion.
