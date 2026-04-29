# Feature Specification: Agent Control Plane

**Feature Branch**: `001-agent-control-plane`  
**Created**: 2026-04-24
**Status**: Verified
**Input**: User description: "Evolve directly to the latest architecture: a physically separated deterministic CLI/runtime, a thin packaged skill adapter, and multi-agent coordination for complex PR repair work."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Review Initialization & Inspection (Priority: P1)

As a developer or automation system, I want to initiate a review session via a deterministic CLI/runtime that is separate from the packaged skill so that the system inspects the PR and ingests findings reliably without relying on an agent's memory or on Markdown-driven runtime behavior.

**Why this priority**: Without deterministic intake, the foundation for any agent action is flawed.

**Independent Test**: Can be tested by running the CLI command against a PR and verifying it correctly outputs a structured list of pending review threads and findings without any AI involvement.

**Acceptance Scenarios**:

1. **Given** a repository identifier and PR number with open review threads, **When** I run the review command, **Then** the system fetches, parses, and normalizes the findings into a machine-readable format.
2. **Given** the system has parsed findings, **When** processing begins, **Then** it emits a structured `ActionRequest` for the next pending item.
3. **Given** the packaged skill is installed, **When** the deterministic CLI/runtime is missing, **Then** the skill adapter fails loudly with installation guidance instead of silently running an embedded copy of the control plane.

---

### User Story 2 - Agentic Resolution Loop (Priority: P1)

As an AI agent, I want to receive a structured `ActionRequest` and return an `ActionResponse` so that I can focus solely on code fixes, clarification, deferral, or rejection without worrying about GitHub IO or state management.

**Why this priority**: This separates the cognitive work from the side-effect work, ensuring the agent's actions are cleanly scoped and deterministic.

**Independent Test**: Can be tested by providing mock `ActionRequest` payloads to an agent and verifying it produces valid `ActionResponse` JSON/structured payloads.

**Acceptance Scenarios**:

1. **Given** an `ActionRequest` for a code issue, **When** the agent acts, **Then** it returns an `ActionResponse` specifying a "fix" action and provides code modifications as evidence.
2. **Given** an `ActionRequest` that is ambiguous, **When** the agent evaluates it, **Then** it returns a "clarify" action with an explanation as evidence.
3. **Given** a review item has not been classified as `fix`, `clarify`, `defer`, or `reject`, **When** a fixer agent requests mutating work, **Then** the control plane blocks the request before code mutation and records rejected-request evidence explaining the missing classification.

---

### User Story 3 - Evidence Ledger & GitHub IO (Priority: P2)

As the control plane, I want to record agent actions in an evidence ledger and automatically post replies/resolves to GitHub so that the PR state reflects the work done without the agent directly calling GitHub APIs.

**Why this priority**: Protects against agent drift and ensures all API calls are deterministic and auditable.

**Independent Test**: Can be tested by injecting an `ActionResponse` into the system and verifying it correctly calls the GitHub API to reply and resolve, and records it in the ledger.

**Acceptance Scenarios**:

1. **Given** an `ActionResponse` indicating a fix, **When** the CLI processes it, **Then** it posts a reply to the thread, marks it as resolved, and logs the evidence.
2. **Given** an interrupted session, **When** resumed via a resume token, **Then** the CLI picks up from the last recorded state in the ledger.

---

### User Story 4 - Final Gate Validation (Priority: P1)

As a project maintainer, I want the system to strictly run a final gate proving the PR session has no unresolved remote work, no missing reply evidence, no pending current-login review, no blocking local session items, and required validation evidence before claiming completion so that no incomplete work is prematurely merged.

**Why this priority**: Ensures the primary value proposition—correctness and safety—is upheld.

**Independent Test**: Can be tested by running the final gate command on PR sessions with and without unresolved threads, pending reviews, missing reply evidence, blocking local findings, and required validation evidence.

**Acceptance Scenarios**:

1. **Given** all threads are resolved, reply evidence is durable, current-login pending reviews are cleared, session blocking items are zero, and required validation evidence exists, **When** the final gate runs, **Then** it exits with success (0) and proves completion.
2. **Given** 1 unresolved thread remains, **When** the final gate runs, **Then** it fails loudly and prevents completion claims.
3. **Given** a terminal thread has no durable reply evidence, **When** the final gate runs, **Then** it fails loudly even if the remote unresolved-thread count is zero.

---

### User Story 5 - Multi-Agent Work Coordination (Priority: P1)

As a maintainer running complex PR repair work, I want the control plane to split work across specialized AI agents so that review production, triage, fixing, verification, and GitHub publication can proceed without ownership conflicts or duplicated side effects.

**Why this priority**: Multi-agent execution is the target operating model. Without explicit ownership, leases, and evidence handoff, parallel agents can overwrite each other, resolve without reply evidence, or claim completion from stale state.

**Independent Test**: Can be tested by creating multiple independent pending items, assigning them to different agent roles, and verifying that each agent can only mutate its claimed item while the control plane merges evidence and blocks conflicting submissions.

**Acceptance Scenarios**:

1. **Given** three independent review items, **When** the coordinator assigns them to different fixer agents, **Then** each item receives a unique claim lease and action request.
2. **Given** two agents attempt to submit evidence for the same item, **When** the control plane validates the responses, **Then** only the active lease holder's response is accepted.
3. **Given** a verifier agent rejects a fixer agent's evidence, **When** the coordinator resumes the session, **Then** the item returns to a blocked state without posting GitHub side effects.

---

### User Story 6 - Runtime And Skill Separation (Priority: P1)

As a skill maintainer, I want the control-plane runtime to live outside the packaged skill payload so that the CLI can be versioned, tested, installed, and reused independently while the skill remains a thin adapter for AI agents.

**Why this priority**: Keeping runtime code inside the skill preserves the current coupling problem. Physical separation is required before multi-agent coordination becomes maintainable.

**Independent Test**: Can be tested by installing the CLI/runtime independently, invoking the packaged skill adapter, and verifying that the adapter delegates to the installed runtime or fails loudly when the runtime is absent.

**Acceptance Scenarios**:

1. **Given** the runtime package is installed, **When** the skill adapter invokes the review workflow, **Then** the adapter delegates to the external runtime and preserves the same machine-readable status contract.
2. **Given** the runtime package is not installed, **When** the skill adapter is invoked, **Then** it fails with a clear missing-runtime message and does not execute stale bundled workflow code.
3. **Given** the runtime version is incompatible with the skill's declared contract, **When** the adapter starts, **Then** it blocks execution and reports the version mismatch.

### Edge Cases

- What happens when the agent returns a malformed `ActionResponse`? (CLI should reject it, log an error, and retry or fail the session)
- How does the system handle GitHub API rate limits during IO operations? (CLI classifies the failure, distinguishes immediate retry from scheduled backoff, records retry/backoff evidence, and blocks without duplicate side effects when retry budget is exhausted)
- What happens if the agent tries to claim completion without generating evidence? (CLI's policy checks block the resolve and demand evidence)
- What happens when two agents try to claim the same item? (CLI grants one active lease and rejects stale or conflicting submissions)
- What happens when an agent is interrupted mid-fix? (CLI reclaims the stale lease after the configured timeout and preserves existing evidence)
- What happens when a verifier and fixer disagree? (CLI records the verification failure and requires a new fix or explicit defer/clarify decision)
- What happens when the skill adapter and installed runtime versions disagree? (The adapter blocks execution and reports the required compatible version range)
- What happens when the old skill-local script entrypoint is used? (The shim delegates to the installed runtime or fails loudly with migration guidance)

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST provide a CLI entrypoint for initializing a review session (`gh-address-cr review <owner/repo> <pr_number>`).
- **FR-002**: System MUST convert GitHub PR threads and review comments into a normalized, deterministic data structure.
- **FR-003**: System MUST define and emit a structured `ActionRequest` schema for agents to consume.
- **FR-004**: System MUST accept a structured `ActionResponse` schema from agents indicating the action (`fix`, `clarify`, `defer`, `reject`) and providing necessary evidence.
- **FR-005**: System MUST maintain a local `EvidenceLedger` tracking all state transitions and actions.
- **FR-006**: System MUST perform all GitHub side-effects (replying, resolving) deterministically based on the `ActionResponse` and ledger, completely hiding the GitHub API from the agent.
- **FR-007**: System MUST provide a `ResumeToken` or session ID allowing resumption of an interrupted PR review loop without redundant operations.
- **FR-008**: System MUST enforce a Final Gate that verifies 0 unresolved remote threads, 0 current-login pending reviews, 0 session blocking items, no terminal GitHub thread missing durable reply evidence, and required validation evidence before allowing a completion state.
- **FR-009**: System MUST prevent "resolve-only" actions without accompanying evidence of a fix, clarification, deferral, or rejection.
- **FR-010**: System MUST define specialized multi-agent roles for coordinator, review producer, triage, fixer, verifier, GitHub publisher, and final gate.
- **FR-011**: System MUST issue item-scoped claim leases so parallel agents cannot mutate the same work item concurrently.
- **FR-012**: System MUST record each agent role, lease, action request, action response, validation result, and side effect in the evidence ledger.
- **FR-013**: System MUST reject stale, duplicate, or cross-role submissions that do not match the active lease and required evidence schema.
- **FR-014**: System MUST support parallel processing of independent items while keeping GitHub reply/resolve side effects serialized through the deterministic control plane.
- **FR-015**: System MUST physically separate the deterministic runtime from the packaged skill adapter so runtime logic is not authored or maintained as skill-owned workflow code.
- **FR-016**: System MUST provide an independently installable runtime CLI with a stable public entrypoint for review orchestration.
- **FR-017**: System MUST keep the packaged skill as a thin adapter that routes agents to the runtime, explains status handling, and preserves final-gate discipline.
- **FR-018**: System MUST provide a compatibility shim for existing skill-local entrypoint usage that delegates to the installed runtime or fails loudly when the runtime is missing.
- **FR-019**: System MUST define version compatibility between the skill adapter and the runtime CLI before the adapter can execute runtime actions.
- **FR-020**: System MUST document and test the migration path from skill-bundled scripts to the separated runtime without changing the public review workflow semantics.
- **FR-021**: System MUST define boundary rules that assign session mutation, protocol validation, GitHub IO, evidence ledger writes, and final-gate evaluation to the runtime CLI; instructions, status interpretation, references, hints, assets, and bootstrap guidance to the skill adapter; and delegation-only behavior to compatibility shims.
- **FR-022**: System MUST use `CapabilityManifest` data to decide which agents are eligible for each role, action, and request format before issuing claim leases.
- **FR-023**: System MUST define item independence for parallel processing using distinct work item IDs, compatible active leases, and no known conflicting file or side-effect ownership.
- **FR-024**: System MUST define the claim lease lifecycle across creation, active ownership, submission, acceptance, rejection, expiry, release, and reclaiming.
- **FR-025**: System MUST define bounded retry, scheduled backoff, blocking, and evidence-recording behavior for transient GitHub API failures such as rate limits without emitting duplicate side effects.
- **FR-026**: System MUST require recorded triage/classification evidence before issuing any mutating fixer request or accepting code-modifying evidence.

### Constitution Alignment *(mandatory)*

- **Control Plane Impact**: This feature solidifies the separated runtime CLI as the sole deterministic owner of session state, GitHub IO, leases, evidence, and the final gate. The agent operates strictly as a worker function inside this loop.
- **CLI / Agent Contract Impact**: Introduces formal `ActionRequest`, `ActionResponse`, `AgentRole`, `ClaimLease`, and `CapabilityManifest` contracts. Defines strict policy checks for wait states and exit codes based on evidence.
- **Evidence Requirements**: Every thread resolution requires code modifications, a test run output, or a written justification recorded in the `EvidenceLedger` before the CLI will push the resolve to GitHub.
- **Packaged Skill Boundary**: The packaged skill contains only thin adapter guidance, references, agent hints, templates, and compatibility/bootstrap shims. The deterministic control-plane runtime lives outside the packaged skill payload and is installed/versioned as the CLI product.
- **Fail-Fast Behavior**: Malformed `ActionResponse` payloads, missing evidence, or failure to pass the final gate will cause the CLI to fail loudly and immediately halt the loop.

### Key Entities

- **ReviewSession**: Represents the overall state of addressing a PR's review threads, containing the ledger and resume token.
- **ActionRequest**: The structured payload given to the AI containing the context, the specific thread/finding, and available actions.
- **ActionResponse**: The structured payload returned by the AI containing the chosen action (`fix`, `clarify`, `defer`, `reject`) and the required evidence.
- **EvidenceLedger**: An append-only log of actions taken, ensuring auditability and resumability.
- **AgentRole**: A named responsibility boundary for one agent in the workflow, such as coordinator, review producer, triage, fixer, verifier, publisher, or gatekeeper.
- **ClaimLease**: An item-scoped ownership record that allows one agent to work on one item for a bounded period.
- **CapabilityManifest**: A declaration of which roles and actions a specific agent or adapter can perform.
- **RuntimeCLI**: The independently installed deterministic runtime that owns orchestration, state, side effects, and gate evaluation.
- **SkillAdapter**: The packaged skill layer that tells AI agents how to invoke the runtime and react to structured statuses.
- **CompatibilityShim**: A legacy entrypoint that delegates to `RuntimeCLI` or fails loudly with migration guidance.
- **RuntimeCompatibility**: The version and protocol compatibility record checked before a skill adapter or shim may delegate to the runtime.
- **LeasePolicy**: The rules for claim ownership, expiry, reclaiming, and conflict detection across parallel agents.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The CLI successfully parses 100% of the repository's standard GitHub PR thread fixture corpus into normalized findings without agent intervention.
- **SC-002**: A supported AI agent can process a scripted fixture corpus of at least 20 representative `ActionRequest` payloads across `fix`, `clarify`, `defer`, and `reject`, returning schema-valid `ActionResponse` payloads at least 95% of the time without syntax errors.
- **SC-003**: A fully interrupted session can be resumed from the exact state 100% of the time using the `EvidenceLedger` and `ResumeToken` without re-evaluating completed threads.
- **SC-004**: The final gate command reliably exits with a non-zero code if any remote thread remains unresolved, any terminal thread lacks reply evidence, any current-login review remains pending, or any session blocking item remains open.
- **SC-005**: In a simulated parallel run with at least 3 independent items and 3 agent roles, 100% of accepted submissions match an active claim lease and no duplicate GitHub side effects are emitted.
- **SC-006**: Stale leases can be reclaimed without losing accepted evidence or corrupting the session state.
- **SC-007**: The packaged skill adapter can operate with the installed runtime and produces the same status contract as direct CLI invocation.
- **SC-008**: When the installed runtime is absent or incompatible, the skill adapter fails before session mutation and gives actionable remediation.
- **SC-009**: No authoritative control-plane state transition, GitHub side effect, or final-gate rule remains implemented only in skill Markdown.

## Assumptions

- The AI agent chosen (Codex, Claude, etc.) is capable of adhering to a strict structured response schema (e.g., JSON or well-defined markdown blocks).
- GitHub's API for retrieving and resolving review threads remains relatively stable.
- The project will implement runtime/skill physical separation before focusing on an optional custom runner.
- Multi-agent execution is coordinated by the deterministic control plane; agents do not directly post replies, resolve threads, or mutate shared session files without a CLI-mediated lease.
- Users can install or otherwise make the runtime CLI available separately from the packaged skill; the skill adapter is allowed to fail loudly when that prerequisite is missing.
