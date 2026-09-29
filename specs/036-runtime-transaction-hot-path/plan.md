# Implementation Plan: O(changed) Runtime Transaction Hot Path

**Branch**: `perf/036-runtime-transaction-hot-path` | **Date**: 2026-09-28 |
**Spec**: [spec.md](./spec.md) | **Tasks**: [tasks.md](./tasks.md) |
**Validation**: [validation.md](./validation.md)

## Summary

Reduce the mutable runtime transaction path from whole-session normalization
and entity re-encoding to a bounded command working set selected from normalized
SQLite rows. Preserve SQLite as the only authority and keep full-session APIs
and compatibility artifacts as explicit materialization boundaries.

The rejected proxy prototype proved that preserving an implicit whole-session
mutable dict inside every command cannot meet the slope budget cleanly. The
revised design must make the working-set boundary explicit and versioned while
keeping selection, lease, and response policy in the existing runtime kernel.

## Current Evidence

On `develop` (`8269e40`), Python 3.14.7, profile M (300 items / 3,000 seed
events / 300 CRs):

| Metric | Result | Budget |
|---|---:|---:|
| per-CR p50 | 48.101 ms | advisory |
| per-CR p90 | 68.111 ms | no worse than Spec 035 closeout |
| degradation ratio | 2.801 | <= 1.5 |
| load before -> after p50 | 1.712 -> 4.812 ms | advisory |

The absolute timings differ from the Spec 035 Python 3.11 measurements, but the
within-session ratio independently reproduces the structural failure.

### Prototype checkpoint (reverted)

An experimental implementation pass completed tracked mutation, fragment reuse,
single-snapshot handoff, and exact projection contracts. Profile M improved in
absolute terms, but did not meet the degradation budget:

| Stage | p50 | p90 | Degradation |
|---|---:|---:|---:|
| `develop` baseline | 48.101 ms | 68.111 ms | 2.801 |
| Reverted checkpoint | 36.406 ms | 49.643 ms | 2.386 |

This is roughly a 24% p50 and 27% p90 improvement, but only a 15% improvement
in the degradation ratio. Continuing to add mutation-specific shortcuts would
optimize around the remaining architectural cost instead of removing it.

The prototype was reverted after later experiments expanded
`runtime_store.py` by more than 1,000 lines while the best observed degradation
ratio remained above `2.0`. The current working tree contains no production
implementation from that experiment. The accepted replacement is the bounded
working-set and schema-v3 design below; `research.md` retains the rejected
direction as historical evidence. No success criterion was relaxed.

## Architecture Preflight

### Authoritative State Owner

- `runtime.sqlite3` remains the only authoritative store.
- `session.json`, `evidence.jsonl`, and their metadata remain rebuildable
  compatibility projections.
- Runtime schema v3 normalizes append-only lease lifecycle events out of the
  growing session root. The v2-to-v3 migration moves existing events in one
  transaction and removes the embedded array only after every row is copied.
  SQLite remains the sole authority; no second writer is introduced.

### External Facts and Event Inputs

- A declarative working-set request containing operation category, target item
  or lease identity when known, and required active-policy rows.
- Existing buffered evidence records and outbox commands.
- New lease lifecycle events emitted by the existing runtime kernel.
- Existing expected-revision compare-and-swap boundary.
- No new external fact or public protocol field.

### Projection Shape

1. Resolve a bounded working set from canonical SQLite rows without decoding
   unrelated items or terminal lease payloads.
2. Run the existing deterministic policy over an explicit working-set DTO.
3. Compare and commit item, lease, evidence, outbox, and session-field changes
   inside the selected scope under the existing expected-revision transaction.
4. Append lease lifecycle events to their normalized table without rewriting
   prior events or the session root.
5. Materialize compatibility artifacts after commit under the existing public
   freshness contract.
6. Keep `session.json` byte-identical to a canonical full rebuild.

### Policy and Deterministic Decision Function

| Condition | Path | Result |
|---|---|---|
| Bounded working set with validated write scope | Incremental | Decode and encode selected entities only |
| Whole-payload replacement or unprovable input | Full | Existing normalization and equality checks |
| Fragment missing or inconsistent | Full rebuild | Identical output; no silent partial projection |
| Expected revision changed | Reject | Existing `STALE_REVISION` behavior |

The fallback is a performance path only. It does not change state, output, or
error semantics.

### Side-Effect and Outbox Boundary

- The SQLite transaction, evidence insertion, outbox insertion, revision
  advance, and commit ordering are unchanged.
- No filesystem write is moved into the canonical transaction.
- Incremental evidence materialization remains after commit. Full
  `session.json` materialization moves to the explicit full-load, reporting,
  export, and recovery boundaries defined by ADR-001.

### Artifact Truth and Telemetry Self-Reference

- Encoded fragments are a transaction-local optimization, not durable
  authority independent of their SQLite rows.
- `session.json` is never read to decide a transaction or projection value.
- Existing persistence spans retain their names and bounded attributes.
- No per-item span or identifier-bearing telemetry is added.

### Recovery, Replay, and Executable Contracts

- A randomized mutation sequence compares every incremental projection with a
  fresh canonical compact rebuild.
- Crash, drift-repair, migration, outbox, and concurrent materialization tests
  continue to run unchanged.
- Focused contracts prove no full snapshot load or whole-session `json_ready`
  walk on the bounded command path, and no encoding of unrelated entities.
- The existing benchmark proves M/L degradation and tracing overhead budgets.

## Detailed Design

### Versioned Command Working Set

Introduce one internal, versioned DTO that contains session metadata, selected
item rows, selected lease rows, active-lease summaries, and the expected
revision. Selection is declarative data, not a second policy implementation.
The runtime kernel remains responsible for eligibility, conflict, recovery,
and transition decisions.

The runtime kernel mutates this bounded DTO in place. The store compares only
its selected canonical fragments and validates that every pre-existing changed
identity belonged to the requested working set. New item and lease identities
created by the operation are allowed. Evidence records and outbox commands are
append-only members of the same bounded transaction. The store then commits the
validated write set with the existing compare-and-swap revision boundary.

ADR-002 records why a separate explicit-delta DTO is not introduced until a
consumer needs field-level merge, cross-working-set composition, or an external
mutation provider.

### Canonical Fragments

The canonical load retains each row's `payload_json`. A changed entity replaces
its fragment after normalization; an unchanged entity reuses the fragment read
from SQLite. The committed `StoreSnapshot` carries these fragments only as
ephemeral projection inputs.

### Normalized Lease Event Log

Schema v3 adds an ordered `lease_events` table owned by the same database and
transaction as session, item, and lease state. A bounded mutation inserts only
the events it produced. Full replacement rewrites the table from the supplied
complete event list. Full loads and compatibility projection reassemble the
public `lease_events` array in insertion order.

The v2-to-v3 migration reads the embedded `lease_events` array, inserts every
entry in order, removes that field from `sessions.payload_json`, and marks
artifacts dirty in one exclusive transaction. Replay and projection tests prove
that no history is lost or duplicated.

### Compact Projection

Construct the top-level compact JSON object in sorted-key order. `items` and
`leases` are objects assembled from sorted IDs and their canonical fragments.
The `persistence` entry is generated from the committed schema/revision.
The bytes must equal:

```python
json.dumps(full_payload, sort_keys=True, separators=(",", ":"), default=json_ready) + "\n"
```

### Full Materialization and Compatibility Fallback

`load_session`, `replace()`, `agent leases`, reporting, drift repair, and legacy
compatibility retain explicit full materialization. The command hot path must
not call those APIs implicitly. Equivalence tests compare bounded commits with
a fresh canonical full load and projection.

ADR-001 versions the artifact cadence for schema v3: bounded commits keep the
append-only evidence projection current and leave `session_json` dirty. A full
compatibility boundary materializes the latest revision before returning.

## Delivery

This is one implementation PR. Splitting tracking, canonical fragments, and
projection assembly would leave lower PRs with unused machinery or an
incomplete performance contract, so they are not useful independent review
units. Spec 037 starts only after this PR's performance and correctness gates
are recorded.

## Complexity Budget

- One versioned working-set DTO, one write-scope validator, and one store commit path.
- No dict/list/set proxy emulation, daemon, cache database, or compatibility
  alias.
- No operation-specific SQL policy. Queries may select rows by declarative
  identity/status predicates; policy stays in the runtime kernel.
- Stop if the design needs hidden dirty flags or duplicates selection/lease
  decisions in the store.

## Corrected Cost Model

The tracked working set removes repeated normalization and encoding, but two
operations are still proportional to total session size:

1. `_load_snapshot` eagerly decodes every item and lease row before a targeted
   command can access one item.
2. Atomic `session.json` materialization writes the full projection bytes after
   each committed revision, even when unchanged fragments are reused.

The bounded preflight implementation removed the first cost from explicit
claim and normal submit. Profile M then reached p50 `16.387 ms`, p90
`21.630 ms`, and degradation `2.044`; measured load cost is zero for all three
stages. Remaining transaction degradation (`2.069` to `2.595`) correlates with
the embedded append-only `lease_events` array, while materialization remains
`2.331` to `2.515`. Schema v3 removes the transaction-side growing root before
any decision about artifact cadence.

The next implementation phase must prove that one benchmark command can run
from a bounded working set and validated write set without invoking `load_session`
or `replace()`. Full projection cost is measured separately and remains a
public recovery-contract decision if it alone prevents SC-001.

### Second prototype checkpoint: retained lease history

In the reverted prototype, after submit was moved from full `replace()` to the tracked transaction path,
the validated session-item helper stopped enumerating the tracked map, and item
rows became lazy, profile M reached p50 `26.304 ms` and p90 `35.897 ms`. The
degradation ratio remained `2.436`: fixed overhead fell, but the last decile
still grows with retained terminal leases.

A complete 300-CR profile attributes cumulative time to 905 snapshot loads,
141,757 JSON decodes, 270,300 lease datetime coercions, and repeated claim
projection checks. Each completed CR leaves one terminal lease in the public
session map, so all three commands repeatedly decode and scan history that is
not active policy input.

The next design checkpoint is therefore lease-specific. It must preserve the
full public lease collection and terminal recovery history while letting active
lease policy use the normalized SQLite columns without decoding terminal
`payload_json`. Deleting terminal leases or omitting them from `session.json`
is out of bounds without a separately versioned contract change.

The dict-subclass/lazy-proxy approach used by the prototype is rejected: it
required duplicating Python container protocols, introduced hidden coupling to
session helpers, and reduced latency without meeting the slope budget. A new
plan must reduce the amount of state entering each command, not simulate a
complete mutable session graph more efficiently.
