# Validation: Transactional Lease Runtime Architecture

**Date**: 2026-09-24
**Scope**: Architecture artifacts only; no Phase A/B/C implementation

## Current-State Evidence

- GitHub repository default branch: `main`.
- Current task base: `origin/develop` at `9bdab3006231da2af3dfe2550295088c127e59a9`.
- PR #285: `MERGED`, base `develop`, merged at 2026-09-24T09:02:33Z.
- Starting `main`: `b7d6d1c`, tag `v3.15.3`; it did not contain Spec 033.
- Spec 033 FR-009 and its required follow-up explicitly exclude cross-process
  atomicity and session/ledger crash consistency.
- Current session persistence uses atomic JSON replacement without a surrounding
  cross-process revision/lock transaction.
- Current evidence persistence appends JSONL independently.
- Current shadow leases are persisted in `orchestration.json` and apply a separate
  context-key conflict, TTL, token, and release policy.

## Architecture Consistency Review

- One authoritative owner is named after migration.
- Typed inputs, canonical tables, projections, policy tables, transaction/CAS
  boundary, outbox, artifact truth, telemetry, recovery/replay, and orchestrator
  ownership are all defined.
- Persistence options cover current-runtime fit, migration cost, concurrency,
  crash recovery, testability, compatibility, and long-term complexity.
- A/B/C are one dependency chain with explicit owning branches and completion
  criteria; none may be implemented as an independent local patch.
- In-place downgrade, dual-primary operation, hidden fallback, and artifact-backed
  truth are explicitly rejected.
- The open implementation blocker is governance approval, not an unresolved
  persistence choice.

## Executed Checks

| Check | Result |
|---|---|
| `pip install -e .` | Passed after filesystem approval; installed current checkout as 3.15.2 |
| `ruff check src tests scripts/build_plugin_payload.py` | Passed |
| `PYTHONPATH=src GH_ADDRESS_CR_STATE_DIR=/private/tmp/gh-address-cr-034-tests python3 -m unittest discover -s tests` | Passed: 1182 tests in 453.074s |
| `python3 -m gh_address_cr --help` | Passed |
| `python3 -m gh_address_cr agent manifest` | Passed; `MANIFEST_READY` |
| `python3 scripts/build_plugin_payload.py --output dist/plugin/gh-address-cr` | Passed |
| `python3 scripts/build_plugin_payload.py --check` | Passed |

## Environment Correction

The first full-suite attempt failed with seven permission errors because the
existing editable installation resolved modules from another checkout and tests
used the sandbox-external default state directory. That run is not counted as a
code failure. The repeated suite explicitly bound `PYTHONPATH=src` to this
worktree and used a writable isolated state directory; it completed with `OK`.

## Not Run

- `final-gate`: no target PR session exists for this documentation-only task.
  Each implementation layer requires its own affected PR-session final-gate and
  compact completion evidence before completion.
- Live crash/race acceptance: these are Phase A/B executable implementation
  gates, not claims made by this architecture-only change.
