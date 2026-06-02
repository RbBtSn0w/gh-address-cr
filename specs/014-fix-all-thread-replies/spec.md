# Feature Specification: Fix-All Thread Replies

**Feature Branch**: `014-fix-all-thread-replies`  
**Created**: 2026-06-02  
**Status**: In Review
**Input**: User description: "Downgrade `gh-address-cr agent fix-all` to a shortcut that is only appropriate for pure repeated nits or the same issue repeated across homogeneous locations. Default PR thread addressing should return to the submit-batch skeleton so agents answer each review thread one-to-one with per-thread `summary` and `why`. If `fix-all` remains available, it must support a per-item evidence input file, or otherwise generate or require independent per-thread responses from session thread bodies, with tests proving published replies differ and include targeted rationale."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Address Threads One-To-One (Priority: P1)

An agent handling ordinary PR review threads can see each reviewer question and submit a response that answers that specific thread, while still sharing common commit, file, and validation evidence when appropriate.

**Why this priority**: Review-thread completion is not just a state transition. The reviewer expects a direct answer to the specific concern they raised, and final completion should not be satisfied by repeated generic replies.

**Independent Test**: Can be tested by presenting two active review threads on the same changed file with different questions, then verifying the default addressing flow requires per-thread `summary` and `why` entries and publishes distinct replies that address each question.

**Acceptance Scenarios**:

1. **Given** multiple active GitHub review threads with different bodies, **When** the agent asks for the next addressing action, **Then** the default guidance presents the per-thread batch skeleton rather than a generic fix-all command as the primary path.
2. **Given** two review threads on the same file with different reviewer questions, **When** the agent submits shared commit and validation evidence, **Then** each item must include its own summary and rationale before it can be accepted for publishing.
3. **Given** accepted per-thread evidence for multiple review threads, **When** replies are published, **Then** each published reply includes the shared evidence plus a targeted rationale for that thread.

---

### User Story 2 - Constrain Fix-All To Homogeneous Repeats (Priority: P2)

An agent can still use `fix-all` for low-risk repeated nits or the same issue repeated across homogeneous locations, but the shortcut must not silently produce generic replies for distinct reviewer questions.

**Why this priority**: The shortcut is valuable for repeated mechanical feedback, but it becomes misleading when used as the default path for semantically different review threads.

**Independent Test**: Can be tested by running fix-all against homogeneous repeated nit threads and against mixed-question threads, then verifying homogeneous usage remains low-friction while mixed usage requires per-item evidence or fails with a clear next action.

**Acceptance Scenarios**:

1. **Given** multiple review threads that repeat the same mechanical issue, **When** the agent uses fix-all with appropriate evidence, **Then** the shortcut may accept the batch and publish replies that clearly identify the homogeneous repeated concern.
2. **Given** multiple review threads on the same file with materially different questions, **When** the agent attempts fix-all without per-item evidence, **Then** the workflow refuses generic batch acceptance and directs the agent to the per-thread skeleton path.
3. **Given** fix-all remains available for mixed or uncertain thread sets, **When** the agent supplies per-item evidence, **Then** each item's independent summary and rationale are preserved through acceptance and publishing.

---

### User Story 3 - Prevent Generic Reply Regression (Priority: P3)

Maintainers and agents can trust documentation, machine summaries, and tests to preserve the one-to-one reply contract over future workflow changes.

**Why this priority**: The previous regression happened because the batch contract supported per-thread rationale while the shortcut and tests did not enforce that property.

**Independent Test**: Can be tested by comparing generated guidance, accepted evidence, and published reply artifacts for mixed review threads and confirming generic duplicate replies are rejected or absent.

**Acceptance Scenarios**:

1. **Given** the public guidance for PR thread addressing, **When** an agent reads the next action, **Then** it explains when to use per-thread batch evidence and when fix-all is only safe for homogeneous repeated concerns.
2. **Given** automated tests cover fix-all and batch publishing, **When** two different review questions are processed, **Then** the tests verify the published replies are not identical and include targeted rationale.
3. **Given** a future change tries to reintroduce generic repeated replies for distinct questions, **When** the verification suite runs, **Then** the regression is caught before release.

### Edge Cases

- Multiple review threads may share the same file and commit but ask different questions; shared evidence must not imply shared rationale.
- Some review threads may lack a readable body in the current session; the workflow must require explicit per-item evidence rather than inventing a targeted answer.
- Stale or outdated threads remain outside the ordinary fix-all shortcut unless their handling includes runtime-mediated evidence and an explicit stale-thread path.
- Homogeneous repeated nits may still need distinct line or thread references so the reviewer can tell which comment was addressed.
- Per-item evidence must not weaken lease ownership, reply evidence, severity evidence, validation evidence, or final-gate requirements.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The default PR thread addressing guidance MUST prioritize per-thread response evidence through the batch skeleton when multiple review threads need handling.
- **FR-002**: Each accepted GitHub review-thread fix in a multi-thread batch MUST carry item-specific summary or rationale evidence before it can be published.
- **FR-003**: Published replies for materially different review questions MUST include targeted rationale for the specific thread and MUST NOT be identical generic replies.
- **FR-004**: `fix-all` MUST be documented and surfaced as a shortcut only for homogeneous repeated nits or the same issue repeated across equivalent review locations.
- **FR-005**: `fix-all` MUST require per-item evidence or otherwise require independently targeted per-thread rationale when the matched threads are mixed, uncertain, or not explicitly homogeneous.
- **FR-006**: If the workflow cannot determine that matched threads are homogeneous and no per-item evidence is supplied, it MUST fail loudly with a next action that points to the per-thread batch skeleton.
- **FR-007**: Any per-item evidence supplied through the shortcut path MUST preserve the item identity, lease identity, summary, rationale, files, validation evidence, severity evidence, and publish-ready reply evidence for each thread.
- **FR-008**: Machine summaries, skill guidance, and user-facing command descriptions MUST consistently distinguish shared fix evidence from per-thread reviewer-answer evidence.
- **FR-009**: Regression coverage MUST prove that same-file threads with different questions produce distinct targeted replies or are rejected before publishing.
- **FR-010**: Regression coverage MUST prove that homogeneous repeated nit handling remains possible without bypassing leases, validation evidence, reply evidence, or final-gate proof.

### Constitution Alignment *(mandatory)*

- **Control Plane Impact**: This feature affects session state transitions, accepted action evidence, GitHub reply publication, machine summaries, and final-gate readiness. Deterministic runtime behavior remains the owner of classification, leases, evidence acceptance, publishing, and final-gate decisions.
- **CLI / Agent Contract Impact**: The public agent contract changes the meaning and guidance of `agent fix-all`, the default addressing next action, and the expected batch evidence shape for multi-thread PR addressing. The Status-to-Action Map must continue to route agents through runtime-mediated actions rather than direct GitHub replies.
- **Evidence Requirements**: Completion requires classification evidence, active lease ownership, item-specific reply rationale for each review thread, shared or item-specific commit and file evidence, validation evidence, durable reply evidence, resolved or terminal thread state, and final-gate proof.
- **Packaged Skill Boundary**: Skill-owned guidance may explain when to use per-thread batch evidence versus fix-all, but deterministic acceptance, rejection, publishing, and gate behavior belong to the runtime. Repo-root tests and specs remain development support outside the installed skill payload.
- **External Intake Replaceability**: The feature does not change normalized local finding or external producer intake. It preserves the distinction between GitHub review-thread replies and producer findings.
- **Fail-Fast Behavior**: Missing per-item rationale, unsupported generic fix-all usage, unreadable thread bodies without explicit evidence, stale lease ownership, malformed per-item evidence, duplicate item identity, missing validation, and unsafe publish-only attempts must fail loudly.

### Key Entities *(include if feature involves data)*

- **Review Thread Question**: The reviewer concern, body, line context, and priority/severity signals that define what must be answered.
- **Per-Thread Reply Evidence**: The item-specific summary and rationale that explain how the fix addresses one review thread.
- **Shared Fix Evidence**: Commit, file, and validation details that may apply to more than one thread without replacing per-thread rationale.
- **Homogeneous Fix-All Batch**: A set of review threads that repeat the same low-risk concern across equivalent locations and can safely share a shortcut rationale.
- **Per-Item Evidence Input**: A structured set of item-specific response details supplied when a shortcut handles more than one review thread.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In a mixed two-thread scenario, the default addressing flow requires two item-specific response entries before either thread is accepted for publishing.
- **SC-002**: In a mixed two-thread scenario, published replies are distinct and each contains rationale that maps to the corresponding reviewer question.
- **SC-003**: In a mixed two-thread scenario, attempting generic fix-all without per-item evidence fails before publishing and reports a per-thread batch next action.
- **SC-004**: In a homogeneous repeated-nit scenario, the shortcut can still complete the review-thread evidence flow with shared validation while preserving lease and final-gate requirements.
- **SC-005**: Public guidance and machine summaries consistently present per-thread batch evidence as the default route for ordinary PR thread addressing.

## Assumptions

- The product keeps `fix-all` as a public shortcut, but narrows its safe usage rather than removing it entirely.
- Homogeneous repeated nits are defined by equivalent reviewer concern and equivalent fix rationale, not merely by matching file paths.
- The agent is expected to inspect thread bodies when ordinary PR review comments ask different questions.
- Existing final-gate semantics remain authoritative; this feature strengthens reply quality without redefining completion around reply count alone.
