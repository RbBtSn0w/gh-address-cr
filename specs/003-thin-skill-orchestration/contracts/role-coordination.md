# Contract: Role Coordination

## Purpose

Define the multi-agent coordination boundary for PR-scoped review resolution without requiring a custom autonomous runner.

## Roles

| Role | Responsibility | Runtime-Owned Authority |
| --- | --- | --- |
| `coordinator` | Starts or resumes a PR session and requests eligible work. | Session state, work selection, lease issuance. |
| `review_producer` | Emits normalized findings or fixed `finding` blocks. | Intake validation and session ingestion. |
| `triage` | Classifies items as `fix`, `clarify`, `defer`, or `reject`. | Classification acceptance and evidence recording. |
| `fixer` | Changes code or prepares a non-code resolution response. | Lease validation and response acceptance. |
| `verifier` | Checks fixer evidence and validation results. | Publishing decision and state transition. |
| `publisher` | Publishes replies and resolves GitHub threads. | GitHub side effects are deterministic runtime behavior. |
| `gatekeeper` | Proves completion through final gate. | Final-gate evaluation and completion authority. |

## Lease Rules

- Mutating work requires an active item-scoped claim lease.
- A lease binds `item_id`, `agent_id`, `role`, `request_id`, and request context.
- Submissions from non-holders, expired holders, duplicate holders, or mismatched roles are rejected.
- Overlapping item, thread, file, or side-effect conflict keys force serialization.
- Expired leases may be reclaimed without deleting accepted evidence.

## Evidence Rules

- Triage output requires classification and rationale.
- Fix output requires changed-file evidence and validation commands.
- Clarify, defer, and reject output require reply or rationale evidence.
- Verifier rejection returns the item to a blocked state without publishing side effects.
- Publisher side effects require accepted evidence and runtime ownership.
- Gatekeeper completion requires final-gate success.

## Parallel Work Rules

Independent work may proceed in parallel only when:

- Items have distinct IDs.
- Active leases do not conflict.
- File ownership does not overlap.
- GitHub side-effect ownership does not overlap.
- Each agent capability manifest supports the requested role and response format.

## Test Expectations

- A simulated session with at least 3 independent items and 4 roles accepts only active lease-holder submissions.
- Conflicting leases are rejected or serialized.
- Verifier rejection blocks publishing.
- No duplicate GitHub replies or resolves are emitted.
