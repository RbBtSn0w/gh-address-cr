# Data Model: Dynamic CR Replies & Severity Accuracy

## Entities

### SeverityRubric
Defines the mapping between finding impact and P-level classification.
- **P0 (Blocker)**: Severe security flaw, data loss, or system-wide crash.
- **P1 (Critical)**: Significant logic error in a core path, significant performance regression.
- **P2 (Major)**: Functional bug in a non-critical path, moderate logic error.
- **P3 (Minor)**: Small UX improvement, missing unit test for low-risk logic, sub-optimal but functional code.
- **P4 (Nit)**: Typo, style inconsistency, non-functional code cleanup suggestion.

### RichReply
The data structure used to generate a contextual GitHub reply.
- **severity**: P0, P1, P2, P3, or P4.
- **commit_hash**: The SHA of the fixing commit.
- **files**: List of changed files.
- **summary**: Short description of the change.
- **why**: Multi-paragraph technical rationale.
- **test_command**: Command used to verify.
- **test_result**: Formatted result of the test run.

## State Transitions
- **Classify Finding**: Review Comment -> [SeverityRubric] -> Severity Level (P0-P4).
- **Generate Reply**: [RichReply Data] + [Markdown Template] -> Formatted GitHub Reply.
