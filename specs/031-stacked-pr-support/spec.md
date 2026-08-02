# Feature Specification: Stacked Pull Request Support

**Feature Branch**: `031-stacked-pr-support`  
**Created**: 2026-08-01  
**Status**: Draft  
**Input**: User description: "Analyze GitHub's newly released stacked pull requests, plan support in gh-address-cr, and verify each feature increment before considering the feature shipped."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Understand the Current Layer and Stack (Priority: P1)

An engineer runs an existing review-resolution command for any pull request. If
the pull request belongs to a stack, the result identifies the current layer,
the ordered members below and above it, the stack trunk, and whether the
observed topology is current enough for the requested operation. If it is not
stacked, existing behavior remains unchanged.

**Why this priority**: Every later safety decision depends on correctly
distinguishing an independent pull request from one layer of a dependency chain.
Awareness alone prevents agents from treating the layer's direct base branch as
the final integration target or editing the wrong branch.

**Independent Test**: Use one unstacked pull request plus bottom, middle, and top
members of a three-layer stack. Run each existing high-level command and verify
that machine output identifies the correct context without changing any review
thread or branch.

**Acceptance Scenarios**:

1. **Given** an unstacked pull request, **When** an existing review-resolution command runs, **Then** it behaves as before and explicitly reports that no stack is present.
2. **Given** any member of a stack, **When** an existing review-resolution command runs, **Then** it reports the stack identifier, trunk, size, current position, ordered members, and current layer's head and base identity.
3. **Given** stack metadata cannot be read, **When** a normal single-layer operation runs, **Then** the operation may continue with stack awareness marked unavailable and must not claim stack-wide readiness.
4. **Given** stack metadata cannot be read, **When** a stack-wide operation is requested, **Then** it fails loudly with a stable recovery action.

---

### User Story 2 - Resolve Review Feedback on the Owning Layer (Priority: P2)

An engineer or agent addresses feedback on one stack member while preserving
the existing per-pull-request evidence lifecycle. The action request identifies
the branch and pull request that own the change. After a lower layer changes,
the system detects affected upper-layer head changes and does not reuse stale
validation as proof for the new revision.

**Why this priority**: GitHub can cascade a lower-layer change through every
layer above it. Without revision-bound evidence, a previously passing session
can become misleading even though its pull request number and review threads
have not changed.

**Independent Test**: Resolve one finding on the middle layer of a three-layer
stack, update the upper layer to a new revision, and prove that the middle layer
retains valid evidence while the changed upper layer requires fresh validation.

**Acceptance Scenarios**:

1. **Given** a finding on a stack member, **When** an action request is issued, **Then** it names the owning pull request, expected head branch, observed revision, stack position, and prohibited stack-management side effects.
2. **Given** accepted validation evidence for a stack member, **When** the member's observed revision is unchanged, **Then** the evidence remains eligible for that member's gate.
3. **Given** accepted validation evidence for a stack member, **When** a cascade, rebase, reorder, or push changes the member's revision or position, **Then** the affected completion proof becomes stale and the next action requires refresh and revalidation.
4. **Given** a change belongs to a different layer, **When** an agent attempts to submit it under the current layer's request, **Then** the submission is rejected before publication with a stable reason code.

---

### User Story 3 - Prove Layer and Stack Readiness Separately (Priority: P3)

An engineer can prove that the current pull request layer is review-complete and,
when explicitly requested, prove that the contiguous stack segment from the
lowest unmerged member through the selected member is ready. Output never
confuses layer completion with stack merge readiness.

**Why this priority**: GitHub merges stack members bottom-up and may merge all
members below the selected pull request in one operation. A green current layer
is insufficient if a lower layer is blocked.

**Independent Test**: Exercise a three-layer stack with one blocked lower layer,
then clear each blocker bottom-up. Verify that layer gates and the aggregate
stack gate report distinct results and that the stack gate passes only after all
included layers pass against the same current topology.

**Acceptance Scenarios**:

1. **Given** a stack member whose own review evidence is complete, **When** its normal final gate runs, **Then** the result clearly identifies layer scope and does not claim stack merge readiness.
2. **Given** an explicit stack-wide final gate request for a middle or top member, **When** any included lower member is blocked, stale, missing a session, or has non-green required checks, **Then** the aggregate gate fails and identifies the first blocked member in bottom-up order.
3. **Given** every included member passes its current layer gate, **When** the stack-wide gate revalidates unchanged topology and revisions, **Then** it passes and reports the exact contiguous member set covered by the proof.
4. **Given** the stack changes during evaluation, **When** the aggregate decision would otherwise be emitted, **Then** it fails as stale rather than combining facts from different stack revisions.
5. **Given** an unstacked pull request, **When** stack-wide final gating is explicitly requested, **Then** the single pull request is evaluated as a one-member scope with an explicit unstacked result.

---

### User Story 4 - Adopt Preview Support Safely (Priority: P4)

A maintainer can ship, observe, and troubleshoot stacked pull request support
without exposing repository-sensitive data or coupling review resolution to
GitHub's branch-management tooling. Documentation states the preview boundary,
the supported workflow, and the operations intentionally left to GitHub.

**Why this priority**: The upstream feature is a public preview and its contract
may change. A narrow, observable boundary makes updates inexpensive and avoids
turning gh-address-cr into a second stack manager.

**Independent Test**: Run contract fixtures for supported, unavailable,
malformed, and changed stack facts; inspect public artifacts and telemetry; then
run a live read-only smoke test against GitHub before an isolated live stack
acceptance test.

**Acceptance Scenarios**:

1. **Given** supported stack facts, **When** commands emit telemetry and reports, **Then** they expose only bounded stack dimensions and no raw local paths, branch names, titles, bodies, or credentials.
2. **Given** upstream stack facts change shape or violate invariants, **When** they are ingested, **Then** stack-specific behavior fails fast with diagnostics while existing unstacked review resolution remains available where safe.
3. **Given** the feature documentation, **When** an agent follows it, **Then** branch creation, cascading rebase, force-push, and merge remain explicit GitHub or `gh stack` operations rather than hidden gh-address-cr side effects.
4. **Given** the release candidate, **When** all repository verification and live acceptance scenarios run, **Then** each feature slice has reproducible passing evidence and any preview-only limitation remains visible.

### Edge Cases

- A stack contains open, draft, queued, merged, or closed members in one history.
- The selected pull request is the bottom, middle, or top member, or its lower
  members merged between two observations.
- GitHub automatically retargets and rebases remaining members after a partial
  stack merge.
- A member is removed, inserted, reordered, or the entire stack is dissolved
  while a local session or action lease exists.
- A lower-layer fix changes upper-layer commit identities while review thread
  identities remain unchanged.
- A stack exceeds one response page and must not be silently truncated.
- A malformed stack repeats a member, has non-contiguous positions, reports a
  size that differs from the members returned, or points to another repository.
- GitHub.com exposes stack support but an older GitHub Enterprise Server or an
  older API version does not.
- Stack metadata is temporarily unavailable while review-thread reads remain
  available.
- The official stack CLI extension is not installed locally.
- Required checks are skipped, pending, failed, or re-triggered after a cascade.
- Two concurrent stack-gate attempts observe different topology revisions.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST discover stack membership from current GitHub facts for every pull request-scoped high-level command and final gate.
- **FR-002**: The system MUST represent stack absence, stack presence, stack-context unavailability, and malformed stack facts as distinct states.
- **FR-003**: For a stacked pull request, the system MUST expose a deterministic context containing stack identity, trunk, size, current position, ordered members, each member's pull request identity, direct base, head, state, and observed revision.
- **FR-004**: The system MUST validate that stack members belong to the same repository, positions are unique and contiguous, the selected pull request appears exactly once, reported size matches the complete member set, and the dependency chain is coherent.
- **FR-005**: The system MUST paginate stack member reads to completion and MUST fail rather than evaluate a truncated stack.
- **FR-006**: Existing unstacked pull request commands MUST preserve their current inputs, exit semantics, evidence obligations, and side-effect boundaries.
- **FR-007**: A normal pull request-scoped operation MAY continue when stack context is unavailable, but MUST mark stack readiness as unknown and MUST NOT emit stack-wide completion proof.
- **FR-008**: An explicitly stack-scoped operation MUST fail loudly when stack context is unavailable, malformed, incomplete, or stale.
- **FR-009**: Each pull request MUST retain its own authoritative session, work items, leases, reply evidence, validation evidence, and final-gate decision.
- **FR-010**: Stack state MUST be a derived aggregation of current GitHub facts and member sessions; it MUST NOT become a second mutable workflow state engine.
- **FR-011**: Action requests for a stacked pull request MUST identify the owning pull request, expected head, observed revision, current stack position, and member relationships.
- **FR-012**: Action requests MUST explicitly forbid agents from creating, restructuring, rebasing, force-pushing, unstacking, queuing, or merging a stack unless a separate user-authorized workflow owns that operation.
- **FR-013**: The system MUST reject action evidence that is explicitly associated with a different pull request, head, or observed revision than the active request.
- **FR-014**: Validation and completion evidence used for a stacked member MUST be bound to the member revision against which it was produced.
- **FR-015**: When a member revision or material stack position changes, the system MUST classify affected revision-bound evidence as stale and provide a deterministic refresh action.
- **FR-016**: Reply and resolve evidence that remains valid on GitHub MAY survive a revision change; validation or completion evidence MUST NOT survive merely because thread identities are unchanged.
- **FR-017**: The normal final gate MUST state whether its proof scope is one pull request layer or an explicitly evaluated stack segment.
- **FR-018**: A passing layer-scoped final gate on a stacked pull request MUST NOT claim stack merge readiness.
- **FR-019**: The system MUST offer an explicit stack-wide final gate that evaluates the contiguous range from the lowest unmerged member through the selected member in bottom-up order.
- **FR-020**: The stack-wide final gate MUST recompute each included member's layer decision from its current authoritative session and current GitHub facts; prior report artifacts MUST NOT be accepted as gate truth.
- **FR-021**: The stack-wide final gate MUST fail for any included member that is missing required session evidence, has unresolved review items, lacks durable reply or validation evidence, has a pending current-user review, has stale revision-bound evidence, or does not meet the requested check policy.
- **FR-022**: The stack-wide final gate MUST use one coherent topology observation and MUST fail as stale if topology or included member revisions change before the decision is emitted.
- **FR-023**: Stack-wide failure output MUST identify the first blocked member in bottom-up order, all observed member outcomes, a stable reason code, a wait state, and executable recovery commands.
- **FR-024**: A passing stack-wide result MUST identify the stack, selected member, exact covered member range, topology observation identity, check policy, and per-member layer outcomes.
- **FR-025**: Machine-readable additions MUST be documented, versioned where compatibility requires it, and reflected in the Status-to-Action Map without repurposing existing reason codes.
- **FR-026**: Stack discovery, topology validation, revision freshness, per-member gate evaluation, aggregate policy, and recovery mapping MUST be deterministic and replayable from captured facts.
- **FR-027**: Stack support MUST add OpenTelemetry evidence for discovery and aggregate evaluation using bounded values such as present/unavailable, position class, member count, outcome, and reason code.
- **FR-028**: Telemetry and public-safe reports MUST NOT contain raw branch names, pull request titles or bodies, repository-local paths, usernames, credentials, or unbounded member lists as attributes. Direct machine output MAY include the branch identities required to select the owning layer, but MUST keep them out of telemetry attributes and redacted public summaries.
- **FR-029**: Missing or damaged telemetry MUST remain fail-open for review completion, while malformed or unsafe telemetry input MUST remain visible and follow existing telemetry policy.
- **FR-030**: The shipped skill MUST explain layer ownership, bottom-up handling, revision invalidation, the distinction between layer and stack proof, and the boundary with GitHub's stack-management and merge tooling.
- **FR-031**: Verification MUST cover pure policy tests, API-shape contract fixtures, CLI machine summaries, session replay, stack topology mutation, packaged-skill checks, and a live GitHub acceptance stack.
- **FR-032**: Live acceptance MUST avoid production repositories and destructive merge behavior; creation, rebase, push, or cleanup of a disposable test stack requires an explicit, isolated test setup.

### Constitution Alignment *(mandatory)*

- **Control Plane Impact**: This feature affects GitHub IO, session metadata,
  structured action context, final-gate truth semantics, audit output, and
  telemetry. Deterministic runtime code remains the sole owner of all state and
  decisions. Per-PR sessions remain authoritative; the stack view is derived.
- **Runtime Kernel Model**: External facts are pull request identity, stack
  membership and order, member states and revisions, review threads, pending
  reviews, and checks. Projections produce validated layer contexts and a
  bottom-up stack segment. Explicit policies decide availability, freshness,
  layer completion, and aggregate readiness. Side effects remain existing
  reply/resolve operations for one PR; stack-management and merge side effects
  are excluded. Reports are evidence only. Replay and mutation contracts cover
  every state transition.
- **CLI / Agent Contract Impact**: Existing command inputs remain valid. Machine
  summaries and action-request repository context gain versioned stack fields,
  stable stack reason codes, and recovery commands. A stack-scoped final-gate
  request is added without changing the meaning of existing layer-scoped input.
  The Status-to-Action Map gains explicit unavailable, stale, malformed,
  member-blocked, and passed outcomes.
- **Evidence Requirements**: Each member independently retains classification,
  reply, resolve, and revision-bound validation evidence. Stack proof recomputes
  those member decisions against one current topology observation and never
  trusts a prior summary artifact.
- **Packaged Skill Boundary**: Runtime discovery, projection, policy, freshness,
  and gate logic belong under `src/`. The `skill/` payload only routes agents,
  explains policy, and documents machine contracts. Development fixtures and
  live acceptance support remain at repository root.
- **External Intake Replaceability**: Normalized findings remain PR-scoped and
  producer-agnostic. Stack membership changes repository context, not the
  findings format or review-producer contract.
- **Telemetry Evidence Boundary**: Stack telemetry observes discovery and gate
  efficiency only. It cannot resolve items or satisfy gates. It uses bounded,
  privacy-safe dimensions, preserves coverage labels, and excludes topology
  details that would leak branch or repository information.
- **Architecture Plateau Risk**: This is a blast-radius feature and therefore
  requires an architecture spec. The design adds one validated external-fact
  adapter and one aggregate projection over unchanged PR-scoped kernels rather
  than scattering stack checks across command handlers or introducing a second
  session engine.
- **Fail-Fast Behavior**: Explicit stack operations fail on unavailable,
  incomplete, malformed, cross-repository, contradictory, paginated-truncated,
  or changed topology; mismatched action evidence; stale member revisions; and
  unsupported stack-specific usage. Existing layer operations degrade only to
  an explicit unknown stack-readiness state when safe.

### Key Entities *(include if feature involves data)*

- **Stack Observation**: An immutable, time-bounded record of GitHub-supplied
  stack identity, trunk, ordered membership, member revisions, completeness,
  and availability.
- **Stack Member Context**: The selected pull request's position, dependency
  relationships, direct base and head identity, current revision, state, and
  owning PR-scoped session reference.
- **Revision-Bound Evidence**: Existing validation or completion evidence plus
  the member revision for which it is eligible.
- **Stack Gate Projection**: The contiguous bottom-up member range, current
  layer decisions, freshness status, and requested check policy derived from
  one coherent observation.
- **Stack Gate Decision**: A deterministic pass or blocking outcome with stable
  reason, wait state, member attribution, and recovery commands.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In the acceptance matrix, 100% of unstacked, bottom, middle, and top pull requests are classified with the correct scope and ordered position.
- **SC-002**: In every topology-mutation scenario, stale stack or revision evidence is detected before publication or stack-wide completion is claimed.
- **SC-003**: A three-layer stack with one blocked member identifies that member and the correct bottom-up recovery action in one command result.
- **SC-004**: A stack-wide result passes only when 100% of included members independently pass against the same current topology observation.
- **SC-005**: Existing unstacked public-contract and regression suites pass without callers adding new arguments or changing their workflows.
- **SC-006**: All new malformed, incomplete, unavailable, cross-repository, and concurrent-change fixtures produce deterministic stable outcomes across replay.
- **SC-007**: Public telemetry and designated public-safe reports contain zero raw branch names, local paths, titles, bodies, usernames, tokens, or credentials in automated privacy checks.
- **SC-008**: A maintainer can follow the quickstart to validate each of the four user stories independently, with every command, expected result, and cleanup boundary documented.
- **SC-009**: Repository install, lint, unit, CLI smoke, agent manifest, and plugin payload checks all pass before the feature is considered complete.
- **SC-010**: One isolated live GitHub stack proves discovery and layer/stack gating; destructive stack management or merging is either explicitly authorized in the disposable fixture or remains unexecuted and documented.

## Assumptions

- GitHub stacked pull requests remain a public preview and their programmatic
  contract may change; stack-specific parsing is isolated behind capability and
  shape validation.
- The supported stack is contained in one repository. Cross-fork stacks are not
  supported by GitHub and remain out of scope.
- `gh-address-cr` continues to productize review resolution. Stack creation,
  navigation, restructuring, cascading rebase, force-push, queueing, and merge
  are owned by GitHub and the official stack tooling.
- Existing commands continue to select one pull request by number. Stack-wide
  evaluation uses a selected member as the upper boundary rather than adding a
  separate user-maintained stack identifier.
- Per-PR sessions remain stable across stack position changes because pull
  request identity does not change; revision-bound evidence is refreshed when
  the pull request revision changes.
- The first implementation targets GitHub.com. Older enterprise installations
  may expose stack context as unavailable while retaining current unstacked
  behavior.
- Live acceptance uses a disposable repository or explicitly isolated branches
  and does not merge production work.
