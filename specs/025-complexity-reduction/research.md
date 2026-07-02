# Phase 0 Research: Core-Path-Anchored Complexity Reduction

The deletable-layer inventory was produced by tracing the core journey and
measuring each accreted subsystem (LOC, dependents, blast radius). No open
`NEEDS CLARIFICATION`. Decisions below drive planning.

## R1 — Order the reduction by governance-first, then value ÷ risk

- **Decision**: `US5 (governance) → US1 (meta-layer) → US2 (dual engine) → US3
  (deprecated sweep) → US4 (telemetry/orchestrator)`.
- **Rationale**: Governance must precede code (FR-015) or every deletion violates
  the current constitution. Among code stages, blast radius rises left→right; US1
  is zero-core-dependency and reclaims the most weight fastest.
- **Alternatives considered**: (a) code-first, governance later — rejected: each
  stage fails its own Constitution Check. (b) telemetry-first — rejected: largest
  surface + most tests, worst risk-adjusted return early.

## R2 — Kernel fate: abandon the kernel-as-state-engine (keep `workflow.py`)

- **Decision**: `workflow.py`/`workflow_matching.py` stay as the single
  authoritative review engine; delete the kernel review-state-machine slice
  (`projections/policies/commands/events/identity/session_projection`); **keep
  `runtime_kernel/final_gate.py`** (hard-wired into `core/gate.py:16` for the gate
  verdict, both inline and `final-gate`).
- **Rationale**: The kernel review engine is dead beside `workflow.py` (consumed
  only by the now-removed 024 parity). Abandoning it matches the owner's
  simplification intent (spec Assumptions) at far lower risk than migrating.
- **Alternatives considered**: Commit to the kernel and delete `workflow.py`
  (~1,672 LOC) — rejected: heavier, higher-risk, contradicts the goal.

## R3 — Evidence gate for every deletion

- **Decision**: Delete an item only after (1) `ruff`/import graph shows no live
  importer on the core path, and (2) the full `unittest` suite stays green with
  that item's dedicated tests removed. Per-stage green is the merge gate (FR-009).
- **Rationale**: Prevents a dangling import or half-removed engine; makes each
  stage independently revertable via git.
- **Alternatives considered**: One big-bang removal — rejected: unattributable
  regressions, non-revertable.

## R4 — Versioning for public-surface removals

- **Decision**: Removing `evaluation`/`consolidation` commands and any
  public-contract shim is a **versioned** change (bump per Compatibility Policy)
  with help/metavar, `skill/` guidance, and tests updated in the same commit.
  Core-command machine summaries stay byte-for-byte identical (SC-004).
- **Rationale**: Constitution II + AGENTS Compatibility Policy require preserved-
  or-versioned public contracts.
- **Alternatives considered**: Silent removal — rejected: forbidden by policy and
  breaks installed agents.

## R5 — Deprecated-code sweep is evidence-gated, not blind

- **Decision**: After US1 removes `core/consolidation/` (which holds ~100 of the
  133 markers), drive remaining `deprecated`/`legacy`/`compat`/`shim` markers in
  `src/` to zero — `(all hits) − (entries in `.deprecated-allowlist.txt`) == 0`,
  the allowlist enumerating each intentionally-retained match with a reason; each
  removal gated on no live consumer; any still-referenced public-contract shim
  removed via a versioned change (FR-016).
- **Rationale**: Finishes the convergence without risking a live shim.
- **Alternatives considered**: Keep referenced shims indefinitely — rejected:
  leaves known debt; blind delete-all — rejected: could drop a live contract shim.

## R6 — OpenTelemetry rides with surviving business functionality (not an empty shell)

- **Decision**: Keep OpenTelemetry **as observability of the surviving core
  journey** — the OTLP span in `telemetry.py`/`__main__.py` keeps tracing the live
  CLI invocation. Do **not** retain an empty-shell OTel wrapper solely to honor
  "keep OTel", and remove any OTel plumbing/instrumentation that only served a
  removed subsystem. Shrink `core/telemetry*.py`/`host_telemetry/` to a minimal
  optional, off-by-default, fail-open hook; core review/resolve/gate must complete
  when it is absent. The `final-gate` efficiency-report text degrades gracefully,
  never the verdict.
- **Clarification (Session 2026-07-01)**: "Keep OTel" is conditional on live
  business functionality, not an unconditional protection of OTel code. Business
  function first; OTel is kept where and because it traces it.
- **Rationale**: Owner directive (FR-006/014) + Constitution VIII (post-amendment)
  keeps tracing as observability while removing the heavy attribution weight.
- **Alternatives considered**: Delete all telemetry — rejected: violates the
  OpenTelemetry floor. Keep the full cluster — rejected: 2,697 LOC the core path
  doesn't need.

## R7 — Governance amendment shape (US5)

- **Decision**: Constitution MAJOR bump with a Sync Impact Report. Relax VI/VIII/IX
  from unconditional MUST to **blast-radius-triggered** (they apply when a change's
  blast radius crosses a defined threshold, e.g. multi-agent work, external
  telemetry ingestion, or new runtime state axes). Add Principle **X — Minimal
  Viable / Complexity Budget**: the protected baseline (core journey +
  OpenTelemetry) is the floor; any new subsystem beyond it requires a recorded
  blast-radius justification. Update AGENTS.md's Architecture Preflight Gate to
  fire only on that trigger.
- **Rationale**: Removes the accretion engine (universal heavy MUSTs) while keeping
  the discipline where it actually matters.
- **Alternatives considered**: Delete principles VI/VIII/IX outright — rejected:
  they still matter for genuinely high-blast-radius work; make them conditional
  instead. Leave governance unchanged — rejected: the reduction would be illegal
  and regrow (the whole reason for the clarification).

## R8 — Skill sync in lockstep

- **Decision**: In every stage that removes a command, update `skill/SKILL.md`,
  `skill/references/{agent-protocol,mode-producer-matrix,status-action-map}.md`,
  and `skill/agents/openai.yaml` so no installed guidance references a removed
  command or removed architecture (FR-017); when the removal changes the public
  command surface or runtime architecture described in repo-root docs, update
  those docs in the same change as well (FR-011); ship together as one
  versioned change.
- **Rationale**: The installed skill is the agent's instruction surface; stale
  references would send agents to non-existent commands, and stale repo-root docs
  would leave contributor guidance out of sync with the reduced surface.
- **Alternatives considered**: Update skill/docs in a later pass — rejected:
  leaves a window where the shipped guidance lies about the CLI or architecture.
