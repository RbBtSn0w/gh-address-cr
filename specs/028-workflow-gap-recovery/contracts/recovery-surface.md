# Contract: Recovery Surface

## Purpose

Define the machine-readable recovery contract for blocked PR-closure workflows
that involve terminal GitHub-thread evidence gaps, lease conflicts, or mixed
claimability.

## Surfaces In Scope

- `gh-address-cr final-gate <owner/repo> <pr_number> --machine`
- `gh-address-cr agent evidence add ...`
- `gh-address-cr agent leases <owner/repo> <pr_number>`
- `gh-address-cr agent reclaim <owner/repo> <pr_number>`
- `gh-address-cr agent resolve ...`

## Final-Gate Recovery Rules

### `FINAL_GATE_MISSING_REPLY_EVIDENCE`

- **Required behavior**:
  - If accepted publish-ready evidence exists, next action may route to `agent publish`.
  - If the blocking thread is terminal and not claimable, next action must route to an explicit reconcile flow rather than a dead-end publish loop.
  - Machine summary must expose enough detail to distinguish publishable vs reconcile-only blockers.

### `FINAL_GATE_MISSING_VALIDATION_EVIDENCE`

- **Required behavior**:
  - For terminal `github_thread` items that already carry fix classification and reply evidence, next action must point to validation reconciliation, not stale or batch claim routes.
  - The contract must remain fail-fast for non-terminal items.

### Lease-owned no-work cases

- **Required behavior**:
  - If an item is blocked only because an active lease currently owns it, the command response must include lease-recovery details or an equivalent machine-readable explanation.
  - A generic `NO_ELIGIBLE_ITEM` response is insufficient when the true blocker is an active lease owned by a known workflow.

## Reconcile Contract

### Reply evidence reconcile

- **Inputs**:
  - PR scope
  - `item_id` or `thread_id`
  - `reply_url`
  - `author_login`
- **Preconditions**:
  - Item must exist and be a GitHub thread in session state.
- **Effects**:
  - Record durable evidence in the ledger.
  - Update item reply evidence in session state.
  - Make the evidence visible to final-gate.

### Validation evidence reconcile

- **Inputs**:
  - PR scope
  - terminal `item_id` or `thread_id`
  - `commit`
  - `files`
  - success-like `validation`
- **Preconditions**:
  - Item must be a terminal GitHub thread.
- **Effects**:
  - Record validation evidence in the ledger.
  - Update item validation evidence in session state.
  - Clear logic-validation blockers when the evidence is sufficient.

## Lease Recovery Contract

- `agent leases` rows must expose:
  - `lease_id`
  - `item_id`
  - `lease_status`
  - `lease_recovery.recovery_outcome`
  - `lease_recovery.reason_code`
  - `lease_recovery.resume_command` when safe
- Recovery outcomes:
  - `renew`: request a fresh action request for the same item
  - `reclaim`: run the supported reclaim path and then request work again
  - `refresh_state`: discard stale local context and resync runtime truth
  - `stop`: another actor or newer state owns the item
  - `already_completed`: the work is terminal; continue to publish or gate

## Compatibility Rules

- Existing high-level commands remain the main surface.
- New recovery behavior must be additive or reason-code-refining, not a silent
  change in the meaning of existing successful paths.
- Skill references and status-action-map documentation must stay aligned with
  runtime behavior.
