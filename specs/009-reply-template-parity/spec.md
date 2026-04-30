# Feature Specification: Reply Template Parity

**Feature Branch**: `009-reply-template-parity`  
**Created**: 2026-04-30  
**Status**: Verified
**Input**: User description: "Fix GitHub CR reply template parity so native runtime publishes v1-style skill reply templates for fix, clarify, and defer."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Template-Consistent Fix Replies (Priority: P1)

As a reviewer or PR author, I want fix replies posted by `agent publish` to match the documented v1 fix templates, so GitHub review conversations remain predictable and audit-friendly.

**Why this priority**: Fix replies are the most common terminal CR response and currently show the visible template drift.

**Independent Test**: Publishing an accepted `fix` response for a GitHub thread posts a body matching the severity-specific v1 template.

**Acceptance Scenarios**:

1. **Given** a publish-ready GitHub thread with a P1 fix response, **When** `agent publish` posts the reply, **Then** the body uses the P1 `Fixed in` / `Severity` / `What I changed` / `Why this addresses the CR` / `Validation` template and P1 closing line.
2. **Given** a fix response includes both `reply_markdown` and `fix_reply`, **When** the response is published, **Then** `fix_reply` remains the source for the templated fix reply.

---

### User Story 2 - Template-Consistent Clarify And Defer Replies (Priority: P2)

As a reviewer or PR author, I want clarify and defer replies to use the documented v1 templates, so non-code-change decisions are explicit and consistent.

**Why this priority**: Raw `reply_markdown` preserves content but bypasses the policy language that explains why no code change was made or why work is deferred.

**Independent Test**: Publishing accepted `clarify` and `defer` responses wraps their rationale in the v1 clarify/defer templates.

**Acceptance Scenarios**:

1. **Given** a publish-ready GitHub thread with a `clarify` response, **When** `agent publish` posts the reply, **Then** the body starts with `Thanks for the review.` and includes `Analysis & Rationale` plus `Decision`.
2. **Given** a publish-ready GitHub thread with a `defer` response, **When** `agent publish` posts the reply, **Then** the body starts with `Thanks, this is valid feedback.` and includes `Decision` plus `Follow-up plan`.

---

### User Story 3 - Skill And Runtime Renderer Parity (Priority: P3)

As a maintainer, I want `generate-reply`, `skill/assets`, and native publish output to stay aligned, so future changes cannot silently reintroduce template drift.

**Why this priority**: The bug exists because runtime and skill template outputs drifted without executable parity checks.

**Independent Test**: Tests compare skill script output and asset templates against the runtime renderer contract.

**Acceptance Scenarios**:

1. **Given** `skill/scripts/generate_reply.py` is used in fix, clarify, or defer mode, **When** it renders a reply, **Then** its output matches the native runtime renderer for the same inputs.
2. **Given** packaged skill template assets are inspected, **When** parity tests run, **Then** the documented headings and severity-specific lines match the runtime contract.

### Edge Cases

- Missing `fix_reply` for a `fix` response must fail before GitHub side effects.
- Missing `reply_markdown` for `clarify` or `defer` must fail before GitHub side effects.
- Unknown fix severity must normalize to P2.
- Existing final-gate reply evidence behavior must remain unchanged.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The runtime MUST render GitHub `fix` replies using severity-specific v1 template wording for P1, P2, and P3.
- **FR-002**: The runtime MUST render GitHub `clarify` replies using the v1 clarify template and the accepted `reply_markdown` as rationale.
- **FR-003**: The runtime MUST render GitHub `defer` replies using the v1 defer template and the accepted `reply_markdown` as the defer reason.
- **FR-004**: `agent publish` MUST keep `fix_reply` as the required evidence for `fix` responses and `reply_markdown` as the required evidence for `clarify` and `defer`.
- **FR-005**: `skill/scripts/generate_reply.py` MUST render replies through the same runtime contract or equivalent output as `agent publish`.
- **FR-006**: The project MUST include executable parity tests that fail when runtime output, skill script output, or documented skill assets drift.
- **FR-007**: The change MUST NOT alter final-gate pass criteria, batch evidence schema, findings intake, or ActionResponse schema version.

### Constitution Alignment *(mandatory)*

- **Control Plane Impact**: GitHub reply body generation remains deterministic runtime behavior owned by `src/gh_address_cr/core`.
- **CLI / Agent Contract Impact**: Public reply text changes, but `ActionResponse` fields, reason codes, wait states, and exit codes remain compatible.
- **Evidence Requirements**: Existing accepted evidence is still required before publish; missing reply evidence fails before GitHub side effects.
- **Packaged Skill Boundary**: `skill/` keeps template assets and script output as a packaged policy surface, but runtime remains authoritative.
- **External Intake Replaceability**: No changes to findings normalization or review producer contracts.
- **Fail-Fast Behavior**: Malformed or incomplete reply evidence must continue to block publish without posting or resolving threads.

### Key Entities

- **ReplyTemplateContract**: The documented output structure for fix, clarify, and defer replies.
- **ActionResponse Evidence**: Existing accepted response fields used to populate templates.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of runtime GitHub reply modes covered by tests render documented v1 template headings.
- **SC-002**: `generate-reply` and runtime renderer produce identical output for representative fix, clarify, and defer inputs.
- **SC-003**: Full project unit tests, lint, CLI smoke checks, and `git diff --check` pass after implementation.

## Assumptions

- Runtime renderer is the single source of truth for generated reply bodies.
- `skill/assets/reply-templates/*` are documentation/parity fixtures, not runtime business logic.
- P2 remains the default severity for missing or unknown fix severity.
