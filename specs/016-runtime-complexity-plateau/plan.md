# Implementation Plan: Runtime Complexity Plateau

**Branch**: `016-runtime-complexity-plateau` | **Date**: 2026-06-04 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/016-runtime-complexity-plateau/spec.md`

**Note**: This template is filled in by the `/speckit.plan` command. See `.specify/templates/plan-template.md` for the execution workflow.

## Summary

Stabilize `gh-address-cr` at the current complexity plateau by turning overloaded runtime behavior into explicit, testable contracts. The plan uses phased delivery: first introduce work item handling boundaries and lease recovery semantics for at least one high-value work item type, then enforce telemetry performance/fail-open boundaries, then add advisory-first logic validation signals for gate-quality risks. Public CLI behavior remains stable unless a documented, tested machine-readable contract is extended.

## Technical Context

**Language/Version**: Python 3.10+  
**Primary Dependencies**: Python standard library runtime modules, existing `gh-address-cr` package, GitHub CLI integration through existing runtime IO helpers  
**Storage**: PR-scoped cache workspace with `session.json`, `audit.jsonl`, `trace.jsonl`, telemetry JSONL/JSON artifacts, and generated request/response artifacts  
**Testing**: `ruff check src tests`, `python3 -m unittest discover -s tests`, focused unit/contract tests for lease recovery, agent protocol, telemetry, final gate, and skill docs  
**Target Platform**: Local-first CLI on macOS/Linux with Python 3.10+  
**Project Type**: Python CLI/runtime package with packaged agent skill payload  
**Performance Goals**: Normal telemetry path adds no more than 250ms user-visible delay per core workflow command; lease recovery and handler matching remain bounded to the active PR session state  
**Constraints**: Preserve `review` as the primary public entrypoint, keep Status-to-Action Map machine-readable, keep telemetry fail-open for core review flows and fail-loud for telemetry-specific commands, keep skill as thin adapter  
**Scale/Scope**: PR-scoped sessions with multiple GitHub review threads, local findings, multi-agent leases, runtime telemetry, imported telemetry, and final-gate evidence

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Control plane ownership**: PASS. Runtime code remains authoritative for session state, handling boundary selection, lease ownership, telemetry artifacts, logic validation diagnostics, GitHub side effects, and final-gate evaluation.
- **Public CLI contract**: PASS. The plan preserves the `review` entrypoint and existing high-level commands. Any new machine-readable outcomes, especially lease recovery outcomes and validation signals, are documented as additive contracts.
- **Evidence-first handling**: PASS. Handling boundaries define required evidence and completion criteria, but do not replace classification, reply, resolve, or final-gate proof.
- **Packaged skill boundary**: PASS. Skill updates are limited to behavioral guidance for new next actions and diagnostics. Runtime-owned state transitions, arbitration, safety filtering, and gates remain under `src/`.
- **External intake replaceability**: PASS. The feature does not change normalized findings intake or bind the control plane to a specific review producer or agent host.
- **Telemetry evidence boundary**: PASS. Telemetry remains attributed observed evidence with coverage labels and privacy filtering. Core review flows fail open for telemetry damage; telemetry-specific surfaces fail loudly.
- **Fail-fast verification**: PASS. The plan includes contract tests for handler matching conflicts, lease recovery outcomes, telemetry degradation, validation signal gating, skill guidance, and CLI smoke behavior.

## Project Structure

### Documentation (this feature)

```text
specs/016-runtime-complexity-plateau/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── work-item-handling.md
│   ├── lease-recovery.md
│   ├── telemetry-runtime-boundary.md
│   └── logic-validation.md
└── tasks.md
```

### Source Code (repository root)

```text
src/gh_address_cr/
├── cli.py
├── commands/
│   ├── agent.py
│   ├── final_gate.py
│   └── telemetry.py
├── core/
│   ├── agent_protocol.py
│   ├── gate.py
│   ├── leases.py
│   ├── models.py
│   ├── telemetry.py
│   └── workflow.py
└── evidence/
    └── ledger.py

skill/
├── SKILL.md
└── references/
    ├── agent-protocol.md
    ├── completion-contract.md
    └── status-action-map.md

tests/
├── test_agent_protocol.py
├── test_claim_leases.py
├── test_lease_scheduling.py
├── test_final_gate.py
├── test_issue78_agent_experience.py
├── test_skill_docs.py
├── test_telemetry_acceptance_matrix.py
└── core/
    └── test_telemetry.py
```

**Structure Decision**: Use the existing single Python runtime package and packaged skill layout. New implementation may add focused runtime modules under `src/gh_address_cr/core/` or `src/gh_address_cr/commands/` only when they reduce real coupling and keep public contracts stable. Repo-root tests own executable contracts; `skill/` only mirrors agent-facing guidance.

## Complexity Tracking

No constitution violations are required. The feature explicitly reduces hidden complexity by creating staged contracts instead of adding another broad fallback path.

## Phase 0: Research

Research decisions are captured in [research.md](research.md). All planning unknowns are resolved there:

- Delivery slicing and scope control
- Work item handling boundary contract
- Lease recovery outcomes and stale submission behavior
- Telemetry overhead/fail-open policy
- Logic validation signal authority
- Skill documentation boundary

## Phase 1: Design & Contracts

Design artifacts generated for this phase:

- [data-model.md](data-model.md)
- [contracts/work-item-handling.md](contracts/work-item-handling.md)
- [contracts/lease-recovery.md](contracts/lease-recovery.md)
- [contracts/telemetry-runtime-boundary.md](contracts/telemetry-runtime-boundary.md)
- [contracts/logic-validation.md](contracts/logic-validation.md)
- [quickstart.md](quickstart.md)

## Constitution Check Post-Design

- **Control plane ownership**: PASS. Data model entities keep runtime-owned state separate from skill guidance, and contracts define runtime-owned outcomes.
- **Public CLI contract**: PASS. Contracts are additive and preserve existing command identity. Any new fields must be documented and tested before exposure.
- **Evidence-first handling**: PASS. Work item boundaries and validation signals cannot mark completion without runtime completion evidence.
- **Packaged skill boundary**: PASS. Agent context update changes only the active Spec Kit plan pointer in `AGENTS.md`; future skill edits must remain behavioral guidance.
- **External intake replaceability**: PASS. No contract depends on a review producer vendor.
- **Telemetry evidence boundary**: PASS. Telemetry contract preserves coverage labels, privacy filtering, and fail-open/fail-loud split.
- **Fail-fast verification**: PASS. Quickstart defines focused verification plus standard repo checks.
