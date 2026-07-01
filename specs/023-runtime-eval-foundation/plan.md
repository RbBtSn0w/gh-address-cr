# Implementation Plan: Read-Only Evaluation Plane

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Branch**: `023-runtime-eval-foundation` | **Date**: 2026-06-30 | **Spec**: [spec.md](spec.md)  
**Input**: Feature specification from `specs/023-runtime-eval-foundation/spec.md`

## Summary

Add a deterministic, read-only evaluation subsystem that projects archived runtime evidence and later GitHub observations into versioned per-concern and per-run records. The subsystem will distinguish provisional from durable verification, report dimensional evidence coverage, calculate concurrency-aware workflow cost, and compare matched runtime cohorts without allowing evaluation output to mutate review state or satisfy `final-gate`.

The implementation extends the normal archive path with a public-safe `run-manifest.v1` artifact, stores later reviewer observations in an evaluation-only append-only ledger, and rebuilds a local SQLite catalog from those source artifacts. The catalog and comparison reports are disposable projections. Missing or unsupported evidence returns `INSUFFICIENT_EVIDENCE`; missing optional evaluation evidence remains fail-open for review resolution.

## Technical Context

**Language/Version**: Python 3.10+  
**Primary Dependencies**: Python standard library (`dataclasses`, `datetime`, `hashlib`, `json`, `sqlite3`, `statistics`); existing `packaging>=24`; existing GitHub CLI integration  
**Storage**: Existing JSON/JSONL PR workspaces and archives; append-only evaluation observation JSONL; rebuildable SQLite catalog and derived JSON reports under the runtime state directory  
**Testing**: `unittest`, fixture-driven replay and CLI contract tests; `ruff`; strict `mypy` ratchet  
**Target Platform**: Local-first macOS and Linux CLI environments with Python 3.10+ and `gh` for live observation capture  
**Project Type**: Python CLI/runtime package with an installable thin skill adapter  
**Performance Goals**: Added normal final-gate manifest/evaluation capture stays within the existing 250 ms telemetry normal-path budget; catalog queries over 10,000 runs complete within 2 seconds on a typical local development machine; interval-union timing remains linearithmic in span count  
**Constraints**: Evaluation is read-only with respect to runtime truth and GitHub review state; core review flows remain fail-open for missing evaluation/host telemetry; evaluation commands fail loudly on malformed, unsafe, ambiguous, or unsupported input; no raw prompts, credentials, usernames, private machine identifiers, or unnecessary absolute paths are stored; public contracts are additive and versioned  
**Scale/Scope**: First supported cohort covers the normal GitHub review-thread flow; design target is at least 10,000 archived runs and 250,000 concern records without introducing an external database service

## Constitution Check

*GATE: PASS before Phase 0 research. Re-checked after Phase 1 design: PASS.*

- **Control plane ownership — PASS**: Runtime session state, evidence ledger records, GitHub reply/resolve execution evidence, and final-gate remain authoritative. Evaluation modules only read archives and write evaluation-owned projections.
- **First-principles runtime kernel — PASS**: Inputs, projections, policy, local artifact writes, recovery, and replay are explicit in the Architecture Preflight below. Evaluation has no GitHub mutation command plan.
- **Public CLI contract — PASS**: The existing `review`, `address`, `agent`, `telemetry`, and `final-gate` behavior remains unchanged. A new advanced `evaluation` command family and versioned machine schemas are additive.
- **Evidence-first handling — PASS**: Provisional verification requires classification, reply, required resolve/publish, and passing final-gate evidence. Durable verification requires a later supported reviewer observation.
- **Packaged skill boundary — PASS**: Deterministic implementation and tests stay in repo-root runtime paths. Skill changes, if later required, are limited to routing and interpretation guidance.
- **External intake replaceability — PASS**: Evaluation consumes versioned runtime/archive contracts and vendor-neutral host telemetry; it does not depend on one review producer.
- **Telemetry evidence boundary — PASS**: Source attribution, dimensional coverage, safety filtering, deduplication, fail-open core workflows, and fail-loud evaluation commands are explicit.
- **Architecture plateau discipline — PASS**: A dedicated evaluation package provides one projection and comparison policy instead of extending `telemetry.py`, `cr_metrics.py`, or final-gate with more scoring branches.
- **Fail-fast verification — PASS**: Contract, replay, CLI, safety, archive, timing, deduplication, and failure-boundary tests are included in the design.

## Architecture Preflight

### Authoritative owners

- Review/session truth: `session.json`, evidence ledger records, runtime-kernel projections, recorded GitHub side-effect results, and final-gate result.
- Workflow telemetry truth: existing runtime and external telemetry stores with their fingerprints and source attribution.
- Evaluation-only later observations: versioned append-only observation ledger rows captured from read-only GitHub queries.
- Evaluation records, SQLite catalog, and comparison reports: derived projections only; never accepted as runtime facts.

### External facts and event inputs

- Archived `session.json`, `evidence.jsonl`, `audit.jsonl`, `trace.jsonl`, `efficiency-report.json`, and final-gate summary evidence.
- `run-manifest.v1.json`, finalized only after all normal final-gate artifacts and any archive path rewrites are stable.
- Runtime and host operation spans with source identity, timestamps, duration, status, and correlation identifiers.
- Later GitHub review-thread/review-round observations captured after provisional verification, including observed head revision and deterministic observation fingerprint.

### Projection and policy

- `ArchiveProjector` validates one archived run and produces concern-level and run-level `evaluation.v1` records.
- `CoveragePolicy` independently evaluates workflow, timing, token, and outcome coverage and returns exact evidence deficits.
- `VerificationPolicy` derives provisional and durable states without mutating source evidence.
- `ComparisonPolicy` selects compatible cohorts, enforces minimum samples and quality guardrails, and returns dimension-specific results or `INSUFFICIENT_EVIDENCE`.

### Side-effect and outbox boundary

- Live observation capture performs GitHub reads only; no reply, resolve, review submission, or PR mutation is permitted.
- Local writes are limited to atomic manifest/report writes, append-only observation records with deterministic fingerprints, and transactional catalog replacement. Manifest digests are computed only after archive path rewriting is complete and never include the manifest itself.
- A failed optional manifest or projection write is surfaced in final-gate diagnostics but does not change final-gate truth. Explicit `evaluation` commands fail non-zero on the same error.

### Artifact truth and self-reference boundary

- Archived runtime evidence and observation ledger rows are evaluation inputs.
- `evaluation.v1` rows, SQLite tables, and comparison reports are rebuildable outputs and can be deleted without losing runtime or observation truth.
- Evaluation overhead measures input validation, projection, and report construction but excludes the final persistence write to avoid recursive self-measurement; the excluded boundary is reported.

### Recovery, replay, and executable contracts

- Catalog recovery deletes or atomically replaces the derived database and replays all supported archives plus observation rows.
- Duplicate manifests, observations, and archive scans converge through stable fingerprints and uniqueness constraints.
- Contract fixtures prove deterministic projection, hybrid verification, interval union, privacy rejection, duplicate handling, unsupported evidence, cohort matching, and zero mutation of runtime/final-gate state.

## Project Structure

### Documentation (this feature)

```text
specs/023-runtime-eval-foundation/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── evaluation-cli.md
│   ├── evaluation-v1.md
│   └── run-manifest-v1.md
└── tasks.md
```

### Source Code (repository root)

```text
src/gh_address_cr/
├── cli.py
├── commands/
│   ├── evaluation.py
│   └── final_gate.py
├── core/
│   ├── evaluation/
│   │   ├── __init__.py
│   │   ├── models.py
│   │   ├── archive.py
│   │   ├── observations.py
│   │   ├── projector.py
│   │   ├── coverage.py
│   │   ├── timing.py
│   │   ├── catalog.py
│   │   └── comparison.py
│   ├── paths.py
│   ├── telemetry_models.py
│   └── telemetry_safety.py
└── github/
    └── client.py

tests/
├── fixtures/
│   └── evaluation/
├── core/
│   └── test_evaluation.py
├── test_evaluation_cli.py
└── test_final_gate.py
```

**Structure Decision**: Use a focused `core/evaluation/` package because archive reading, observation capture, projections, coverage, timing, catalog persistence, and comparison are independently testable responsibilities. `commands/evaluation.py` is a thin CLI adapter. `final_gate.py` only invokes manifest construction and reports diagnostics; it does not contain evaluation policy.

## Delivery Plan

The slices below define dependency order and independently shippable capability boundaries; they are not implementation tasks. `/speckit.tasks` MUST decompose them into 2–5 minute TDD steps. No generated task may modify more than two files or introduce more than 100 lines of production code without further decomposition.

### Slice 1 — Contracts, models, and archive manifest

- Add versioned data models and validation for run manifests, observations, coverage, concern records, run records, and comparison results.
- Add evaluation paths without changing existing telemetry paths.
- Build manifest metadata during final-gate, then write `run-manifest.v1.json` into the final stable target: the workspace after all artifacts for `--no-auto-clean`, or the archive after copy and path rewriting for auto-clean.
- Keep manifest failure fail-open for final-gate and fail-loud for explicit validation commands.

### Slice 2 — Deterministic projection and hybrid verification

- Load and validate archived evidence without writing to the archive.
- Project provisional verification from classification, accepted/published response, reply, resolve, and passing final-gate evidence.
- Capture and deduplicate read-only later GitHub observations.
- Project durable verification only from supported correlated observations; leave unsupported cases unknown.

### Slice 3 — Dimensional coverage and workflow economics

- Derive independent workflow, timing, token, and outcome coverage with evidence deficits.
- Preserve runtime-owned `ExecutionMetric` start/end timestamps when normalizing them into telemetry events, and instrument the centralized GitHub command runner so supported CLI and GitHub operations emit measured intervals with correlation identity.
- Replace summed duration as wall time with interval-union active time while retaining separately labeled resource time.
- Split expected control-flow rejections from actionable workflow/protocol failures.
- Measure evaluation overhead against the 250 ms normal-path budget without self-referential persistence timing.

### Slice 4 — Rebuildable catalog and CLI

- Build a versioned SQLite catalog in a temporary file and atomically replace the previous catalog only after successful replay.
- Add `evaluation observe`, `evaluation rebuild`, `evaluation show`, and `evaluation compare` as advanced additive CLI commands.
- Keep JSON the default machine format and make Markdown an explicit presentation option.

### Slice 5 — Matched comparison and regression guardrails

- Match supported runs by declared complexity buckets and runtime version.
- Require at least 10 eligible runs per compared cohort in the initial comparison policy.
- Report sample size, median, p90 where supported, quality rates, and deterministic uncertainty bounds.
- Return `INSUFFICIENT_EVIDENCE` for missing coverage, samples, correlation, or cohort compatibility; never collapse dimensions into one score.

## Requirement Coverage

| Specification requirements | Delivery coverage | Contract/design evidence |
|---|---|---|
| FR-001–FR-006 | Slices 1–2 | `evaluation.v1`, hybrid verification rules, evidence pointers |
| FR-007–FR-010 | Slices 2–3 | Dimensional coverage and outcome-state model |
| FR-011–FR-013 | Slice 3 | Workflow cost model, runtime-owned intervals, interval union |
| FR-014–FR-015 | Slice 5 | Cohort policy and unsupported-claim guard |
| FR-016–FR-020 | Slices 1–4 | Safety boundary, manifests, dedupe, deficits, fail-open/fail-loud contracts |
| FR-021 | Slice 3 | Expected versus actionable rejection taxonomy |
| FR-022 | Slice 5 | Version grouping, sample/distribution/uncertainty report |
| FR-023 | Slices 1 and 3 | 250 ms overhead budget and non-self-referential timing boundary |
| SC-001–SC-003 | Slice 2 | Hybrid verification replay fixtures |
| SC-004–SC-006 | Slices 3 and 5 | Coverage, insufficiency, and quality guardrail tests |
| SC-007–SC-008 | Slice 3 | Interval-union and fail-open telemetry tests |
| SC-009–SC-010 | Slices 2 and 4 | Deterministic rebuild and zero-mutation tests |
| SC-011–SC-012 | Slices 3 and 5 | Distribution and overhead acceptance tests |

## Phase 0: Research Output

Research decisions and rejected alternatives are documented in [research.md](research.md). All technical questions required for planning are resolved.

## Phase 1: Design Output

- Entity fields, relationships, validation rules, and derived state transitions: [data-model.md](data-model.md)
- Public CLI, reason codes, exit codes, and failure boundaries: [contracts/evaluation-cli.md](contracts/evaluation-cli.md)
- Evaluation record and comparison schema: [contracts/evaluation-v1.md](contracts/evaluation-v1.md)
- Archive manifest contract and truth boundary: [contracts/run-manifest-v1.md](contracts/run-manifest-v1.md)
- Runnable end-to-end validation scenarios: [quickstart.md](quickstart.md)

## Post-Design Constitution Re-check

**Result: PASS.** The Phase 1 design preserves all pre-research gates. In particular, the observation ledger is explicitly evaluation-only, the catalog is rebuildable, final-gate remains authoritative and fail-open for optional evidence, explicit evaluation commands remain fail-loud, and no skill-owned file is assigned deterministic logic.

## Complexity Tracking

No constitution violations require justification.
