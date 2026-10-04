> Archived design reference. Current code, tests, and `AGENTS.md` govern
> execution; historical delivery status and commands are not active instructions.

# Plan: Runtime Store Consistency Fixes (3.16.0 release blockers)

**Branch:** `fix/runtime-store-consistency`
**Decision record:** [`adr-001-revision-token-and-commit-boundaries.md`](adr-001-revision-token-and-commit-boundaries.md)
**Source:** the 3.16.0 release review of `origin/main...origin/develop`. It verified 15 findings, plus one legacy-shape crash found by the gap sweep.

## Goal

Make the transactional runtime keep the guarantees Spec 034 promised before
3.16.0 ships. The legacy-to-SQLite migration is one-way, so these defects
cannot be fixed after users upgrade.

1. A whole-session save can never overwrite a commit it did not observe.
2. Every ledger event is committed with the state change it describes.
3. No projection file is read back as runtime input.
4. Each persistence failure surfaces as its documented reason code, with
   `retryable` set correctly.

## Approach

Test-first. Each finding becomes a failing contract test, converted from its
review probe, before the fix lands. Commits are grouped by root cause, in
dependency order:

| Phase | Root cause | Findings | Main files |
|---|---|---|---|
| 1 | Revision token forwarding (D1, D2) | publisher lost update, `_begin_attempt` split | `core/runtime_store.py`, `core/side_effect_outbox.py`, `core/session.py`, `core/publisher.py`, `commands/*publish*` |
| 2 | Evidence after commit, projection as truth (D3, D4) | `request_issued` and batch evidence dropped, `evidence.jsonl` read as truth | `core/agent_protocol.py`, `core/agent_batch.py`, `evidence/ledger.py`, `core/utils.py` |
| 3 | Re-check under lock (D5) | `recover()` TOCTOU, metadata clobber | `core/runtime_store.py`, `core/agent_protocol.py`, `core/agent_batch.py` |
| 4 | Error mapping (D6, D9) | raw busy errors, gate catch-all, final-gate stale, load blocking under write lock | `core/runtime_store.py`, `core/gate.py`, `commands/final_gate.py`, `core/session.py` |
| 5 | Authority after commit (D7) | migration bundle bricking, legacy shape `AttributeError` | `core/runtime_store.py` |
| 6 | Boundary contracts (D8) | dev-preview minimum, protocol 1.0, naive timestamps, batch re-entry hash, lifecycle ordering, live SQLite archive | `core/workflow.py`, `core/agent_protocol*.py`, `core/agent_batch.py`, `core/runtime_store.py`, `core/cr_metrics.py`, `commands/final_gate.py` |
| 7 | Docs and contracts | evidence-ledger meaning, protocol/upgrade note, status-action map, Spec 033 FR-004 | `skill/references/*.md`, `docs/rfcs/033-*/spec.md` |

## Verification

Run the AGENTS.md gate set, in this order:

1. `ruff check src tests scripts/build_plugin_payload.py`
2. `python3 scripts/check_mypy_ratchet.py`
3. `python3 -m unittest discover -s tests`
4. `python3 -m gh_address_cr --help`
5. `python3 -m gh_address_cr agent manifest`
6. `python3 scripts/build_plugin_payload.py --check`

Then rerun every review probe from the scratchpad as a final regression check.
Every probe must report the corrected behavior.

## Out of scope (recorded in the ADR)

These stay out of this branch so its blast radius stays at the release-blocker
level:

- per-item publisher transactions (Option C);
- read-path `BEGIN` / WAL;
- O(N²) publish decode, the `lease_events` full rewrite, and empty-mutation commits;
- orchestrator v1 token mapping;
- Windows `fsync`, lock-file cleanup, and coarse-mtime drift detection.
