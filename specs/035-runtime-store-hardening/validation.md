# Validation: Runtime Store Hardening

**Date**: 2026-09-26
**Scope**: Audit evidence and acceptance plan. No implementation has landed.

## Audit Baseline

- Audited range: `origin/main` (`b7d6d1c`, v3.15.3) → `origin/develop` (`4ba50e6`), 17 commits,
  71 files, +8859/−590.
- CI on the develop head (lint-and-test 3.10/3.13, CodeQL) was green; the defects
  below are outside what the existing suites exercise.

## Reproductions (to become permanent contract tests)

| ID | Scenario | Observed on `4ba50e6` | Regression test |
|---|---|---|---|
| R1 | `write_json_atomic` fails before the bundle manifest is written | Every later `open_or_migrate` fails: `PERSISTENCE_INVALID: Legacy recovery bundle integrity check failed` | `test_crash_at_every_bundle_checkpoint_recovers` |
| R2 | Writer A initializes and commits revision 2 inside writer B's exists→replace window | Store reads revision 1; A's commit is lost | `test_concurrent_bootstrap_never_clobbers_committed_revision` |
| R3 | 8 processes run `open_or_migrate` on one legacy workspace, 5 trials | 1–6 successes per trial; bare `FileExistsError` and `PERSISTENCE_INVALID` | `test_concurrent_legacy_migration_is_exactly_once` |
| R4 | A command is `in_flight`; another process calls `recover()` as `load_session` does | Status becomes `unknown` while the executor is alive | `test_load_does_not_demote_live_in_flight_command` |
| R5 | A succeeded reply is committed and materialized; `evidence.jsonl` is truncated | `recover_artifacts` repairs 0 files; `successful_side_effect_url` returns `None` while SQLite holds the record | `test_publish_decisions_ignore_projection_tampering` |

## Spec 034 Requirement Status

| Requirement | Before 035 | Owning 035 PR | After 035 |
|---|---|---|---|
| SC-001 one winner under claim race | ✅ | — | |
| FR-003 serialized claims | ✅ | — | |
| SC-004 no independent orchestrator lease policy | ✅ (mostly) | 035d | |
| SC-002 old or complete revision after any crash | ⚠️ migration path fails (R1) | 035a | |
| SC-003 idempotent migration/recovery replay | ⚠️ not under concurrency (R3) | 035a | |
| FR-007 outbox truth | ⚠️ `unknown` misclassified (R4) | 035b | |
| FR-008 projections are not truth | ❌ publisher reads JSONL (R5) | 035b | |
| FR-009 exactly-once exclusive migration | ❌ (R2, R3) | 035a | |
| FR-014 stable bounded-contention outcome | ⚠️ codes flattened at CLI | 035c | |
| US-C2 dispatch rebuilt after restart | ⚠️ prune only | 035d | |

## Performance Baseline

Preliminary measurement on `4ba50e6` (one transaction plus full materialization,
median of 20):

| Items | Evidence rows | ms per write |
|---|---|---|
| 50 | 200 | 21.4 |
| 300 | 3000 | 57.8 |

Full P1 baselines (`main` and `develop`, profiles S/M/L, CR-loop degradation
ratio) are recorded here by task A003 before any runtime change.

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
