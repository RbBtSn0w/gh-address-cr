# Feature Specification: Runtime Store Hardening

**Feature Branch**: `fix/035-runtime-store-hardening` (stacked as 035a → 035b → 035c → 035d)
**Created**: 2026-09-26
**Status**: Draft — planning approved; no implementation has landed
**Input**: Post-merge audit of Spec 034 (PRs #287, #288, #290, #292, #293) on
`develop` before release PR #289 promotes it to `main`.

## Why this exists

Spec 034 delivered its core objective: one per-PR SQLite store is the single
source of runtime truth, and claims serialize across processes (the 100-process
race contract is real). The audit found that the edge paths around that core —
first-open migration, crash recovery, and the publisher — do not yet meet
Spec 034's own requirements. Five defects were reproduced with scripts (R1–R5
below); two more were confirmed by reading the code.

The release risk is asymmetric. FR-010a of Spec 034 makes the legacy-to-SQLite
migration one-way (no in-place downgrade). Shipping a migration with a
concurrency hole or a crash window to users cannot be rolled back, so the
migration fixes must land before `develop` is promoted.

This spec fixes all seven findings under one set of design rules, with one
schema bump, and adds the performance baseline and observability that Spec 034
did not have.

## Audit findings (inputs to this spec)

| ID | Severity | Finding | Evidence |
|---|---|---|---|
| F1 | High | `RuntimeStore._bootstrap_new` checks existence, builds a temp database, then `os.replace`s it; a late writer overwrites a store that already committed revisions. Concurrent legacy migration raises bare `FileExistsError` or transient `PERSISTENCE_INVALID`. | R2: committed revision 2 overwritten back to revision 1. R3: 8-process migration failed in 5/5 trials. |
| F2 | High | The `legacy-v1-recovery/` bundle is created with `mkdir` → copies → `manifest.json`. A crash before the manifest makes every later `load()` fail with `PERSISTENCE_INVALID` until a human deletes the directory. | R1 |
| F3 | Medium-high | `load_session` calls `RuntimeStore.recover()` on every load, which demotes every `in_flight` outbox row to `unknown` even while its executor is alive, and takes a write lock on every read. | R4 |
| F4 | Medium | The publisher decides reply/resolve idempotency by reading `evidence.jsonl` (a compatibility projection), violating Spec 034 FR-008. `recover_artifacts` never compares the recorded `content_hash`, so an edited projection goes undetected. Migrated legacy sessions have side-effect evidence but no outbox rows. | R5: truncated projection → publisher sees "never replied"; the outbox blocks the duplicate only via an unstructured `ValueError`. |
| F5 | Medium | 28 write sites use whole-document compare-and-swap (`save_session`), only 4 use `transact_session`. `STALE_REVISION` / `PERSISTENCE_BUSY` / `PERSISTENCE_INVALID` are flattened into `SESSION_ERROR` / `PUBLISH_ERROR` by catch-all handlers, and `status-action-map.md` has no entries for them although `skill/SKILL.md` tells agents to follow them. | Code reading |
| F6 | Medium-low | Normalized columns and `lease_conflict_keys` are written but never read; the truth is `payload_json`. "One active lease per item" is enforced only in Python and, if violated, bricks every subsequent load. `transaction_id` is always NULL; `last_observed_revision` is bumped on every commit. | Code reading |
| F7 | Low | The orchestrator prunes stale dispatches but never rebuilds them from canonical leases after restart (Spec 034 US-C2 partially met); a post-claim `except Exception` in `handle_step` orphans the committed lease until TTL; Phase C contract tests assert source text, not behavior. | Code reading |
| P0 | — | No performance acceptance existed. Every commit rewrites all session rows and the whole `evidence.jsonl`, so per-write cost grows with session size (21 ms at 200 events, 58 ms at 3000). Local efficiency reporting only flags operations over 60 s, so gradual slowdown is invisible. | Measurement |

## User Scenarios & Testing

### US1 — First open after upgrade is exactly-once under concurrency (P1)

As several agents starting on the same PR right after an upgrade, exactly one
process performs the legacy import or bootstrap; the others wait and then load
the committed store. No committed revision is ever overwritten.

**Independent test**: N processes behind a barrier open or migrate the same
workspace while one of them commits a claim immediately after initializing.

**Acceptance**:
1. **Given** 32 concurrent initializers, **when** all return, **then** the store
   has exactly one `migration_history` row and every committed transaction is present.
2. **Given** a lock wait that exceeds the bounded timeout, **then** the caller
   gets `PERSISTENCE_BUSY` and no partial store is visible.
3. **Given** a crash inside initialization, **then** the store reopens as
   uninitialized and a retry succeeds.

### US2 — A crash during migration never strands the session (P1)

**Acceptance**:
1. **Given** a crash at any recovery-bundle checkpoint, **when** migration is
   retried, **then** it succeeds and the bundle hashes match the legacy inputs.
2. **Given** a complete bundle whose hashes no longer match, **then** the runtime
   still fails fast with `PERSISTENCE_INVALID` (tampering is not auto-repaired).

### US3 — `unknown` means the executor died (P1)

**Acceptance**:
1. **Given** a live process executing an outbox command, **when** other processes
   load the session any number of times, **then** the command stays `in_flight`.
2. **Given** the executor dies, **when** the next load runs, **then** the command
   becomes `unknown` and follows the existing reconcile/retry rules.
3. **Given** two publishers on one item, **then** GitHub receives one reply and the
   other publisher gets `SIDE_EFFECT_IN_PROGRESS`.

### US4 — Publishing never trusts projections (P1)

**Acceptance**:
1. **Given** a truncated or edited `evidence.jsonl`, **when** publish runs,
   **then** decisions come from the outbox table and no duplicate side effect occurs.
2. **Given** a session migrated from legacy JSON with prior side effects,
   **then** the outbox is backfilled and publish does not repeat them.

### US5 — Agents receive stable persistence reason codes (P2)

**Acceptance**: Every agent/high-level command returns the original
`reason_code` and an additive `retryable` flag for persistence failures, and
each code has a `status-action-map.md` entry.

### US6 — Store invariants are enforced by the database (P2)

**Acceptance**: A second active lease for one item is rejected inside the
transaction and the store remains loadable.

### US7 — Orchestrator dispatch is rebuilt from canonical leases (P3)

**Acceptance**: After `orchestration.json` is lost, dispatch for
orchestrator-held canonical leases is rebuilt and the worker's original token
still submits; a failure after the core claim releases the claim.

### US8 — Slowdown is measured, budgeted, and visible (P1, cross-cutting)

**Acceptance**: A benchmark establishes `main` and `develop` baselines; every
035 PR proves it stays within budget; persistence latency is observable in OTel
and local efficiency reports flag within-session latency growth.

## Requirements

- **FR-001 (atomic initialization)**: Store creation and legacy import MUST run
  in place under one SQLite `BEGIN EXCLUSIVE` transaction on the target database.
  Temp-file-and-rename publication of the database is removed.
- **FR-002 (initialized, not present)**: Callers MUST decide between load and
  initialize by `RuntimeStore.is_initialized()` (committed metadata row), never by
  file existence.
- **FR-003 (no bootstrap over legacy)**: An uninitialized workspace containing a
  legacy `session.json` MUST be migrated; direct bootstrap from an in-memory
  payload MUST fail with `PERSISTENCE_INVALID`.
- **FR-004 (atomic recovery bundle)**: The bundle MUST be built and fsynced in a
  temporary sibling directory and published by atomic rename while the
  initialization lock is held. A bundle without `manifest.json` is provably
  incomplete and is quarantined deterministically with a bounded event.
- **FR-005 (single schema bump)**: Outbox ownership columns, outbox backfill,
  the active-lease unique index, and `transaction_id` population ship together
  as schema version 2 with an explicit, exactly-once v1→v2 migration.
- **FR-006 (executor liveness)**: An `in_flight` outbox row MUST record an owner
  token and be protected by an OS advisory lock held for the full external call.
  Only rows whose lock is acquirable may be demoted to `unknown`.
- **FR-007 (read-only load)**: `load_session` MUST NOT open a write transaction
  unless there is a dead-owner `in_flight` row or a pending schema migration.
- **FR-008 (outbox is the publish authority)**: Publisher idempotency decisions
  MUST read the outbox table. `EvidenceLedger.successful_side_effect_url` and
  `latest_side_effect_status` are removed.
- **FR-009 (backfill)**: Legacy import and v1→v2 migration MUST derive outbox rows
  from `side_effect_attempt` evidence with one shared function; conflicting
  derivations fail with `PERSISTENCE_INVALID`.
- **FR-010 (projection drift)**: Drift detection MUST use a stat fast path
  (recorded size and mtime) and hash only on mismatch; drift rebuilds the
  projection and never changes canonical truth.
- **FR-011 (stable reason codes)**: `STALE_REVISION`, `PERSISTENCE_BUSY`,
  `PERSISTENCE_INVALID`, `SIDE_EFFECT_IN_PROGRESS`, `PUBLISH_RECONCILE_REQUIRED`,
  and `DISPATCH_PROJECTION_FAILED` MUST reach agent-facing JSON unchanged, with an
  additive `retryable` field; exit codes are unchanged (FR-012 of Spec 034).
- **FR-012 (transactional hot paths)**: `release_claimed_lease`, `reclaim_leases`,
  and agent submit/accept MUST use `transact_session` mutation closures that
  perform no file or network IO.
- **FR-013 (database invariants)**: At most one `active`/`submitted` lease per
  item MUST be enforced by a partial unique index.
- **FR-014 (dispatch rebuild)**: Dispatch receipts (`dispatch-receipt.v2`) MUST
  derive their delivery token from the canonical lease `resume_token`, and
  reconciliation MUST rebuild missing receipts for orchestrator-held leases.
- **FR-015 (performance budget)**: Each 035 PR MUST report benchmark results
  against the recorded baselines and stay within the budgets in `plan.md`.
- **FR-016 (persistence observability)**: Transaction, materialization, recovery,
  and migration MUST be child spans with separate lock-wait and execute
  durations and bounded size buckets, without paths, identifiers, SQL, or payloads.
- **FR-017 (regression visibility)**: The local efficiency report MUST flag a
  command whose latency grows more than 2× between the first and last 20% of a
  session (minimum 10 samples).

## Success Criteria

- **SC-001**: R1–R5 are permanent contract tests that fail on the pre-fix commit
  and pass after the fix.
- **SC-002**: Every Spec 034 FR/SC is ✅ in `validation.md`.
- **SC-003**: Fault injection at every initialization, bundle, migration, outbox,
  and materialization checkpoint reopens to the old or complete new revision.
- **SC-004**: An upgrade from `v3.15.3` state with already-published replies
  produces zero duplicate GitHub side effects and an unchanged final-gate result.
- **SC-005**: The simulated CR loop's degradation ratio (last-decile ÷ first-decile
  median per-CR latency) is ≤ 1.5 at the L profile from 035b onward.
- **SC-006**: Telemetry privacy tests pass for every new span and event.

## Scope Boundaries

- No move to reading normalized columns as truth; `payload_json` remains the
  per-row truth and normalized columns are same-transaction index projections.
- No change to GitHub stack ownership, merge side effects, or final-gate semantics.
- No remote or multi-host storage. Network filesystems remain unsupported
  (Spec 034 FR-013), which also covers the advisory execution lock.
- The full session-row rewrite per transaction is not changed here; it is
  revisited only if P2 size-bucketed telemetry shows it matters.
