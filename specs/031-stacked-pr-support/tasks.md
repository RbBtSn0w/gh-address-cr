# Tasks: Stacked Pull Request Support

**Input**: Design documents from `specs/031-stacked-pr-support/`  
**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/`, `quickstart.md`

**Test discipline**: Every behavior task starts with the named focused test,
records the expected failure, makes the smallest production change, then records
the passing focused command before its checkbox is completed.

## Phase 1: Setup and Fixtures

**Purpose**: Establish replay inputs without changing runtime behavior.

- [X] T001 Create absent, valid three-layer, multi-page, merged-prefix, draft, queued, unavailable, and malformed GraphQL fixtures in `tests/fixtures/stacked_pr/`
- [X] T002 [P] Add reusable stacked-PR session and GitHub runner builders in `tests/helpers.py`
- [X] T003 [P] Add the stack feature contract constants and expected stable reason-code inventory to `tests/contract/test_stacked_pr_contract.py`

---

## Phase 2: Foundational Runtime Contracts

**Purpose**: Lock the fact/projection/policy and compatibility boundaries before user-facing integration.

- [X] T004 Write failing replay tests for stack observation validation, canonical fingerprinting, merged-prefix segmentation, and deterministic failure precedence in `tests/test_stack_kernel.py`; focused command: `python3 -m unittest tests.test_stack_kernel`
- [X] T005 Implement immutable stack facts, context projection, canonical fingerprinting, active-segment selection, and policy decisions in `src/gh_address_cr/core/runtime_kernel/stack.py` until T004 passes
- [X] T006 [P] Write failing reason-code and Status-to-Action inventory assertions in `tests/contract/test_stacked_pr_contract.py`; focused command: `python3 -m unittest tests.contract.test_stacked_pr_contract`
- [X] T007 Add stack availability, freshness, member, and revision reason codes without repurposing existing values in `src/gh_address_cr/core/protocol_codes.py` until T006 passes
- [X] T008 Verify the foundational replay boundary and diff hygiene with `python3 -m unittest tests.test_stack_kernel tests.contract.test_stacked_pr_contract` and `git diff --check`

**Checkpoint**: The pure kernel can replay every supported/invalid topology without GitHub IO or session mutation.

---

## Phase 3: User Story 1 — Understand the Current Layer and Stack (Priority: P1) 🎯 MVP

**Goal**: Existing PR commands report validated stack context while unstacked behavior remains compatible.

**Independent Test**: Run unstacked plus bottom/middle/top fixtures through high-level commands and verify correct context with zero side effects.

### Tests for User Story 1

- [X] T009 [P] [US1] Write failing GitHub adapter tests for selected PR facts, `stack`/`stackEntry`, full pagination, capability absence, and bounded malformed diagnostics in `tests/test_stack_github_client.py`; focused command: `python3 -m unittest tests.test_stack_github_client`
- [X] T010 [P] [US1] Write failing machine-summary compatibility tests for unstacked and valid stack positions in `tests/contract/test_stacked_pr_contract.py`; focused command: `python3 -m unittest tests.contract.test_stacked_pr_contract.StackContextContractTests`
- [X] T011 [P] [US1] Write failing high-level integration tests proving stack discovery is read-only and unavailable context remains explicit in `tests/test_python_wrappers.py`; focused command: `python3 -m unittest tests.test_python_wrappers`

### Implementation for User Story 1

- [X] T012 [US1] Add a separate paginated pull-request/stack context read with preview-capability classification to `src/gh_address_cr/github/client.py` until T009 passes
- [X] T013 [US1] Add non-authoritative observed PR context refresh/cache helpers to `src/gh_address_cr/core/session.py` without creating stack-owned state
- [X] T014 [US1] Add `stack_context`, `completion_scope=pull_request`, and `stack_merge_readiness=not_evaluated` to high-level summaries in `src/gh_address_cr/commands/high_level.py` until T010 and T011 pass
- [X] T015 [US1] Keep PR-scoped command templates unchanged and centralize safe reusable stack serialization in `src/gh_address_cr/core/runtime_kernel/stack.py`
- [X] T016 [US1] Verify US1 with `python3 -m unittest tests.test_stack_kernel tests.test_stack_github_client tests.contract.test_stacked_pr_contract.StackContextContractTests tests.test_python_wrappers`

**Checkpoint**: US1 is independently shippable as read-only stack awareness; no worker, publish, or gate semantics have changed.

---

## Phase 4: User Story 2 — Resolve Feedback on the Owning Layer (Priority: P2)

**Goal**: Requests and validation evidence are bound to the stacked member revision and become stale before side effects when context changes.

**Independent Test**: Accept a same-context response, then mutate head OID and position fixtures and prove submit/publish rejects before GitHub calls.

### Tests for User Story 2

- [X] T017 [P] [US2] Write failing ActionRequest and batch-request contract tests for `stack_context.v1`, `revision_binding.v1`, and stack-management prohibitions in `tests/test_agent_protocol.py`; focused command: `python3 -m unittest tests.test_agent_protocol`
- [X] T018 [P] [US2] Write failing stale-head, reordered-stack, explicit wrong-owner, and no-GitHub-side-effect tests in `tests/contract/test_stacked_pr_contract.py`; focused command: `python3 -m unittest tests.contract.test_stacked_pr_contract.RevisionBindingContractTests`
- [X] T019 [P] [US2] Write failing evidence eligibility tests for current, unbound, and stale stacked revisions in `tests/test_logic_validation.py` and `tests/test_final_gate_kernel.py`; focused command: `python3 -m unittest tests.test_logic_validation tests.test_final_gate_kernel`

### Implementation for User Story 2

- [X] T020 [US2] Add current stack/revision context to single-item ActionRequest creation and immutable request hashing in `src/gh_address_cr/core/agent_protocol.py` until T017 passes
- [X] T021 [US2] Add the identical stack/revision context contract to batch request creation in `src/gh_address_cr/core/agent_batch.py` until T017 passes
- [X] T022 [US2] Refresh and compare request context before submit, convenience resolve, evidence add, and publish in `src/gh_address_cr/core/agent_protocol.py`, `src/gh_address_cr/core/workflow.py`, and `src/gh_address_cr/core/publisher.py` until T018 passes
- [X] T023 [US2] Attach runtime-owned `revision_binding.v1` to accepted validation evidence and implement current/unbound/stale eligibility in `src/gh_address_cr/core/validation_evidence.py` until T019 passes
- [X] T024 [US2] Project stale/unbound revision signals into existing logic and layer final-gate policy in `src/gh_address_cr/core/logic_validation.py` and `src/gh_address_cr/core/runtime_kernel/final_gate.py`
- [X] T025 [US2] Wire stack refresh failures and deterministic recovery output through `src/gh_address_cr/commands/agent.py` without changing unstacked command input
- [X] T026 [US2] Verify US2 with `python3 -m unittest tests.test_agent_protocol tests.test_logic_validation tests.test_final_gate_kernel tests.contract.test_stacked_pr_contract.RevisionBindingContractTests`

**Checkpoint**: US2 prevents stale or cross-layer evidence from reaching existing reply/resolve side effects.

---

## Phase 5: User Story 3 — Prove Layer and Stack Readiness Separately (Priority: P3)

**Goal**: Default final-gate proves one layer; explicit `--stack` recomputes a coherent bottom-up segment.

**Independent Test**: Clear blockers across a three-layer fixture bottom-up, then mutate the closing topology and prove the aggregate pass is suppressed.

### Tests for User Story 3

- [X] T027 [P] [US3] Write failing CLI parser and machine-output tests for `final-gate --stack`, option composition, unstacked one-member scope, and layer compatibility in `tests/test_final_gate.py`; focused command: `python3 -m unittest tests.test_final_gate`
- [X] T028 [P] [US3] Write failing aggregate tests for missing sessions, draft/closed/queued members, nested member failures, bottom-up ordering, passing range, and closing-fingerprint mutation in `tests/test_stack_final_gate.py`; focused command: `python3 -m unittest tests.test_stack_final_gate`
- [X] T029 [P] [US3] Write failing completion-contract and stable stack Status-to-Action assertions in `tests/contract/test_stacked_pr_contract.py`; focused command: `python3 -m unittest tests.contract.test_stacked_pr_contract.StackFinalGateContractTests`

### Implementation for User Story 3

- [X] T030 [US3] Implement the read-only aggregate coordinator that loads existing member sessions and recomputes current layer gates in `src/gh_address_cr/core/stack_gate.py` until T028 passes
- [X] T031 [US3] Add `--stack` parsing and check-policy composition without changing default layer behavior in `src/gh_address_cr/commands/final_gate.py` until T027 passes
- [X] T032 [US3] Add layer `completion_scope`, aggregate `stack_gate_result.v1`, exact covered range, and nested member outcomes to `src/gh_address_cr/core/gate.py` and `src/gh_address_cr/commands/final_gate.py`
- [X] T033 [US3] Add closing topology reobservation and suppress completion artifacts/lines on `STACK_CONTEXT_STALE` in `src/gh_address_cr/core/stack_gate.py` and `src/gh_address_cr/commands/final_gate.py`
- [X] T034 [US3] Add member-specific recovery command templates and Status-to-Action mapping in `src/gh_address_cr/core/command_templates.py` and `src/gh_address_cr/core/gate.py` until T029 passes
- [X] T035 [US3] Update compact completion summaries to state `PR layer` versus `stack segment` scope in `src/gh_address_cr/commands/final_gate.py`
- [X] T036 [US3] Verify US3 with `python3 -m unittest tests.test_final_gate tests.test_stack_final_gate tests.contract.test_stacked_pr_contract.StackFinalGateContractTests`

**Checkpoint**: US3 supplies deterministic stack readiness without trusting prior artifacts or mutating GitHub stack state.

---

## Phase 6: User Story 4 — Adopt Preview Support Safely (Priority: P4)

**Goal**: Ship observable, privacy-safe, documented preview support with reproducible local and live evidence.

**Independent Test**: Run privacy/docs contracts, full repo gates, live schema probe, then an isolated real-stack acceptance run.

### Tests for User Story 4

- [X] T037 [P] [US4] Write failing telemetry tests for bounded stack discovery/evaluation events, existing coverage labels, and fail-open telemetry in `tests/test_otel_telemetry.py`; focused command: `python3 -m unittest tests.test_otel_telemetry`
- [X] T038 [P] [US4] Write failing privacy tests excluding branches, member lists, fingerprints, paths, titles, bodies, users, and tokens from exported telemetry/public-safe reports in `tests/contract/test_stacked_pr_contract.py`; focused command: `python3 -m unittest tests.contract.test_stacked_pr_contract.TelemetryPrivacyContractTests`
- [X] T039 [P] [US4] Write failing packaged-skill and repo-doc sync assertions for layer ownership, bottom-up flow, revision invalidation, and `gh stack` boundary in `tests/test_skill_docs.py`; focused command: `python3 -m unittest tests.test_skill_docs`

### Implementation for User Story 4

- [X] T040 [US4] Emit stack discovery and aggregate decision events on the existing root invocation span in `src/gh_address_cr/otel_tracing.py` and command integration points until T037 passes
- [X] T041 [US4] Add bounded size/position helpers and privacy sanitization in `src/gh_address_cr/core/telemetry_safety.py` until T038 passes
- [X] T042 [US4] Update public workflow and stable machine-field guidance in `README.md` with the public-preview and stack-management boundary
- [X] T043 [US4] Update installed routing/policy in `skill/SKILL.md` and `skill/references/agent-protocol.md` for stack context and revision binding
- [X] T044 [US4] Update `skill/references/completion-contract.md` and `skill/references/status-action-map.md` for layer versus stack proof and recovery codes until T039 passes
- [X] T045 [US4] Verify US4 with `python3 -m unittest tests.test_otel_telemetry tests.test_skill_docs tests.contract.test_stacked_pr_contract.TelemetryPrivacyContractTests`

**Checkpoint**: All four stories are locally complete and independently reproducible.

---

## Phase 7: Full Verification and Live Acceptance

- [X] T046 Run `pip install -e .` before repository verification
- [X] T047 Run `ruff check src tests scripts/build_plugin_payload.py`
- [X] T048 Run `python3 -m unittest discover -s tests`
- [X] T049 [P] Run `python3 -m gh_address_cr --help` and verify `final-gate --help` documents `--stack`
- [X] T050 [P] Run `python3 -m gh_address_cr agent manifest`
- [X] T051 Run `python3 scripts/build_plugin_payload.py --output dist/plugin/gh-address-cr` and `python3 scripts/build_plugin_payload.py --check`
- [X] T052 Run the read-only live GraphQL schema probe and record `gh`/extension capability evidence in `specs/031-stacked-pr-support/validation.md`
- [X] T053 Run read-only bottom/middle/top discovery against an authorized disposable real stack and record exact machine results in `specs/031-stacked-pr-support/validation.md`
- [X] T054 Run the explicitly authorized lower-layer mutation, stale-evidence rejection, revalidation, and aggregate gate acceptance sequence from `quickstart.md`, or record the exact external authorization blocker in `specs/031-stacked-pr-support/validation.md`
- [X] T055 Review `git diff --check`, repository-root versus skill-root path language, public contract consistency, and uncommitted user changes; draft but do not create a Conventional Commit

---

## Dependencies & Execution Order

### Phase Dependencies

- Setup → Foundational → US1 → US2 → US3 → US4 → Full Verification.
- US1 is the MVP and can ship independently as read-only awareness.
- US2 depends on US1 context but is independently tested with immutable fixtures.
- US3 depends on US1 context and US2 evidence eligibility while reusing the existing layer gate.
- US4 observes and documents the completed behavior; it cannot satisfy earlier gates.

### Parallel Opportunities

- T002 and T003 may run in parallel after T001.
- Within each story, test tasks marked `[P]` may be authored in parallel before implementation.
- T049 and T050 may run in parallel after the full unit suite.
- Live Level A (T052) is independent of mutation authorization; T053/T054 are intentionally sequential.

## Implementation Strategy

### MVP First

1. Complete T001–T008 foundational contracts.
2. Complete T009–T016 (US1).
3. Stop and verify the read-only awareness slice before any evidence/gate change.

### Incremental Delivery

1. US1: identify stack and owner safely.
2. US2: prevent revision/context drift before side effects.
3. US3: aggregate current member gates bottom-up.
4. US4: add privacy-safe observability and installed guidance.
5. Run local gates, then report live capability, discovery, and mutation proof separately.

## Notes

- Do not mark a behavior task complete without first observing its focused test fail for the missing behavior and then pass.
- Do not install extensions, create remote stacks, push, force-update, or merge without the live-acceptance authorization described in T053/T054.
- Do not stage, commit, push, or create a PR unless explicitly requested.
