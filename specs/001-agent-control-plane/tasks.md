# Tasks: Agentic Control Plane Runtime Separation

**Input**: Design documents from `/specs/001-agent-control-plane/`
**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/`, `quickstart.md`
**Fail-Fast Rule**: Every behavior task starts with a failing executable check or an exact contract assertion before implementation. No hidden fallback, guessed compatibility, or silent downgrade is allowed.

## Agent Ownership Lanes

Use these lanes when assigning work to parallel Codex agents. Each lane owns a disjoint write set unless a task explicitly says otherwise.

- **Runtime CLI Agent**: owns `pyproject.toml`, `src/gh_address_cr/cli.py`, `src/gh_address_cr/__main__.py`, `src/gh_address_cr/core/workflow.py`, and public command wiring.
- **Protocol Agent**: owns `src/gh_address_cr/agent/`, `src/gh_address_cr/core/models.py`, and protocol/manifest tests.
- **Lease Coordinator Agent**: owns `src/gh_address_cr/core/leases.py`, lease state transitions, conflict detection, and lease tests.
- **GitHub Evidence Agent**: owns `src/gh_address_cr/github/`, `src/gh_address_cr/evidence/`, side-effect idempotency, retry records, and GitHub IO tests.
- **Gate Agent**: owns `src/gh_address_cr/core/gate.py`, final-gate behavior, and gate tests.
- **Skill Adapter Agent**: owns `gh-address-cr/SKILL.md`, `gh-address-cr/scripts/cli.py`, `gh-address-cr/runtime-requirements.json`, `gh-address-cr/agents/`, `gh-address-cr/references/`, and skill boundary docs/tests.
- **Verification Agent**: owns test orchestration, task/spec coverage checks, and final validation commands in `tests/` and `specs/001-agent-control-plane/quickstart.md`.

## Parallel Execution Policy

- The Runtime CLI Agent and Skill Adapter Agent may work in parallel only after `T001-T010` establish the package and compatibility test skeletons.
- The Protocol Agent and Lease Coordinator Agent may work in parallel after `T011-T019` define failing schema and model tests.
- The GitHub Evidence Agent and Gate Agent may work in parallel after the Protocol Agent lands `ActionResponse`, `EvidenceRecord`, and `SideEffectAttempt` models.
- GitHub side-effect publishing tasks must remain serialized by the GitHub Evidence Agent; parallel agents may prepare ledger evidence but must not post or resolve directly.
- The Verification Agent should run after each story phase and reject completion claims that lack exact test evidence.

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: Can run in parallel with other tasks in the same phase if ownership lanes do not overlap.
- **[Story]**: User story label from `spec.md`; omitted for setup/foundation/polish tasks.
- Ownership appears inside the description as `Owner: <lane> - ...` to keep Spec Kit task labels parser-safe.
- Every task names the file path it changes or verifies.

## Phase 1: Setup

**Purpose**: Create the physical runtime package surface without moving behavior yet.

- [X] T001 Owner: Runtime CLI Agent - Create runtime package directories under `src/gh_address_cr/` for `agent/`, `core/`, `github/`, `intake/`, and `evidence/`.
- [X] T002 Owner: Runtime CLI Agent - Add minimal package markers in `src/gh_address_cr/__init__.py`, `src/gh_address_cr/agent/__init__.py`, `src/gh_address_cr/core/__init__.py`, `src/gh_address_cr/github/__init__.py`, `src/gh_address_cr/intake/__init__.py`, and `src/gh_address_cr/evidence/__init__.py`.
- [X] T003 Owner: Runtime CLI Agent - Update `pyproject.toml` with runtime package metadata, Python `>=3.10`, setuptools package discovery from `src`, and console script `gh-address-cr = "gh_address_cr.cli:main"`.
- [X] T004 Owner: Runtime CLI Agent - Add module entrypoint `src/gh_address_cr/__main__.py` that invokes `gh_address_cr.cli.main`.
- [X] T005 Owner: Skill Adapter Agent - Add `gh-address-cr/runtime-requirements.json` declaring required runtime package name, minimum runtime version, supported protocol version range, and required public entrypoints.
- [X] T006 Owner: Verification Agent - Add shared test helpers for repo root, skill root, runtime source root, command execution, and environment-path overrides in `tests/helpers.py`.
- [X] T007 Owner: Verification Agent - Document the multi-agent ownership lanes in `specs/001-agent-control-plane/quickstart.md`.
- [X] T008 Owner: Verification Agent - Run `python3 -m unittest discover -s tests` and record the expected setup-only failures in `specs/001-agent-control-plane/quickstart.md`.

## Phase 2: Foundation

**Purpose**: Establish fail-fast contracts, schema validation, tool preflight, and minimal runtime wiring required by every story.

- [X] T009 [P] Owner: Verification Agent - Add a failing console entrypoint test for `gh-address-cr --help` and `python3 -m gh_address_cr --help` in `tests/test_runtime_packaging.py`.
- [X] T010 [P] Owner: Skill Adapter Agent - Add a failing shim delegation test that proves `python3 gh-address-cr/scripts/cli.py --help` exits non-zero with a clear runtime-missing error when the runtime is absent in `tests/test_skill_runtime_shim.py`.
- [X] T011 [P] Owner: Protocol Agent - Add failing ActionRequest schema tests for required fields, `item_id`, `role`, `allowed_actions`, and `required_evidence` in `tests/test_agent_protocol.py`.
- [X] T012 [P] Owner: Protocol Agent - Add failing ActionResponse schema tests for `fix`, `clarify`, `defer`, and `reject` outcomes with exact evidence assertions in `tests/test_agent_protocol.py`.
- [X] T013 [P] Owner: Lease Coordinator Agent - Add failing lease lifecycle tests for `active`, `released`, `expired`, and `rejected` transitions in `tests/test_claim_leases.py`.
- [X] T014 [P] Owner: Lease Coordinator Agent - Add failing conflict-key tests that reject overlapping write leases and allow read-only compatible leases in `tests/test_claim_leases.py`.
- [X] T015 [P] Owner: GitHub Evidence Agent - Add failing EvidenceRecord and SideEffectAttempt serialization tests in `tests/test_control_plane_workflow.py`.
- [X] T016 [P] Owner: Gate Agent - Add failing final-gate tests for unresolved threads, missing reply evidence, pending review, blocking local items, and missing validation evidence in `tests/test_control_plane_workflow.py`.
- [X] T017 [P] Owner: Runtime CLI Agent - Add failing GitHub tool preflight tests for missing `gh`, unauthenticated `gh`, and exact non-zero reason codes in `tests/test_runtime_packaging.py`.
- [X] T018 Owner: Runtime CLI Agent - Implement fail-fast CLI argument parsing in `src/gh_address_cr/cli.py` with `--help`, command dispatch, and explicit unknown-command errors.
- [X] T019 Owner: Protocol Agent - Implement core dataclasses or typed models in `src/gh_address_cr/core/models.py` for `ReviewSession`, `WorkItem`, `ActionRequest`, `ActionResponse`, `EvidenceRecord`, `SideEffectAttempt`, `CapabilityManifest`, and `ClaimLease`.
- [X] T020 Owner: Protocol Agent - Implement protocol validation helpers in `src/gh_address_cr/agent/requests.py`, `src/gh_address_cr/agent/responses.py`, `src/gh_address_cr/agent/roles.py`, and `src/gh_address_cr/agent/manifests.py`.
- [X] T021 Owner: Lease Coordinator Agent - Implement lease lifecycle and conflict validation in `src/gh_address_cr/core/leases.py`.
- [X] T022 Owner: GitHub Evidence Agent - Implement append-only ledger primitives in `src/gh_address_cr/evidence/ledger.py`.
- [X] T023 Owner: Gate Agent - Implement gate result model and exact failure reasons in `src/gh_address_cr/core/gate.py`.
- [X] T024 Owner: Runtime CLI Agent - Add basic session persistence helpers in `src/gh_address_cr/core/session.py` without GitHub side effects.
- [X] T025 Owner: Runtime CLI Agent - Create `src/gh_address_cr/core/workflow.py` with explicit no-side-effect workflow primitives used by later story phases.
- [X] T026 Owner: Runtime CLI Agent - Implement GitHub CLI preflight in `src/gh_address_cr/cli.py` before PR IO command dispatch and before session mutation.
- [X] T027 Owner: Runtime CLI Agent - Add failing runtime public command parity tests for `review`, `threads`, `findings`, `adapter`, `review-to-findings`, `final-gate`, and `cr-loop --help` in `tests/test_runtime_packaging.py` before the skill shim is replaced.
- [X] T028 Owner: Verification Agent - Run `python3 -m unittest tests.test_runtime_packaging tests.test_agent_protocol tests.test_claim_leases tests.test_control_plane_workflow` and record failures that remain blocked by story work in `specs/001-agent-control-plane/quickstart.md`.

## Phase 3: User Story 6 - Runtime And Skill Separation (Priority: P1)

**Goal**: The runtime CLI is outside the packaged skill; the packaged skill contains only instructions, references, assets, assistant hints, and a thin compatibility shim.

**Independent Test**: Installing the runtime exposes `gh-address-cr` and `python3 -m gh_address_cr`; invoking the skill shim delegates to that runtime or fails loudly before mutating session state.

- [X] T029 [P] [US6] Owner: Runtime CLI Agent - Add failing packaging test that imports `gh_address_cr.cli` from `src/gh_address_cr/cli.py` and rejects importing runtime code from `gh-address-cr/` in `tests/test_runtime_packaging.py`.
- [X] T030 [P] [US6] Owner: Skill Adapter Agent - Add failing test that scans `gh-address-cr/` and rejects copied runtime modules outside approved shim/reference paths in `tests/test_skill_runtime_shim.py`.
- [X] T031 [P] [US6] Owner: Skill Adapter Agent - Add failing compatibility preflight tests for missing runtime, too-old runtime version, unsupported protocol version, and missing entrypoints in `tests/test_skill_runtime_shim.py`.
- [X] T032 [US6] Owner: Runtime CLI Agent - Implement package version and protocol version exports in `src/gh_address_cr/__init__.py`.
- [X] T033 [US6] Owner: Runtime CLI Agent - Implement runtime compatibility reporting in `src/gh_address_cr/cli.py` for `gh-address-cr adapter check-runtime`.
- [X] T034 [US6] Owner: Verification Agent - Run the public command parity tests from `tests/test_runtime_packaging.py` before replacing `gh-address-cr/scripts/cli.py`.
- [X] T035 [US6] Owner: Skill Adapter Agent - Replace `gh-address-cr/scripts/cli.py` with a compatibility shim that loads the installed runtime entrypoint or exits with a clear remediation message before session mutation.
- [X] T036 [US6] Owner: Skill Adapter Agent - Update `gh-address-cr/SKILL.md` to describe the packaged skill as a thin adapter and point all stateful work to the runtime CLI.
- [X] T037 [US6] Owner: Skill Adapter Agent - Update `gh-address-cr/references/` docs to remove any claim that the skill owns runtime state machines or GitHub side effects.
- [X] T038 [US6] Owner: Verification Agent - Update `README.md` to document separate runtime installation, packaged skill installation, and compatibility shim behavior.
- [X] T039 [US6] Owner: Verification Agent - Run `python3 gh-address-cr/scripts/cli.py --help` and assert the output either delegates to runtime help or fails loudly with no session mutation.
- [X] T040 [US6] Owner: Verification Agent - Run `python3 -m unittest tests.test_runtime_packaging tests.test_skill_runtime_shim` and verify `gh-address-cr/` contains no runtime package copy via `tests/test_skill_runtime_shim.py`.

## Phase 4: User Story 1 - Review Initialization And Inspection (Priority: P1)

**Goal**: A coordinator can inspect a PR, ingest normalized findings, initialize a session, and emit the first ActionRequest through the runtime CLI.

**Independent Test**: Given a fixture PR and normalized findings, `gh-address-cr review` creates a session, preserves finding provenance, and emits a valid ActionRequest without relying on skill-local runtime code.

- [X] T041 [P] [US1] Owner: Runtime CLI Agent - Add failing CLI tests for `gh-address-cr review <owner/repo> <pr>` session initialization in `tests/test_control_plane_workflow.py`.
- [X] T042 [P] [US1] Owner: Protocol Agent - Add failing ActionRequest emission tests for PR thread items, local finding items, role eligibility, and required evidence in `tests/test_agent_protocol.py`.
- [X] T043 [P] [US1] Owner: GitHub Evidence Agent - Add failing normalized findings ingestion tests for fixed `finding` blocks and narrative rejection in `tests/test_findings_intake.py`.
- [X] T044 [US1] Owner: Runtime CLI Agent - Implement `review` command routing in `src/gh_address_cr/cli.py`.
- [X] T045 [US1] Owner: Runtime CLI Agent - Implement session creation and status persistence in `src/gh_address_cr/core/session.py`.
- [X] T046 [US1] Owner: Protocol Agent - Implement ActionRequest generation for first available blocking item in `src/gh_address_cr/agent/requests.py`.
- [X] T047 [US1] Owner: GitHub Evidence Agent - Implement PR thread inspection adapter interfaces in `src/gh_address_cr/github/threads.py`.
- [X] T048 [US1] Owner: GitHub Evidence Agent - Implement normalized findings ingestion in `src/gh_address_cr/intake/findings.py`.
- [X] T049 [US1] Owner: GitHub Evidence Agent - Implement intake adapter dispatch in `src/gh_address_cr/intake/adapters.py`.
- [X] T050 [US1] Owner: Runtime CLI Agent - Add `threads` and `findings` command routing in `src/gh_address_cr/cli.py` for existing public surfaces.
- [X] T051 [US1] Owner: Verification Agent - Update `README.md` examples for runtime-owned `review`, `threads`, and `findings` commands.
- [X] T052 [US1] Owner: Verification Agent - Run `python3 -m unittest tests.test_control_plane_workflow tests.test_agent_protocol tests.test_findings_intake` and record exact failures or passes in `specs/001-agent-control-plane/quickstart.md`.

## Phase 5: User Story 2 - Agentic Resolution Loop (Priority: P1)

**Goal**: An AI agent consumes ActionRequest, returns ActionResponse, and the runtime validates outcome-specific evidence before any terminal state or side effect.

**Independent Test**: A malformed or evidence-light ActionResponse is rejected with exact validation errors; valid `fix`, `clarify`, `defer`, and `reject` responses update local state without hidden defaults.

- [X] T053 [P] [US2] Owner: Protocol Agent - Add failing tests for `fix` response evidence: files changed, validation commands, result summary, and lease ID in `tests/test_agent_protocol.py`.
- [X] T054 [P] [US2] Owner: Protocol Agent - Add failing tests for `clarify`, `defer`, and `reject` response evidence rules in `tests/test_agent_protocol.py`.
- [X] T055 [P] [US2] Owner: Runtime CLI Agent - Add failing CLI tests for `gh-address-cr agent next` and `gh-address-cr agent submit` in `tests/test_control_plane_workflow.py`.
- [X] T056 [US2] Owner: Protocol Agent - Implement outcome-specific ActionResponse validators in `src/gh_address_cr/agent/responses.py`.
- [X] T057 [US2] Owner: Runtime CLI Agent - Implement `agent next` command in `src/gh_address_cr/cli.py`.
- [X] T058 [US2] Owner: Runtime CLI Agent - Implement `agent submit` command in `src/gh_address_cr/cli.py`.
- [X] T059 [US2] Owner: Runtime CLI Agent - Update `src/gh_address_cr/core/workflow.py` to apply accepted local ActionResponse results to session state.
- [X] T060 [US2] Owner: Protocol Agent - Add machine-readable error codes for invalid ActionResponse submissions in `src/gh_address_cr/agent/responses.py`.
- [X] T061 [US2] Owner: Skill Adapter Agent - Update `gh-address-cr/SKILL.md` with the ActionRequest/ActionResponse contract and the allowed `fix`, `clarify`, `defer`, and `reject` outcomes.
- [X] T062 [US2] Owner: Skill Adapter Agent - Add assistant-specific protocol hints in `gh-address-cr/agents/openai.yaml`.
- [X] T063 [US2] Owner: Verification Agent - Update `specs/001-agent-control-plane/contracts/agent-protocol.md` if implementation exposes stricter validation error names.
- [X] T064 [US2] Owner: Verification Agent - Run `python3 -m unittest tests.test_agent_protocol tests.test_control_plane_workflow` and record exact evidence in `specs/001-agent-control-plane/quickstart.md`.

## Phase 6: User Story 5 - Multi-Agent Work Coordination (Priority: P1)

**Goal**: A coordinator can safely split work across specialized agents using capability manifests, claim leases, conflict keys, and serialized side effects.

**Independent Test**: Two independent items can be leased concurrently; conflicting file or side-effect ownership is rejected; stale or duplicate submissions do not mutate session state or GitHub.

- [X] T065 [P] [US5] Owner: Protocol Agent - Add failing CapabilityManifest tests for eligible roles, allowed actions, evidence formats, and protocol version compatibility in `tests/test_agent_protocol.py`.
- [X] T066 [P] [US5] Owner: Lease Coordinator Agent - Add failing tests for concurrent independent leases with distinct item IDs and non-overlapping conflict keys in `tests/test_claim_leases.py`.
- [X] T067 [P] [US5] Owner: Lease Coordinator Agent - Add failing tests for duplicate lease claims, stale lease submissions, expired leases, and cross-role submissions in `tests/test_claim_leases.py`.
- [X] T068 [P] [US5] Owner: Runtime CLI Agent - Add failing CLI tests for `gh-address-cr agent manifest`, `gh-address-cr agent leases`, and `gh-address-cr agent reclaim` in `tests/test_control_plane_workflow.py`.
- [X] T069 [US5] Owner: Protocol Agent - Implement CapabilityManifest loading and validation in `src/gh_address_cr/agent/manifests.py`.
- [X] T070 [US5] Owner: Runtime CLI Agent - Implement `agent manifest` command routing and JSON output in `src/gh_address_cr/cli.py`.
- [X] T071 [US5] Owner: Lease Coordinator Agent - Implement claim, release, expire, reject, and reclaim operations in `src/gh_address_cr/core/leases.py`.
- [X] T072 [US5] Owner: Lease Coordinator Agent - Implement conflict-key calculation for item IDs, file ownership, thread ownership, and GitHub side-effect ownership in `src/gh_address_cr/core/leases.py`.
- [X] T073 [US5] Owner: Runtime CLI Agent - Implement `agent leases` and `agent reclaim` command routing in `src/gh_address_cr/cli.py`.
- [X] T074 [US5] Owner: Runtime CLI Agent - Update `src/gh_address_cr/core/workflow.py` so accepted submissions require an active compatible lease.
- [X] T075 [US5] Owner: GitHub Evidence Agent - Ensure lease events append evidence records through `src/gh_address_cr/evidence/ledger.py`.
- [X] T076 [US5] Owner: Skill Adapter Agent - Update `gh-address-cr/SKILL.md` with coordinator, fix-agent, review-agent, verifier-agent, docs-agent, and release-agent responsibilities.
- [X] T077 [US5] Owner: Verification Agent - Add multi-agent examples to `specs/001-agent-control-plane/quickstart.md` using separate `agent next` and `agent submit` commands for independent items.
- [X] T078 [US5] Owner: Verification Agent - Run `python3 -m unittest tests.test_claim_leases tests.test_agent_protocol tests.test_control_plane_workflow` and record exact evidence in `specs/001-agent-control-plane/quickstart.md`.

## Phase 7: User Story 4 - Final Gate Validation (Priority: P1)

**Goal**: The final gate is the only authority for completion and rejects unresolved remote work, missing replies, pending current-login reviews, blocking local items, and missing validation evidence.

**Independent Test**: A session cannot complete unless all remote and local completion conditions pass in one fresh final-gate run with exact machine-readable summary fields.

- [X] T079 [P] [US4] Owner: Gate Agent - Add failing tests for final-gate machine summary fields in `tests/test_final_gate.py`.
- [X] T080 [P] [US4] Owner: Gate Agent - Add failing tests for missing terminal reply evidence even when a thread is resolved in `tests/test_final_gate.py`.
- [X] T081 [P] [US4] Owner: Gate Agent - Add failing tests for current-login pending review detection in `tests/test_final_gate.py`.
- [X] T082 [P] [US4] Owner: Gate Agent - Add failing tests for missing validation evidence on terminal local findings in `tests/test_final_gate.py`.
- [X] T083 [US4] Owner: Gate Agent - Implement final-gate aggregation in `src/gh_address_cr/core/gate.py`.
- [X] T084 [US4] Owner: Gate Agent - Implement explicit final-gate failure codes in `src/gh_address_cr/core/gate.py`.
- [X] T085 [US4] Owner: Runtime CLI Agent - Wire `final-gate` command output and non-zero failure behavior in `src/gh_address_cr/cli.py`.
- [X] T086 [US4] Owner: GitHub Evidence Agent - Implement review-state provider interface in `src/gh_address_cr/github/reviews.py`.
- [X] T087 [US4] Owner: GitHub Evidence Agent - Implement thread-state provider fields required by final-gate in `src/gh_address_cr/github/threads.py`.
- [X] T088 [US4] Owner: Skill Adapter Agent - Update `gh-address-cr/SKILL.md` to forbid completion claims before `gh-address-cr final-gate` passes.
- [X] T089 [US4] Owner: Verification Agent - Update `README.md` final-gate section with required summary fields and failure semantics.
- [X] T090 [US4] Owner: Verification Agent - Run `python3 -m unittest tests.test_final_gate tests.test_control_plane_workflow` and record exact evidence in `specs/001-agent-control-plane/quickstart.md`.

## Phase 8: User Story 3 - Evidence Ledger And GitHub IO (Priority: P2)

**Goal**: The runtime records every decision, validation, GitHub side-effect attempt, reply URL, resolve state, retry, and resume token in an append-only ledger.

**Independent Test**: A simulated transient GitHub failure records retry evidence, avoids duplicate replies/resolves through idempotency keys, and returns a resume command without marking the item complete.

- [X] T091 [P] [US3] Owner: GitHub Evidence Agent - Add failing tests for append-only ledger ordering, actor role, lease ID, item ID, and timestamp fields in `tests/test_evidence_ledger.py`.
- [X] T092 [P] [US3] Owner: GitHub Evidence Agent - Add failing tests for reply-posted, reply-url, resolve-state, and idempotency-key evidence in `tests/test_evidence_ledger.py`.
- [X] T093 [P] [US3] Owner: GitHub Evidence Agent - Add failing tests for transient GitHub failure immediate retry, scheduled backoff, retry exhaustion, and resume-token output in `tests/test_evidence_ledger.py`.
- [X] T094 [P] [US3] Owner: GitHub Evidence Agent - Add failing resolve-only publishing tests proving `github_resolve` is rejected before GitHub mutation when accepted evidence lacks a reply body or durable reply policy in `tests/test_evidence_ledger.py`.
- [X] T095 [US3] Owner: GitHub Evidence Agent - Implement durable ledger append and load APIs in `src/gh_address_cr/evidence/ledger.py`.
- [X] T096 [US3] Owner: GitHub Evidence Agent - Implement audit helpers for evidence completeness in `src/gh_address_cr/evidence/audit.py`.
- [X] T097 [US3] Owner: GitHub Evidence Agent - Implement reply posting adapter with idempotency recording in `src/gh_address_cr/github/replies.py`.
- [X] T098 [US3] Owner: GitHub Evidence Agent - Implement thread resolve adapter with idempotency recording in `src/gh_address_cr/github/threads.py`.
- [X] T099 [US3] Owner: Runtime CLI Agent - Wire publish-ready workflow transitions in `src/gh_address_cr/core/workflow.py`.
- [X] T100 [US3] Owner: Runtime CLI Agent - Add an explicit resolve-only guard in `src/gh_address_cr/core/workflow.py` so resolve publication requires accepted evidence and reply-ready state before calling GitHub adapters.
- [X] T101 [US3] Owner: Runtime CLI Agent - Add resume-token display and recovery command output in `src/gh_address_cr/cli.py`.
- [X] T102 [US3] Owner: Skill Adapter Agent - Update `gh-address-cr/references/` to describe evidence-ledger audit expectations without exposing internal implementation APIs as agent-safe commands.
- [X] T103 [US3] Owner: Verification Agent - Run `python3 -m unittest tests.test_evidence_ledger tests.test_control_plane_workflow` and record exact evidence in `specs/001-agent-control-plane/quickstart.md`.

## Phase 9: Public Compatibility And Migration

**Purpose**: Preserve existing public command semantics while moving runtime ownership outside the skill.

- [X] T104 [P] Owner: Runtime CLI Agent - Add end-to-end compatibility tests for existing public commands `review`, `threads`, `findings`, `adapter`, `review-to-findings`, `final-gate`, and `cr-loop --help` in `tests/test_runtime_packaging.py`.
- [X] T105 [P] Owner: Skill Adapter Agent - Add shim compatibility tests for legacy invocation `python3 gh-address-cr/scripts/cli.py <command>` in `tests/test_skill_runtime_shim.py`.
- [X] T106 Owner: Runtime CLI Agent - Preserve public command names and summary field names in `src/gh_address_cr/cli.py`.
- [X] T107 Owner: Skill Adapter Agent - Preserve skill-root-relative path language in `gh-address-cr/SKILL.md` and repo-root path language in `README.md`.
- [X] T108 Owner: Verification Agent - Update `specs/001-agent-control-plane/contracts/cli-contract.md` if compatibility behavior becomes stricter during implementation.
- [X] T109 Owner: Verification Agent - Run `python3 gh-address-cr/scripts/cli.py cr-loop --help` and record exact output expectation in `specs/001-agent-control-plane/quickstart.md`.

## Phase 10: Polish And Cross-Cutting Verification

**Purpose**: Prove the plan is complete, coherent, and executable before claiming the architecture migration is ready.

- [X] T110 [P] Owner: Verification Agent - Run `ruff check gh-address-cr src tests` and fix reported issues in the owning files.
- [X] T111 [P] Owner: Verification Agent - Run `python3 -m unittest discover -s tests` and record exact pass/fail evidence in `specs/001-agent-control-plane/quickstart.md`.
- [X] T112 [P] Owner: Verification Agent - Run `python3 gh-address-cr/scripts/cli.py --help` and record exact pass/fail evidence in `specs/001-agent-control-plane/quickstart.md`.
- [X] T113 [P] Owner: Verification Agent - Run `python3 -m gh_address_cr --help` and record exact pass/fail evidence in `specs/001-agent-control-plane/quickstart.md`.
- [X] T114 [P] Owner: Verification Agent - Run `python3 gh-address-cr/scripts/cli.py final-gate --help` and record exact pass/fail evidence in `specs/001-agent-control-plane/quickstart.md`.
- [X] T115 Owner: Verification Agent - Check every FR in `specs/001-agent-control-plane/spec.md` has at least one task in `specs/001-agent-control-plane/tasks.md`.
- [X] T116 Owner: Verification Agent - Check every public command in `specs/001-agent-control-plane/contracts/cli-contract.md` has a packaging or workflow test in `tests/`.
- [X] T117 Owner: Verification Agent - Check every ActionRequest, ActionResponse, ClaimLease, CapabilityManifest, EvidenceRecord, SideEffectAttempt, RuntimeCompatibility, and LeasePolicy field in `specs/001-agent-control-plane/data-model.md` has validation coverage in `tests/`.
- [X] T118 Owner: Verification Agent - Run `git diff --check` for whitespace validation across `specs/001-agent-control-plane/tasks.md`, `README.md`, `gh-address-cr/SKILL.md`, and `src/gh_address_cr/`.
- [X] T119 Owner: Verification Agent - Prepare the implementation readiness note structure in `specs/001-agent-control-plane/quickstart.md` listing blocker categories, verification commands, and which agent lane owns each blocker.

## Phase 11: Analysis Remediation Gate

**Purpose**: Close post-analysis gaps before implementation readiness is claimed.

- [X] T120 Owner: Protocol Agent - Add failing pre-fix classification gate tests proving fixer leases and code-modifying ActionResponse submissions are rejected without `classification_recorded` evidence and append `request_rejected` or `response_rejected` ledger evidence in `tests/test_agent_protocol.py`.
- [X] T121 Owner: Runtime CLI Agent - Implement pre-fix classification enforcement and rejected-request evidence in `src/gh_address_cr/core/workflow.py` and `src/gh_address_cr/agent/requests.py`.
- [X] T122 Owner: GitHub Evidence Agent - Create the standard GitHub PR thread fixture corpus and expected normalized findings under `tests/fixtures/github_threads/`.
- [X] T123 Owner: GitHub Evidence Agent - Add fixture-corpus parsing tests proving 100% of `tests/fixtures/github_threads/` cases normalize successfully in `tests/test_findings_intake.py`.
- [X] T124 Owner: Protocol Agent - Create at least 20 representative ActionRequest and ActionResponse fixture pairs across `fix`, `clarify`, `defer`, and `reject` under `tests/fixtures/action_protocol/`.
- [X] T125 Owner: Protocol Agent - Add fixture-corpus validation tests proving at least 95% schema-valid ActionResponse parsing for `tests/fixtures/action_protocol/` in `tests/test_agent_protocol.py`.
- [X] T126 Owner: Runtime CLI Agent - Add verifier rejection workflow tests proving rejected fixer evidence returns the item to blocked/open state and emits no GitHub side-effect attempts in `tests/test_control_plane_workflow.py`.
- [X] T127 Owner: Runtime CLI Agent - Implement verifier rejection handling in `src/gh_address_cr/core/workflow.py` with `verification_rejected` ledger evidence and no GitHub side effects.
- [X] T128 Owner: Verification Agent - Run `python3 -m unittest tests.test_agent_protocol tests.test_findings_intake tests.test_control_plane_workflow` and record fixture corpus, pre-fix classification, and verifier rejection evidence in `specs/001-agent-control-plane/quickstart.md`.
- [X] T129 Owner: Verification Agent - Produce the final implementation readiness note in `specs/001-agent-control-plane/quickstart.md` after `T120-T128` pass.

## Dependency Graph

- **Setup** (`T001-T008`) must complete before Foundation.
- **Foundation** (`T009-T028`) blocks all user stories.
- **US6** (`T029-T040`) should land before public runtime behavior is migrated, because it establishes the physical runtime/skill split.
- **US1** (`T041-T052`) depends on Foundation and US6.
- **US2** (`T053-T064`) depends on US1 ActionRequest generation.
- **US5** (`T065-T078`) depends on Foundation protocol models and can proceed after US2 validators exist.
- **US4** (`T079-T090`) depends on US1 session state and US2 terminal evidence semantics.
- **US3** (`T091-T103`) depends on US2 response semantics and feeds stronger evidence into US4.
- **Compatibility** (`T104-T109`) depends on US6 and the migrated public commands.
- **Polish** (`T110-T119`) depends on all story phases.
- **Analysis Remediation** (`T120-T129`) closes post-analysis gaps and must
  complete before implementation readiness can be claimed.

## Parallel Examples

### After Setup

- Runtime CLI Agent: `T009`, `T017`, `T018`, `T024`, `T025`, `T026`, `T027`
- Skill Adapter Agent: `T010`, `T030`, `T031`
- Protocol Agent: `T011`, `T012`, `T019`, `T020`
- Lease Coordinator Agent: `T013`, `T014`, `T021`
- GitHub Evidence Agent: `T015`, `T022`
- Gate Agent: `T016`, `T023`

### After US6

- Runtime CLI Agent can implement `T041`, `T044`, `T045`, `T050`.
- Protocol Agent can implement `T042`, `T046`, `T053`, `T054`, `T056`.
- GitHub Evidence Agent can implement `T043`, `T047`, `T048`, `T049`.
- Skill Adapter Agent can update `T061`, `T062`, `T076` without touching runtime code.

### Multi-Agent Coordination Slice

- Protocol Agent owns `T065`, `T069`.
- Lease Coordinator Agent owns `T066`, `T067`, `T071`, `T072`.
- Runtime CLI Agent owns `T068`, `T070`, `T073`, `T074`.
- GitHub Evidence Agent owns `T075`.
- Verification Agent owns `T077`, `T078`.

## MVP Scope Recommendation

The smallest useful MVP is **US6 + US1 + US2 + US5 + US4**:

1. Runtime and packaged skill are physically separate.
2. `review` initializes a session and emits ActionRequest.
3. agents submit validated ActionResponse evidence.
4. claim leases allow safe parallel work.
5. final-gate proves completion.

US3 should follow immediately after MVP because durable side-effect evidence, resolve-only protection, and retry/resume behavior are required before using the system on high-risk PRs.

## Fail-Fast Checklist

- Every validator rejects malformed input with an exact error code.
- Every CLI command exits non-zero when required runtime, protocol, session, lease, evidence data, or `gh` tooling is missing.
- No task introduces a silent fallback from the packaged skill to copied runtime logic.
- No GitHub reply or resolve can occur before ActionResponse evidence validates.
- No code-modifying fixer request or submission is accepted before classification evidence is recorded.
- No resolve-only publication can reach a GitHub adapter before reply-ready evidence exists.
- No completion claim is allowed before final-gate passes.
- No stale, duplicate, or cross-role lease submission mutates session state.
- No transient GitHub failure is hidden; retries, exhaustion, and resume commands are recorded in the ledger.
