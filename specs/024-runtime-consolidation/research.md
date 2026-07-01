# Phase 0 Research: Evidence-Gated Runtime Consolidation

All Technical Context unknowns are resolved below. No open `NEEDS CLARIFICATION`.

## R1 — Migration unit: framework + slices vs. single rewrite

- **Decision**: Deliver a reusable migration framework (Authority Map, Migration
  Slice contract, Parity Observer, Rollout Gate) and land #173 as a sequence of
  independent slices, not one port.
- **Rationale**: FR-002 forbids one unbounded rewrite; #173 combines state
  migration, public-contract change, and performance work whose risks and
  rollback boundaries differ. Bundling them makes regressions unattributable
  (spec "Program Boundaries And Order").
- **Alternatives considered**: (a) Direct port of `workflow.py` into
  `runtime_kernel` in one PR — rejected: no reversible boundary, violates
  FR-002/FR-004. (b) Feature-flag per call site without an authority map —
  rejected: cannot detect duplicate ownership (FR-005) or prove single-owner
  invariant (SC-001).

## R2 — Authority declaration & duplicate-ownership detection

- **Decision**: A machine-readable **Runtime Authority Map** enumerates every
  migrated axis with exactly one `authoritative_owner` (`legacy` | `kernel`) and
  a `compatibility_direction`. An `AuthorityMap` projection validates the map
  against the active runtime and fails loudly if two paths claim the same
  transition.
- **Rationale**: FR-001/FR-005 and SC-001 require one owner per axis and loud
  failure on ambiguity; Edge Case requires stating which axes are
  kernel-authoritative during partial migration (FR-019).
- **Alternatives considered**: Implicit "kernel wins" fallback — rejected by the
  spec Edge Case ("fails loudly rather than selecting an implicit fallback") and
  Constitution Fail-Fast.

## R3 — Parity comparison without duplicate side effects

- **Decision**: `ParityObserver` replays the same runtime facts through legacy
  and candidate projections and compares **projections, policy decisions, and
  planned commands** — never executed commands. It emits a `parity-report.v1`.
  Command *plans* are compared by idempotency key + payload digest; no outbox
  execution occurs.
- **Rationale**: FR-007, SC-003, and the Edge Case "a shadow comparison must not
  execute duplicate GitHub side effects." The kernel already separates command
  *planning* (`runtime_kernel/commands.py`, `planned_command_digest`) from
  execution, so plans can be diffed structurally with zero IO.
- **Alternatives considered**: Live dual-write shadowing — rejected: duplicates
  GitHub side effects. Post-hoc log diffing only — rejected: cannot prove
  candidate parity for unexercised transitions; replay over recorded facts is
  deterministic (SC-002).

## R4 — Rollout stages, gate, and rollback storage

- **Decision**: A versioned `rollout-state.v1` artifact records each slice's
  `stage` ∈ {`shadow`, `opt_in`, `default`, `deprecating`, `deleted`} and an
  `enabled` flag. `RolloutPolicy` is a deterministic function that permits a
  forward transition only when the Migration Slice Acceptance Gate holds, and
  triggers a reversal when a Rollback Trigger is breached. Rollback is a single
  `rollout-state` transition; it never edits runtime facts.
- **Rationale**: FR-008/FR-014/FR-016, SC-004/SC-005/SC-008. Provisional
  evidence may unlock `shadow`/`opt_in`; `default` requires durable feature-023
  evidence; `deleted` additionally requires a completed deprecation window
  (spec Acceptance Gate).
- **Alternatives considered**: Environment-variable flags — rejected: not
  auditable/versioned, no recovery contract. Storing stage inside `session.json`
  — rejected: conflates rollout control with review truth (Principle IX
  artifact-truth boundary).

## R5 — Consuming feature-023 evidence without letting it become truth

- **Decision**: `RolloutPolicy` reads feature-023 `evaluation.v1` comparison
  results as *rollout evidence only*. `INSUFFICIENT_EVIDENCE`, unknown durable
  outcomes, or regressed quality guardrails block default rollout and legacy
  deletion. Evaluation output is never written into `session.json`, evidence
  ledger, or `final-gate`.
- **Rationale**: FR-013/FR-014, Constitution "Evidence Requirements" — 023
  evaluates after the fact and cannot satisfy completion.
- **Alternatives considered**: Gating `final-gate` on evaluation coverage —
  rejected: violates fail-open core-workflow boundary (Principle VIII).

## R6 — Three optimization hypotheses kept independent

- **Decision**: Output truncation, `command-session` adoption, and
  workflow-surface deletion are modeled as separate **Optimization Hypothesis**
  entries, each with its own guardrails, cohort, staged enablement, and rollback
  action in `rollout-state.v1`. A supported non-session path and a non-truncated
  (`--full`) path remain available until each independently passes its gate.
- **Rationale**: FR-010/FR-011/FR-012, SC-007, Non-Goals (session not the only
  path; truncation not default before gates pass). #173 ADR-002 lists these as
  distinct changes.
- **Alternatives considered**: One "performance" flag toggling all three —
  rejected: regressions become unattributable and irreversible together.

## R7 — Public-contract preservation for truncation & structured handoff

- **Decision**: Lossy truncation defaults to **off**; when enabled it is a
  versioned change to the `threads`/`address` output contract with `--full`
  escape and updated tests/docs/skill guidance in the same change. The
  `workflow_decision.v1` structured handoff is introduced additively alongside
  the existing verbose output until its hypothesis passes.
- **Rationale**: FR-009/FR-012, SC-009, Constitution Principle II & V.
- **Alternatives considered**: Silent 500-char truncation default (as sketched in
  #173) — rejected: unversioned lossy change to a public machine surface.

## R8 — First slice ordering

- **Decision**: Order slices by isolation and reversibility: (1) **PR check
  state** and (2) **lease state** first (well-bounded, already partly modeled),
  then (3) **local findings triage**, then (4) reduce imperative transitions in
  `workflow.py` to a boundary coordinator, and finally (5) delete
  `workflow_matching.py` only after all prior slices reach `default` and their
  deprecation windows complete.
- **Rationale**: spec Program Boundaries And Order; #173 Action Roadmap; each
  early slice must reduce a duplicate owner without a public-contract change
  (SC-010) so parity is the dominant risk, not compatibility.
- **Alternatives considered**: Migrating imperative `workflow.py` first —
  rejected: largest blast radius and hardest parity proof; violates
  smallest-safe-change discipline.
