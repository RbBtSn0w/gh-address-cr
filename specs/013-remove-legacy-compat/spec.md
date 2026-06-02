# Feature Specification: Remove Legacy Compatibility

**Feature Branch**: `013-remove-legacy-compat`  
**Created**: 2026-06-02  
**Status**: Verified
**Input**: User description: "历史兼容代码移除，保证高效性执行和最佳化。"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Use Only Current Supported Workflows (Priority: P1)

As an agent or maintainer, I want the product to expose only the current supported workflow contracts, so that every successful run follows the modern review-resolution path without spending time on obsolete compatibility behavior.

**Why this priority**: Removing unsupported legacy behavior only creates value if the primary user path remains clear, fast, and trustworthy.

**Independent Test**: Can be fully tested by running the documented current workflows and confirming they complete without requiring any historical invocation shape, deprecated handoff format, or hidden compatibility path.

**Acceptance Scenarios**:

1. **Given** a maintainer follows the current documented workflow, **When** they start a new review-resolution session, **Then** the system accepts the workflow and reports progress through current public statuses only.
2. **Given** an agent uses the packaged skill guidance, **When** it chooses the next action, **Then** it routes through the current supported contract and does not reference historical compatibility instructions.

---

### User Story 2 - Reject Superseded Entrypoints Clearly (Priority: P2)

As a maintainer, I want superseded compatibility entrypoints and historical invocation shapes to fail clearly, so that obsolete automation is discovered quickly instead of silently taking a slower or ambiguous path.

**Why this priority**: Explicit rejection protects correctness and saves operator time during migration cleanup.

**Independent Test**: Can be tested by attempting each known superseded workflow and confirming the result is a clear unsupported-usage outcome with a pointer to the current supported workflow.

**Acceptance Scenarios**:

1. **Given** a user invokes a superseded compatibility path, **When** the system evaluates the request, **Then** it rejects the usage before performing review side effects.
2. **Given** old automation depends on a historical input shape, **When** that automation runs, **Then** the failure message identifies that the shape is unsupported and names the current contract to use.

---

### User Story 3 - Preserve Historical Context Without Runtime Cost (Priority: P3)

As a maintainer, I want historical documentation to remain recognizable as past context, so that future agents can understand why older material exists without treating it as active runtime guidance.

**Why this priority**: The repository still needs auditability, but historical context must not create active compatibility obligations.

**Independent Test**: Can be tested by reviewing historical artifacts and confirming each retained obsolete reference is explicitly marked as superseded or archival.

**Acceptance Scenarios**:

1. **Given** an older spec or reference mentions a deprecated workflow, **When** an agent reads it, **Then** the artifact clearly identifies the current authority for active behavior.
2. **Given** a maintainer audits the repository, **When** they search for historical compatibility references, **Then** every remaining reference is either removed from active guidance or marked as archival context.

### Edge Cases

- A historical reference is retained because it documents release history or prior decisions; it must be labeled as archival and must not be usable as active instruction.
- A current workflow still accepts an older-looking value for a documented public reason; that acceptance must be named as current behavior, not hidden compatibility.
- A user attempts unsupported legacy usage while a review session is already in progress; the system must not mutate session state or perform external side effects before rejecting the request.
- Existing automation fails after compatibility removal; the failure must be actionable enough for the operator to migrate to the current supported workflow.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST define the current supported workflow surface for review-resolution usage and distinguish it from historical compatibility behavior.
- **FR-002**: The system MUST remove or disable active support for superseded compatibility paths that are not part of the current supported workflow surface.
- **FR-003**: The system MUST reject unsupported legacy usage before performing review state changes, external replies, resolutions, or completion claims.
- **FR-004**: Rejection of unsupported legacy usage MUST include a clear reason and the current supported workflow the user should use instead.
- **FR-005**: Active user-facing guidance MUST avoid instructing agents or maintainers to use deprecated compatibility paths.
- **FR-006**: Historical artifacts that retain deprecated workflow references MUST mark those references as superseded or archival.
- **FR-007**: Current supported workflows MUST remain fully usable after compatibility removal.
- **FR-008**: The feature MUST preserve audit evidence for review handling, including verification, classification, reply, resolve, and final-gate outcomes.
- **FR-009**: The feature MUST avoid creating new hidden fallbacks, silent shims, or alternate undocumented prompt contracts.
- **FR-010**: The feature MUST provide measurable verification that current workflows complete without depending on removed compatibility behavior.
- **FR-011**: The runtime package MUST NOT retain `legacy_handlers`, `command_handlers`, or obsolete low-level handler modules as active implementation surface; current helper behavior MUST live only under the current `gh_address_cr.commands` module set.

### Constitution Alignment *(mandatory)*

- **Control Plane Impact**: This feature affects the review-resolution control plane by narrowing accepted runtime behavior. The deterministic runtime remains the owner of session state, external side effects, loop safety, audit artifacts, telemetry, and final-gate behavior.
- **CLI / Agent Contract Impact**: This feature changes unsupported legacy acceptance, but preserves the current public workflow surface, machine-readable statuses, wait states, reason codes, exit codes, and the Status-to-Action Map for supported usage.
- **Evidence Requirements**: Supported review items must still be verified, classified, replied to, resolved when applicable, and gated before completion. Unsupported legacy usage must produce rejection evidence before any review side effect occurs.
- **Packaged Skill Boundary**: The packaged skill remains a thin behavioral adapter that points agents to current supported workflows. Runtime decisions and side effects remain outside the packaged skill payload.
- **External Intake Replaceability**: The feature preserves review-producer replaceability by keeping the normalized findings boundary as the accepted intake model for active workflows.
- **Fail-Fast Behavior**: Superseded entrypoints, malformed historical handoffs, obsolete instruction paths, and unsupported public command usage must fail loudly with actionable migration guidance.

### Key Entities

- **Current Workflow Surface**: The active set of user-facing review-resolution behaviors that are supported, documented, and verified.
- **Superseded Compatibility Path**: A historical entrypoint, instruction, or input shape that previously existed but is no longer part of supported behavior.
- **Unsupported Usage Outcome**: The clear rejection result produced when a user attempts obsolete behavior.
- **Historical Artifact**: A retained document, spec, or reference that may mention old behavior for audit context but must not act as current instruction.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of documented current workflow checks complete successfully after compatibility removal.
- **SC-002**: 100% of known superseded compatibility paths are either removed from active guidance or rejected before side effects.
- **SC-003**: Maintainers can identify the current supported workflow from active guidance in under 2 minutes without following historical references.
- **SC-004**: No active user-facing artifact contains an unmarked instruction to use a deprecated compatibility path.
- **SC-005**: Unsupported legacy usage produces an actionable rejection outcome in every tested case.
- **SC-006**: Current workflow execution avoids additional compatibility-only decision steps, reducing obsolete-path evaluation to zero for supported usage.
- **SC-007**: Installed package inspection shows `gh_address_cr/legacy_scripts`, `gh_address_cr/legacy_handlers`, and `gh_address_cr/command_handlers` are absent from the runtime payload.

## Assumptions

- The target users are maintainers and AI coding agents operating this repository's review-resolution workflow.
- The active product identity remains `gh-address-cr`; this feature removes historical compatibility behavior without renaming the product.
- Compatibility removal is scoped to unsupported legacy behavior, not to current documented public contracts that are still required by users or tests.
- Historical context may remain in specs or release notes when clearly marked as superseded or archival.
- Downstream implementation will update code, active guidance, and executable tests together for any public behavior change.
