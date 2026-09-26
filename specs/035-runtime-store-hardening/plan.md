# Implementation Plan: Runtime Store Hardening

**Branch**: stacked `fix/035a` → `fix/035b` → `fix/035c` → `fix/035d` | **Date**: 2026-09-26 |
**Spec**: [spec.md](./spec.md) | **Tasks**: [tasks.md](./tasks.md) | **Validation**: [validation.md](./validation.md)

## Summary

Fix the seven Spec 034 audit findings (F1–F7) under shared design rules and a
single schema bump, and add the performance baseline, budgets, and
observability that Spec 034 lacked (P1–P4). Release PR #289 waits for 035a, and
preferably 035b, so the one-way migrations ship only once.

## Shared Design Rules

1. **SQLite is the only lock and the only truth.** Initialization and migration
   run in place under `BEGIN EXCLUSIVE`; no separate migration lock file. The one
   exception is executor liveness (F3), which SQLite cannot express without
   blocking all writers for the duration of a GitHub call; it uses an OS advisory lock.
2. **One schema bump (v1 → v2)** carries outbox ownership, outbox backfill, the
   active-lease unique index, and `transaction_id`.
3. **Every persistence failure reaches the agent as a stable reason code.**
4. **No silent fallback.** Each automatic repair is provably deterministic, documented,
   tested, and emits a bounded event.
5. **Contract discipline** per `AGENTS.md`: code, docs, and tests change together.
6. **Measure first; prove no slowdown.** The benchmark lands in the first PR; every
   later PR compares against it. Any added per-command fixed cost must be quantified.

## Delivery Stack

| PR (base) | Scope | Blocks #289 |
|---|---|---|
| 035a `fix/035a-atomic-store-init` (develop) | F1, F2, P1 benchmark + baselines, this spec | Yes |
| 035b `fix/035b-outbox-ownership` (035a) | F3, F4, F6 (schema v2), P2 persistence spans, P3 incremental projection | Recommended |
| 035c `fix/035c-persistence-reason-codes` (035b) | F5 | No |
| 035d `fix/035d-orchestrator-dispatch-rebuild` (035c) | F7, P4 regression detection | No |

Spec 034's status line is amended in 035a to "Superseded in part by 035".

## F1 — Atomic initialization and migration (035a)

- Replace `_bootstrap_new` temp-db + `os.replace` with a private
  `RuntimeStore._initialize(...)` behind the existing `bootstrap` and
  `open_or_migrate` entry points: connect to `runtime.sqlite3`,
  `BEGIN EXCLUSIVE`; if `store_metadata` exists, roll back and `load()`;
  otherwise create schema, write rows and `migration_history`, commit. A crash
  rolls back via the journal. The schema is created one statement at a time
  because `executescript` commits any open transaction first.
- Add `RuntimeStore.is_initialized()` (committed metadata row, not file
  existence); replace every `database_path.exists()` decision in
  `src/gh_address_cr/core/session.py`. A metadata table without its row fails
  fast with `PERSISTENCE_INVALID`; `load()` on an uninitialized store still fails fast.
- `bootstrap(..., require_new=True)` raises `StaleRevisionError` when another
  writer initialized first, so `save_session` never silently drops its payload.
- `save_session` refuses to bootstrap over a legacy `session.json` (FR-003).
- Lock timeout surfaces as `PersistenceBusyError`; no bare `FileExistsError`.
- Migration is the only documented case of file IO inside a write transaction.

## F2 — Atomic recovery bundle (035a)

- Build `legacy-v1-recovery.tmp-<uuid>/`, copy and fsync files, write and fsync the
  manifest and directory, then rename to `legacy-v1-recovery/`, all under the F1 lock.
- Under the lock: delete `legacy-v1-recovery.tmp-*`; a published bundle without
  `manifest.json` (possible only from interrupted pre-035 builds) is renamed to
  `legacy-v1-recovery.incomplete-<ts>/`, rebuilt, and reported with
  `persistence.migration outcome=bundle_quarantined`. A manifest hash mismatch still fails fast.
- Add `write_json_durable` in `src/gh_address_cr/core/io.py` for the bundle only.
  `write_json_atomic` stays unsynced: projections are rebuildable, so a global
  fsync would add fixed cost with no durability benefit.

## F3 — Executor liveness for outbox commands (035b, schema v2)

- `outbox_commands` gains `owner_token` and `in_flight_since`.
- New `src/gh_address_cr/core/process_lock.py`: `hold_execution_lock(workspace, command_id)`
  (POSIX `fcntl.flock`, Windows `msvcrt.locking`, otherwise fail fast) on
  `<workspace>/outbox-exec/<command_id>.lock`, and a non-blocking
  `is_execution_lock_held(...)` probe. The OS releases the lock on process death.
- New `side_effect_outbox.execute_side_effect(session, attempt, call)` owns the
  lock for plan → in_flight → external call → result; the publisher's reply and
  resolve paths call it instead of sequencing three `_record_side_effect_attempt` calls.
- `recover()` reads `in_flight` rows first; it opens a write transaction only for
  rows whose lock is acquirable. No `in_flight` rows means no write transaction.
- A live `in_flight` row seen by another publisher yields `SIDE_EFFECT_IN_PROGRESS`.

## F4 — Outbox as publish authority (035b)

- Add `RuntimeStore.outbox_command(effect_type, idempotency_key)` and
  `side_effect_outbox.side_effect_state(...) -> (status, external_ref, owner_alive)`;
  replace the three projection reads in `src/gh_address_cr/core/publisher.py`.
- Remove `EvidenceLedger.successful_side_effect_url` and `latest_side_effect_status`.
- Shared `_derive_outbox_from_evidence(...)` backfills rows during legacy import
  and v1→v2 migration: latest attempt per `(side_effect_type, idempotency_key)`;
  `succeeded` keeps `external_url`, `in_flight` becomes `unknown`, `failed` stays
  `failed`; conflicts fail with `PERSISTENCE_INVALID`.
- `persist_side_effect_attempt` raises `WorkflowError(PUBLISH_RECONCILE_REQUIRED)`
  instead of `ValueError`.
- Materialization rows record `size` and `mtime_ns`; `recover_artifacts` stats
  first and hashes only on mismatch; hash drift rebuilds and emits
  `artifact.materialization outcome=drift_repaired`.
- `materialize_compatibility_artifacts` reads snapshot and evidence in one read transaction.

## F5 — Stable persistence reason codes (035c)

- `output_session_error(exc, repo, pr_number)` in `src/gh_address_cr/commands/common.py`
  preserves `reason_code`, adds `retryable`, and sets a deterministic `next_action`.
  Handlers in `commands/agent.py` and `commands/high_level.py` catch
  `session_store.SessionError` before their catch-all. Exit code stays 5.
- `side_effect_outbox.py` wraps `RuntimeStoreError` into `SessionError` using the
  same mapping as `core/session.py`.
- Convert `leases.release_claimed_lease`, `leases.reclaim_leases`, and agent
  submit/accept to `transact_session` closures. The publisher keeps CAS because an
  external call cannot sit inside a write transaction; after F4, rerunning
  publish on `STALE_REVISION` is safe because `succeeded` outbox rows short-circuit.
- Add the codes to `src/gh_address_cr/core/protocol_codes.py`, a "Runtime
  Persistence" section to `skill/references/status-action-map.md`, and matching
  text in `skill/references/agent-protocol.md` and `skill/SKILL.md`.

## F6 — Database-enforced invariants (035b, schema v2)

- Document `payload_json` as per-row truth and normalized columns as same-transaction index projections.
- `CREATE UNIQUE INDEX leases_one_active_per_item ON leases(session_id, item_id) WHERE status IN ('active','submitted')`;
  violations map to `PersistenceInvalidError` and roll back. Existing violating
  data fails the v2 migration with a diagnostic.
- `transact` writes a UUID `transaction_id` to its evidence and outbox rows.
- `last_observed_revision` changes only when the item payload changes (single
  query shared with `first_observed_revision`).
- Minimal migration framework: `_MIGRATIONS = {1: _migrate_v1_to_v2}` executed
  under `BEGIN EXCLUSIVE`, recorded in `migration_history`; `SCHEMA_VERSION = 2`.

## F7 — Orchestrator dispatch rebuild (035d)

- `DispatchReceipt.delivery_token` comes from the canonical lease `resume_token`;
  receipts become `dispatch-receipt.v2`; v1 receipts are revalidated.
- `reconcile_dispatches` also rebuilds receipts for `orchestrator:{run_id}` leases
  that are `active`/`submitted` but have no dispatch; the reconcile event adds a bounded `rebuilt` count.
- `validate_dispatch` keeps only token match and lease existence; status, expiry,
  and request binding belong to core submit policy.
- `handle_step` catches known exceptions after `issue_action_request`, releases
  the claim via `leases.release_claimed_lease(..., reason="dispatch_projection_failed")`,
  and returns `DISPATCH_PROJECTION_FAILED`.

## Performance and Observability

### Verified baseline gaps

- OTel exports traces only (no metrics). Persistence emits span events with a
  single `contention` bucket measured from transaction start, mixing lock wait
  and execution; materialization, recovery, and migration have no timing.
- Local efficiency reporting (`ExecutionMetric` → `telemetry_reporting.py` →
  final-gate completion line) flags only operations over 60 s
  (`MAX_DURATION_SECONDS`) or error rates over 20%.
- `cr_metrics` per-CR spans come from evidence timestamps and mostly measure agent think time.
- Spec 034 already grows per-write cost with session size (full row rewrite plus
  full `evidence.jsonl` rewrite per commit).

### Per-change cost review

| Change | Per-command effect |
|---|---|
| F3 read-only load | Faster: reads stop taking the write lock |
| F3 liveness probe | Only when `in_flight` rows exist; one non-blocking lock per row |
| F4 outbox lookup | Faster: indexed query replaces 2–3 JSONL scans per item |
| F4 drift detection | stat fast path; hash only on size/mtime mismatch |
| F2 fsync | One-time, recovery bundle only |
| F5 transactional hot paths | Fewer whole-command reruns on `STALE_REVISION`; closures must not do IO |
| F6 index and revision tracking | Negligible |
| P2 spans | No-op when telemetry is disabled; ≤ 5% overhead budget |

### P1 — Benchmark and baselines (035a)

`scripts/benchmark_runtime_store.py`, structured like
`scripts/benchmark_telemetry_grouping.py` (JSON output, warmups, median of samples):

- Profiles S / M / L: items 50 / 300 / 1000; evidence 200 / 3000 / 20000.
- Operations: `load_session`, claim, submit, publish (fake GitHub client), materialize, migration.
- Simulated CR loop: next → submit → publish for every item; reports per-CR p50/p90
  and the degradation ratio (last-decile median ÷ first-decile median).
- Baselines recorded in `validation.md` for `main` (v3.15.3) and `develop` (Spec 034).

### P2 — Persistence spans (035b)

Child spans via `start_child_span` (INTERNAL): `gh_address_cr.persistence.transaction`,
`.materialize`, `.recover`, `.migrate`. Bounded attributes: operation, outcome,
`lock_wait_ms`, `execute_ms`, `items_bucket`, `evidence_bucket`
(0, 1–10, 11–100, 101–1000, 1000+). Per-command `persistence_ms` and
`lock_wait_ms` are added to `ExecutionMetric` as additive fields.

### P3 — Incremental projection (035b)

`evidence.jsonl` is append-only in the database, so materialization records the
last written `sequence` and appends only new rows; full rebuild happens only on
drift or a missing file. Bytes are identical to a full rewrite, so the projection
contract is unchanged; per-write cost becomes O(new events).

### P4 — Regression detection (035d)

`telemetry_reporting.py` orders the session's `ExecutionMetric`s per command
type and compares first-20% and last-20% medians; a ratio above 2 with at least
10 samples adds `"<command> latency grew Nx over this session"` to the
inefficiency flags, which appear in the final-gate completion line. The report
also shows per-command p50/p90 and `persistence_ms` share.

### Budgets

| Metric | Budget | Where checked |
|---|---|---|
| Per-command p90 (M) | ≤ 1.2× develop baseline and ≤ 1.5× main baseline | Full benchmark in PR description |
| CR-loop degradation ratio (L) | ≤ 1.5 from 035b | Full benchmark + CI smoke |
| `load_session` without `in_flight` rows | No write transaction | Contract test |
| Telemetry on vs off | ≤ 5% overhead | Full benchmark |
| Mutation closures | No file or network IO | Contract test (patched `open` / client) |

CI runs only the S profile and checks output shape and self-relative ratios, not
absolute milliseconds, to avoid runner noise.

## Risks and Trade-offs

- Advisory locks are unreliable on network filesystems; consistent with Spec 034 FR-013.
- The publisher keeps CAS; F4's outbox short-circuit makes reruns safe.
- Reading normalized columns as truth is deferred: low value, high risk.
- New mechanisms run only when there is work to do; the common path gets shorter.
  The benchmark and P4 detection prove this with data rather than inference.
