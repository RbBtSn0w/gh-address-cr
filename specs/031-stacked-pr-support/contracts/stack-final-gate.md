# Contract: Stack-Aware Final Gate

## CLI

```text
gh-address-cr final-gate <owner/repo> <pr_number> [existing options]
gh-address-cr final-gate <owner/repo> <pr_number> --stack [existing options]
```

`--stack` composes with `--require-checks` and
`--require-required-checks`. Existing conflicting check flags remain invalid.

## Layer Gate

Default final-gate keeps current semantics and adds:

```json
{
  "gate_scope": "final",
  "completion_scope": "pull_request",
  "stack_context": {},
  "stack_merge_readiness": "not_evaluated"
}
```

A pass is authoritative only for the selected PR. On a stacked member the
completion line identifies `PR #N layer` and never claims stack readiness.

## Aggregate Gate

`--stack` returns `completion_scope=stack_segment` and a versioned
`stack_gate` object containing the selected PR, exact covered PR numbers, first
blocked member, and all member outcomes. For an unstacked PR, the covered range
contains only the selected PR and availability is `absent`.

## Stable Stack Reason Codes

| Reason code | `waiting_on` | Recovery |
|-------------|--------------|----------|
| `STACK_CONTEXT_UNAVAILABLE` | `stack_context` | Restore supported capability |
| `STACK_CONTEXT_INVALID` | `stack_context` | Refresh and inspect diagnostics |
| `STACK_CONTEXT_STALE` | `stack_refresh` | Refresh affected members |
| `STACK_MEMBER_SESSION_MISSING` | `member_session` | Run member review/address |
| `STACK_MEMBER_SESSION_INVALID` | `member_session` | Repair named session |
| `STACK_MEMBER_DRAFT` | `member_state` | Mark ready when appropriate |
| `STACK_MEMBER_CLOSED` | `member_state` | Reopen/restructure externally |
| `STACK_MEMBER_QUEUED` | `merge_queue` | Wait for or inspect queue |
| `STACK_MEMBER_BLOCKED` | nested wait state | Run member recovery command |
| `FINAL_GATE_STALE_REVISION_EVIDENCE` | `validation_evidence` | Revalidate current revision |
| `FINAL_GATE_UNBOUND_REVISION_EVIDENCE` | `validation_evidence` | Record fresh bound validation |

Existing member final-gate codes remain nested in
`member_outcomes[].layer_reason_code` and are not renamed.
`FINAL_GATE_MISSING_REPLY_EVIDENCE` maps member recovery to
`agent evidence add --reply-url`; it does not route a terminal out-of-band
resolution through `agent publish` when no publish-ready item exists.
Revision-evidence recovery also follows the blocking signal's `item_kind`:
terminal GitHub threads and local findings use item-scoped `agent evidence
add`. `FINAL_GATE_BLOCKING_LOCAL_ITEMS` uses the normal member `review`
workflow and never routes through thread-only `--auto-simple` handling.

## Freshness, Exit, and Completion Rules

- Input misuse remains exit `2`; GitHub/context preflight failures use `5`;
  member blockers use the existing final-gate failure exit; only a coherent
  aggregate pass exits `0`.
- The gate rereads context after member evaluation. A changed fingerprint
  suppresses the completion line and returns `STACK_CONTEXT_STALE`.
- Layer and stack compact lines state their distinct scopes. All existing
  counts, telemetry coverage, duration, artifacts, and diagnostics remain.
