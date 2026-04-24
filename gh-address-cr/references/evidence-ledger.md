# Evidence Ledger Expectations

The runtime owns the append-only evidence ledger. Skill instructions may describe
the policy, but they must not expose ledger internals as agent-safe mutation
APIs.

Agents should expect the runtime to record:

- `request_issued` when an `ActionRequest` is written
- `request_rejected` when classification or manifest rules block a request
- `lease_created`, `lease_submitted`, `lease_accepted`, `lease_rejected`,
  `lease_expired`, and `lease_released` for lease lifecycle changes
- `response_accepted` and `response_rejected` for `ActionResponse` handling
- `verification_rejected` when verifier evidence reopens a work item
- `reply_posted`, `thread_resolved`, and side-effect attempt records for
  deterministic GitHub publishing
- `gate_passed` or `gate_failed` for final-gate decisions

AI agents must return evidence, not side effects. In particular, they must not
claim that they posted a GitHub reply or resolved a GitHub thread. The runtime
serializes those operations and records idempotency keys, retry state, durable
reply URLs, and resume actions.

Resolve-only publishing is invalid unless the runtime already has durable reply
evidence or the same deterministic publishing action posts a fresh reply first.
