# Implementation Plan: Orchestrator Product Safety & Convergence

**Branch**: `006-orchestrator-product-safety` | **Date**: 2026-04-27 | **Spec**: [specs/006-orchestrator-product-safety/spec.md]
**Input**: Feature specification from `/specs/006-orchestrator-product-safety/spec.md`

**Note**: This template is filled in by the `/speckit.plan` command. See `.specify/templates/plan-template.md` for the execution workflow.

## Summary

Transforming Orchestrator 005 into an AI-safe deliverable product by solidifying the Status-to-Action map, defining the Human Intervention recovery path, enforcing Coordination Guardrails (concurrency/circuit breaking), and implementing a non-intrusive Orchestration Completion Lock.

## Technical Context

**Language/Version**: Python 3.10+
**Primary Dependencies**: `gh_address_cr.core` (internal), `argparse`, `json`
**Storage**: `orchestration.json` (volatile coordination state), `session.json` (authoritative core state), `orchestration_audit.log`
**Testing**: `unittest`
**Target Platform**: CLI / CI (AI Runner Consumption)
**Project Type**: CLI Tool Integration
**Performance Goals**: Status/lock resolution overhead <100ms.
**Constraints**: Orchestration locks must not mutate `session.json`. Safe guardrail defaults hardcoded, overrides persisted.
**Scale/Scope**: PR-scoped multi-agent coordination.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Control plane ownership**: PASS. The completion lock acts as a transient shadow flag (`completed: true`) within `orchestration.json`, deferring true state authority to `session.json`.
- **Public CLI contract**: PASS. Extends the public interface to explicitly map warnings and intervention requirements to machine-readable signals. Solidifies the `Status-to-Action Map`.
- **Evidence-first handling**: PASS. Human intervention recovery follows the standard evidence-first submit path; no silent overrides bypass the checks.
- **Packaged skill boundary**: PASS. Forces `SKILL.md` to be a pure policy layer dictating branches purely on machine codes, not text parsing.
- **External intake replaceability**: PASS. Operates exclusively on normalized findings.
- **Fail-fast verification**: PASS. Guardrail parameters and parsing failure thresholds trigger immediate stops instead of infinite retry loops.

## Project Structure

### Documentation (this feature)

```text
specs/006-orchestrator-product-safety/
├── spec.md              # Requirements
├── plan.md              # This file
├── research.md          # Design decisions
├── data-model.md        # orchestration.json additions
├── quickstart.md        # User guide
└── contracts/
    └── orchestrator-product-safety.md # Status-to-Action signals
```

### Source Code (repository root)

```text
src/gh_address_cr/
├── orchestrator/
│   ├── harness.py       # Update start/step/status/submit with locks and signals
│   ├── session.py       # Add lock, config (max_concurrency), handoff state
│   └── queue.py         # Ensure queue respects max_concurrency
└── core/
    ├── models.py        # Minor updates if needed for signal types

tests/
├── test_orchestrator_harness.py
├── test_orchestrator_session.py
└── test_lease_scheduling.py
```

**Structure Decision**: Extending the existing `orchestrator` module with safety and guardrail features.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| N/A | | |
