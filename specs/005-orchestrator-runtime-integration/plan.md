# Implementation Plan: Orchestrator-Runtime Integration

**Branch**: `005-orchestrator-runtime-integration` | **Date**: 2026-04-27 | **Spec**: [specs/005-orchestrator-runtime-integration/spec.md]
**Input**: Feature specification from `/specs/005-orchestrator-runtime-integration/spec.md`

## Summary
Transform the skeleton Agent Orchestrator from a mock dispatcher into a fully integrated coordinator that drives the Runtime CLI control plane. The orchestrator will act as a thin coordination layer that delegates all authoritative state transitions, GitHub IO, and task identification to the `gh_address_cr.core.workflow` and `gh_address_cr.core.session_engine` modules.

## Technical Context

**Language/Version**: Python 3.10+  
**Primary Dependencies**: `gh_address_cr.core` (internal), `argparse`, `json`, `pathlib`, `packaging`  
**Storage**: `orchestration.json` (volatile orchestration state), `session.json` (authoritative core state), `orchestration_audit.log` (audit trail)  
**Testing**: `unittest`  
**Target Platform**: CLI / CI  
**Project Type**: CLI Tool Integration  
**Performance Goals**: <1s for queue re-sync, <5s for session resume.  
**Constraints**: Zero bypass of `final-gate`. Authoritative state MUST remain in `session.json`.  
**Scale/Scope**: PR-scoped multi-agent coordination.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Control plane ownership**: PASS. All state transitions (submit/publish/issue) and GitHub IO are delegated to deterministic `workflow.py` and `session_engine.py` methods.
- **Public CLI contract**: PASS. Extends the `agent orchestrate` group while preserving the core `review` contract and Status-to-Action Map.
- **Evidence-first handling**: PASS. `orchestrate submit` enforces evidence validation (`files`, `note`, etc.) before calling the runtime submission.
- **Packaged Skill Boundary**: PASS. Logic resides in `src/gh_address_cr/orchestrator/`.
- **External Intake Replaceability**: PASS. Operates on normalized findings within the core session.
- **Fail-fast verification**: PASS. Implements version checks, lease conflict detection, and bounded retry loops for response parsing.

## Project Structure

### Documentation (this feature)

```text
specs/005-orchestrator-runtime-integration/
├── spec.md              # Requirements
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
└── contracts/           # Phase 1 output
    └── orchestrator-runtime-link.md
```

### Source Code (repository root)

```text
src/gh_address_cr/
├── orchestrator/
│   ├── harness.py       # Main CLI entrypoint (integration fix)
│   ├── session.py       # Orchestration state management
│   ├── worker.py        # Worker packet and response handling
│   └── queue.py         # Volatile queue logic
└── core/
    ├── workflow.py      # Authoritative state machine (delegate)
    └── session_engine.py # authoritative session IO (delegate)

tests/
├── test_orchestrator_harness.py
├── test_orchestrator_session.py
└── test_lease_scheduling.py
```

**Structure Decision**: Single project integration. Enhances the existing `orchestrator/` package and wires it to `core/`.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| N/A | | |
