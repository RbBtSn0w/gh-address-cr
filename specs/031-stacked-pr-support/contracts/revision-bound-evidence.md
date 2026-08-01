# Contract: Revision-Bound Stacked-Member Evidence

## ActionRequest Addition

For a valid stacked member, `repository_context` adds `stack_context.v1` and:

```json
{
  "revision_binding": {
    "schema_version": "revision_binding.v1",
    "pr_number": "102",
    "head_oid": "full-oid",
    "stack_number": 7,
    "stack_position": 2,
    "topology_fingerprint": "sha256:...",
    "captured_at": "2026-08-01T12:00:00Z"
  }
}
```

The request still forbids direct GitHub reply/resolve. It also communicates that
stack creation, checkout, rebase, push, modify, unstack, queue, and merge are
outside the worker action.

## Acceptance Rules

Before response acceptance, convenience resolution, or publish:

1. Refresh selected PR and stack context.
2. Compare PR, head OID, stack number, position, and topology fingerprint.
3. On equality, preserve existing response validation.
4. On mismatch, reject before side effects with `STALE_REQUEST_CONTEXT` and
   `waiting_on=stack_refresh`.
5. Refresh and issue a new request; never rewrite the old request or lease hash.

An explicitly claimed different PR/head returns
`STACK_ACTION_CONTEXT_MISMATCH`. An echoed context remains optional because the
request ID, lease, immutable request file, and refreshed binding own context.

## Evidence and Gate Eligibility

Accepted validation records and manual `agent evidence add` records attach the
current binding automatically; callers cannot supply arbitrary fingerprints.

- Current binding: eligible.
- Mismatch: `FINAL_GATE_STALE_REVISION_EVIDENCE`.
- Missing binding on a currently stacked member:
  `FINAL_GATE_UNBOUND_REVISION_EVIDENCE` and fresh validation required.
- Unstacked/unavailable PRs retain current layer behavior but cannot be promoted
  to stack-wide proof while context is unavailable.
- Durable GitHub reply/resolve facts do not expire solely because the head moved.
