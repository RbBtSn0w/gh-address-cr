# Implementation Plan: Lease State Machine Contract

**Branch**: `033-lease-state-machine` | **Date**: 2026-09-23 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/033-lease-state-machine/spec.md`

## Summary

Write down the lease state machine as two executable tables and an entry-point
inventory, then bring the two entry points that violate it into line. The tables are
not new policy: they were produced by executing every operation against every status,
and the test reads them back from the markdown so the document and the code cannot
drift. The inventory is compared in both directions with an AST scan of `src/`, so a new
lease-creating call site fails the build until it is classified.

Behaviour changes are limited to the two violations of FR-001 plus removal of the
unreferenced `reject_lease` writer. Nothing else about leases, TTLs, the public status
set, commands, reason codes or exit codes changes (FR-007). This plan proves sequential
transition correctness; it does not claim cross-process atomicity or session/ledger crash
consistency (FR-009).

## Technical Context

**Language/Version**: Python 3.10+  
**Primary Dependencies**: stdlib (`ast` for the scan); existing `leases`, `agent_protocol`,
`agent_batch`, `workflow_matching` and orchestrator modules  
**Storage**: existing `session.json` and evidence ledger; no new fields  
**Testing**: `unittest`; contract tests read the markdown contracts as their fixtures  
**Project Type**: single Python CLI runtime plus packaged skill payload  
**Constraints**: no public CLI, reason-code or exit-code change; no new lease status;
`src/` carries zero in-code lint suppressions  
**Scale/Scope**: 6 statuses, 4 transition operations, 3 claimant kinds, 11 call sites

## Constitution Check

*GATE: checked before implementation.*

- **I. Control plane ownership — PASS**: `session.json` remains the owner of leases. The
  orchestrator's shadow lease stays subordinate and, after this change, can no longer be
  refused while the core lease it would shadow is left `active`.
- **II. Public CLI contract — PASS**: no command, field, reason code or exit code changes.
  `agent resolve --commit --files` and `agent orchestrate step` return the same errors they
  do today; the only difference is that the lease they created is released first.
- **III. Evidence-first handling — PASS**: no path to `accepted` is added; rollback only
  ever releases a lease that has not been accepted (`release_claimed_lease` ignores
  terminal leases).
- **IV. Packaged skill boundary — PASS**: contracts live under `specs/`, code under `src/`.
  The one `skill/` change corrects an existing agent-facing statement:
  `references/evidence-ledger.md` promised a `lease_rejected` event that no runtime path
  ever emitted, and its only emitter (`reject_lease`, unreferenced) is deleted here.
- **V. Testable contracts — PASS**: every table cell and every inventory row is asserted;
  each fix is preceded by a failing test.
- **VI. Claim leases — PASS**: this plan is the "lease policies" Article VI asks for,
  written down; it tightens rollback ownership without adding roles or states.
- **VIII. Telemetry boundary — PASS**: no telemetry change. The release is recorded as a
  `lease_released` event with a reason, which is ledger evidence, not telemetry.
- **Architecture plateau — PASS**: removes state (a stranded lease is an unmodelled state)
  rather than adding branches. See Complexity Tracking.

## Architecture Preflight

Required: the change alters lease ownership (AGENTS.md, blast-radius trigger).

### Authoritative state owner

`session.json`: `leases[*]` and the item claim marker (`items[*].state`,
`items[*].active_lease_id`). The orchestration session's `active_leases` is a shadow and
owns nothing.

### External facts or event inputs

The lease records present before a command runs, the leases the command creates, and the
outcome of the step that follows the claim (batch submit, shadow grant).

### Projection or derived state

"Leases created by this call" = lease ids returned by this call's claims, minus the lease
ids that existed in the session before the call. The difference is what a rollback may
touch. It is recomputed per call and never persisted.

This rule, not "the lease this call returned", is what FR-002 needs: a batch fast-fix
passes `item_id`, so `issue_action_request` may re-enter a lease the agent already held,
and returning a lease id is not evidence of having created it.

### Policy table

`contracts/lease-transitions.md` (both tables) and the class column of
`contracts/lease-entry-points.md`. Rollback policy per class:

| Class | Failure after the claim | Rollback |
|---|---|---|
| `one-shot` | a `WorkflowError` | release every lease created by the call |
| `orchestrated` | `LeaseConflictError` from the shadow grant | release the core lease created by the step |
| `two-step`, `batch-claim` after hand-over | any | none: the agent holds the skeleton |
| any | an unexpected exception | none: an unmodelled failure is not evidence the claim is safe to undo (same rule as `claimed_fixer_lease`) |

The last row is intentionally narrower than a blanket "no stranded leases" promise.
Unexpected failures may occur after an effect that cannot be inferred safely from the
exception type. The runtime keeps the lease available for owner recovery, inspection, or
TTL expiry. FR-001 covers the modeled failure boundaries named in this table.

### Side-effect plan

No GitHub side effect. The only effect is `release_claimed_lease`, which writes the lease
status, resets the item claim marker when it belongs to that lease, appends a
`lease_released` event with the triggering reason, and saves the session. It is tolerant:
a lease already terminal (for example accepted by an earlier row of the same batch) is
left alone.

### Artifact truth and self-reference

The batch file written before submit is an input artifact; it is not read back to decide
what to release. The decision uses the session's lease ids only.

### Recovery, replay, contract tests

- `test_lease_state_machine_contract.py`: both tables, the inventory in both directions,
  and a check that no `one-shot` or `orchestrated` row is marked unprotected.
- One failure-injection test per violation, written first and seen failing:
  a batch fast-fix whose submit is rejected leaves no lease it created `active`, and leaves
  a lease the agent already held untouched; an orchestrator step refused a shadow lease
  leaves no core lease `active` and the item claimable.
- Replay: rerunning the same command after the rollback claims the item again.

## Project Structure

```text
specs/033-lease-state-machine/
├── spec.md
├── plan.md
└── contracts/
    ├── lease-transitions.md
    └── lease-entry-points.md

src/gh_address_cr/
├── core/workflow_matching.py      # batch fast-fix rollback
└── orchestrator/harness.py        # release the core lease on a shadow conflict

tests/contract/
├── test_lease_state_machine_contract.py
└── test_claim_rollback_contract.py  # the two failure-injection cases
```

## Complexity Tracking

No violation to justify. The two fixes each add one `except WorkflowError` /
`except LeaseConflictError` release step to a path that already catches the error; they
remove the stranded-lease state rather than adding a flag or a fallback.

The orchestrator fix treats the symptom of a deeper disagreement: the shadow lease refuses
two items on the same file (`context_key` is the path) while the core `claim_lease` allows
them when their hunks do not overlap. Releasing the core lease makes the conflict a clean
`RETRY` instead of a lock. Whether the shadow should be as strict as it is, or should defer
to the core's conflict keys, is recorded as an open question rather than changed here.

## Deferred Atomic Persistence Work

This PR deliberately does not add a file lock, session revision/CAS protocol, SQLite
store, or session/ledger transaction. Choosing one changes persistence ownership,
recovery, replay, and compatibility semantics and therefore needs its own Architecture
Preflight and executable concurrency/crash contracts. That follow-up must cover at least:

- two processes claiming the same item (exactly one succeeds);
- two processes claiming different items (neither update is lost);
- concurrent claim/release and re-entry/rollback without resurrection;
- explicit `created` versus `re-entered` acquisition provenance;
- reconciliation after a crash between session and ledger writes; and
- one conflict policy for the core lease and orchestrator shadow/reference.
