# Architecture Preflight: GitHub Review-Stage Outcome Correlation

**Status:** Complete; implementation deferred
**Date:** 2026-09-30
**Scope:** Optional correlation with GitHub `pull_request_review_times`

## Decision

Do not ingest GitHub review-stage metrics into `cr-lifecycle.v1` or
`final-gate`. If organization or enterprise access becomes available, a future
external analytics adapter may correlate repository/day aggregates with
aggregated gh-address-cr lifecycle exports. It must remain outside runtime
state, evidence sufficiency, completion truth, and PR-side effects.

GitHub's repository report is an organization/enterprise, repository/day
aggregate. It is not a PR-level event source and cannot supply item-level
`observed_at`, `verified_at`, or merge readiness. In the initial release it
times only human-authored PRs reviewed by another human; Copilot, bot, and
author reviews are ignored. Data is not backfilled for PRs ready before
2026-09-21. These boundaries make it an external outcome signal, not a runtime
measurement source.

Authoritative sources:

- [GitHub changelog: review-stage metrics](https://github.blog/changelog/2026-09-25-usage-metrics-api-adds-pull-request-review-stages/)
- [GitHub REST API: Copilot usage metrics](https://docs.github.com/en/rest/copilot/copilot-usage-metrics)

## Architecture Preflight

### Authoritative state owner

- GitHub owns `pull_request_review_times` and its inclusion policy.
- gh-address-cr owns its local evidence ledger and `cr-lifecycle.v1` projection.
- A future correlation export is derived from both and owns no workflow truth.

### External facts and event inputs

The GitHub input is the enterprise or organization `repos-1-day` report:

- `authored_by` and `reviewed_by`;
- qualifying `total_merged`;
- median and p90 minutes for ready-to-first-review;
- median and p90 minutes for first-to-final-review;
- median and p90 minutes for final-review-to-merge;
- report day and repository identity.

The endpoint returns signed download links, requires the relevant Copilot
metrics read permission and an enabled usage-metrics policy, and may return
empty/no-content results. Signed URLs are transport details and must never be
persisted as metrics or telemetry attributes.

### Projection shape

```text
GitHub repos-1-day aggregate ----+
                                 +--> external correlation report
gh-address-cr aggregate export --+          (advisory only)
```

The minimum join grain is repository plus report day and compatible cohort.
There is no valid item-level or individual-PR join in the published contract.
The report must retain both denominators because GitHub qualifying merges and
gh-address-cr eligible items measure different populations.

### Deterministic policy table

| Condition | Action |
|---|---|
| No enterprise/organization access | Report `unavailable`; do not retry from runtime |
| Policy disabled or permission denied | Report access diagnostic; no fallback token path |
| Empty array / no qualifying merges | Record `no_sample`, never numeric zero duration |
| Pre-backfill boundary data | Exclude and record coverage boundary |
| Human-only cohort | Label explicitly; never claim AI-review timing |
| Denominators differ | Present both; forbid ratio-to-ratio causal inference |
| Missing or malformed report | Fail the external analytics job only |

### Side-effect and command boundary

- No request is added to `final-gate`.
- No GitHub mutation or PR comment is permitted.
- Retrieval belongs to an explicitly invoked external analytics job with
  organization/enterprise credentials.
- Runtime and skill payloads must not store those credentials or signed URLs.

### Artifact truth and self-reference risks

- The correlation artifact is rebuildable advisory output, never input to
  `cr-lifecycle.v1`, session state, release gates, or agent decisions.
- It must label aggregation grain, source day, cohort, denominators, coverage
  gaps, and API/schema version.
- A correlation must not be described as causal evidence that gh-address-cr or
  AI review improved merge time.

### Recovery, replay, and executable contracts

A future implementation requires a new versioned contract and tests for:

- 200, 204, 403, 404, expired signed URL, empty array, and malformed NDJSON;
- repository/day attribution and duplicate-day idempotency;
- backfill cutoff and cohort/denominator preservation;
- permission and secret redaction;
- replay from saved sanitized source rows;
- proof that failures cannot affect runtime or `final-gate`.

## Re-entry Criteria

Implementation may start only when all are true:

1. An organization or enterprise scope with the required metrics permission is
   available for dogfood.
2. At least 10 natural `cr-lifecycle.v1` sessions exist in the same repository
   and observation window.
3. The intended question is explicitly aggregate and observational.
4. A separate versioned external-report contract and retention policy are
   approved.

Until then, the correct architecture is no integration.
