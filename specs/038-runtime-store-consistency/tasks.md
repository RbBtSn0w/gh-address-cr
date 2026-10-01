# Tasks: Runtime Store Consistency Fixes

Each fix task follows a RED contract test of its own. Tests live in
`tests/contract/test_runtime_store_consistency_contract.py` unless noted.

## Phase 1 — Revision token forwarding

- [x] T001 RED: a commit made by another process while publish's GitHub call is
      in progress (a lease claim or item edit) survives the publish.
- [x] T002 RED: a publish replay after `STALE_REVISION` performs zero new
      `post_reply` / `resolve_thread` calls.
- [x] T003 Store outbox transitions return `OutboxCommit(base_revision, revision)`.
      The `in_flight` transition commits its attempt evidence.
- [x] T004 `side_effect_outbox` advances the token only across contiguous
      commits. `recover()` reports its commit so `side_effect_state` applies the
      same rule.
- [x] T005 Wrap the publish entry in `retry_on_stale_revision` and widen its
      documented contract.

## Phase 2 — Evidence commit boundary

- [x] T006 RED: a fresh claim commits `request_issued` with the lease.
- [x] T007 RED: a batch claim commits `classification_recorded` and
      `request_issued`.
- [x] T008 RED: a forged `evidence.jsonl` line is never restored as a
      classification.
- [x] T009 Append claim and batch evidence inside the transaction.
- [x] T010 `SessionEvidenceLedger.load` reads canonical rows plus the pending
      buffer.
- [x] T011 Audit every `_ledger(` / `get_session_ledger(` append site for a
      persist of the same dict.

## Phase 3 — Re-check under lock

- [x] T012 RED: `recover()` does not demote a command re-marked by a live owner.
- [x] T013 RED: a claim preserves metadata keys written concurrently.
- [x] T014 Make `recover()` demote per row, guarded by `owner_token`.
- [x] T015 Make claims apply a metadata delta instead of replacing the whole
      object.

## Phase 4 — Error mapping

- [x] T016 RED: a locked store yields `PERSISTENCE_BUSY` from load and from
      outbox transitions (small `busy_timeout_ms`).
- [x] T017 RED: the gate re-raises a non-`SESSION_NOT_FOUND` `SessionError`.
      final-gate keeps the reason code and `retryable`.
- [x] T018 RED: `load_session` does not wait for the busy timeout while
      another writer holds the lock.
- [x] T019 Add store-wide busy translation, with `_validate_schema` checking
      busy first.
- [x] T020 Narrow the gate's catch. final-gate maps `SessionError` and reruns
      on stale.
- [x] T021 Make projection repair on read opportunistic.

## Phase 5 — Migration authority

- [x] T022 RED: a failed legacy import followed by a corrected retry migrates
      successfully. The superseded bundle is kept.
- [x] T023 RED: a malformed legacy item fails with `PERSISTENCE_INVALID`.
- [x] T024 Set the uncommitted bundle aside and rebuild it. Validate legacy
      shapes.

## Phase 6 — Boundary contracts

- [x] T025 RED and fix: a dev-preview runtime satisfies the minimum, and
      `3.15.9` does not.
- [x] T026 RED and fix: submitting against a `1.0` request fails with
      `PROTOCOL_VERSION_INCOMPATIBLE`. Re-entry rebuilds the request at
      protocol 1.1 and updates the lease hash.
- [x] T027 RED and fix: batch re-entry recomputes `request_hash` after a
      rebuild.
- [x] T028 RED and fix: a naive lease timestamp expires without a `TypeError`.
- [x] T029 RED and fix: an item verified before it was addressed is excluded,
      not a crash.
- [x] T030 RED and fix: the final-gate archive uses the SQLite backup API.

## Phase 7 — Contracts and verification

- [x] T031 Update `evidence-ledger.md`, `agent-protocol.md` and
      `status-action-map.md`, and amend Spec 033 FR-004.
- [x] T032 Run the full AGENTS.md verification set.
- [x] T033 Rerun every review probe.
