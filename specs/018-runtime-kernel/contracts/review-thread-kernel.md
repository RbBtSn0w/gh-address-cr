# Contract: Review Thread Runtime Kernel

## Scope

This contract covers the first runtime-kernel slice for GitHub review-thread handling. It is an internal runtime contract. It does not change public CLI behavior or the structured agent protocol in this phase.

## Input Facts

### `review_thread_observed`

Required fields:

- `schema_version`
- `fact_kind`
- `fact_id`
- `observed_at`
- `payload.thread_id`

Optional fields:

- `sequence`
- `payload.item_id`
- `payload.is_resolved`
- `payload.is_outdated`
- `payload.state`
- `payload.status`
- `payload.path`
- `payload.line`
- `payload.url`
- `payload.body`
- `payload.reply_evidence_present`
- `payload.external_wait`

Unsupported schema versions, malformed `observed_at` values, missing thread
identity, ambiguous item identity, and non-boolean review-thread boolean fields
must fail loudly. Fact ordering must compare normalized chronological
timestamps, not raw timestamp strings.

## Projection Contract

Projection must:

- sort facts deterministically
- derive exactly one current `ReviewWorkItem` per thread item
- derive a current review-thread generation from the latest review-thread observation
- treat unresolved and stale/outdated threads as active work
- treat resolved threads as terminal only when no later reopened observation exists
- treat external-wait observations as waiting before stale or reopened local-action states
- mark later unresolved observations after terminal history as reopened
- mark items evidence-pending when required reply or resolve evidence is missing
- count command execution evidence only when it matches the current generation and expected planned command identity
- expose final-gate blockers from active, reopened, stale, waiting, or evidence-pending work

## Policy Contract

Policy must map one projection to one decision:

| Projection condition | Decision | Required reason code |
|---|---|---|
| Blocking diagnostics exist | `blocked` | `KERNEL_FACT_INVALID` or `KERNEL_PROJECTION_CONTRADICTION` |
| Active, stale, reopened, or evidence-pending local-action work exists | `ready_for_action` | `REVIEW_THREAD_ACTION_REQUIRED` |
| Only external-wait work remains | `waiting_for_external_input` | `WAITING_FOR_EXTERNAL_INPUT` |
| No blockers remain | `final_gate_eligible` | `FINAL_GATE_ELIGIBLE` |

## Determinism Requirements

- The same fact set must produce identical projection dictionaries.
- Reordering the same fact set must produce identical projection dictionaries.
- The same projection must produce identical policy decision dictionaries.

## Non-Goals

- No GitHub API calls in projection or policy.
- No artifact writes in projection or policy.
- No public CLI output changes in this phase.
