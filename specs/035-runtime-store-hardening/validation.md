# Validation: Runtime Store Hardening

**Date**: 2026-09-26
**Scope**: Audit evidence, acceptance plan, and 035a results.

## Audit Baseline

- Audited range: `origin/main` (`b7d6d1c`, v3.15.3) → `origin/develop` (`4ba50e6`), 17 commits,
  71 files, +8859/−590.
- CI on the develop head (lint-and-test 3.10/3.13, CodeQL) was green; the defects
  below are outside what the existing suites exercise.

## Reproductions (to become permanent contract tests)

| ID | Scenario | Observed on `4ba50e6` | Regression test |
|---|---|---|---|
| R1 | `write_json_atomic` fails before the bundle manifest is written | Every later `open_or_migrate` fails: `PERSISTENCE_INVALID: Legacy recovery bundle integrity check failed` | `test_crash_at_every_bundle_checkpoint_recovers` |
| R2 | Writer A initializes and commits revision 2 inside writer B's exists→replace window | Store reads revision 1; A's commit is lost | `test_late_initializer_cannot_replace_committed_store` |
| R3 | 8 processes run `open_or_migrate` on one legacy workspace, 5 trials | 1–6 successes per trial; bare `FileExistsError` and `PERSISTENCE_INVALID` | `test_concurrent_legacy_migration_is_exactly_once` |
| R4 | A command is `in_flight`; another process calls `recover()` as `load_session` does | Status becomes `unknown` while the executor is alive | `test_load_does_not_demote_live_in_flight_command` |
| R5 | A succeeded reply is committed and materialized; `evidence.jsonl` is truncated | `recover_artifacts` repairs 0 files; `successful_side_effect_url` returns `None` while SQLite holds the record | `test_publish_decisions_ignore_projection_tampering` |

## Spec 034 Requirement Status

| Requirement | Before 035 | Owning 035 PR | After 035 |
|---|---|---|---|
| SC-001 one winner under claim race | ✅ | — | |
| FR-003 serialized claims | ✅ | — | |
| SC-004 no independent orchestrator lease policy | ✅ (mostly) | 035d | |
| SC-002 old or complete revision after any crash | ⚠️ migration path fails (R1) | 035a | ✅ initialization and bundle checkpoints (035a); outbox checkpoints re-verified in 035b |
| SC-003 idempotent migration/recovery replay | ⚠️ not under concurrency (R3) | 035a | ✅ (035a) |
| FR-007 outbox truth | ⚠️ `unknown` misclassified (R4) | 035b | |
| FR-008 projections are not truth | ❌ publisher reads JSONL (R5) | 035b | |
| FR-009 exactly-once exclusive migration | ❌ (R2, R3) | 035a | ✅ (035a) |
| FR-014 stable bounded-contention outcome | ⚠️ codes flattened at CLI | 035c | |
| US-C2 dispatch rebuilt after restart | ⚠️ prune only | 035d | |

## Performance Baseline

`scripts/benchmark_runtime_store.py --profile M --profile L --json`, CPython
3.11.15, same container for all three runs, seeded from identical legacy JSON
state. `main` is `b7d6d1c` (v3.15.3, JSON store); `develop` is `b9a50b3`
(Spec 034 SQLite store); 035a is `fix/035a-atomic-store-init`.

Per-CR latency is classify + next + submit for one local finding. Degradation
ratio is last-decile ÷ first-decile per-CR median.

| Profile | Build | First load (migration) | CR p50 | CR p90 | Degradation ratio | `load_session` p50 before → after loop |
|---|---|---|---|---|---|---|
| M (300 items, 3000 evidence) | main | 36 ms | 67 ms | 100 ms | 4.26 | 0.6 → 5.6 ms |
| M | develop (034) | 4053 ms | 458 ms | 608 ms | 1.99 | 7.7 → 23.2 ms |
| M | 035a | **348 ms** | 428 ms | 568 ms | 2.02 | 7.9 → 21.6 ms |
| L (1000 items, 20000 evidence) | main | 3 ms | 234 ms | 372 ms | 5.50 | 2.1 → 23.5 ms |
| L | develop (034) | 30908 ms | 1809 ms | 2329 ms | 1.95 | 29.4 → 91.9 ms |
| L | 035a | **1204 ms** | 1827 ms | 2490 ms | 2.17 | 36.1 → 87.3 ms |

### Findings

1. **Spec 034 regressed per-CR latency 6.8× (M) to 7.7× (L) against `main`.**
   Profiling 10 CRs at M on `develop`: `materialize_compatibility_artifacts`
   takes 64% of the time — every CR rewrites the whole `evidence.jsonl` three
   times and JSON-decodes every canonical evidence row to do it. This is the
   P3 (incremental projection) target in 035b.
2. **Spec 034 first-open migration took 4.1 s (M) and 30.9 s (L)** — longer
   than the 5 s default busy timeout, so peers opening the session during an
   upgrade would receive `PERSISTENCE_BUSY`. Root cause: `_create_schema` used
   `executescript`, which commits the open transaction, so every subsequent
   row insert ran in autocommit mode with its own journal sync. 035a creates
   the schema statement by statement inside the exclusive transaction:
   migration is now 12× (M) and 26× (L) faster and atomic.
3. **`main` already slowed down within a session** (degradation ratio 4.3–5.5:
   the whole `session.json` grows and is rewritten per write). Spec 034 lowered
   the ratio to ~2 by raising the constant cost; neither meets the 1.5 target.
4. 035a steady-state per-CR cost is within noise of `develop`
   (p90 0.93× at M, 1.07× at L), meeting the ≤ 1.2× develop budget.

### Budget status after 035a

| Budget | Status |
|---|---|
| Per-command p90 ≤ 1.2× develop | ✅ M 0.93×, L 1.07× |
| Per-command p90 ≤ 1.5× main | ❌ M 5.7×, L 6.7× — inherited from 034; owned by 035b P3 |
| Degradation ratio ≤ 1.5 (from 035b) | ❌ 2.0–2.2 — owned by 035b P3 |
| First-open migration below the 5 s busy timeout | ✅ M 0.35 s, L 1.2 s (was 4.1 s, 30.9 s) |

## 035a Regression Evidence

`tests/contract/test_runtime_store_init_contract.py` on the pre-fix code
(`b9a50b3` runtime with the new tests): `FAILED (failures=13, errors=6)` across
all 8 tests. After the fix: `OK`, repeated 3 times.

| Reproduction | Test | Pre-fix result |
|---|---|---|
| R1 | `test_crash_at_every_bundle_checkpoint_recovers` | every checkpoint fails (stranded bundle or missing API) |
| R2 | `test_late_initializer_cannot_replace_committed_store` | `AssertionError: 1 != 2` — the committed revision was replaced |
| R3 | `test_concurrent_legacy_migration_is_exactly_once` | 9–11 of 20 rounds fail per run with bare `FileExistsError` / `PERSISTENCE_INVALID` |
| — | `test_concurrent_bootstrap_never_clobbers_committed_revision` | passed pre-fix (the R2 window is too narrow for a free-running race); kept as a 32-process concurrency guard |
| FR-003 | `test_save_session_refuses_to_bootstrap_over_legacy_session` | `SessionError not raised` |

## 035a Gates

| Gate | Result |
|---|---|
| `ruff check src tests scripts/build_plugin_payload.py scripts/benchmark_runtime_store.py` | Passed |
| `python3 -m unittest discover -s tests` | 1230 tests; 1 error in `test_stacked_pr_e2e_script` (`GitHub CLI is required.`) — the container has no `gh`; the same test fails identically on unmodified `develop` |
| `python3 -m gh_address_cr --help` / `agent manifest` | Passed |
| `build_plugin_payload.py --output` / `--check` | Passed |
| `final-gate` | Not run: no PR session exists yet for this branch |

## Required Gates Per PR

- `pip install -e .`
- `ruff check src tests scripts/build_plugin_payload.py`
- `python3 -m unittest discover -s tests`
- `python3 -m gh_address_cr --help`
- `python3 -m gh_address_cr agent manifest`
- `python3 scripts/build_plugin_payload.py --output dist/plugin/gh-address-cr`
- `python3 scripts/build_plugin_payload.py --check`
- `python3 scripts/benchmark_runtime_store.py --profile M --json` compared with the baselines above
- `final-gate` on the PR session with the compact metrics line
