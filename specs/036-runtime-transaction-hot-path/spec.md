# Feature Specification: O(changed) Runtime Transaction Hot Path

**Feature Branch**: `perf/036-runtime-transaction-hot-path`
**Created**: 2026-09-28
**Status**: Implemented and locally validated
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

- **FR-001** A mutating command requests a bounded, versioned working set from
  SQLite and does not implicitly materialize the full session. Full loads stay
  explicit for compatibility, reporting, and recovery consumers.
- **FR-002** The deterministic runtime kernel returns an explicit delta over the
  selected session fields, items, leases, evidence, and outbox commands. The
  store must not infer changes by wrapping or deep-walking a mutable dict graph.
- **FR-003** The bounded transaction validates and encodes only declared changed
  rows. `last_observed_revision` semantics from Spec 035 US6 are unchanged.
- **FR-004** When explicitly materialized, the `session.json` projection is assembled from per-entity encoded
  fragments. Only changed entities are re-encoded, and the output stays
  **byte-identical** to a full compact re-encode. The projection's public format
  (compact, `sort_keys`) is unchanged.
- **FR-005** Tracing adds at most 5% to per-CR p50 and p90 in `benchmark_runtime_store.py --trace`.
  The fix, if one is needed, removes span work from inner loops. It never
  drops the required CLI span attributes or the persistence spans' bounded attributes.
- **FR-006** No second authority, hidden dirty flag, or command-specific policy
  implementation. A caller that needs the full session uses the existing full
  path explicitly; bounded and full paths have identical committed semantics.

## Success Criteria

| ID | Criterion | How it is checked |
|---|---|---|
| SC-001 | Degradation ratio ≤ 1.5 at M and L | `benchmark_runtime_store.py --profile M --profile L`, recorded in `validation.md` |
| SC-002 | Per-command p90 no worse than the Spec 035 closeout numbers (M 1.49×, L 1.24× `main`) | Same benchmark |
| SC-003 | Tracing overhead ≤ 5% at p50 and p90 | `--trace` versus plain, three alternating runs |
| SC-004 | Incremental evidence is current after every transaction; explicitly materialized `session.json` is byte-identical to a full rebuild | New equivalence contract test over a randomized mutation sequence |
| SC-005 | All Spec 034/035 contract tests pass unchanged | Full unittest suite |

## Scope Boundaries

- In scope: `src/gh_address_cr/core/runtime_store.py`, one internal working-set
  and delta contract in the runtime kernel, minimal agent-protocol wiring to
  use it, projection materialization, and `scripts/benchmark_runtime_store.py`.
- Out of scope: public CLI/agent protocol shapes, the public projection format,
  and the SQLite-as-truth model from Spec 034/035. Runtime schema v3 is in scope
  only to normalize the existing append-only `lease_events` array; it adds no
  public state or second authority.

## Architecture Preflight

This touches session persistence internals but not their semantics. Record the preflight in `plan.md` before implementing:

- **Authoritative state owner:** the SQLite store (unchanged).
- **Derived state:** `session.json`, which must stay byte-identical.
- **Recovery and replay:** unchanged; SC-004 guards it.
- **Telemetry:** span count and attributes stay bounded; FR-005 is measured, not assumed.

## Architecture Checkpoint — 2026-09-28

The reverted prototype satisfied its bounded-mutation and byte-equivalence
contracts in FR-001 through FR-004, but profile M still reports a degradation
ratio above the `1.5` budget. The original performance model was therefore
incomplete: it accounted for repeated loads and re-encoding, but not for the
first eager decode of every item row or for writing every byte of the
compatibility projection after each commit.

The prototype was reverted after it grew the runtime store by more than 1,000
lines without meeting SC-001. That historical checkpoint required the next
design to address the
remaining whole-session work at the canonical load/projection boundary without
adding command-specific persistence paths or weakening compatibility recovery.
The accepted bounded working set, normalized lease event log, and versioned
artifact cadence now meet SC-001; see `validation.md` for closeout evidence.
