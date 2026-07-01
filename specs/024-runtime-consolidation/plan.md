# Implementation Plan: Evidence-Gated Runtime Consolidation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Branch**: `024-runtime-consolidation` | **Date**: 2026-07-01 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/024-runtime-consolidation/spec.md`

## Summary

Consolidate the runtime onto the event-sourced `runtime_kernel` (issue #173) by
delivering a **reversible migration framework** plus its first slices, instead of
one rewrite. The plan introduces a machine-readable **Runtime Authority Map**
(one owner per state axis), a **Migration Slice** contract, a side-effect-free
**Parity Observation** harness that replays runtime facts through legacy and
kernel paths, and a deterministic **Rollout Gate** / **Rollback Trigger** state
machine that governs shadow → opt-in → default → deprecation → deletion stages.
Feature 023's read-only evaluation plane supplies the *outcome/cost* evidence a
slice needs to advance, but never becomes runtime truth or `final-gate` evidence.

Duplicate-ownership targets from #173 (lease state, PR check state, local
findings triage, and eventually imperative transitions in `workflow.py` /
`workflow_matching.py`) each migrate as an independent slice behind explicit
enablement. The three optimization hypotheses (output truncation,
`command-session` adoption, workflow-surface deletion) are tracked as separate
Optimization Hypotheses with independent guardrails and rollback. No legacy path
is deleted on provisional evidence alone; deletion additionally requires a
completed deprecation window and passing feature-023 durable evidence.

## Technical Context

**Language/Version**: Python 3.10+ (enforced by `pyproject.toml`)
**Primary Dependencies**: Python standard library (`dataclasses`, `enum`, `json`, `hashlib`, `datetime`); existing `packaging>=24`; existing `runtime_kernel` (018), evaluation plane (023), and `gh` CLI integration
**Storage**: Existing JSON/JSONL PR workspaces (`session.json`, `evidence.jsonl`, `audit.jsonl`, `trace.jsonl`) as authoritative facts; a new versioned, human-editable **rollout-state** artifact (`rollout-state.v1`) recording per-slice stage and enablement; rebuildable parity/evaluation reports as disposable projections
**Testing**: `unittest` with fixture-driven replay and CLI contract tests; `ruff`; strict `mypy` ratchet (per repo quality gates)
**Target Platform**: Local-first macOS and Linux CLI environments with Python 3.10+ and `gh`
**Project Type**: Single Python CLI/runtime package with an installable thin skill adapter under `skill/`
**Performance Goals**: Parity observation for a supported PR replays within the existing final-gate/telemetry normal-path budget (≤250 ms added on the normal path); shadow comparison adds zero GitHub side effects; slice enablement lookup is O(number of slices)
**Constraints**: Migration is additive and reversible per slice; core review flows (`review`, `address`, publish, reply, resolve, `final-gate`) remain fail-open for missing evaluation/telemetry evidence; ambiguous or duplicate state ownership fails loudly; public CLI, machine summaries, reason codes, wait states, and structured agent contracts are preserved or explicitly versioned; no reporting artifact is treated as authoritative truth; rollback never rewrites runtime facts
**Scale/Scope**: First cohort is the normal GitHub review-thread flow already supported by 023; framework must accommodate the full #173 axis inventory (leases, checks, local findings, imperative transitions) plus three optimization hypotheses without a second rewrite

## Constitution Check

*GATE: PASS before Phase 0 research. Re-checked after Phase 1 design: PASS.*

- **Control plane ownership — PASS**: The Runtime Authority Map keeps runtime
  state, GitHub side effects, reply evidence, leases, and final-gate inside
  deterministic code. The rollout-state artifact governs *which projection path
  is authoritative* per slice; it never becomes review-resolution truth. Parity
  observation is read-only.
- **First-principles runtime kernel — PASS**: Each slice is defined by external
  facts, one authoritative projection, deterministic policy, an idempotent
  command/outbox plan, recorded execution evidence, and replay/contract tests.
  The framework's job is to move ownership of an axis *into* this kernel model,
  reducing scattered imperative branches in `workflow.py`.
- **Public CLI contract — PASS**: `review`, `address`, `threads`, `agent`,
  `telemetry`, and `final-gate` behavior is preserved. New surface is additive:
  an advanced `consolidation` / rollout command family, the `rollout-state.v1`
  artifact, and versioned parity/authority schemas. Output truncation and the
  `workflow_decision.v1` handoff are versioned public-contract changes, not
  silent defaults. The Status-to-Action Map is unchanged until a slice versions it.
- **Evidence-first handling — PASS**: Review items are still verified,
  classified `fix`/`clarify`/`defer`/`reject`, replied, resolved, and proven by
  `final-gate` from runtime facts. Feature 023 evidence gates *rollout*, not
  completion.
- **Packaged skill boundary — PASS**: All migration logic and tests stay in
  repo-root runtime paths (`src/gh_address_cr/...`, `tests/...`). Skill changes,
  if any, are limited to Status-to-Action routing and diagnostics guidance under
  `skill/`.
- **External intake replaceability — PASS**: Slices consume versioned
  runtime/archive/finding contracts; consolidation does not couple the control
  plane to a specific review producer.
- **Telemetry evidence boundary — PASS**: Telemetry and evaluation observe cost
  and health and can *limit* rollout evidence, but missing optional telemetry
  never blocks review completion and never owns review state.
- **Architecture plateau discipline — PASS**: Each slice must reduce a duplicate
  owner or decision surface (FR-020 / SC-010). A slice that adds hidden
  fallbacks, artifact-backed truth, duplicate decision surfaces, or new state
  flags without reducing ambiguity is rejected and forces a spec revision.
- **Fail-fast verification — PASS**: Ambiguous ownership, malformed facts,
  inconsistent execution references, unsafe contract changes, and unsupported
  rollout claims fail loudly; each changed public behavior/parser/CLI surface
  gets contract or replay tests.

No violations — Complexity Tracking is empty.

## Architecture Preflight

*Required by AGENTS.md / Constitution Principle IX — this feature touches runtime
state, leases, checks, final-gate, telemetry attribution, and GitHub side
effects. Each concrete slice re-runs this preflight; the entries below are the
framework-level owners.*

### Authoritative owners

- **Review/session truth**: `session.json` facts, `evidence.jsonl` execution
  records, `runtime_kernel` projections, recorded GitHub side-effect results,
  and the `final-gate` result. Unchanged.
- **Per-axis authority**: The **Runtime Authority Map** declares exactly one
  owner (legacy `workflow`/`leases`/imperative path *or* a `runtime_kernel`
  projection) for each migrated axis, plus the derived compatibility direction.
- **Rollout truth**: The `rollout-state.v1` artifact owns each slice's current
  stage and enablement flag. It is authoritative for *rollout*, not for review
  resolution; disabling a slice never edits runtime facts.
- **Evaluation/parity outputs**: Feature-023 records and parity reports are
  derived projections only.

### External facts and event inputs

- Existing runtime facts (`REVIEW_THREAD_OBSERVED`, `COMMAND_EXECUTED`,
  `REPORTING_OBSERVED`, …) plus the new modeled fact events required by #173
  slices (`lease_acquired`/`lease_expired`, `check_state_observed`,
  `finding_ingested`) once their slice is designed.
- The `rollout-state.v1` artifact (operator/CI-controlled stage + enablement).
- Feature-023 `evaluation.v1` comparison results consumed read-only as rollout
  evidence.

### Projection and policy

- **AuthorityMap** projection: derives, for the active runtime version, which
  axes are kernel-authoritative and which remain legacy-owned; detects and fails
  loudly on duplicate or ambiguous ownership (FR-005, SC-001).
- **ParityObserver**: replays the same facts through legacy and candidate
  projections and compares projections, policy decisions, and command *plans*
  (not executions) into a `parity-report.v1`. Side-effect-free.
- **RolloutPolicy**: a deterministic function over `(rollout-state, parity
  evidence, feature-023 evidence, quality/health guardrails)` returning the
  permitted next stage or a block/rollback reason code (FR-008, FR-014).

### Side-effect and outbox boundary

- Parity observation performs **zero** GitHub side effects and executes **no**
  command plans; it only compares planned commands (Edge Case: shadow must not
  duplicate side effects; SC-003).
- The only writes are atomic `rollout-state.v1` transitions and atomic
  parity/report artifact writes.
- When a slice is enabled as default, the authoritative projection for that axis
  switches to the kernel path; the legacy path remains callable (non-authoritative)
  until its deprecation window completes.

### Artifact truth and self-reference boundary

- `rollout-state.v1` is a versioned *control* artifact, not review truth.
- Parity reports and feature-023 records are rebuildable and deletable without
  losing runtime or observation truth (SC-005).
- Rollback restores the prior authoritative projection path via a
  `rollout-state` transition and never reconstructs review state from a report
  (Edge Case; FR-016).

### Recovery, replay, and executable contracts

- Any enabled slice can be disabled by a single `rollout-state` transition;
  runtime facts and execution evidence are untouched (SC-005).
- Contract fixtures prove: single-owner authority, loud failure on duplicate
  ownership, deterministic parity replay, zero side effects during shadow,
  rollout-gate stage transitions, rollback resumption, and independent
  accept/reject/rollback of the three optimization hypotheses (SC-002…SC-010).

## Project Structure

### Documentation (this feature)

```text
specs/024-runtime-consolidation/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output (authority-map, migration-slice, parity-report, rollout-state schemas)
├── checklists/          # Pre-existing spec checklists
└── tasks.md             # Phase 2 output (/speckit.tasks — NOT created here)
```

### Source Code (repository root)

```text
src/gh_address_cr/
├── core/
│   ├── consolidation/               # NEW: reversible migration framework
│   │   ├── __init__.py
│   │   ├── types.py                 # Shared enums (StateAxis, Owner, CompatibilityDirection, RolloutStage) + schema-version constants
│   │   ├── authority_map.py         # Runtime Authority Map projection + duplicate-owner fail-loud
│   │   ├── migration_slice.py       # Migration Slice contract + acceptance-gate + state-space-reduction check
│   │   ├── parity.py                # ParityObserver: side-effect-free legacy/candidate comparison
│   │   ├── rollout.py               # RolloutPolicy + Rollout Gate/Rollback Trigger state machine
│   │   ├── rollout_state.py         # rollout-state.v1 load/validate/atomic-write
│   │   ├── optimization.py          # OptimizationHypothesis registry (truncation/session/surface-removal)
│   │   ├── evidence.py              # Read-only feature-023 evaluation.v1 → rollout evidence adapter
│   │   └── deprecations.py          # deprecation-inventory.v1 (FR-017): duplicate models/shims/telemetry fields
│   ├── runtime_kernel/              # EXISTING kernel — slices add modeled facts/projections here
│   │   ├── events.py                # + lease/check/finding fact events (per slice, when designed)
│   │   └── projections.py           # + migrated-axis projections (per slice)
│   ├── workflow.py                  # Legacy path — reduced to boundary coordinator as slices land
│   └── workflow_matching.py         # Legacy path — deprecated/deleted only after final slice gate
├── commands/
│   └── consolidation.py             # NEW: advanced `consolidation` CLI family (status/parity/rollout)
└── core/evaluation/                 # EXISTING (023) — consumed read-only as rollout evidence

tests/
├── consolidation/                   # NEW: authority, parity, slice, rollout, rollback, deprecation tests
│   ├── test_authority_map.py
│   ├── test_parity_observation.py
│   ├── test_migration_slice.py
│   ├── test_rollout_state.py
│   ├── test_rollout_gate.py
│   ├── test_rollback.py
│   ├── test_deprecations.py
│   ├── test_optimization_hypotheses.py
│   ├── test_evidence_consumption.py
│   └── test_performance_budget.py
├── contract/                        # + test_consolidation_cli.py, test_public_contract_stability.py
└── (existing unit/integration tests)
```

**Structure Decision**: Single-project Python package (Option 1). Consolidation
logic lives in a dedicated `core/consolidation/` package so the migration
framework is one authority/parity/rollout surface rather than new branches
scattered across `workflow.py`, `telemetry.py`, or `final_gate.py` — directly
satisfying architecture-plateau discipline (SC-010). Per-slice modeled facts and
projections extend the existing `runtime_kernel` package. The advanced CLI family
is additive and does not alter the `review` default orchestration path.

## Complexity Tracking

> No Constitution Check violations — this section is intentionally empty.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| —         | —          | —                                   |
