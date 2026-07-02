# Implementation Plan: Core-Path-Anchored Complexity Reduction

**Branch**: `025-complexity-reduction` | **Date**: 2026-07-01 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/025-complexity-reduction/spec.md`

## Summary

Reduce the codebase back to the protected baseline: the core PR-review
resolution journey plus OpenTelemetry of that live journey. The plan removes
off-core-path layers in strict stages: governance first, then consolidation /
evaluation, then the duplicate kernel review engine, then dead scraps, then the
internal telemetry and orchestration surplus. Every stage is independently
green, versioned when public CLI surface changes, and must update both `skill/`
and affected repo-root docs in the same change.

## Technical Context

**Language/Version**: Python 3.10+ (enforced by `pyproject.toml`)  
**Primary Dependencies**: Python stdlib; `opentelemetry`; `requests`; `packaging`; `gh` CLI  
**Storage**: Local filesystem artifacts and session/evidence files under the existing runtime layout; no new storage introduced  
**Testing**: `python3 -m unittest discover -s tests`, `ruff check src tests scripts/build_plugin_payload.py`, CLI smoke checks, protected-layer import assertions, grep-based removal proofs  
**Target Platform**: Local-first macOS/Linux CLI with Python 3.10+ and authenticated `gh`  
**Project Type**: Single Python CLI/runtime package with a thin published skill under `skill/`  
**Performance Goals**: Preserve core command semantics and machine-readable outputs; keep `final-gate` verdicts byte-for-byte stable where specified; remove at least 4,500 LOC across US1-US3 without regressing the protected baseline  
**Constraints**: Protected baseline = core journey + OpenTelemetry of that journey (FR-014); public-command removals are explicit versioned contract changes (FR-008); each stage must leave the suite green with no dangling imports or half-removed engine (FR-009); removed subsystems must also lose their docs and skill references in the same change (FR-011/FR-017)  
**Scale/Scope**: Remove `core/consolidation/`, `core/evaluation/`, kernel review-state-machine modules, deprecated/legacy scraps, most internal telemetry attribution plumbing, and default-orchestrator weight; amend `.specify/memory/constitution.md`, `AGENTS.md`, `skill/`, and affected repo-root docs

## Constitution Check

*GATE: This feature intentionally amends the governing constitution as US5. The
pre-amendment evaluation below identifies which principles are intentionally
relaxed and why that amendment must land first.*

- **I. Control Plane Owns Runtime State — PASS**: Runtime state, GitHub side
  effects, reply/resolve evidence, and `final-gate` ownership remain in
  deterministic runtime code. Removed layers never own review-resolution truth.
- **II. CLI Is The Stable Public Interface — PASS (versioned)**: The core
  `review`-led interface remains stable. Removing `consolidation`,
  `evaluation`, and any removed telemetry subcommands is treated as a versioned
  CLI-contract change with help, metavar, tests, and guidance updated together.
- **III. Evidence-First Review Handling — PASS**: Verify/classify/reply/resolve
  behavior and `final-gate` proof remain on the protected baseline and are not
  relaxed.
- **IV. Packaged Skill Boundary Is Explicit — PASS**: `skill/` stays a thin
  adapter / behavioral policy layer. Guidance is pruned in lockstep, but no
  runtime logic moves into the skill.
- **V. Testable Contracts — PASS**: Every public-behavior removal is verified by
  tests, smoke checks, or explicit grep/import proofs in the same stage.
- **VI. Multi-Agent Coordination and Claim Leases — AMENDED by US5**: The
  current constitution makes multi-agent coordination mandatory. US4 demotes
  orchestration to optional and keeps single-agent as the default supported
  path. This is resolved by making Principle VI blast-radius-triggered.
- **VII. External Intake Is Replaceable — PASS**: Intake contracts and producer
  replaceability remain untouched.
- **VIII. Telemetry Is Attributed Observed Evidence — AMENDED by US5**: The full
  attribution/fingerprint/coverage contract becomes mandatory only for external
  telemetry ingestion. Core-path OpenTelemetry remains protected.
- **IX. First-Principles Runtime Kernel — AMENDED by US5**: `final-gate`
  continues to use fact -> projection -> policy via
  `runtime_kernel/final_gate.py`, but the broader duplicate kernel review engine
  is removed. This is resolved by making the larger kernel requirement
  blast-radius-triggered instead of universal.
- **Architecture Preflight / Plateau Discipline — PASS (remedy)**: The plan
  reduces state space and duplicate ownership. It removes branches and layers
  rather than adding new fallback paths or artifact-backed truth.

**Gate result**: PASS, conditional on **US5 landing first**. No code-removal
stage may merge before the governance amendment lands (FR-015).

## Architecture Preflight

*Required because the reduction touches runtime state boundaries, `final-gate`,
telemetry, orchestration, public CLI surface, and agent guidance.*

- **Authoritative state owners**: `session.json` and related runtime session
  state remain authoritative; GitHub reply/resolve execution evidence remains
  owned by runtime code and persisted by existing session/evidence flows;
  `core/gate.py` + `runtime_kernel/final_gate.py` remain authoritative for
  completion truth.
- **External facts / event inputs**: GitHub review threads, normalized findings,
  pending review state, CLI command inputs, agent action requests, telemetry
  observations, and verification command outputs remain the only inputs that
  affect review-resolution truth.
- **Projection / derived-state shape**: The surviving gate slice keeps
  fact-derived projections for `final-gate`; deleted review-state-machine
  projections are non-authoritative duplicates and are removed rather than
  replaced.
- **Policy / decision functions**: The authoritative review engine remains
  `workflow.py` / `workflow_matching.py`; the surviving gate policy remains in
  `runtime_kernel/final_gate.py`; removed command surfaces must fail loudly as
  unknown commands.
- **Side-effect / outbox boundary**: GitHub reply and resolve side effects stay
  in the existing publisher / client path. This feature does not move or widen
  that boundary.
- **Artifact truth boundary**: Baseline snapshots, grep proofs, allowlists,
  machine-summary captures, and docs are evidence artifacts only. They are never
  authoritative runtime state.
- **Recovery / replay**: Each stage is independently revertable through git. No
  stage may leave a partial engine or dangling import. No runtime fact is
  rewritten.
- **Executable contract tests**: Full unit suite, `ruff`, CLI smoke, protected
  import assertions, representative `final-gate` comparisons, removed-command
  unknown-command checks, `skill/` grep checks, and repo-root docs sync checks.

## Project Structure

### Documentation (this feature)

```text
specs/025-complexity-reduction/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── README.md
└── tasks.md
```

### Removal / amendment map (repository root)

```text
GOVERNANCE (US5, P0 — lands first)
  .specify/memory/constitution.md   # relax VI/VIII/IX -> blast-radius-triggered; add Principle X; MAJOR bump + Sync Impact Report
  AGENTS.md                         # Architecture Preflight Gate -> blast-radius-triggered; prune references to removed layers

CODE REMOVAL (staged; each stage independently green)
  US1  src/gh_address_cr/core/consolidation/**   + commands/consolidation.py + cli.py wiring + protocol codes + tests
       src/gh_address_cr/core/evaluation/**       + commands/evaluation.py    + cli.py wiring + final_gate.py manifest call + tests
       skill/** + repo-root command-surface docs  # remove consolidation/evaluation guidance in the same change
  US2  src/gh_address_cr/core/runtime_kernel/{projections,policies,commands,events,identity,session_projection}.py + tests
       keep src/gh_address_cr/core/runtime_kernel/final_gate.py
       skill/** architecture guidance             # remove dual-engine / kernel-review-engine descriptions in the same change
  US3  src/gh_address_cr/cli.py (_legacy_module, unsupported reject table, overlapping command sets)
       src/gh_address_cr/github/{replies.py,threads.py} unused wrappers
       remaining deprecated/legacy/compat/shim code -> allowlist-scoped zero
  US4  src/gh_address_cr/core/telemetry*.py + core/host_telemetry/** shrink/remove
       orchestrator/** demoted to optional default path
       skill/** + repo-root telemetry/orchestration docs  # remove stale guidance in the same change
  CROSS README.md and any affected repo-root developer docs must stay aligned with each story-local removal, not only at the final sweep
```

**Structure Decision**: No new runtime structure is introduced. This feature is
deletion + governance amendment across the existing CLI/runtime package and
published skill. Ordering is strict: **US5 -> US1 -> US2 -> US3 -> US4**, with
story-local docs and skill sync landing in the same change as each affected
surface.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| Principle IX universal kernel requirement | The duplicate kernel review engine is dead weight; only the `final-gate` slice is load-bearing | Finishing the kernel migration is heavier, riskier, and opposite to the reduction goal |
| Principle VI universal multi-agent requirement | The default supported path should be single-agent; orchestration becomes optional | Keeping orchestration mandatory forces multi-agent weight onto the common path |
| Principle VIII full telemetry contract for all core flows | Internal efficiency telemetry is being shrunk while core-path OpenTelemetry remains | Keeping the full attribution/fingerprint cluster preserves large off-core-path weight with little benefit |
