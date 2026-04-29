# Tasks: Thin Skill Orchestration

**Input**: Design documents from `specs/003-thin-skill-orchestration/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: This feature changes packaged-skill behavior, agent-facing contracts, documentation semantics, and multi-agent coordination expectations. Tests are required for documentation contracts, status/action mapping, lease behavior, producer intake, and final-gate-backed completion examples.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing. Stage 4 thin-skill work is deliberately separated from Stage 5 orchestration-readiness work so the MVP is not blocked by multi-agent fixtures. No task in this list implements a generic agent runner or built-in review engine.

## Phase 1: Setup

**Purpose**: Establish Stage 4 fixture and test-file scaffolding only.

- [x] T001 Create thin-skill orchestration fixture directory at `tests/fixtures/thin_skill_orchestration/`
- [x] T002 [P] Create documentation contract fixture/allowlist data in `tests/fixtures/thin_skill_orchestration/documentation_contracts.json`
- [x] T003 [P] Create representative runtime machine summary fixture corpus in `tests/fixtures/thin_skill_orchestration/status_summaries.json`
- [x] T004 [P] Create thin-skill orchestration contract test module in `tests/test_thin_skill_orchestration.py`

---

## Phase 2: Stage 4 Foundational

**Purpose**: Shared validators needed for the thin-skill MVP and status navigation.

**Critical**: This phase blocks US1 and US2 only. Stage 5 multi-agent and producer fixtures are introduced later so they do not delay the thin-skill MVP.

- [x] T005 Add shared documentation-contract helpers and fixture loading in `tests/test_skill_docs.py`
- [x] T006 [P] Add shared status-action fixture loading helpers in `tests/test_thin_skill_orchestration.py`
- [x] T007 [P] Add runtime compatibility pre-mutation helper coverage in `tests/test_runtime_packaging.py`
- [x] T008 Define no-runner/no-review-engine scope assertions in `tests/test_thin_skill_orchestration.py`

**Checkpoint**: Stage 4 validation scaffolding is ready; US1 and US2 can proceed.

---

## Phase 3: User Story 1 - Thin Skill Entry Contract (Priority: P1) MVP

**Goal**: Make the packaged skill first-read entrypoint a concise adapter that routes agents to the runtime and does not redefine runtime workflow behavior.

**Independent Test**: Reading `gh-address-cr/SKILL.md` proves it identifies itself as an adapter, routes first to the high-level runtime command, keeps runtime ownership explicit, and fails loudly when runtime compatibility is missing.

### Tests for User Story 1

- [x] T009 [US1] Add failing first-read adapter contract tests in `tests/test_skill_docs.py`
- [x] T010 [US1] Add failing runtime compatibility and missing-runtime pre-mutation tests in `tests/test_runtime_packaging.py`
- [x] T011 [US1] Add failing assistant hint thin-adapter and no-direct-side-effect tests in `tests/test_skill_docs.py`

### Implementation for User Story 1

- [x] T012 [US1] Rewrite first-read adapter guidance in `gh-address-cr/SKILL.md`
- [x] T013 [US1] Delete or compress duplicate workflow-state prose in `gh-address-cr/SKILL.md` and preserve runtime-owned details in `gh-address-cr/references/mode-producer-matrix.md`
- [x] T014 [US1] Update assistant-specific thin-adapter hints in `gh-address-cr/agents/openai.yaml`
- [x] T015 [US1] Update runtime compatibility wording in `gh-address-cr/runtime-requirements.json`

**Checkpoint**: MVP complete. The packaged skill can be used as a thin adapter without relying on repository-only documentation.

---

## Phase 4: User Story 2 - Structured Status Navigation (Priority: P1)

**Goal**: Provide a small status-to-action map derived from runtime machine summaries, with fail-loud behavior for unknown or malformed summaries.

**Independent Test**: Every status summary fixture maps to exactly one safe next action or one explicit stop condition; unknown or malformed summaries stop loudly.

### Tests for User Story 2

- [x] T016 [US2] Add status-to-action fixture contract tests in `tests/test_thin_skill_orchestration.py`
- [x] T017 [US2] Add malformed and unknown machine-summary fail-loud tests with actionable recovery-path assertions in `tests/test_thin_skill_orchestration.py`
- [x] T018 [US2] Add completion-summary final-gate evidence tests in `tests/test_skill_docs.py`

### Implementation for User Story 2

- [x] T019 [US2] Add packaged status-action reference in `gh-address-cr/references/status-action-map.md`
- [x] T020 [US2] Link the status-action map from `gh-address-cr/SKILL.md`
- [x] T021 [US2] Update status summary fixtures in `tests/fixtures/thin_skill_orchestration/status_summaries.json`

**Checkpoint**: Agents can interpret runtime statuses without parsing prose or inventing an adapter-owned state machine.

---

## Phase 5: Stage 5 Contract Foundation

**Purpose**: Introduce multi-agent and producer fixtures after the thin-skill MVP is available.

**Critical**: This phase blocks US3, US4, and US6 only. It must not introduce scheduler, agent spawning, polling loop, generic runner, or built-in review engine behavior.

- [x] T022 Create multi-agent orchestration fixture corpus for three items and four roles in `tests/fixtures/thin_skill_orchestration/multi_agent_session.json`
- [x] T023 [P] Create producer intake fixture corpus in `tests/fixtures/thin_skill_orchestration/producer_inputs/`
- [x] T024 [P] Add shared multi-agent session fixture loading helpers in `tests/test_control_plane_workflow.py`
- [x] T025 Add shared producer-intake fixture loading helpers in `tests/test_findings_intake.py`
- [x] T026 Add Stage 5 scope-guard assertions in `tests/test_thin_skill_orchestration.py`

**Checkpoint**: Contract-first orchestration readiness work can proceed without blocking Stage 4 delivery.

---

## Phase 6: User Story 3 - Multi-Agent Role Coordination (Priority: P1)

**Goal**: Define and validate role boundaries, capability checks, claim leases, evidence requirements, verifier rejection, and serialized GitHub publishing.

**Independent Test**: A simulated session with at least three independent items and four roles accepts only active lease-holder submissions, rejects conflicts or stale responses, blocks verifier-rejected fixes, and emits no duplicate GitHub side effects.

### Tests for User Story 3

- [x] T027 [P] [US3] Add capability manifest role/action eligibility tests in `tests/test_agent_protocol.py`
- [x] T028 [US3] Add multi-agent three-item lease conflict, stale submission, and interrupted lease resume/reclaim tests in `tests/test_control_plane_workflow.py`
- [x] T029 [US3] Add required-evidence rejection, verifier-rejection, and no-duplicate reply/resolve publishing regression tests in `tests/test_control_plane_workflow.py`
- [x] T030 [US3] Add role-coordination documentation contract tests in `tests/test_skill_docs.py`

### Implementation for User Story 3

- [x] T031 [US3] Add packaged multi-agent orchestration reference in `gh-address-cr/references/multi-agent-orchestration.md`
- [x] T032 [US3] Update multi-agent section in `gh-address-cr/SKILL.md`
- [x] T033 [US3] Align runtime agent manifest role/action descriptions in `src/gh_address_cr/cli.py` without adding runner, scheduler, or spawning behavior
- [x] T034 [US3] Update multi-agent fixture in `tests/fixtures/thin_skill_orchestration/multi_agent_session.json`

**Checkpoint**: Multi-agent execution is contract-first, lease-first, and runtime-owned, without scheduler or runner lock-in.

---

## Phase 7: User Story 6 - Replaceable Review Producer Intake (Priority: P2)

**Goal**: Preserve normalized findings as the stable intake boundary and reject narrative-only review output without binding the workflow to a specific review engine.

**Independent Test**: Two producer identities emitting normalized findings behave identically, fixed `finding` blocks are accepted through the converter path, narrative-only Markdown is rejected, and completion semantics remain unchanged.

### Tests for User Story 6

- [x] T035 [US6] Add narrative-only producer rejection tests in `tests/test_findings_intake.py`
- [x] T036 [US6] Add producer identity replacement tests in `tests/test_findings_intake.py`
- [x] T037 [P] [US6] Add fixed `finding` block converter contract tests in `tests/test_native_intake.py`
- [x] T038 [US6] Add producer-boundary documentation tests in `tests/test_skill_docs.py`

### Implementation for User Story 6

- [x] T039 [US6] Update producer intake guidance in `gh-address-cr/references/local-review-adapter.md`
- [x] T040 [US6] Update concise producer boundary in `gh-address-cr/SKILL.md`
- [x] T041 [US6] Update producer intake fixtures in `tests/fixtures/thin_skill_orchestration/producer_inputs/`

**Checkpoint**: The workflow remains a PR review resolution control plane, not a review engine.

---

## Phase 8: User Story 4 - Orchestration Readiness Without Runner Lock-In (Priority: P2)

**Goal**: Provide a human-usable orchestration runbook that demonstrates coordinator, triage, fixer, verifier, publisher, and gatekeeper flow without requiring an autonomous runner.

**Independent Test**: The runbook dry run uses high-level runtime surfaces, covers lease conflicts, verifier rejection, unsupported producer output, and final-gate proof, while explicitly excluding generic runner behavior.

### Tests for User Story 4

- [x] T042 [US4] Add runbook no-runner scope tests in `tests/test_thin_skill_orchestration.py`
- [x] T043 [US4] Add high-level-command-only runbook tests in `tests/test_skill_docs.py`
- [x] T044 [US4] Add quickstart dry-run coverage tests in `tests/test_skill_docs.py`

### Implementation for User Story 4

- [x] T045 [US4] Add manual orchestration runbook with active-lease interruption recovery in `gh-address-cr/references/multi-agent-runbook.md`
- [x] T046 [US4] Link the runbook from `gh-address-cr/SKILL.md`
- [x] T047 [US4] Align the feature quickstart with shipped runbook references in `specs/003-thin-skill-orchestration/quickstart.md`

**Checkpoint**: A human operator can coordinate multi-agent work through the runtime contract without a new runner.

---

## Phase 9: User Story 5 - Migration And Documentation Consistency (Priority: P2)

**Goal**: Keep README, packaged skill docs, advanced references, assistant hints, and compatibility guidance aligned on runtime ownership, path scope, public commands, and completion semantics.

**Independent Test**: Documentation scans find no contradictory ownership claims, repo-root paths in skill-owned docs, low-level scripts promoted as agent-safe APIs, or completion claims without final-gate evidence.

### Tests for User Story 5

- [x] T048 [US5] Add repo-root versus skill-root path-scope tests in `tests/test_skill_docs.py`
- [x] T049 [US5] Add low-level script non-public-surface and legacy delegate-or-fail-loud guidance tests in `tests/test_skill_docs.py`
- [x] T050 [US5] Add ownership contradiction scan tests in `tests/test_skill_docs.py`
- [x] T051 [US5] Add final-gate-backed completion example tests in `tests/test_skill_docs.py`

### Implementation for User Story 5

- [x] T052 [US5] Update public architecture and boundary sections in `README.md`
- [x] T053 [P] [US5] Update packaged advanced references in `gh-address-cr/references/mode-producer-matrix.md`
- [x] T054 [P] [US5] Update packaged triage and evidence references in `gh-address-cr/references/cr-triage-checklist.md` and `gh-address-cr/references/evidence-ledger.md`
- [x] T055 [P] [US5] Update assistant hint boundary wording in `gh-address-cr/agents/openai.yaml`

**Checkpoint**: Public docs agree on runtime ownership and path scope across repo-root and packaged skill payload.

---

## Phase 10: Polish & Cross-Cutting Concerns

**Purpose**: Verify all changed contracts together and prepare for implementation review.

- [x] T056 [P] Run documentation placeholder and contradiction scans for `README.md`, `gh-address-cr/SKILL.md`, `gh-address-cr/references/`, and `gh-address-cr/agents/openai.yaml`
- [x] T057 [P] Run quickstart validation commands from `specs/003-thin-skill-orchestration/quickstart.md`
- [x] T058 Run `ruff check gh-address-cr tests` for `gh-address-cr/` and `tests/`
- [x] T059 Run `python3 -m unittest discover -s tests` for `tests/`
- [x] T060 Run `python3 gh-address-cr/scripts/cli.py --help` for `gh-address-cr/scripts/cli.py`
- [x] T061 Run `python3 gh-address-cr/scripts/cli.py adapter check-runtime` for `gh-address-cr/scripts/cli.py`
- [x] T062 Run `git diff --check` from repository root `/Users/snow/Documents/GitHub/gh-address-cr-skill`
- [x] T063 Update implementation evidence and residual risks in `specs/003-thin-skill-orchestration/quickstart.md`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies.
- **Stage 4 Foundational (Phase 2)**: Depends on Setup and blocks US1/US2.
- **US1 Thin Skill Entry Contract (Phase 3)**: Depends on Stage 4 Foundational and is the MVP.
- **US2 Structured Status Navigation (Phase 4)**: Depends on Stage 4 Foundational; can run after or alongside US1 with an adapter-doc owner coordinating `gh-address-cr/SKILL.md`.
- **Stage 5 Contract Foundation (Phase 5)**: Depends on Setup and can start after US1 begins; blocks US3/US4/US6.
- **US3 Multi-Agent Role Coordination (Phase 6)**: Depends on Stage 5 Contract Foundation.
- **US6 Replaceable Review Producer Intake (Phase 7)**: Depends on Stage 5 Contract Foundation; can run in parallel with US3 except for shared `gh-address-cr/SKILL.md` edits.
- **US4 Orchestration Readiness (Phase 8)**: Depends on US3 role vocabulary for final runbook wording.
- **US5 Documentation Consistency (Phase 9)**: Final documentation pass; depends on all selected story docs changes.
- **Polish (Phase 10)**: Depends on selected story phases being complete.

### User Story Dependencies

- **US1 (P1)**: MVP; no dependency on other user stories after Stage 4 Foundation.
- **US2 (P1)**: Independent after Stage 4 Foundation; shares final `gh-address-cr/SKILL.md` link wording with US1.
- **US3 (P1)**: Independent after Stage 5 Foundation; runtime protocol tests may run separately from docs edits.
- **US6 (P2)**: Independent after Stage 5 Foundation; can run in parallel with US3.
- **US4 (P2)**: Depends on US3 role vocabulary and should not introduce runner behavior.
- **US5 (P2)**: Cross-cutting final pass after docs from US1, US2, US3, US4, and US6 settle.

### TDD Order

- Write story tests first and confirm they fail for the missing behavior.
- Implement only the files named by that story phase.
- Rerun the story-specific tests before marking the story complete.
- Run Phase 10 checks before any completion claim.

---

## Parallel Execution Examples

### Stage 4 MVP Split

```text
Agent A: US1 adapter entry contract
  Owns gh-address-cr/SKILL.md, gh-address-cr/runtime-requirements.json, and gh-address-cr/agents/openai.yaml.
  Coordinates all first-read SKILL.md edits.

Agent B: US2 status-action map
  Owns tests/test_thin_skill_orchestration.py, tests/fixtures/thin_skill_orchestration/status_summaries.json, and gh-address-cr/references/status-action-map.md.
  Requests Agent A to add only the final SKILL.md link.
```

### Stage 5 Contract Split

```text
Agent C: US3 role coordination
  Owns tests/test_agent_protocol.py, tests/test_control_plane_workflow.py, tests/fixtures/thin_skill_orchestration/multi_agent_session.json, and gh-address-cr/references/multi-agent-orchestration.md.
  May only align src/gh_address_cr/cli.py manifest descriptions; must not add runner behavior.

Agent D: US6 producer intake
  Owns tests/test_findings_intake.py, tests/test_native_intake.py, tests/fixtures/thin_skill_orchestration/producer_inputs/, and gh-address-cr/references/local-review-adapter.md.
```

### Final Documentation Pass

```text
Agent E: US5 docs consistency
  Owns README.md plus final consistency checks across gh-address-cr/SKILL.md, gh-address-cr/references/, and gh-address-cr/agents/openai.yaml.
  Runs after story docs settle to avoid parallel edits to the same public docs.
```

### Runner Boundary Guard

```text
Agent F: US4 manual orchestration runbook
  Owns gh-address-cr/references/multi-agent-runbook.md and specs/003-thin-skill-orchestration/quickstart.md.
  Must not add scheduler, spawning, polling loop, or generic runner implementation.
```

---

## Implementation Strategy

### MVP First

Complete Phase 1, Phase 2, and US1. This gives a safer packaged skill entrypoint even before full orchestration readiness lands.

### Incremental Delivery

1. Deliver US1 and US2 together to make the skill both thin and navigable.
2. Deliver Stage 5 Contract Foundation.
3. Deliver US3 to make multi-agent coordination contract-backed.
4. Deliver US6 to lock review producer replacement and narrative rejection.
5. Deliver US4 to document manual orchestration without runner lock-in.
6. Deliver US5 and Phase 10 as the final consistency and verification pass.

### Scope Guardrails

- Do not implement an autonomous scheduler, agent spawner, polling loop, or generic task runner.
- Do not add a built-in review engine or prompt-owned review producer.
- Do not make low-level scripts the recommended agent-safe public API.
- Do not weaken `reply evidence + resolved thread state + final-gate proof`.
