# Feature Specification: Agent Control Plane

**Feature Branch**: `001-agent-control-plane`  
**Created**: 2026-04-24
**Status**: Draft  
**Input**: User description: "Agentic Control Plane + Deterministic CLI + Thin Skill..."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Review Initialization & Inspection (Priority: P1)

As a developer or automation system, I want to initiate a review session via a deterministic CLI so that the system inspects the PR and ingests findings reliably without relying on an agent's memory.

**Why this priority**: Without deterministic intake, the foundation for any agent action is flawed.

**Independent Test**: Can be tested by running the CLI command against a PR and verifying it correctly outputs a structured list of pending review threads and findings without any AI involvement.

**Acceptance Scenarios**:

1. **Given** a PR URL with open review threads, **When** I run the review command, **Then** the system fetches, parses, and normalizes the findings into a machine-readable format.
2. **Given** the system has parsed findings, **When** processing begins, **Then** it emits a structured `ActionRequest` for the next pending item.

---

### User Story 2 - Agentic Resolution Loop (Priority: P1)

As an AI agent, I want to receive a structured `ActionRequest` and return an `ActionResponse` so that I can focus solely on code fixes, clarification, or deferral without worrying about GitHub IO or state management.

**Why this priority**: This separates the cognitive work from the side-effect work, ensuring the agent's actions are cleanly scoped and deterministic.

**Independent Test**: Can be tested by providing mock `ActionRequest` payloads to an agent and verifying it produces valid `ActionResponse` JSON/structured payloads.

**Acceptance Scenarios**:

1. **Given** an `ActionRequest` for a code issue, **When** the agent acts, **Then** it returns an `ActionResponse` specifying a "fix" action and provides code modifications as evidence.
2. **Given** an `ActionRequest` that is ambiguous, **When** the agent evaluates it, **Then** it returns a "clarify" action with an explanation as evidence.

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

As a project maintainer, I want the system to strictly run a final gate proving 0 unresolved threads and successful test execution before claiming completion so that no incomplete work is prematurely merged.

**Why this priority**: Ensures the primary value proposition—correctness and safety—is upheld.

**Independent Test**: Can be tested by running the final gate command on a PR with and without unresolved threads.

**Acceptance Scenarios**:

1. **Given** all threads are resolved and tests pass, **When** the final gate runs, **Then** it exits with success (0) and proves completion.
2. **Given** 1 unresolved thread remains, **When** the final gate runs, **Then** it fails loudly and prevents completion claims.

### Edge Cases

- What happens when the agent returns a malformed `ActionResponse`? (CLI should reject it, log an error, and retry or fail the session)
- How does the system handle GitHub API rate limits during IO operations? (CLI handles backoff and retry deterministically)
- What happens if the agent tries to claim completion without generating evidence? (CLI's policy checks block the resolve and demand evidence)

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST provide a CLI entrypoint for initializing a review session (`gh-address-cr review <PR_URL>`).
- **FR-002**: System MUST convert GitHub PR threads and review comments into a normalized, deterministic data structure.
- **FR-003**: System MUST define and emit a structured `ActionRequest` schema for agents to consume.
- **FR-004**: System MUST accept a structured `ActionResponse` schema from agents indicating the action (`fix`, `clarify`, `defer`, `reject`) and providing necessary evidence.
- **FR-005**: System MUST maintain a local `EvidenceLedger` tracking all state transitions and actions.
- **FR-006**: System MUST perform all GitHub side-effects (replying, resolving) deterministically based on the `ActionResponse` and ledger, completely hiding the GitHub API from the agent.
- **FR-007**: System MUST provide a `ResumeToken` or session ID allowing resumption of an interrupted PR review loop without redundant operations.
- **FR-008**: System MUST enforce a Final Gate that verifies 0 unresolved threads on the remote PR before allowing a completion state.
- **FR-009**: System MUST prevent "resolve-only" actions without accompanying evidence of a fix, clarification, or deferral.

### Constitution Alignment *(mandatory)*

- **Control Plane Impact**: This feature solidifies the CLI as the sole deterministic owner of session state, GitHub IO, and the final gate. The agent operates strictly as a worker function inside this loop.
- **CLI / Agent Contract Impact**: Introduces formal `ActionRequest` and `ActionResponse` contracts. Defines strict policy checks for wait states and exit codes based on evidence.
- **Evidence Requirements**: Every thread resolution requires code modifications, a test run output, or a written justification recorded in the `EvidenceLedger` before the CLI will push the resolve to GitHub.
- **Packaged Skill Boundary**: The `gh-address-cr/` directory will contain the thin `SKILL.md` (router/policy) and `agents/` hints, while the deterministic control plane lives in `src/gh_address_cr` (or equivalent core directory).
- **Fail-Fast Behavior**: Malformed `ActionResponse` payloads, missing evidence, or failure to pass the final gate will cause the CLI to fail loudly and immediately halt the loop.

### Key Entities

- **ReviewSession**: Represents the overall state of addressing a PR's review threads, containing the ledger and resume token.
- **ActionRequest**: The structured payload given to the AI containing the context, the specific thread/finding, and available actions.
- **ActionResponse**: The structured payload returned by the AI containing the chosen action (`fix`, `clarify`, `defer`) and the required evidence.
- **EvidenceLedger**: An append-only log of actions taken, ensuring auditability and resumability.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The CLI successfully parses 100% of standard GitHub PR threads into normalized findings without agent intervention.
- **SC-002**: A supported AI agent can process `ActionRequest` payloads and return valid `ActionResponse` payloads 95% of the time without syntax errors.
- **SC-003**: A fully interrupted session can be resumed from the exact state 100% of the time using the `EvidenceLedger` and `ResumeToken` without re-evaluating completed threads.
- **SC-004**: The final gate command reliably exits with a non-zero code if any thread remains unresolved on GitHub.

## Assumptions

- The AI agent chosen (Codex, Claude, etc.) is capable of adhering to a strict structured response schema (e.g., JSON or well-defined markdown blocks).
- GitHub's API for retrieving and resolving review threads remains relatively stable.
- The project will implement Phase 1 and 2 (engine + CLI + agent protocol) before focusing on an optional custom runner.