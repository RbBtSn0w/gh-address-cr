# Feature Specification: Dynamic CR Replies & Severity Accuracy

**Feature Branch**: `010-dynamic-cr-replies`  
**Created**: 2024-05-24  
**Status**: Verified
**Input**: User description: "发现一个问题现在cr的回复内容很多都是死板的内容，回答的内容并不是完整按照提问者进行回答的，还有对于问题的评审级别是p0，p1，p2, 还是什么级别，也是不准确的。"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Dynamic, Context-Aware Code Review Replies (Priority: P1)

As a code author and reviewer, I want the agent's replies to PR comments to be dynamic and directly answer the specific questions or concerns raised in the original comment. The replies should follow a "Structured but Rich" format: maintaining clear headers for auditability (What changed, Validation, Rationale) while allowing the agent to provide multi-paragraph, free-form technical explanations tailored to the reviewer's query.

**Why this priority**: Rigid, single-bullet-point replies erode trust. Multi-paragraph explanations prove the agent has performed deep reasoning and handles nuance correctly.

**Independent Test**: Can be fully tested by submitting a complex "Why" question to a PR thread and verifying the agent provides a coherent, multi-paragraph response within the "Rationale" header that directly addresses the architectural trade-offs mentioned.

**Acceptance Scenarios**:

1. **Given** a reviewer asks about a specific architectural trade-off, **When** the agent replies, **Then** the "Rationale" section contains a detailed paragraph explaining the choice, rather than a generic boilerplate sentence.
2. **Given** a reviewer identifies a complex race condition, **When** the agent provides a fix, **Then** the reply explicitly describes the synchronization primitive added and why it solves the specific race condition identified.

---

### User Story 2 - Accurate P0-P4 Severity Classification (Priority: P1)

As a code reviewer, I want the agent to accurately assess findings using a standardized P0-P4 scale:
- **P0**: Blocker (Crashes, data loss, critical security holes)
- **P1**: Critical (Major logic errors, regression in core paths)
- **P2**: Major (Standard bugs, performance regressions)
- **P3**: Minor (Sub-optimal logic, missing tests)
- **P4**: Nit/Suggestion (Typos, style consistency, non-functional improvements)

**Why this priority**: Accurate classification ensures critical fixes aren't missed and reduces "alert fatigue" caused by over-escalating minor style issues.

**Independent Test**: Verified by a benchmark suite where a known P0 (e.g., SQL injection) and a known P4 (e.g., camelCase vs snake_case) are correctly classified by the agent.

**Acceptance Scenarios**:

1. **Given** a crash-on-startup bug, **When** the agent processes it, **Then** it classifies it as P0.
2. **Given** a variable naming suggestion, **When** the agent processes it, **Then** it classifies it as P4.

### Edge Cases

- **Severity Overlap**: How to handle a comment that contains both a P4 typo and a P1 logic error? (Requirement: Split into multiple findings or classify by highest severity).
- **Vague Rubric**: How to maintain consistency across different LLM providers? (Requirement: Provide a canonical Rubric artifact).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST provide a formal **Severity & Tone Rubric** in the agent's prompt context, defining the P0-P4 scale and the expected response depth for each level.
- **FR-002**: System MUST support "Structured but Rich" reply generation, allowing multi-paragraph, free-form strings in the `technical_reasoning` and `summary` fields of the Agent Protocol JSON.
- **FR-003**: Agent replies MUST explicitly reference domain-specific concepts, variable names, or logic branches from the original reviewer comment to demonstrate "Deep Comprehension."
- **FR-004**: System MUST accurately map the P0-P4 classification to the corresponding visual representation in the GitHub thread (e.g., emojis or clear labels).
- **FR-005**: For P0 and P1 findings, the system MUST require the agent to provide at least two paragraphs of technical rationale explaining the fix and the impact.

### Constitution Alignment *(mandatory)*

- **Control Plane Impact**: Impacts the finding classification and reply generation phases. The deterministic state machine continues to own the workflow.
- **CLI / Agent Contract Impact**: Updates the `fix_reply`, `clarify_reply`, and `defer_reply` definitions in the Agent Protocol to explicitly permit and expect rich, multi-line rationales.
- **Evidence Requirements**: The rich rationale text provides better evidence of "Deep Verification."
- **Packaged Skill Boundary**: Updates to `skill/agents/` (prompts) and `skill/assets/reply-templates/` (formatting). Updates to `src/gh_address_cr/core/` to support P0/P4 and rich string handling.
- **External Intake Replaceability**: Maintains finding normalization.
- **Fail-Fast Behavior**: Schema validation must fail if an invalid severity (e.g., "Medium") is provided instead of the P0-P4 standard.

### Key Entities

- **Agent Reply**: The generated text responding to a review comment, including severity, commit hash, files changed, test command, and technical rationale.
- **Severity Level**: A classification mapping (e.g., P0, P1, P2, P3) determining the impact of a review finding.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 95% of agent replies explicitly reference at least one domain-specific term from the original review comment.
- **SC-002**: Zero instances of exact duplicate "boilerplate" response strings across different review threads in a single session.
- **SC-003**: 90% accuracy in severity classification when tested against a benchmark suite of 50 diverse, pre-graded code review comments.
- **SC-004**: Reviewers rate the contextual accuracy of the AI's answers as "helpful" or "accurate" in qualitative feedback.

## Assumptions

- We assume the underlying LLM (e.g., GPT-4o, Claude 3.5 Sonnet) is capable of accurate severity classification and contextual response generation when provided with a proper rubric and prompt instructions.
- We assume the current rigidity is a symptom of prompt design or over-constrained reply templates, rather than a fundamental limitation of the LLM.
