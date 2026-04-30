# Feature Specification: Action Request Friction Repair

**Feature Branch**: `codex/010-agent-contract-friction`  
**Created**: 2026-04-30  
**Status**: Verified
**Input**: User description: "Fix issue #30: `submit_action.py` fails on runtime `ActionRequest.repository_context`, classification and resolution guidance is ambiguous, and small PR review fixes need a lower-overhead batch evidence path without weakening lease safety."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Submit Runtime Action Requests (Priority: P1)

An agent receives a runtime-generated action request and uses the packaged skill helper to prepare and submit evidence without manually editing the request JSON.

**Why this priority**: The reported schema mismatch blocks the manual continuation path and forces unsafe hand edits to runtime artifacts.

**Independent Test**: Can be tested by issuing a runtime action request, passing that exact request file to the helper, and verifying that the generated response contains the issued request and lease identity plus repository context.

**Acceptance Scenarios**:

1. **Given** a runtime action request with repository details under repository context, **When** the helper is invoked with fix evidence, **Then** it prepares a valid response without requiring top-level repository fields.
2. **Given** a legacy loop request with top-level repository fields, **When** the helper is invoked, **Then** it remains accepted for backward compatibility.
3. **Given** a malformed request without repository context or top-level repository fields, **When** the helper is invoked, **Then** it fails loudly before writing a response.

---

### User Story 2 - Understand Classification and Submission Fields (Priority: P2)

An agent can follow the workflow without confusing triage classification with fixer resolution, and error messages point to the correct command and field.

**Why this priority**: Ambiguous field names caused repeated attempts and state-machine friction during the reported PR repair.

**Independent Test**: Can be tested by triggering missing-classification and missing-response-field failures and verifying that each failure names the missing workflow phase, field, and next command.

**Acceptance Scenarios**:

1. **Given** an unclassified work item, **When** a fixer request is attempted, **Then** the system reports that triage classification evidence is missing and shows the classify command shape.
2. **Given** an action response missing resolution, **When** submission is attempted, **Then** the system reports that fixer resolution is missing and shows the response field shape.
3. **Given** a help or reference path, **When** an agent reads the protocol guidance, **Then** classification and resolution are described as separate phases with separate payloads.

---

### User Story 3 - Batch Small GitHub Thread Fixes (Priority: P3)

An agent handling several small GitHub review-thread fixes can use a documented batch response flow when one commit and validation set address multiple leased threads.

**Why this priority**: The existing strict lease model is correct, but small PRs with many minor threads need a lower-overhead path that does not bypass leases or evidence.

**Independent Test**: Can be tested by claiming multiple GitHub-thread fixer leases, submitting one batch response with shared evidence, and verifying that every included item is accepted or the whole batch is rejected without partial mutation.

**Acceptance Scenarios**:

1. **Given** multiple active GitHub-thread fixer leases, **When** the agent submits one batch response with shared commit, files, validation, and per-thread summaries, **Then** all included responses are accepted for publishing.
2. **Given** a batch response that includes a local finding, duplicate lease, stale lease, or non-fix resolution, **When** the batch is submitted, **Then** the batch is rejected without accepting any item.
3. **Given** the agent manifest or README guidance, **When** an agent wants to process several small fixes, **Then** the documented path explains `submit-batch`, lease requirements, and the max-claim limit rationale.

### Edge Cases

- Runtime requests may carry repository details only in `repository_context`, while older loop requests may still carry `repo` and `pr_number` at the top level.
- The helper may be invoked without a resume command; it still must write a reusable response artifact and print the correct next command.
- GitHub thread fixes require reply-ready evidence, while clarify, defer, and reject paths require human-readable reply text.
- Batch submission must not partially accept earlier items when a later item is stale or invalid.
- Network instability from `gh` is out of scope for this feature except that guidance should distinguish transport failure from protocol failure.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The helper MUST accept runtime action requests that store repository identity under repository context.
- **FR-002**: The helper MUST continue to accept legacy loop requests with top-level repository identity.
- **FR-003**: The helper MUST include request identity, lease identity, agent identity, resolution, note, validation evidence, and fix or reply evidence in generated response artifacts.
- **FR-004**: The helper MUST fail before writing response artifacts when required request context or evidence is missing.
- **FR-005**: Missing-classification failures MUST identify classification as triage evidence and point to the classification command.
- **FR-006**: Missing-resolution or missing-response-field failures MUST identify resolution as fixer response evidence and point to the response payload contract.
- **FR-007**: Public guidance MUST describe classification and resolution as separate workflow phases with distinct commands and payload fields.
- **FR-008**: Public guidance MUST document when `submit-batch` is appropriate, including the requirement for active leases, GitHub-thread fix-only scope, shared evidence, and per-item summaries.
- **FR-009**: Batch response behavior MUST preserve all-or-nothing rejection for invalid local findings, stale leases, duplicate leases, duplicate items, and unsupported resolutions.
- **FR-010**: The agent manifest MUST continue to expose batch response capability and max-claim constraints without suggesting that agents may mutate items without leases.

### Constitution Alignment *(mandatory)*

- **Control Plane Impact**: Runtime state, leases, evidence acceptance, GitHub side effects, and final-gate authority remain owned by deterministic runtime code. The helper only prepares response artifacts or delegates back to public commands.
- **CLI / Agent Contract Impact**: The stable public surfaces remain `review`, `agent classify`, `agent next`, `agent submit`, `agent submit-batch`, `agent publish`, and `final-gate`. This feature clarifies payload compatibility and error guidance without replacing the Status-to-Action Map.
- **Evidence Requirements**: Fix evidence must include files and validation; GitHub-thread fixes must include reply-ready fix evidence; clarify, defer, and reject responses must include reply markdown where required; final completion remains proven by `final-gate`.
- **Packaged Skill Boundary**: Skill-owned helper code may parse request files and create response artifacts, but authoritative session transitions, leases, publishing, and gating stay in `src/gh_address_cr/`.
- **External Intake Replaceability**: The feature does not change the normalized findings contract or couple review production to a specific producer.
- **Fail-Fast Behavior**: Missing request context, missing request/lease identity, unsupported item kind, missing GitHub-thread fix evidence, missing reply text, stale leases, and invalid batch shapes must fail loudly.

### Key Entities *(include if feature involves data)*

- **Action Request**: Runtime-issued work request containing request identity, lease identity, role, work item, required evidence, repository context, forbidden actions, and resume command.
- **Action Response**: Agent-produced evidence payload containing request identity, lease identity, agent identity, resolution, note, files, validation commands, and optional fix or reply evidence.
- **Batch Action Response**: Grouped evidence payload for multiple GitHub-thread fix responses that share commit/files/validation evidence while keeping per-item request and lease identity.
- **Classification Evidence**: Triage-phase record that declares whether an item should be fixed, clarified, deferred, or rejected.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A runtime-generated action request from `agent next` can be passed to the helper without manual JSON editing and produces a valid response artifact on the first attempt.
- **SC-002**: Missing classification and missing resolution failures are distinguishable by status, reason code, and next-action text.
- **SC-003**: Batch response documentation and tests cover at least two accepted GitHub-thread items and at least one all-or-nothing rejection scenario.
- **SC-004**: Existing unit tests, linting, and CLI smoke checks pass after the repair.

## Assumptions

- The reported network `TLS handshake timeout` is a transport issue outside this protocol repair.
- `max_parallel_claims: 2` remains the default safety constraint for now; the feature improves batch guidance and helper compatibility rather than raising the limit.
- `submit_action.py` remains a helper, not a new authoritative state machine.
- Existing `agent submit-batch` runtime behavior is the preferred low-overhead path for multiple small GitHub-thread fixes.
