# Validation: Runtime Store Hardening

**Date**: 2026-09-26
**Scope**: Audit evidence, acceptance plan, and 035a–035d results.

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
| SC-001 one winner under claim race | ✅ | — | ✅ |
| FR-003 serialized claims | ✅ | — | ✅ |
| SC-004 no independent orchestrator lease policy | ✅ (mostly) | 035d | ✅ (035d) |
| SC-002 old or complete revision after any crash | ⚠️ migration path fails (R1) | 035a | ✅ initialization and bundle checkpoints (035a); outbox and projection checkpoints (035b) |
| SC-003 idempotent migration/recovery replay | ⚠️ not under concurrency (R3) | 035a | ✅ (035a) |
| FR-007 outbox truth | ⚠️ `unknown` misclassified (R4) | 035b | ✅ (035b) |
| FR-008 projections are not truth | ❌ publisher reads JSONL (R5) | 035b | ✅ (035b) |
| FR-009 exactly-once exclusive migration | ❌ (R2, R3) | 035a | ✅ (035a) |
| FR-014 stable bounded-contention outcome | ⚠️ codes flattened at CLI | 035c | ✅ (035c) |
| US-C2 dispatch rebuilt after restart | ⚠️ prune only | 035d | ✅ (035d) |

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
| M | 035b | 328 ms | **154 ms** | **227 ms** | 3.07 | 2.9 → 9.3 ms |
| L | 035b | 965 ms | **457 ms** | **675 ms** | 3.37 | 6.7 → 35.2 ms |
| M | 035b + compact `session.json` | 387 ms | **107 ms** | **149 ms** | 2.20 | 2.6 → 8.2 ms |
| L | 035b + compact `session.json` | 831 ms | **294 ms** | **462 ms** | 4.12 | 5.3 → 24.1 ms |
| M | 035d, measured before the compact projection | 325 ms | 147 ms | 228 ms | 3.16 | 2.9 → 8.2 ms |
| L | 035d, measured before the compact projection | 1044 ms | 450 ms | 678 ms | 3.70 | 8.7 → 26.0 ms |

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

### 035b performance

The profile of Spec 034 attributed most per-CR time to rewriting projections;
035b removed that and the other per-write re-reads, in measured steps at M
(per-CR p50): 428 ms (035a) → 274 ms (incremental `evidence.jsonl`) → 219 ms
(single normalization, whole-set projection) → 190 ms (`replace()` without
snapshot reloads, stat-gated bundle verification) → 165 ms (differential row
writes) → 153 ms (in-memory committed view, reuse of the committed snapshot).

What remains is structural: canonical SQLite rows plus the `session.json`
projection cost more than `main`'s single JSON file. Two measured alternatives
were not adopted:

| Experiment (M) | CR p50 | CR p90 | Decision |
|---|---|---|---|
| WAL + `synchronous=NORMAL` | 176 ms | 242 ms | Rejected: no gain; commit fsync is not the bottleneck |
| Compact (non-indented) `session.json` | 121 ms | 173 ms | Adopted after owner approval (2026-09-28); with the encoder `default` hook it measures 107 ms / 149 ms |

### Budget status after 035b

| Budget | Status |
|---|---|
| Per-command p90 ≤ 1.2× develop | ✅ M 0.37×, L 0.29× |
| Per-command p90 ≤ 1.5× main | ❌ M 2.27×, L 1.82× — structural; see the experiments above |
| Degradation ratio ≤ 1.5 | ❌ M 3.07, L 3.37 (`main` 4.26 / 5.50) — every write still re-encodes the whole `session.json` projection |
| First-open migration below the 5 s busy timeout | ✅ M 0.33 s, L 0.96 s |
| `load_session` without `in_flight` rows opens no write transaction | ✅ `test_read_only_load_takes_no_write_lock` |

### Budget status after the compact projection

| Budget | Status |
|---|---|
| Per-command p90 ≤ 1.5× main | ✅ M 1.49×, L 1.24× |
| Degradation ratio ≤ 1.5 | ❌ M 2.20, L 4.12 (`main` 4.26 / 5.50). Early CRs got faster, so the ratio rose at L; absolute late-session cost is still below `main`. Every write re-encodes the whole projection, so the ratio cannot reach 1.5 without incremental session projection. |

## 035b Regression Evidence

`tests/contract/test_outbox_ownership_contract.py` (19 tests, including the compact projection contract) passes three
consecutive runs. R4 and R5 were reproduced on `4ba50e6` by the audit scripts
(see Reproductions); the contract module cannot import on pre-035b code
because the APIs it drives (execution guard, outbox lookups, schema v2) do not
exist there.

Upgrade end-to-end (task B011): v3.15.3 posted a reply and was killed while
resolving the thread, leaving `session.json` and `evidence.jsonl` with a
succeeded reply and an in-flight resolve. 035b then migrated that state and
published: `posts=0`, `resolves=1`, reply URL reused, outbox
`{github_reply: succeeded, github_resolve: succeeded}`, `PUBLISH_COMPLETE`.

## 035b Gates

| Gate | Result |
|---|---|
| `ruff check src tests scripts/build_plugin_payload.py scripts/benchmark_runtime_store.py` | Passed |
| `python3 -m unittest discover -s tests` | Passed except the environmental `test_stacked_pr_e2e_script` (`GitHub CLI is required.`), unchanged from `develop` |
| `python3 -m gh_address_cr --help` / `agent manifest` | Passed |
| `build_plugin_payload.py --output` / `--check` | Passed |
| `final-gate` | Not run: no PR session exists yet for this branch |

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

## 035c Regression Evidence

`tests/contract/test_persistence_reason_codes_contract.py` on 035b code:
`FAILED (failures=13, errors=10)`. Every agent command either let the injected
`SessionError` escape as a traceback (`next`, `submit`) or flattened it into
`PUBLISH_ERROR` / `SESSION_ERROR` (`publish`, `leases`, `reclaim`); eight
concurrent classifications surfaced `STALE_REVISION`; concurrent reclaims
failed. After the fix the module passes twice in a row.

Found while building 035d: moving classification, release, and reclaim onto
`transact_session` stopped binding local telemetry to the PR, so their metrics
were dropped. `test_transaction_only_commands_bind_pr_telemetry` failed
(`AssertionError: unexpectedly None`) until `transact_session` bound the same
context `load_session` does; the fix is a separate 035c commit.

## 035c Gates

| Gate | Result |
|---|---|
| `ruff check src tests scripts/build_plugin_payload.py scripts/benchmark_runtime_store.py` | Passed |
| `python3 -m unittest discover -s tests` | Passed except the environmental `test_stacked_pr_e2e_script` |
| `python3 -m gh_address_cr --help` / `agent manifest` | Passed |
| `build_plugin_payload.py --output` / `--check` | Passed |
| `final-gate` | Not run: no PR session exists yet for this branch |

## 035d Regression Evidence

On 035c code, `test_orchestrator_lease_convergence_contract.py` fails 4 of 6
(token is not the lease resume token; a lost dispatch is not rebuilt; a failed
dispatch leaves the claim locked; reconcile telemetry has no rebuild outcome).
The same-file and expired-lease contracts already held and stay as guards.
`test_latency_regression_contract.py` cannot import on 035c (no growth
threshold, no `operation_latency`). After the fix both modules pass.

035d performance is within noise of 035b (per-CR p50 147 ms at M, 450 ms at L);
the CLI's own command metric is one appended line, and telemetry history is no
longer re-read on every session load or transaction.

## 035d Gates

| Gate | Result |
|---|---|
| `ruff check src tests scripts/build_plugin_payload.py scripts/benchmark_runtime_store.py` | Passed |
| `python3 -m unittest discover -s tests` | Passed except the environmental `test_stacked_pr_e2e_script` |
| `python3 -m gh_address_cr --help` / `agent manifest` | Passed |
| `build_plugin_payload.py --output` / `--check` | Passed |
| `final-gate` | Not run: no PR session exists yet for these branches |

## Outcome

Every Spec 034 requirement the audit found unmet is now met (table above), and
R1–R5 are permanent regression contracts.

- Per-command p90 meets the 1.5x `main` budget (M 1.49x, L 1.24x) after the
  owner-approved compact `session.json` projection (035b); 035d adds no
  measurable cost (its benchmark above predates that change).
- The within-session degradation ratio remains unmet: M 2.2, L 4.1 (target 1.5;
  `main` 4.3 / 5.5). Each write re-encodes the whole session projection, so the
  ratio needs an incremental session projection to go further; P4 surfaces any
  command that slows by more than 2x in the final-gate completion line.

## Telemetry Overhead (closeout)

`benchmark_runtime_store.py --trace` runs every step inside a recording CLI root
span (`run_traced`) with an SDK `TracerProvider`, a `BatchSpanProcessor`, and an
in-memory exporter, so the persistence child spans are real. Three alternating
runs of profile M per mode on the authoring container (2,732 spans exported per
traced run):

| Mode | Per-CR p50 (3 runs) | Per-CR p90 (3 runs) | Degradation ratio |
|---|---|---|---|
| Tracing off | 100.3 / 94.3 / 102.9 ms | 135.6 / 145.1 / 142.5 ms | 2.85 / 2.84 / 2.74 |
| Tracing on | 99.1 / 103.7 / 109.9 ms | 154.2 / 157.9 / 153.3 ms | 2.70 / 2.83 / 2.98 |

| Budget | Status |
|---|---|
| Telemetry on versus off ≤ 5% | ✅ p50 +3.3% (median of runs); ❌ p90 +8.2% |

The traced number includes the CLI root span, which predates Spec 035, so the
cost added by the persistence spans alone is at most this figure. Tracing does
not change the degradation ratio. The p90 overage continues in Spec 036.

## Required Gates Per PR

- `pip install -e .`
- `ruff check src tests scripts/build_plugin_payload.py`
- `python3 scripts/check_mypy_ratchet.py`
- `python3 -m unittest discover -s tests`
- `python3 -m gh_address_cr --help`
- `python3 -m gh_address_cr agent manifest`
- `python3 scripts/build_plugin_payload.py --output dist/plugin/gh-address-cr`
- `python3 scripts/build_plugin_payload.py --check`
- `python3 scripts/benchmark_runtime_store.py --profile M --json` compared with the baselines above
- `final-gate` on the PR session with the compact metrics line
