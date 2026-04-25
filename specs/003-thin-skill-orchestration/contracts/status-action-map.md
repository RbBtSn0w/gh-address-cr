# Contract: Status Action Map

## Purpose

Define how the thin skill adapter maps runtime machine summaries to safe agent actions without parsing prose or reimplementing workflow logic.

## Inputs

The adapter consumes structured runtime command output with these fields when present:

- `status`
- `reason_code`
- `waiting_on`
- `next_action`
- `repo`
- `pr_number`
- `item_id`
- `item_kind`
- `counts`
- `artifact_path`
- `exit_code`

## Required Behavior

| Runtime Outcome | Required Adapter Behavior | Forbidden Behavior |
| --- | --- | --- |
| `PASSED` or final-gate success | Report that completion may be claimed only when final-gate proof is present. | Claim completion from a resolved-thread count alone. |
| `WAITING_FOR_EXTERNAL_REVIEW` | Provide or request normalized findings, then rerun the same high-level review command. | Treat narrative review prose as findings. |
| `WAITING_FOR_FIX` | Route the action request to a qualified agent and require structured evidence. | Edit session files directly or bypass `agent submit`. |
| `BLOCKING_ITEMS_REMAIN` | Continue runtime-mediated processing until final-gate passes. | Mark the PR complete. |
| GitHub CLI missing or unauthenticated | Stop and provide remediation for GitHub CLI availability or authentication. | Attempt partial session mutation. |
| Invalid findings input | Stop and ask for normalized findings or fixed `finding` blocks. | Parse arbitrary Markdown. |
| Missing or unknown required status fields | Stop with a fail-loud diagnostic. | Guess the next action from human prose. |

## Validation Rules

- Every stable public status must map to exactly one safe next action or one explicit stop condition.
- `next_action` can be displayed to the agent, but the adapter must not use it to invent new command semantics.
- Unknown statuses, missing `reason_code`, missing `waiting_on`, or malformed summaries are stop conditions.
- Completion examples must include final-gate evidence.

## Test Expectations

- Fixture machine summaries cover every stable public review outcome.
- Tests assert one mapping per fixture.
- Tests assert unknown or malformed summaries fail loudly.
- Tests assert completion examples require final-gate proof.
