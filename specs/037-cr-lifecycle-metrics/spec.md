# Feature Specification: CR Lifecycle Decision Metrics

**Feature Branch**: `feat/spec-037-cr-lifecycle-metrics`
**Created**: 2026-09-29
**Updated**: 2026-09-30
**Status**: Implemented and validated on the feature branch
**Depends On**: Spec 036 merged to `develop` at `907be6bc`

## Purpose

Provide evidence for maintainers to determine whether changes to
`gh-address-cr` reduce review-comment resolution lead time and rework without
changing runtime truth.

This is engineering evaluation instrumentation, not a new evaluation plane.
It extends the existing evidence-ledger projection in
`src/gh_address_cr/core/cr_metrics.py` and makes its report a first-class,
fail-open `final-gate` artifact.

## Consumers

| Consumer | Use | Priority |
|---|---|---:|
| Maintainer / architect | Compare workflow outcomes before and after architecture changes | P0 |
| Release evaluation | Detect advisory cross-version workflow regressions | P1 |
| Agent | Receive compact, non-authorizing feedback | P2 |
| External observability | Correlate internal handling with later GitHub outcomes | P2, deferred |
| Runtime state machine / gate verdict | **Forbidden consumer** | — |

## Lifecycle Model

```mermaid
flowchart LR
    O[Finding observed] --> A[First response accepted]
    A --> V[Item verified]
    V --> G[Final gate completed]
    G -. optional external fact .-> M[PR merged]
```

The v1 projector derives facts from the current evidence projection backed by
canonical SQLite evidence rows, plus the completed gate invocation. It does not
read `cr-metrics.json` as input and never mutates runtime state.

### Timestamp semantics

| Field | Canonical rule |
|---|---|
| `observed_at` | First `finding_observed` event; historical fallback is the earliest item-scoped evidence and MUST be labelled `first_evidence` |
| `addressed_at` | First valid non-verifier `response_accepted` event for the item |
| `verified_at` | GitHub thread: first `response_published`; local finding: first `response_accepted` whose evidence role is `verifier` and which follows the last `verification_rejected` |
| `merge_ready_at` | Time of the successful `final-gate` projection for the current run |
| `merged_at` | Optional external GitHub fact; out of scope for v1 |

An item with inferred observation time, missing terminal evidence, inverted
timestamps, or ambiguous item-kind semantics remains visible in diagnostics
but is excluded from headline aggregates that require the missing fact.

### `cr-lifecycle.v1` report contract

| Concept | JSON field |
|---|---|
| Report completeness | `completeness` (`empty`, `complete`, `partial`, or `unavailable`) |
| Observation provenance | `items[].observation_provenance` |
| Item timestamps | `items[].timestamps.{observed_at,addressed_at,verified_at}` |
| Item stage durations | `items[].durations_ms.{observed_to_addressed,addressed_to_verified,observed_to_verified}` |
| Item friction counts | `items[].counts.{address_attempts,response_rejections,verification_rejections,publish_blocked}` |
| Eligibility and reasons | `items[].eligible`, `items[].exclusion_reasons` |
| Verified and eligible counts | `aggregates.{verified_items,eligible_items,excluded_items}` |
| Lead-time distributions | `aggregates.{observed_to_addressed_ms,addressed_to_verified_ms,observed_to_verified_ms}` |
| First-pass rate | `aggregates.first_pass_verified_rate` |
| Friction rates | `aggregates.friction.*` |
| Slowest eligible stage | `aggregates.slowest_stage` |
| PR-level durations | `pr_durations_ms.{first_observed_to_merge_ready,last_verified_to_merge_ready}` |

Each distribution contains `median`, `p90`, `min`, `max`, `sample_count`, and
`excluded`. Each rate contains an explicit numerator or count, denominator,
rate, and excluded count where applicable. Per-item exclusion reasons explain
why excluded samples do not contribute to headline aggregates.

## Requirements

- **FR-001** Define a versioned, derived `cr-lifecycle.v1` report contract with
  per-item timestamps, durations, event counts, provenance, completeness, and
  diagnostics.
- **FR-002** Keep canonical SQLite evidence rows as authority; the current
  `evidence.jsonl` projection and successful gate invocation are report inputs.
  Do not add a database, catalog, daemon, evaluator registry, or second state authority.
- **FR-003** Project lifecycle timestamps with a deterministic policy table by
  item kind. Unknown item kinds or ambiguous histories fail open into explicit
  diagnostics; they are never silently coerced into a verified sample.
- **FR-004** Derive, where supported:
  `observed_to_addressed_ms`, `addressed_to_verified_ms`,
  `observed_to_verified_ms`, `first_observed_to_merge_ready_ms`, and
  `last_verified_to_merge_ready_ms`.
- **FR-005** Derive friction and rework signals:
  `response_rejection_count`, `verification_rejection_count`,
  `publish_blocked_count`, `address_attempt_count`, and
  `first_pass_verified`. First-pass requires exactly one address attempt, no
  rejection or blocked-publish evidence, and a valid terminal verification.
- **FR-006** Aggregate only eligible samples and report the numerator,
  denominator, excluded count, and exclusion reasons for every rate or
  percentile. Do not emit a synthetic composite score.
- **FR-007** `final-gate` generates `cr-metrics.json` and archives it with the
  audit and efficiency reports. Projection failure is visible but fail-open and
  cannot change the gate verdict or exit code.
- **FR-008** The compact completion output may expose a bounded lifecycle
  summary, but metrics never authorize an action, satisfy evidence, or alter
  `final-gate` truth.
- **FR-009** Emit bounded OTel instrumentation for projection outcome,
  completeness, and duration. Never emit repo, PR, item, path, content, or raw
  timestamps as metric attributes.
- **FR-010** Preserve the existing `cr_metrics` fields during v1 migration or
  explicitly version and test any replacement machine-readable contract.

## Headline Metrics

The first release exposes vector metrics, not a score:

- verified item count and eligible sample count;
- `observed_to_verified_ms` median and p90;
- `first_pass_verified_rate` with numerator and denominator;
- response and verification rejection counts per verified item, with explicit
  denominators and excluded counts;
- `first_observed_to_merge_ready_ms` when observation provenance is exact;
- the slowest eligible stage and item, with identifiers confined to the local
  artifact rather than telemetry attributes.

## Success Criteria

- **SC-001** Golden event-sequence tests cover successful first pass, rework,
  response rejection, publish blocking/recovery, incomplete items, duplicate
  events, interleaving, malformed timestamps, and mixed sessions.
- **SC-002** Every aggregate proves its eligible denominator and exclusions;
  inferred historical samples cannot appear as exact headline lead time.
- **SC-003** A successful `final-gate` archive contains a valid
  `cr-metrics.json`; a forced metrics failure preserves the original gate
  result and exposes diagnostics.
- **SC-004** Existing Spec 034–036 runtime, persistence, artifact, and
  performance contracts pass unchanged.
- **SC-005** Projection is linear in ledger rows, bounded in memory by the
  current session, and adds no GitHub API request to `final-gate` v1.
- **SC-006** Dogfood produces a non-blocking baseline across at least 10
  completed PR sessions before any regression threshold is proposed. A
  controlled pre-merge baseline validates instrumentation and aggregation but
  MUST be labelled threshold-ineligible until natural production sessions are
  available.

## Scope Boundaries

### In scope

- lifecycle event semantics and provenance;
- pure read-only projection in `cr_metrics.py`;
- versioned JSON artifact and compact human/machine summary;
- `final-gate` generation, archive integration, failure diagnostics, and OTel;
- executable contracts and dogfood baseline procedure.

### Out of scope

- GitHub `pull_request_review_times` ingestion;
- organization dashboards or cross-repository storage;
- evaluation database/catalog, cohorts, ranking, or a composite efficiency score;
- blocking CI or release gates based on lifecycle metrics;
- any change to item, lease, publisher, or `final-gate` truth semantics.
