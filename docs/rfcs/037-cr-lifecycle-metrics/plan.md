> Archived design reference. Current code, tests, and `AGENTS.md` govern
> execution; historical delivery status and commands are not active instructions.

# Implementation Plan: CR Lifecycle Decision Metrics

**Branch**: `feat/spec-037-cr-lifecycle-metrics` | **Date**: 2026-09-30 |
**Spec**: spec.md (removed delivery artifact; see Git history) | **ADR**: [adr-001-thin-lifecycle-projection.md](./adr-001-thin-lifecycle-projection.md) |
**Tasks**: tasks.md (removed delivery artifact; see Git history)

## Summary

Evolve the existing `cr_metrics.py` from one coarse
`first event -> thread_resolved` span into a versioned lifecycle projector.
The projector consumes current-session evidence, produces one rebuildable JSON
artifact, and supplies advisory output to maintainers. It is not a runtime
dependency and cannot affect the final-gate verdict.

## Architecture Preflight

### Authoritative state owner

- Runtime SQLite remains authoritative for workflow events. The incrementally
  current `evidence.jsonl` ledger is a rebuildable report input.
- A successful `final-gate` invocation supplies `merge_ready_at` for that run.
- `cr-metrics.json` is derived, disposable, and never read to make a runtime or
  gate decision.

### External facts and event inputs

- Current-session, item-scoped evidence records from a projection whose source
  revision is current.
- Item kind from the canonical session/evidence projection only when required
  by the deterministic terminal-event policy.
- Successful final-gate completion time.
- No GitHub review-times or merge facts in v1.

### Projection shape

```text
evidence ledger + successful gate fact
                |
                v
       lifecycle projector (pure)
                |
       +--------+---------+
       |                  |
       v                  v
cr-metrics.json     compact summary
       |
       v
final-gate archive (fail-open)
```

`cr-lifecycle.v1` contains:

- report metadata and schema version;
- per-item facts, provenance, counts, durations, eligibility, exclusions;
- aggregate distributions and rates with explicit denominators;
- diagnostics and artifact location.

### Deterministic policy table

| Item/history | Addressed | Verified | Aggregate eligibility |
|---|---|---|---|
| GitHub thread + published response | first accepted response | first `response_published` after relevant rejection history | eligible when observation is exact |
| Local finding + accepted verifier response | first accepted fixer response | accepted verifier response after last rejection | eligible when observation is exact |
| Resolve-only classification | no fabricated address time | terminal publish/resolve fact only | excluded from address-stage metrics |
| Incomplete or unknown item | available facts only | none | excluded with reason |
| Historical record without `finding_observed` | first evidence, provenance=`first_evidence` | normal terminal policy | excluded from exact observation aggregates; shown separately |

The implementation phase must validate these rules against actual producer
contracts before freezing fixtures. If a current item kind cannot be proven
from evidence without consulting mutable artifact truth, add an explicit
evidence event rather than an inference branch.

### Side-effect and outbox boundary

- Projection performs no GitHub mutation and creates no outbox command.
- The only filesystem side effect is atomic report writing at the established
  reporting boundary.
- Archive path rewriting follows the existing efficiency-report mechanism.

### Artifact truth and self-reference

- The report records input/session identity and diagnostics but is never an
  input to itself.
- Archive rewriting changes only artifact location fields.
- A missing or malformed report cannot block cleanup or alter gate truth.
- Telemetry describes projector health, not lifecycle item identities.

### Recovery and replay

- Replaying identical ordered evidence produces byte-stable semantic output
  except for explicitly supplied gate time and artifact path.
- Duplicate record IDs are idempotent; conflicting duplicates are diagnostic.
- Malformed rows and timestamps remain visible as diagnostics; affected items
  are excluded whenever a required fact is unavailable.
- Archive/retry cannot double-count events.
- An unreadable evidence projection is diagnosed as report-unavailable and
  remains fail-open. Projection materialization stays owned by the existing
  persistence/reporting boundary rather than being duplicated in this module.

## Delivery Strategy

Use one umbrella spec with independently verifiable implementation slices.
Each slice can be reviewed separately; a later slice may depend on the v1
contract from the previous slice, so stacked PRs are justified only if work is
parallelized before the lower layer merges.

### Slice A — Contract and pure projector

- Freeze `cr-lifecycle.v1` models and event policy.
- Add golden fixtures and rewrite `build_cr_summary` as a pure projection plus
  a thin I/O wrapper.
- Preserve existing public fields during migration.

**Exit gate:** projector contracts pass; no `final-gate` changes.

### Slice B — Final-gate artifact integration

- Generate the report after gate evaluation.
- Archive and rewrite its path alongside existing artifacts.
- Surface fail-open diagnostics in human and machine output.

**Exit gate:** success/failure/archive tests prove verdict independence.

### Slice C — Compact advisory summary and OTel

- Add a bounded lifecycle summary to completion guidance.
- Instrument projector outcome, duration, and completeness with private,
  low-cardinality attributes.

**Exit gate:** completion contract and telemetry privacy tests pass.

### Slice D — Dogfood baseline

- Run at least 10 controlled pre-merge completed sessions on the feature branch.
- Record distributions, exclusions, and sample composition by version.
- Mark controlled timings threshold-ineligible; recommend advisory thresholds
  only after later natural production calibration.

**Exit gate:** validation report distinguishes measured data from unavailable
or inferred data.

## Test Strategy

- Unit: timestamp derivation, event policy, counts, rates, percentile math,
  duplicate handling, provenance, exclusions.
- Contract: schema compatibility, deterministic JSON, fail-open errors,
  telemetry privacy.
- Integration: `final-gate` pass/fail, machine/human output, archive cleanup,
  stack gate behavior.
- Regression: full repository suite and unchanged Spec 036 M/L benchmarks.
- Dogfood: controlled current-branch sessions for pipeline acceptance; natural
  archived sessions remain the later threshold-calibration evidence.

## Complexity Budget

- One versioned projection model and one report artifact.
- No new persistence layer, evaluator framework, background process, GitHub API
  client, or command family.
- No metric may become a runtime conditional or gate predicate.
- Stop and revisit the ADR if item verification needs more than one explicit
  producer event plus one deterministic projector policy per item kind.

## Deferred Decision

GitHub organization-level review-stage metrics may later be joined as an
external outcome benchmark. That requires a separate preflight covering API
availability, aggregation level, privacy, retention, and the mismatch between
human-review stages and gh-address-cr item lifecycle. It is not part of v1.
