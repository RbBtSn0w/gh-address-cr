# Phase 1 Data Model: Core-Path-Anchored Complexity Reduction

This feature removes code and amends governance; its "entities" are planning
constructs (not runtime dataclasses). They make the reduction traceable and
verifiable.

## ProtectedBaseline (the floor — FR-014)

The non-negotiable minimum that every stage must preserve.

| Field | Value | Rule |
|-------|-------|------|
| `core_journey` | findings → classify → reply + resolve → `final-gate` | MUST NOT be removed or degraded by any stage |
| `observability` | OpenTelemetry OTLP tracing **of the surviving core journey** (`telemetry.py`, `__main__.py`) | Kept because it traces live functionality; NOT an empty shell, and no removed-subsystem OTel plumbing retained (FR-006) |
| `expansion_rule` | any new subsystem beyond the baseline requires a recorded blast-radius justification | enforced by Principle X (US5) |

**Validation**: after every stage, the core smoke run passes and one OTel root
span still emits per invocation (SC-005/006).

## ReductionStage

One independently-shippable, revertable removal unit.

| Field | Type | Rule |
|-------|------|------|
| `id` | US5 / US1 / US2 / US3 / US4 | US5 is P0 and merges first (FR-015) |
| `targets` | list of files/dirs removed or amended | from the plan's removal map |
| `keep_list` | modules explicitly preserved | e.g. `runtime_kernel/final_gate.py`, `workflow.py`, OTel |
| `versioned` | bool | true if it removes a public command / public-contract shim (FR-008) |
| `green_gate` | full `unittest` + `ruff` + core smoke pass | MUST hold before merge (FR-009) |
| `evidence` | grep proofs + contract snapshots | no dangling import; no residual deprecated marker (US3); no stale `skill/` reference to a removed command or removed architecture; affected repo-root docs updated in the same change (FR-011, FR-017) |

**State transitions**: `planned → applied → green-verified → merged`. A stage that
fails its green gate reverts (git) rather than partially merging.

## DeletableLayer

An accreted subsystem scored for removal (source of the removal map).

| Field | Type | Rule |
|-------|------|------|
| `path` | module/package | e.g. `core/consolidation/` |
| `on_core_path` | bool | if true → not deletable (KEEP) |
| `blast_radius` | zero / low / medium / high | drives stage assignment |
| `verdict` | cut / shrink / demote / keep | per the inventory |
| `dependents` | modules importing it | must be zero on the core path before cut |

**Validation**: `on_core_path == true` ⇒ `verdict == keep`. A layer may be cut only
when its core-path dependents are zero.

## GovernanceDelta (US5)

The amendment applied to the two governance docs.

| Field | Type | Rule |
|-------|------|------|
| `principle` | VI / VIII / IX | relaxed from unconditional MUST → blast-radius-triggered |
| `added_principle` | X — Minimal Viable / Complexity Budget | new; defines the protected baseline + expansion rule |
| `agents_md_gate` | Architecture Preflight Gate | updated to fire only on blast-radius trigger |
| `version_bump` | MAJOR + Sync Impact Report | required (redefines architecture boundaries) |

**Validation (SC-009)**: post-amendment, no unconditional MUST that US1–US4 violate
remains; version bumped with a Sync Impact Report; AGENTS.md matches.

## Relationships

- `ReductionStage US5` produces the `GovernanceDelta` and MUST precede all others.
- Each code `ReductionStage` removes one or more `DeletableLayer`s and MUST
  preserve the `ProtectedBaseline`.
- Every stage that removes a public command triggers the skill-sync obligation
  (FR-017) and is `versioned`.
- Every stage that removes an externally-described surface must satisfy a
  same-change documentation sync obligation across both `skill/` and affected
  repo-root docs (FR-011).
