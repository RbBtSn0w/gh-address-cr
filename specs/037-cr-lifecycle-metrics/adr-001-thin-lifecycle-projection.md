# ADR-001: Extend the Evidence Projection Instead of Rebuilding Evaluation

**Status:** Accepted
**Date:** 2026-09-30
**Deciders:** Repository architecture owner

## Context

The current `cr_metrics.py` groups evidence by item and reports one span from
the first item event to `thread_resolved`. It cannot distinguish addressing,
verification, rework, or time between verified items and merge readiness.

An earlier evaluation subsystem was removed during complexity reduction. The
current protected baseline keeps findings, deterministic workflow, evidence,
final-gate, and OTel; lifecycle metrics must not recreate a database, catalog,
or policy engine beside that baseline.

## Decision

Implement lifecycle metrics as a thin, versioned, read-only projection over
existing evidence plus the successful final-gate fact. Produce one rebuildable
`cr-metrics.json` artifact and a bounded advisory summary.

The projection is fail-open and forbidden from influencing runtime state,
evidence sufficiency, authorization, or gate verdicts. Missing or ambiguous
facts reduce metric eligibility and create diagnostics rather than inferred
success.

## Options Considered

### Extend the existing projector (selected)

| Dimension | Assessment |
|---|---|
| Complexity | Low to medium |
| New authority | None |
| Replayability | High |
| Cross-run analytics | Deferred |

**Pros:** Reuses evidence, preserves architecture boundaries, small operational
surface, easy to delete and rebuild.

**Cons:** Historical evidence may be incomplete; cross-version comparisons
need later aggregation outside runtime.

### Recreate an evaluation database and catalog

| Dimension | Assessment |
|---|---|
| Complexity | High |
| New authority | Ambiguous |
| Replayability | Medium |
| Cross-run analytics | High |

**Pros:** Rich cohorts and queries.

**Cons:** Reintroduces the subsystem already removed, expands migration and
ownership cost, and risks feeding derived state back into workflow truth.

### Export only OTel metrics

| Dimension | Assessment |
|---|---|
| Complexity | Medium |
| Local-first support | Weak |
| Per-item diagnostics | Privacy-sensitive |
| Offline replay | Weak |

**Pros:** Natural long-term aggregation.

**Cons:** Makes external telemetry availability a prerequisite, loses local
diagnostic detail, and pressures high-cardinality attributes.

## Trade-off Analysis

The thin projector does not solve organization-wide cohort analysis, but it
creates trustworthy per-session evidence without widening runtime authority.
That is the correct first boundary: establish stable lifecycle semantics and
sample quality before choosing any aggregation backend.

## Consequences

- Existing evidence producers may need one explicit `finding_observed` event to
  make future lead-time origins exact.
- Historical sessions remain useful but their inferred origin is labelled and
  excluded from exact-origin headline metrics.
- `final-gate` owns report generation and archiving, not metric truth.
- Metrics failure remains visible and non-blocking.
- A future external analytics layer requires a new ADR and preflight.

## Action Items

1. [x] Accept or revise the v1 lifecycle and eligibility policy.
2. [x] Implement Slice A with golden replay contracts.
3. [x] Integrate fail-open final-gate artifact generation.
4. [x] Add compact advisory output and private OTel health instrumentation.
5. [x] Collect a controlled pre-merge dogfood baseline; keep it ineligible for production thresholds.
