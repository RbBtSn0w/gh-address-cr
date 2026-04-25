# Feature Specification: Thin Skill Orchestration

**Feature Branch**: `003-thin-skill-orchestration`  
**Created**: 2026-04-25  
**Status**: Verified
**Input**: User description: "Plan the next architecture stage after the verified runtime native refactor: thin the shipped gh-address-cr skill so it becomes a router and behavioral policy layer, and prepare deterministic multi-agent orchestration productization around the existing CLI, agent protocol, leases, evidence, resume state, and final gate. Keep deterministic runtime ownership in the CLI/control plane; avoid turning the skill into business logic or implementing a full autonomous runner before the adapter and coordination contract are specified."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Thin Skill Entry Contract (Priority: P1)

As a skill maintainer, I want the packaged skill to be a concise adapter that routes agents to the runtime and explains only the policy needed to use it safely, so that workflow behavior is not maintained in Markdown or duplicated across skill files.

**Why this priority**: The runtime is now native and deterministic. The next architectural risk is instruction drift: if the skill keeps carrying detailed workflow logic, agents can bypass or contradict the control plane.

**Independent Test**: Can be tested by reading the packaged skill payload and verifying that every authoritative state transition, side effect, lease rule, and final-gate rule is owned by the runtime contract or references, while the first-read skill entrypoint remains a routing and policy adapter.

**Acceptance Scenarios**:

1. **Given** an installed skill and available runtime, **When** an agent opens the skill entrypoint, **Then** the first action is to invoke the high-level runtime command and consume its structured status instead of following a long manual procedure.
2. **Given** the runtime is missing or incompatible, **When** the skill adapter is used, **Then** it fails loudly before any session mutation and gives a direct remediation path.
3. **Given** a behavior rule appears in the skill entrypoint, **When** it concerns session mutation, GitHub side effects, lease ownership, evidence acceptance, or final-gate authority, **Then** the rule points to the runtime contract rather than redefining the behavior.

---

### User Story 2 - Structured Status Navigation (Priority: P1)

As an AI agent using the skill, I want a small status-to-action map for runtime outputs so that I can respond to `WAITING`, `BLOCKED`, `FAILED`, and `READY` states without parsing prose or guessing the next command.

**Why this priority**: Thin skills only work if agents can reliably interpret runtime status. The adapter must make structured status handling obvious without becoming another workflow engine.

**Independent Test**: Can be tested with representative machine summaries for review wait states, blocked action requests, accepted responses, failure states, and final-gate outcomes; each summary must map to exactly one safe next action or one loud stop condition.

**Acceptance Scenarios**:

1. **Given** a review command returns a waiting state for external findings, **When** an agent reads the adapter guidance, **Then** it knows to provide normalized findings through the documented handoff path and rerun the same high-level command.
2. **Given** a runtime summary indicates a blocked action request, **When** a fixer or triage agent consumes it, **Then** it submits a structured response with required evidence instead of mutating session files directly.
3. **Given** an unknown status, missing reason code, or malformed machine summary appears, **When** the adapter processes the situation, **Then** it stops with a fail-loud diagnostic instead of inventing a fallback.

---

### User Story 3 - Multi-Agent Role Coordination (Priority: P1)

As a maintainer running a complex PR repair session, I want the adapter and references to define clear role boundaries for coordinator, review producer, triage, fixer, verifier, publisher, and gatekeeper agents so that multiple agents can work without ownership conflicts or duplicated side effects.

**Why this priority**: Multi-agent execution is the target operating model. Without explicit role and handoff boundaries, parallel work can corrupt session state, duplicate replies, or claim completion before the final gate.

**Independent Test**: Can be tested with a simulated session containing at least three independent items and multiple agent roles; each role receives only the work it is allowed to perform, all accepted submissions match active leases, and GitHub side effects remain serialized through the runtime.

**Acceptance Scenarios**:

1. **Given** multiple independent review items, **When** specialized agents request work, **Then** each item is assigned through a bounded lease and action request that names the expected role, action choices, and evidence.
2. **Given** two agents attempt to work on the same item or conflicting ownership area, **When** they request or submit work, **Then** the system accepts only the active lease holder and records rejected or stale attempts.
3. **Given** a verifier rejects a fixer's evidence, **When** the session resumes, **Then** the item returns to a safe blocked state without publishing GitHub replies or resolves.

---

### User Story 4 - Orchestration Readiness Without Runner Lock-In (Priority: P2)

As a project architect, I want the next stage to make multi-agent orchestration product-ready without forcing a single custom runner design too early, so that Codex, Claude, CI, and human operators can all use the same contract.

**Why this priority**: A premature runner would create a new coupling point. The contract should be stable before any optional runner owns agent spawning or scheduling.

**Independent Test**: Can be tested by executing the same documented orchestration flow manually and through a simple coordinator harness, with both paths consuming the same runtime statuses, leases, action requests, action responses, and final-gate evidence.

**Acceptance Scenarios**:

1. **Given** a human operator coordinates multiple agents manually, **When** the documented flow is followed, **Then** all state changes still pass through the runtime contract and final gate.
2. **Given** an optional coordinator harness is introduced later, **When** it consumes the same contract, **Then** it does not require new skill-only behavior or direct GitHub side effects.
3. **Given** the team decides not to ship a runner in this stage, **When** planning completes, **Then** the adapter and protocol still support reliable multi-agent manual execution.

---

### User Story 5 - Migration And Documentation Consistency (Priority: P2)

As a maintainer, I want repository documentation, packaged skill instructions, advanced references, and compatibility guidance to agree on the runtime boundary so that users do not receive contradictory instructions during migration.

**Why this priority**: The project now has both repository-level docs and shipped skill docs. Inconsistent path language or duplicate command ladders can cause agents to call old scripts or bypass the native runtime.

**Independent Test**: Can be tested by scanning public docs for conflicting ownership claims, stale low-level entrypoint guidance, duplicate workflow ladders, and repo-root paths inside packaged skill-owned docs.

**Acceptance Scenarios**:

1. **Given** a rule must ship with the installed skill, **When** docs are reviewed, **Then** that rule is present under the packaged skill payload and uses skill-root-relative path language.
2. **Given** a rule is only for repository development, CI, or release, **When** docs are reviewed, **Then** it remains outside the packaged skill payload and uses repo-root path language.
3. **Given** an old direct script entrypoint is documented, **When** a user follows it, **Then** it either delegates to the runtime or fails loudly with migration guidance.

---

### User Story 6 - Replaceable Review Producer Intake (Priority: P2)

As an external review producer integrator, I want the next-stage workflow to accept the existing normalized findings contract without requiring a specific review engine, prompt, or agent vendor, so that review production remains replaceable while PR resolution remains deterministic.

**Why this priority**: The project should productize PR review resolution, not become a code-review generator. Keeping the intake boundary stable prevents scope creep and lets different review producers feed the same orchestration flow.

**Independent Test**: Can be tested by replacing the review producer with a different source that emits the same normalized findings contract and verifying that the user-facing PR resolution flow, evidence requirements, and final-gate completion semantics remain unchanged.

**Acceptance Scenarios**:

1. **Given** a producer emits valid normalized findings, **When** the PR workflow consumes them, **Then** the same session item handling, evidence, reply, resolve, and final-gate semantics apply regardless of producer identity.
2. **Given** a producer emits narrative review text instead of the accepted findings contract, **When** the adapter or runtime receives it, **Then** the workflow rejects it with actionable guidance rather than treating prose as authoritative input.
3. **Given** a user wants to change review producers, **When** they follow the public documentation, **Then** they do not need to change the completion workflow or learn low-level runtime internals.

### Edge Cases

- What happens when the installed runtime is absent, too old, or too new for the packaged skill adapter?
- What happens when an agent attempts to post a GitHub reply, resolve a thread, or mutate shared session state directly?
- What happens when two agents claim overlapping files, review items, threads, or side-effect ownership areas?
- What happens when a machine summary is missing `status`, `reason_code`, `waiting_on`, or `next_action`?
- What happens when packaged skill docs and repository docs disagree about a public command or completion rule?
- What happens when a verifier rejects evidence after a fixer has changed files but before publishing side effects?
- What happens when an orchestration run is interrupted while leases are active?
- What happens when a review producer emits unsupported narrative output instead of normalized findings?
- What happens when a user attempts to use the workflow for non-PR work such as issue triage, release automation, or generic CI repair?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The packaged skill entrypoint MUST identify itself as an adapter and MUST name the runtime as the deterministic owner of session state, intake routing, GitHub side effects, leases, evidence, resume state, and final-gate authority.
- **FR-002**: The packaged skill entrypoint MUST route agents to the public high-level runtime command before any advanced or low-level surface.
- **FR-003**: The packaged skill entrypoint MUST provide a concise status-to-action map for all stable runtime outcomes used by the public review workflow.
- **FR-004**: The adapter guidance MUST fail loudly for missing, malformed, unknown, or internally inconsistent machine summaries.
- **FR-005**: The adapter guidance MUST forbid AI agents from directly posting GitHub replies, resolving threads, or mutating shared session state outside runtime-mediated actions.
- **FR-006**: The next-stage contract MUST define clear role boundaries for coordinator, review producer, triage, fixer, verifier, publisher, and gatekeeper responsibilities.
- **FR-007**: The next-stage contract MUST define the minimum evidence each role must provide before its output can be accepted or forwarded.
- **FR-008**: The next-stage contract MUST define when independent items are eligible for parallel work and when file, item, thread, or side-effect conflicts force serialization.
- **FR-009**: The next-stage contract MUST require capability and compatibility checks before work is assigned to an agent role.
- **FR-010**: The next-stage contract MUST preserve lease-first ownership for all item mutations and MUST reject stale, duplicate, or cross-role submissions.
- **FR-011**: The next-stage contract MUST preserve serialized publishing of GitHub replies and resolves through the deterministic runtime.
- **FR-012**: The next-stage contract MUST preserve final-gate authority as the only valid completion proof.
- **FR-013**: The packaged skill, repository README, advanced references, and assistant-specific hints MUST use consistent public command semantics and completion rules.
- **FR-014**: Skill-owned documentation MUST use skill-root-relative paths, while repository-owned documentation MUST use repo-root-relative paths.
- **FR-015**: Compatibility guidance MUST describe how legacy or low-level entrypoints delegate to the runtime or fail loudly without creating an alternate workflow.
- **FR-016**: The stage MUST produce a human-usable orchestration flow that does not require a custom autonomous runner to be useful.
- **FR-017**: The stage MUST leave room for a future optional runner by documenting the stable contract it would consume without defining runner-specific scheduling behavior as a prerequisite.
- **FR-018**: The stage MUST include validation coverage proving that no authoritative state transition, side effect, or final-gate rule exists only in skill prose.
- **FR-019**: The next-stage workflow MUST remain scoped to PR review resolution and MUST NOT present itself as a generic agent task runner.
- **FR-020**: The next-stage workflow MUST preserve normalized findings as the stable review intake boundary and MUST NOT require one specific review producer, prompt, model, or review engine.
- **FR-021**: The packaged skill and public documentation MUST NOT present low-level scripts as agent-safe public APIs.
- **FR-022**: User-visible blocking and failure states MUST provide actionable next steps rather than exposing only low-level errors or internal state names.
- **FR-023**: Completion semantics MUST remain `reply evidence + resolved thread state + final-gate proof`; multi-agent orchestration MUST NOT weaken that definition.

### Constitution Alignment *(mandatory)*

- **Control Plane Impact**: This feature should not move ownership away from the runtime. The runtime remains the deterministic owner of session state, GitHub IO, leases, evidence, resume state, and final-gate evaluation.
- **CLI / Agent Contract Impact**: This feature clarifies how agents consume structured statuses, role assignments, action requests, action responses, compatibility checks, and lease outcomes. Public command semantics must remain stable unless a later planning phase explicitly changes them.
- **Evidence Requirements**: Every accepted role output must have role-appropriate evidence. Completion still requires final-gate proof, reply evidence for terminal GitHub threads, no unresolved remote work, no current-login pending review, and zero blocking local items.
- **Packaged Skill Boundary**: The packaged skill should contain adapter guidance, status handling, references, hints, and migration/bootstrap instructions. It must not become the implementation owner for workflow state, GitHub side effects, lease policies, or final-gate rules.
- **Fail-Fast Behavior**: Missing runtime, incompatible runtime, malformed summaries, invalid role submissions, stale leases, direct side-effect attempts, and documentation contradictions must be detected loudly rather than hidden by fallbacks.

### Key Entities

- **SkillAdapter**: The shipped skill entrypoint and references that route agents to the runtime and explain safe status handling.
- **RuntimeCLI**: The deterministic control plane used by agents, humans, and automation to inspect sessions, assign work, accept evidence, publish side effects, and run final gates.
- **AgentRole**: A named responsibility boundary for an AI or human worker participating in orchestration.
- **CapabilityManifest**: A declaration of which roles, actions, formats, and protocol versions an agent or adapter can safely support.
- **ActionRequest**: The structured work item issued to an agent under an active lease.
- **ActionResponse**: The structured response returned by an agent, including the chosen resolution and required evidence.
- **ClaimLease**: The bounded ownership record that prevents concurrent mutation of the same item or conflicting work area.
- **EvidenceLedger**: The audit trail proving role actions, accepted responses, rejected submissions, side effects, validation, and gate outcomes.
- **StatusActionMap**: The adapter-level map from runtime machine summary status to safe next action or stop condition.
- **OrchestrationRunbook**: The product-facing sequence for coordinating multiple agents without relying on a custom runner.
- **CompatibilityShim**: A legacy or skill-local entrypoint that delegates to the runtime or fails loudly with migration guidance.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A first-time agent can use the packaged skill entrypoint to choose the correct next action for at least 95% of representative runtime machine summaries without reading repository-only documentation.
- **SC-002**: In a fixture set covering every stable public review status, 100% of statuses map to exactly one safe next action or one explicit stop condition.
- **SC-003**: In a simulated multi-agent session with at least 3 independent items and 4 distinct roles, 100% of accepted submissions match an active lease and no duplicate GitHub side effects are emitted.
- **SC-004**: Runtime-missing and runtime-incompatible scenarios fail before session mutation in 100% of adapter compatibility checks.
- **SC-005**: Public documentation contains zero contradictory ownership claims about session mutation, GitHub side effects, lease authority, or final-gate authority.
- **SC-006**: The first-read packaged skill entrypoint contains no authoritative workflow state-machine behavior that is not also represented by the runtime contract or advanced references.
- **SC-007**: A human operator can complete a documented multi-agent orchestration dry run using the contract without a custom autonomous runner.
- **SC-008**: Skill-owned docs and repository-owned docs pass path-scope validation with zero repo-root paths in packaged skill guidance and zero skill-root ambiguity in repository-level instructions.
- **SC-009**: Replacing the review producer while preserving the normalized findings contract requires no change to the public PR resolution workflow.
- **SC-010**: Public docs contain zero references that describe low-level scripts as the recommended agent-safe entrypoint.
- **SC-011**: Every completion claim in examples, docs, or runbooks is backed by explicit final-gate evidence.
- **SC-012**: Scope validation confirms zero non-PR workflows are introduced by this stage.

## Assumptions

- The runtime native refactor remains the foundation for this stage and is available as the deterministic control plane.
- The current public review workflow, final gate discipline, and machine summary contract remain stable unless a later planning artifact explicitly proposes a breaking change.
- Multi-agent execution in this stage is contract-first and may be manual or coordinator-assisted; a full autonomous runner is out of scope until the adapter and coordination contract are validated.
- The shipped skill may retain advanced references, but the first-read entrypoint should stay small enough for agents to follow without reimplementing runtime behavior.
- Existing compatibility shims may remain, but they must not become alternate implementation owners.
- This stage does not introduce a built-in review engine; external producers remain replaceable as long as they emit the accepted normalized findings contract.
