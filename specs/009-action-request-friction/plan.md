# Implementation Plan: Action Request Friction Repair

**Branch**: `codex/010-agent-contract-friction` | **Date**: 2026-04-30 | **Spec**: [specs/009-action-request-friction/spec.md](specs/009-action-request-friction/spec.md)
**Input**: Feature specification from `/specs/009-action-request-friction/spec.md`

## Summary

Repair the agent-facing workflow friction reported in issue #30 by making the packaged `submit_action.py` helper consume runtime `ActionRequest` artifacts directly, clarifying classification-vs-resolution failure guidance, and documenting the existing batch evidence flow for small GitHub-thread fixes. Runtime state, lease validation, publishing, and final-gate behavior remain owned by deterministic code.

## Technical Context

**Language/Version**: Python 3.10+  
**Primary Dependencies**: `argparse`, `json`, `subprocess`, `unittest`  
**Storage**: PR-scoped cache artifacts under `GH_ADDRESS_CR_STATE_DIR` or platform cache directory  
**Testing**: `unittest`, `ruff`  
**Target Platform**: Darwin (macOS), Linux  
**Project Type**: CLI tool plus packaged skill adapter  
**Performance Goals**: Helper response generation remains local and completes in under 1s for normal request files  
**Constraints**: Preserve public CLI compatibility, keep the skill as a thin adapter, do not bypass active leases, do not mutate GitHub directly from helper scripts  
**Scale/Scope**: One PR session at a time; multiple small GitHub-thread fixes may be submitted through existing batch evidence contracts while respecting active claim limits  

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Control plane ownership**: PASS. The plan keeps session state, lease acceptance, GitHub side effects, reply evidence, and final-gate behavior inside `src/gh_address_cr/`. The packaged helper only parses request artifacts and writes response artifacts.
- **Public CLI contract**: PASS. Existing high-level commands and agent protocol commands remain stable. The plan clarifies next-action guidance for `agent classify`, `agent submit`, and `agent submit-batch`.
- **Evidence-first handling**: PASS. The plan preserves classification before mutating fixer requests, requires validation/files for fixes, requires reply-ready evidence for GitHub-thread fixes, and leaves final closure to `final-gate`.
- **Packaged skill boundary**: PASS. Changes under `skill/` are adapter/helper behavior and skill-root documentation. Runtime workflow logic stays in `src/gh_address_cr/`.
- **External intake replaceability**: PASS. No change to normalized findings intake or review producer coupling.
- **Fail-fast verification**: PASS. Tests will cover runtime ActionRequest parsing, malformed request rejection, missing classification guidance, missing resolution guidance, and batch all-or-nothing behavior.

## Project Structure

### Documentation (this feature)

```text
specs/009-action-request-friction/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── action-request-helper.md
│   └── batch-action-response.md
├── checklists/
│   └── requirements.md
└── tasks.md
```

### Source Code (repository root)

```text
src/
└── gh_address_cr/
    ├── cli.py
    ├── core/
    │   └── workflow.py
    └── legacy_scripts/
        └── submit_action.py

skill/
├── SKILL.md
└── scripts/
    └── submit_action.py

tests/
├── test_control_plane_workflow.py
└── test_submit_action_helper.py
```

**Structure Decision**: Use the existing single Python project layout. Keep runtime-owned workflow changes under `src/gh_address_cr/`, packaged helper compatibility under `skill/scripts/`, mirrored legacy helper compatibility under `src/gh_address_cr/legacy_scripts/`, and executable regression coverage under `tests/`.

## Complexity Tracking

> **No Constitution Check violations.**
