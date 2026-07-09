# Implementation Plan: Resolve Command Orthogonalization

**Branch**: `029-resolve-orthogonalization` | **Date**: 2026-07-08 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/029-resolve-orthogonalization/spec.md`

## Summary

Replace `agent resolve`'s flat set of ~9 mutually-constraining mode-preset flags
with a small set of orthogonal, independently composable axes — **disposition**
(fix / trivial / reject / clarify), **selection** (single by `item_id` / by
file scope / batch by input), and **thread condition** (fresh / stale) — so
every valid cell is reachable (closing issue #204, including single-thread and
single-stale decline), the emergent conflict matrix disappears, and the surface
converges to ≤3 axis parameters. `submit-action` adopts the **same canonical
disposition vocabulary** as `agent resolve` (Option B, clarified 2026-07-08).
`agent evidence add` has no disposition/resolution surface of its own — it is
excluded from the vocabulary check by construction, not aligned to it (E1
correction; see spec.md FR-006a/SC-004a, data-model.md Entity 2).

**Technical approach (validated by Phase 0 research)**: This is a **façade +
dispatch-unification refactor, not a runtime-kernel change**. The kernel already
supports every cell through the granular protocol (`record_classification` →
`issue_action_request`/lease → `submit_action_response`/`apply_response_to_item`
→ publish → final-gate), and `TERMINAL_RESOLUTIONS = {fix, clarify, defer,
reject}` plus `StaleThreadClaimabilityTests` prove single-item, all-disposition,
including-stale resolution is fully supported. `agent resolve` simply never
wired its single-item dispatch to decline/stale. The plan rebuilds
`_dispatch_agent_resolve` to route `(selection × disposition × condition)` to the
existing primitives, adds a directive axis-coherence validator, and provides a
versioned deprecation alias layer for the retired mode flags.

## Technical Context

**Language/Version**: Python 3.10+ (per `pyproject.toml`; runtime CLI)
**Primary Dependencies**: stdlib `argparse` (CLI); existing runtime kernel
modules (`core/agent_protocol.py`, `core/workflow.py`,
`core/workflow_matching.py`, `core/agent_protocol_evidence.py`,
`core/github_thread_state.py`). OpenTelemetry only incidentally (unchanged).
**Storage**: Existing event-sourced session store (JSON under state dir); no new
storage.
**Testing**: `unittest` (`python3 -m unittest discover -s tests`), `ruff`
lint, CLI smoke (`python3 -m gh_address_cr ...`), contract tests under `tests/`
(incl. `tests/contract/`).
**Target Platform**: Local-first CLI (macOS/Linux dev + CI runners on 3.10/3.13).
**Project Type**: Single-project CLI runtime + packaged skill (`skill/`).
**Performance Goals**: No new target; resolution latency unchanged (same
underlying primitives).
**Constraints**: Public CLI/agent contract change across 3 commands — MUST be
versioned; Status-to-Action Map preserved; deprecation window with visible
aliasing; fail-fast on invalid axis combinations; no kernel invariant weakened.
**Scale/Scope**: 3 public commands (`agent resolve`, `agent evidence add`,
`submit-action`) plus their `SKILL.md` / `references/agent-protocol.md` docs;
dispatch/validation code in `commands/agent.py` (+ `commands/submit_action.py`,
`commands/high_level.py`) and the reason-code/status map.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Control plane ownership**: PASS. Runtime state, GitHub side effects, reply
  evidence, loop safety, and final-gate stay in deterministic code. This feature
  re-routes the CLI dispatch onto existing deterministic primitives; no logic
  moves into Markdown/skill instructions.
- **First-principles runtime kernel**: PASS. External facts (threads,
  fresh/stale condition, lease state), projections (item state machine), and
  policy (Status-to-Action Map) are unchanged. The only kernel-adjacent addition
  is a **deterministic axis-coherence validator** (a pure decision function)
  replacing emergent pairwise mode exclusions. Artifacts remain
  evidence/reporting. Replay/contract tests cover each axis cell (contracts/).
- **Public CLI contract**: PASS **with explicit versioning**. `review` and
  high-level command **behavior** (parsing, state transitions, exit codes) is
  untouched; however their **emitted guidance strings** — `next_action`
  prose, machine-summary `commands` templates (`core/command_templates.py`),
  help epilogs (`cli.py`), and `high_level.py`/`workflow_matching.py`/
  `workflow.py` recovery messages — currently recommend the deprecated
  mode-preset spellings and ARE updated to the axis phrasing (T030, found by
  `/speckit-analyze` I1/E1: an earlier draft of this bullet said "untouched"
  without the behavior/strings distinction, contradicting Project Structure's
  `high_level.py` entry). The three-command change is versioned; machine
  summary fields, existing reason codes, wait states, exit codes preserved;
  new invalid-combination reason codes are **added** to the Status-to-Action
  Map (not repurposed). Deprecated mode flags alias to axes through a
  documented window.
- **Evidence-first handling**: PASS. fix/clarify/defer/reject classification,
  reply, resolve, and final-gate proof are unchanged per intent; the orthogonal
  surface maps to identical evidence obligations (fix → commit/files/validation;
  decline → reason; GitHub thread terminal only with a real reply URL).
- **Packaged skill boundary**: PASS. Runtime dispatch/validation lives in the
  runtime package (repo root). `SKILL.md` and `references/agent-protocol.md`
  updates stay under `skill/` and remain descriptive (Thin Adapter).
- **External intake replaceability**: PASS. Normalized Findings Contract and
  intake agnosticism are untouched; this is the resolution/decline surface only.
- **Telemetry evidence boundary**: PASS. No telemetry semantics change; per-
  invocation span behavior unchanged; telemetry stays observed evidence.
- **Architecture plateau discipline**: PASS — this is the **corrective** move.
  It *reduces* state space (removes an emergent conflict matrix, collapses ~9
  overlapping presets into ≤3 axes) rather than adding scattered branches. This
  is exactly the "stop patching, converge" action the plateau signal (#204)
  called for.
- **Fail-fast verification**: PASS. Each changed CLI surface, the axis
  validator, and each axis cell get contract/unit tests; invalid combinations
  fail loudly with directive errors; deprecated-flag aliasing and post-window
  removal are tested.

**Result**: No violations. Complexity Tracking not required.

## Project Structure

### Documentation (this feature)

```text
specs/029-resolve-orthogonalization/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output (axis model + deprecation mapping)
├── quickstart.md        # Phase 1 output (validation scenarios per axis cell)
├── contracts/           # Phase 1 output
│   ├── resolve-axes-cli.md
│   └── disposition-vocabulary.md
├── checklists/
│   └── requirements.md  # Spec quality checklist (already present)
└── tasks.md             # Phase 2 output (/speckit-tasks - NOT created here)
```

### Source Code (repository root)

```text
src/gh_address_cr/
├── cli.py                          # behavior unchanged; version bump + help-epilog
│                                   #   examples updated to axis phrasing (T030)
├── commands/
│   ├── agent.py                    # PRIMARY: rebuild _dispatch_agent_resolve onto axes;
│   │                               #   add axis-coherence validator; retire preset guards
│   ├── submit_action.py            # align --resolution to canonical disposition vocabulary
│   ├── high_level.py               # behavior unchanged; emitted guidance strings
│   │                               #   (resolution vocabulary + deprecated-flag
│   │                               #   recommendations) updated to axis phrasing (T030)
│   └── common.py                   # register --disposition in the known-flags list (T015)
├── core/
│   ├── agent_protocol.py           # existing single-item primitives (reused; not redesigned)
│   ├── agent_protocol_evidence.py  # TERMINAL_RESOLUTIONS → alias of agent.roles source (T003)
│   ├── command_templates.py        # machine-summary `commands` templates: migrate
│   │                               #   resolve_homogeneous/resolve_decline/resolve_stale
│   │                               #   to axis phrasing (T030 — public contract surface)
│   ├── workflow.py                 # + single-item decline wiring onto record_classification
│   │                               #   + submit primitives (no new algorithm); recovery
│   │                               #   message strings updated (T030)
│   ├── workflow_matching.py        # collective fix/decline/stale (reused); next-action
│   │                               #   message strings updated (T030)
│   ├── github_thread_state.py      # claimable-state model (reused; invariant unchanged;
│   │                               #   no task — read-only dependency)
│   └── protocol_codes.py           # + invalid-axis-combination reason codes
└── ...

skill/
├── SKILL.md                        # present axes, not the preset matrix
└── references/
    └── agent-protocol.md           # axis command shapes + deprecation mapping

tests/
├── contract/
│   └── test_resolve_axes_contract.py   # NEW: every axis cell reachable; invalid cells directive
├── test_agent_resolve_guards.py        # UPDATE: matrix guards → axis-coherence guards
├── test_skill_docs.py                  # UPDATE: docs assert axis shapes
└── test_disposition_vocabulary.py      # NEW: one canonical disposition set across 3 commands
```

**Structure Decision**: Single-project CLI. The change is concentrated in
`src/gh_address_cr/commands/agent.py` (dispatch + validator), with vocabulary
alignment in `commands/submit_action.py` and the evidence-add path, reason-code
additions in `core/protocol_codes.py`, a thin single-item decline wiring in
`core/workflow.py` onto existing `agent_protocol` primitives, and skill-doc
updates under `skill/`. No new packages; no kernel state-model change.

## Phased Delivery (maps to spec user stories)

- **P1 (US1 — close #204)**: single-item selection composes with reject/clarify
  and with the stale condition; wire `_dispatch_single_item_resolution` to all
  dispositions via the existing classify+submit primitives.
- **P2 (US2 — kill the matrix)**: introduce the axis parameters + directive
  axis-coherence validator; retire the pairwise mode-exclusion logic; keep
  collective (file/batch) selection as axis values.
- **P3 (US3 — converge + compatibility)**: deprecation alias layer mapping old
  mode flags → axis equivalents with visible warnings + versioning; align
  `submit-action`/`evidence add` vocabulary; update skill docs.

## Complexity Tracking

> No Constitution Check violations. Section intentionally empty.
