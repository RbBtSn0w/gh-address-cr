# Contract: Lease Transitions

Both tables below were produced by executing each operation against a lease in each
status (`core/leases.py`), not by reading the code, and are asserted cell by cell by
`tests/contract/test_lease_state_machine_contract.py`. A change to either table is a
deliberate contract change: edit this file and the test together.

## Statuses

| Status | Meaning | Counts as leased |
|---|---|---|
| `active` | Claimed; the holder may submit | yes |
| `submitted` | Evidence sent, awaiting acceptance | yes |
| `accepted` | Terminal. Evidence accepted | no |
| `rejected` | Terminal. Rejected by the runtime | no |
| `expired` | Terminal. TTL passed | no |
| `released` | Terminal. Given up by its holder or rolled back | no |

`ACTIVE_LEASE_STATUSES = {active, submitted}`; the other four are
`TERMINAL_LEASE_STATUSES`. A terminal lease never changes status again.

## Table 1: transitions

Rows are the lease's current status, columns the operation. A cell is the resulting
status, or the error raised.

| from \ via | `submit` | `accept` | `reject` | `release` | `expire` (TTL passed) |
|---|---|---|---|---|---|
| `active` | `submitted` | `STALE_LEASE` | `rejected` | `released` | `expired` |
| `submitted` | `DUPLICATE_SUBMISSION` | `accepted` | `rejected` | `released` | `expired` |
| `accepted` | `STALE_LEASE` | `STALE_LEASE` | `STALE_LEASE` | `STALE_LEASE` | `accepted` (no-op) |
| `rejected` | `STALE_LEASE` | `STALE_LEASE` | `STALE_LEASE` | `STALE_LEASE` | `rejected` (no-op) |
| `expired` | `STALE_LEASE` | `STALE_LEASE` | `STALE_LEASE` | `STALE_LEASE` | `expired` (no-op) |
| `released` | `STALE_LEASE` | `STALE_LEASE` | `STALE_LEASE` | `STALE_LEASE` | `released` (no-op) |

Consequences worth stating:

- `accepted` is reachable only through `submitted`; an `active` lease cannot be accepted.
- **`rejected` is unreachable in production.** `reject_lease` has no caller in `src`, so no
  runtime path produces a `rejected` lease; only a test constructing one does. The status
  stays in the table because code still reads it (`STALE_LEASE` handling, recovery
  outcomes), but a maintainer should not assume a `rejected` lease can exist in a real
  session. Whether to remove it or to use it (for example instead of `released` when a
  rollback follows a rejected submit) is undecided and out of scope here.
- `expire` is not an error on a terminal lease. It is the only operation that is safe to
  call unconditionally, which is why `claim` and `issue_action_request` both call it first.
- **A `submitted` lease expires like an `active` one.** Evidence that was sent but not yet
  accepted can lose its lease when the TTL passes. This is current behaviour, recorded
  here so a later decision to protect it is a visible edit (see Open Questions in
  `spec.md`).

## Table 2: claim

`claim` creates a new `active` lease. It is not a transition out of a status: it is
constrained by the status of the item's *other* leases. `claim_lease` calls `expire`
first, so an `active` lease past its TTL is `expired` before the check.

| existing lease on the item | same agent, fixer | another agent, fixer | another agent, verifier |
|---|---|---|---|
| `active` | `ITEM_ALREADY_LEASED` | `ITEM_ALREADY_LEASED` | `ITEM_ALREADY_LEASED` |
| `submitted` | `ITEM_ALREADY_LEASED` | `ITEM_ALREADY_LEASED` | `ITEM_ALREADY_LEASED` |
| `accepted` | new lease | new lease | new lease |
| `rejected` | new lease | new lease | new lease |
| `expired` | new lease | new lease | new lease |
| `released` | new lease | new lease | new lease |

Consequences:

- **`claim_lease` has no re-entry.** Even the holder's own second claim is
  `ITEM_ALREADY_LEASED`. Re-entry is a protocol-layer behaviour, decided in
  `issue_action_request` before `claim_lease` is reached. Do not add it to `claim_lease`.
- An item whose lease was `accepted` can be claimed again, so a verifier rejection can
  reopen an item that had been accepted.
- Separately from the item check, `claim_lease` rejects a claim whose conflict keys
  overlap another lease's (`CONFLICT_KEYS_OVERLAP`), unless both roles are read-only or
  the same agent holds overlapping GitHub-thread file keys.

## Who may trigger what

| Operation | Permitted callers | Rule |
|---|---|---|
| `claim` | `issue_action_request`, `agent_batch._lease_new_github_thread` | The only two lease creators in `core/`; the orchestrator adds a shadow lease on top (see below) |
| `submit`, `accept` | `accept_action_response_submission` | Always together, in that order, in one call |
| `release` | `_release_active_triage_lease`, `release_irrecoverable_request_lease`, `release_self_stale_lease`, `release_claimed_lease` | Each releases a lease it has a specific claim to (below) |
| `reject` | none in `src` | Defined but unreferenced; only `tests/test_claim_leases.py` calls it |
| `expire` | `expire_leases` from `claim_lease`, `issue_action_request`, `issue_batch_action_request`, `reclaim_leases` | Time-driven; needs no ownership |

### Release ownership (FR-002)

| Releaser | May release | Must not release |
|---|---|---|
| `claimed_fixer_lease` rollback | A lease its own call created | A lease the caller already held (re-entry) |
| `_process_fast_fix_matches` rollback | The chunk's leases whose ids were not in the session before its claims | A lease id that existed before the chunk (re-entered), or one already accepted by an earlier row of the same submit |
| `handle_step` rollback | The core lease the step just issued, on `LeaseConflictError` from the shadow grant | Nothing else. The step names no item, so its lease is never a re-entered one |
| `_release_active_triage_lease` | A `triage` lease on the item it just classified | Any other role |
| `release_self_stale_lease` | The resolving agent's own `fixer` lease, on a thread that went stale | Another agent's, or a non-fixer role's |
| `release_irrecoverable_request_lease` | An `active` or `submitted` lease, only on `STALE_REQUEST_CONTEXT` or `STACK_ACTION_CONTEXT_MISMATCH` | On any other rejection. It leaves the item's claim marker alone when `item.active_lease_id` names a different lease |
| `agent reclaim` | Only by expiry, never by release | A still-valid lease |

## The item claim marker is separate state

A lease's status and the item's claim marker are two records that must move together. A
claim sets `item.state = "claimed"` and `item.active_lease_id`; releasing the lease alone
leaves the item marked claimed, and the claim path treats a `claimed` item as not open. The
symptom is `LEASE_LOCKED_ITEM` turning into `NO_ELIGIBLE_ITEM`, not recovery.

The two lease creators do not set the same marker. `issue_action_request` sets only `state`
and `active_lease_id`; `agent_batch._lease_new_github_thread` also sets `claimed_by`,
`claimed_at` and `lease_expires_at`. Every reset below clears all five so it is correct for
either creator, but a reader must not infer that a single-item claim populates them
(executing a claim shows `claimed_by`, `claimed_at` and `lease_expires_at` unset).

Every path that ends a lease must therefore reset the marker, and only when the marker
belongs to that lease:

| Path | Lease | Item marker |
|---|---|---|
| `release_claimed_lease` (rollback) | `released` | `state` returns to `open`, `active_lease_id` and the three batch-only fields cleared |
| `release_irrecoverable_request_lease` | `released` | reset, unless `active_lease_id` names another lease |
| `release_self_stale_lease` | `released` | `state` set to `stale`, `active_lease_id` cleared; `claimed_by` untouched |
| `expire` | `expired` | reset to claimable when `active_lease_id` matches |
| `accept` | `accepted` | advanced by applying the accepted response to the item |

## The two-step exemption (FR-001)

A flow that returns the agent a request and a skeleton keeps its lease across a rejected
submit, so the agent can correct and resubmit against the same `lease_id`:

- `agent next` then `agent submit`
- `agent next --batch` then `agent resolve --input`

The claim phase of `agent next --batch` is still transactional: a failure while claiming
rolls back the whole batch. The exemption covers only what happens *after* the agent holds
the skeleton.

## Re-entry (FR-003)

`issue_action_request(role="fixer", item_id=...)` returns the request for a lease the agent
already holds, without minting a second one, only when **all** hold:

1. the lease is `active` (not `submitted`, not terminal, not expired);
2. its `agent_id` is the requester's and its role is `fixer`;
3. the call names the item (`--item-id`). Without it the item is skipped as already leased
   and the answer is `NO_ELIGIBLE_ITEM`;
4. the lease carries a `request_id` and `request_path`.

The returned request keeps the lease's original `request_id` and `lease_id`. A missing,
unparseable, non-`ActionRequest` or foreign request file is rebuilt under those ids, its
`request_issued` event is recorded, and the lease's `request_hash` is set to the hash of the
file now on disk. A usable request and skeleton are returned untouched, including a
skeleton the agent has already filled in.

## The orchestrator's shadow lease

`orchestrator/session.py` keeps one in-memory `LeaseRecord` per item, keyed by `item_id`,
with a token, a `context_key` and its own TTL. Differences from a core lease that a
maintainer must not assume away:

| | core lease | shadow lease |
|---|---|---|
| Storage | `session.json` | orchestration session |
| Terminal states | four | none; release deletes it |
| Release | status change, event in ledger | `del`, entry in `orchestration_audit.log` |
| Ownership check | agent, role, status | token, with `force=True` to override |

Per the Constitution the shadow is subordinate: it must not outlive or contradict the core
lease it shadows. `handle_step` issues the core lease first, then grants the shadow, so a
failure of the second step must release the first (FR-001).
