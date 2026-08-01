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

Before response acceptance for a request that carries a revision binding or
whose stored stack context is `present`/`unavailable`, and before publish:

1. Refresh selected PR and stack context.
2. Compare PR, head OID, stack number, position, and topology fingerprint.
3. On equality, preserve existing response validation.
4. On mismatch, reject before side effects with `STALE_REQUEST_CONTEXT` and
   `waiting_on=stack_refresh`.
5. Release a stale or cross-layer request's lease, return its item to a
   claimable state, and issue a new request; never rewrite the old request or
   lease hash.

An ordinary unbound request whose stored context is absent or predates stack
metadata preserves the existing local path and performs no submit-time stack
network read. If the session has since observed stack membership, that request
is rejected locally as stale instead of being accepted without a binding.

An unbound request issued during an unavailable observation is also refreshed
at submit. If GitHub then reports current stack membership, reject the request
as stale. A non-authoritative `stack_membership_observed` safety hint prevents a
later unavailable observation from erasing previously discovered membership;
the hint cannot establish current topology or satisfy a revision binding.

An explicitly claimed different PR/head returns
`STACK_ACTION_CONTEXT_MISMATCH`. An echoed context remains optional because the
request ID, lease, immutable request file, and refreshed binding own context.

## Lower-Layer Fix Handoff

The selected PR and its `head_ref_name` own the change. A review worker already
on that branch may implement and validate the fix, but it does not checkout,
rebase, push, or otherwise propagate the stack from the ActionRequest. When the
active checkout is an upper member, it stops and hands the change to a
separately authorized stack-management workflow.

That workflow commits the fix on the owning lower branch and propagates it
upward with GitHub's stack tooling. Because propagation changes revisions and
the topology fingerprint, the old ActionRequest is discarded; runtime context,
leases, validation evidence, and affected layer gates are refreshed before
publication or aggregate completion.

## Evidence and Gate Eligibility

Accepted validation records and manual `agent evidence add` records attach the
current binding automatically; callers cannot supply arbitrary fingerprints.

- Current binding: eligible.
- Mismatch: `FINAL_GATE_STALE_REVISION_EVIDENCE`.
- Missing binding on a currently stacked member:
  `FINAL_GATE_UNBOUND_REVISION_EVIDENCE` and fresh validation required.
- Revision signals include `item_kind`. Terminal GitHub threads and local
  findings reconcile current validation through item-scoped `agent evidence
  add`; the command binds evidence to the refreshed member revision.
- Unstacked/unavailable PRs retain current layer behavior but cannot be promoted
  to stack-wide proof while context is unavailable.
- Durable GitHub reply/resolve facts do not expire solely because the head moved.
