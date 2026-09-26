# Tasks: Runtime Store Hardening

**Input**: [spec.md](./spec.md), [plan.md](./plan.md)

**Rule for every regression test marked (R#)**: it MUST fail on the pre-fix
commit and pass after the fix; paste both outputs in the PR description.

## 035a — Atomic initialization, recovery bundle, benchmark baseline

**Owning branch**: `fix/035a-atomic-store-init` (base `develop`)

- [x] A001 Land this spec; set Spec 034 status to "Superseded in part by 035".
- [x] A002 Add `scripts/benchmark_runtime_store.py` (profiles S/M/L, CR-loop
  degradation ratio) and `tests/test_runtime_store_benchmark.py` (S smoke).
- [x] A003 Record `main` and `develop` baselines in `validation.md` before any runtime change.
- [x] A004 Write failing tests in `tests/contract/test_runtime_store_init_contract.py`:
  `test_late_initializer_cannot_replace_committed_store` (R2),
  `test_concurrent_bootstrap_never_clobbers_committed_revision`,
  `test_concurrent_legacy_migration_is_exactly_once` (R3),
  `test_crash_inside_initialize_leaves_uninitialized_store_that_retries_cleanly`,
  `test_save_session_refuses_to_bootstrap_over_legacy_session`,
  `test_crash_at_every_bundle_checkpoint_recovers` (R1),
  `test_tampered_complete_bundle_still_fails_fast`,
  `test_incomplete_bundle_quarantine_emits_bounded_event`.
- [x] A005 Implement in-place `_initialize` behind `bootstrap` / `open_or_migrate`, plus
  `is_initialized`; remove temp-db publication.
- [x] A006 Route `core/session.py` load/save/transact through `is_initialized`; enforce FR-003.
- [x] A007 Implement atomic bundle build, `write_json_durable`, and deterministic quarantine.
- [x] A008 Run completion gates, benchmark M profile, and compare with A003
  (final-gate pending a PR session; see validation.md).

## 035b — Outbox ownership, outbox authority, schema v2, persistence spans

**Owning branch**: `fix/035b-outbox-ownership` (base 035a)

- [ ] B001 Write failing tests: `test_load_does_not_demote_live_in_flight_command` (R4),
  `test_owner_death_demotes_to_unknown`, `test_concurrent_publish_same_item_posts_once`,
  `test_read_only_load_takes_no_write_lock`,
  `test_publish_decisions_ignore_projection_tampering` (R5),
  `test_v2_migration_backfills_outbox_from_legacy_side_effect_evidence`,
  `test_projection_drift_is_repaired_from_canonical_state`,
  `test_materialized_meta_revision_matches_content_under_concurrent_writes`,
  `test_db_rejects_second_active_lease_for_item_without_bricking_store`,
  `test_v1_store_upgrades_to_v2_exactly_once_under_concurrency`,
  `test_transaction_id_is_shared_by_events_and_outbox_of_one_commit`,
  `test_last_observed_revision_changes_only_with_item_payload`.
- [ ] B002 Schema v2 and migration framework (`_MIGRATIONS`, `SCHEMA_VERSION = 2`).
- [ ] B003 `core/process_lock.py`, outbox owner columns, liveness-aware `recover()`.
- [ ] B004 `execute_side_effect` / `side_effect_state`; switch publisher; remove ledger read helpers.
- [ ] B005 Shared outbox backfill for legacy import and v1→v2.
- [ ] B006 Stat-fast-path drift detection; single-read-transaction materialization.
- [ ] B007 Partial unique index, `transaction_id`, `last_observed_revision` semantics.
- [ ] B008 P2 persistence child spans and `ExecutionMetric` additive fields; privacy and fail-open tests.
- [ ] B009 P3 incremental `evidence.jsonl` append with byte-equivalence test against full rebuild.
- [ ] B010 Update `tests/contract/test_publish_precondition_and_status_contract.py` for outbox reads.
- [ ] B011 Upgrade end-to-end: `v3.15.3` state with published replies → this branch; no duplicate
  side effects, unchanged final-gate. Repeat from a Spec 034 v1 store.
- [ ] B012 Completion gates; benchmark M and L; degradation ratio ≤ 1.5.

## 035c — Persistence reason codes and transactional hot paths

**Owning branch**: `fix/035c-persistence-reason-codes` (base 035b)

- [ ] C001 Write failing tests: `test_persistence_reason_codes_reach_agent_output`,
  `test_concurrent_reclaim_and_release_do_not_surface_stale_revision`,
  mutation-closure no-IO guard.
- [ ] C002 `output_session_error`; `SessionError` handlers in `commands/agent.py` and `commands/high_level.py`.
- [ ] C003 Wrap `RuntimeStoreError` in `side_effect_outbox.py`.
- [ ] C004 Convert `release_claimed_lease`, `reclaim_leases`, agent submit/accept to `transact_session`.
- [ ] C005 Add codes to `protocol_codes.py`; "Runtime Persistence" section in
  `skill/references/status-action-map.md`; sync `agent-protocol.md` and `SKILL.md`.
- [ ] C006 `tests/test_skill_docs.py` asserts every persistence code has a map entry;
  update `tests/contract/test_public_contract_stability.py` for the additive `retryable` field.
- [ ] C007 Completion gates; benchmark M.

## 035d — Orchestrator dispatch rebuild and regression detection

**Owning branch**: `fix/035d-orchestrator-dispatch-rebuild` (base 035c)

- [ ] D001 Replace source-text assertions in
  `tests/contract/test_orchestrator_lease_convergence_contract.py` with behavior tests:
  `test_restart_rebuilds_dispatch_from_canonical_lease`,
  `test_two_non_overlapping_hunks_dispatch_without_second_grant`,
  `test_post_claim_failure_releases_canonical_lease`,
  `test_expired_canonical_lease_rejects_stale_dispatch_submit`.
- [ ] D002 `dispatch-receipt.v2` token from `resume_token`; rebuild in `reconcile_dispatches`.
- [ ] D003 Narrow `validate_dispatch`; `DISPATCH_PROJECTION_FAILED` with claim release in `handle_step`.
- [ ] D004 P4 within-session latency growth flag and per-command p50/p90 in `telemetry_reporting.py`.
- [ ] D005 Completion gates; benchmark M; final Spec 034 FR/SC table all ✅ in `validation.md`.

## Release Gate

- [ ] G001 035a merged to `develop` (035b recommended) before
  [RbBtSn0w/gh-address-cr#289](https://github.com/RbBtSn0w/gh-address-cr/pull/289) merges.
- [ ] G002 Each PR's session runs `final-gate` and records the compact metrics line.
