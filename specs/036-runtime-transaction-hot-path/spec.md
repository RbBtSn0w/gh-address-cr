# Feature Specification: O(changed) Runtime Transaction Hot Path

**Feature Branch**: `perf/036-runtime-transaction-hot-path`
**Created**: 2026-09-28
**Status**: Draft (follow-up to Spec 035; not started)
**Input**: Two Spec 035 performance budgets remain unmet after it merged to `develop` through #294:
the within-session degradation ratio (M 2.2, L 4.1; target ≤ 1.5) and the tracing p90
overhead (+8.2%; target ≤ 5%). See `specs/035-runtime-store-hardening/validation.md`.

## Why this exists

Spec 035 made every write append-only for evidence (P3), but each transaction still
does work proportional to the **total** number of session items, not the number it
changed. A PR with many CRs therefore gets slower per CR as it goes, which is the
slowdown the degradation ratio measures.

A cProfile of `scripts/benchmark_runtime_store.py --profile L --cr-limit 400`
on `develop` (f3271c2) shows where each transaction spends its item-proportional time.
Times are cumulative under the profiler, so treat them as relative weights:

| Hot spot | Cost | Why it scales with total items |
|---|---|---|
| `RuntimeStore._load_snapshot` | 32.4 s (3 calls per command: `load`, `_transact`, `_materialize`) | Decodes every item and lease row on each call |
| `json_ready(working)` in `_transact` | 26.8 s (37.8 M recursive calls) | Deep-walks the whole payload to normalize it |
| `_write_session_projection` | 16.9 s | Re-encodes the whole `session.json` projection |
| `_write_items` | 16.6 s | Re-encodes every item to decide which rows changed |

Each CLI command runs in a new process, so a cross-process cache cannot remove the
one decode a command needs. The goal is one decode per command, plus
encode and normalize work proportional to what the command changed.

## Requirements

- **FR-001** A command decodes the canonical snapshot at most once. `transact` and
  `materialize_compatibility_artifacts` reuse the rows and committed view already in
  hand instead of calling `_load_snapshot` again. `load` stays read-only.
- **FR-002** `_transact` normalizes only entities the mutation changed. Unchanged items
  and leases keep their decoded form and their stored `payload_json` text; nothing is
  deep-walked twice.
- **FR-003** `_write_items` and `_write_leases` detect change by comparing against the
  decoded original. They encode only changed rows. `last_observed_revision` semantics
  from Spec 035 US6 are unchanged.
- **FR-004** The `session.json` projection is assembled from per-entity encoded
  fragments. Only changed entities are re-encoded, and the output stays
  **byte-identical** to a full compact re-encode. The projection's public format
  (compact, `sort_keys`) is unchanged.
- **FR-005** Tracing adds at most 5% to per-CR p50 and p90 in `benchmark_runtime_store.py --trace`.
  The fix, if one is needed, removes span work from inner loops. It never
  drops the required CLI span attributes or the persistence spans' bounded attributes.
- **FR-006** No new state, flag, or fallback path. When a fast path cannot prove its
  input is unchanged, it takes the existing full path; this is a performance
  fallback with identical output, covered by the equivalence tests below.

## Success Criteria

| ID | Criterion | How it is checked |
|---|---|---|
| SC-001 | Degradation ratio ≤ 1.5 at M and L | `benchmark_runtime_store.py --profile M --profile L`, recorded in `validation.md` |
| SC-002 | Per-command p90 no worse than the Spec 035 closeout numbers (M 1.49×, L 1.24× `main`) | Same benchmark |
| SC-003 | Tracing overhead ≤ 5% at p50 and p90 | `--trace` versus plain, three alternating runs |
| SC-004 | `session.json` and `evidence.jsonl` are byte-identical to a full rebuild after every transaction | New equivalence contract test over a randomized mutation sequence |
| SC-005 | All Spec 034/035 contract tests pass unchanged | Full unittest suite |

## Scope Boundaries

- In scope: `src/gh_address_cr/core/runtime_store.py` (`_transact`, `_write_session`,
  `_write_items`, `_write_leases`, `_materialize`, `_write_session_projection`),
  `core/io.py` normalization helpers, `scripts/benchmark_runtime_store.py`.
- Out of scope: the schema (stays v2), the public projection format, the agent protocol,
  and the SQLite-as-truth model from Spec 034/035.

## Architecture Preflight

This touches session persistence internals but not their semantics. Record the preflight in `plan.md` before implementing:

- **Authoritative state owner:** the SQLite store (unchanged).
- **Derived state:** `session.json`, which must stay byte-identical.
- **Recovery and replay:** unchanged; SC-004 guards it.
- **Telemetry:** span count and attributes stay bounded; FR-005 is measured, not assumed.
