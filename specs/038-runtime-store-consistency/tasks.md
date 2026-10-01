# Tasks: Runtime Store Consistency Fixes

Each fix task follows a RED contract test of its own. Tests live in
`tests/contract/test_runtime_store_consistency_contract.py` unless noted.

## Phase 1 — Revision token forwarding

- [ ] T001 RED: a commit made by another process while publish's GitHub call is
      in progress (a lease claim or item edit) survives the publish.
- [ ] T002 RED: a publish replay after `STALE_REVISION` performs zero new
      `post_reply` / `resolve_thread` calls.
- [ ] T003 Store outbox transitions return `OutboxCommit(base_revision, revision)`.
      The `in_flight` transition commits its attempt evidence.
- [ ] T004 `side_effect_outbox` advances the token only across contiguous
      commits. `recover()` reports its commit so `side_effect_state` applies the
      same rule.
- [ ] T005 Wrap the publish entry in `retry_on_stale_revision` and widen its
      documented contract.

## Phase 2 — Evidence commit boundary

- [ ] T006 RED: a fresh claim commits `request_issued` with the lease.
- [ ] T007 RED: a batch claim commits `classification_recorded` and
      `request_issued`.
- [ ] T008 RED: a forged `evidence.jsonl` line is never restored as a
      classification.
- [ ] T009 Append claim and batch evidence inside the transaction.
- [ ] T010 `SessionEvidenceLedger.load` reads canonical rows plus the pending
      buffer.
- [ ] T011 Audit every `_ledger(` / `get_session_ledger(` append site for a
      persist of the same dict.

## Phase 3 — Re-check under lock

- [ ] T012 RED: `recover()` does not demote a command re-marked by a live owner.
- [ ] T013 RED: a claim preserves metadata keys written concurrently.
- [ ] T014 Make `recover()` demote per row, guarded by `owner_token`.
- [ ] T015 Make claims apply a metadata delta instead of replacing the whole
      object.

## Phase 4 — Error mapping

- [ ] T016 RED: a locked store yields `PERSISTENCE_BUSY` from load and from
      outbox transitions (small `busy_timeout_ms`).
- [ ] T017 RED: the gate re-raises a non-`SESSION_NOT_FOUND` `SessionError`.
      final-gate keeps the reason code and `retryable`.
- [ ] T018 RED: `load_session` does not wait for the busy timeout while
      another writer holds the lock.
- [ ] T019 Add store-wide busy translation, with `_validate_schema` checking
      busy first.
- [ ] T020 Narrow the gate's catch. final-gate maps `SessionError` and reruns
      on stale.
- [ ] T021 Make projection repair on read opportunistic.

## Phase 5 — Migration authority

- [ ] T022 RED: a failed legacy import followed by a corrected retry migrates
      successfully. The superseded bundle is kept.
- [ ] T023 RED: a malformed legacy item fails with `PERSISTENCE_INVALID`.
- [ ] T024 Set the uncommitted bundle aside and rebuild it. Validate legacy
      shapes.

## Phase 6 — Boundary contracts

- [ ] T025 RED and fix: a dev-preview runtime satisfies the minimum, and
      `3.15.9` does not.
- [ ] T026 RED and fix: submitting against a `1.0` request fails with
      `PROTOCOL_VERSION_INCOMPATIBLE`. Re-entry rebuilds the request at
      protocol 1.1 and updates the lease hash.
- [ ] T027 RED and fix: batch re-entry recomputes `request_hash` after a
      rebuild.
- [ ] T028 RED and fix: a naive lease timestamp expires without a `TypeError`.
- [ ] T029 RED and fix: an item verified before it was addressed is excluded,
      not a crash.
- [ ] T030 RED and fix: the final-gate archive uses the SQLite backup API.

## Phase 7 — Contracts and verification

- [ ] T031 Update `evidence-ledger.md`, `agent-protocol.md` and
      `status-action-map.md`, and amend Spec 033 FR-004.
- [ ] T032 Run the full AGENTS.md verification set.
- [ ] T033 Rerun every review probe.
