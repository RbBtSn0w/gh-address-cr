# ADR-001: Materialize `session.json` at Explicit Compatibility Boundaries

**Status:** Accepted
**Date:** 2026-09-28
**Deciders:** Repository architecture owner

## Context

Runtime schema v3 makes bounded command reads and writes independent of total
session history. Profile L then measures transaction degradation between
`1.039` and `1.056`, while `session.json` materialization remains between
`2.243` and `2.263`; complete per-CR degradation is `1.683` against the `1.5`
budget. The projection is compact and byte-identical, but atomic replacement
must still emit bytes proportional to the full public history.

SQLite is the sole authority. `session.json` is revision-stamped, rebuildable,
and never accepted as runtime input after migration.

## Decision

Runtime schema v3 commits mark `session_json` dirty and return without rewriting
it. The runtime materializes it at explicit compatibility boundaries:

- full `load_session` and artifact recovery;
- reporting, export, and compatibility commands that request a complete
  session projection;
- explicit materialization APIs and migration recovery.

The append-only `evidence.jsonl` projection remains incrementally current after
normal command commits because appending new evidence is proportional to the
change. Its revision metadata is updated independently of `session.json`.

A dirty or stale `session.json` never changes command truth. Consumers that
require a current file must use a compatibility boundary and verify its
revision. Materialization failure remains recoverable and cannot roll back the
already committed runtime revision.

## Options Considered

### Rewrite after every commit

Preserves the schema-v2 freshness rule, but profile L proves total-size output
alone exceeds the runtime hot-path budget after transaction growth is removed.

### Defer all compatibility artifacts

Removes output from the hot path, but unnecessarily weakens the cheap,
append-only evidence contract used by review and audit surfaces.

### Defer only `session.json` (selected)

Keeps evidence delivery incremental, preserves SQLite authority, and assigns
the unavoidable full projection cost to consumers that explicitly need it.

## Consequences

- Successful bounded commands guarantee a committed SQLite revision and
  current incremental evidence; `session.json` may name an older revision.
- Direct file readers must tolerate a stale revision or request explicit
  materialization.
- Full load/recovery latency remains proportional to total history and is
  measured separately from bounded command latency.
- Crash, drift, migration, and concurrent materialization contracts must cover
  dirty-to-current replay without duplicate evidence or lost lease history.

## Superseded Rule

For runtime schema v3, this ADR narrows step 8 of Spec 034 ADR-001: post-commit
materialization applies to incremental evidence artifacts; full `session.json`
materialization occurs at the explicit boundaries above.
