# Implementation Plan: Reply Template Parity

**Branch**: `009-reply-template-parity` | **Date**: 2026-04-30 | **Spec**: [specs/009-reply-template-parity/spec.md](specs/009-reply-template-parity/spec.md)
**Input**: Feature specification from `/specs/009-reply-template-parity/spec.md`

## Summary

Make native GitHub review-thread replies use the documented v1 reply templates for `fix`, `clarify`, and `defer`. The implementation keeps runtime rendering authoritative, updates the packaged skill generator to match it, and adds parity tests so `agent publish`, `generate-reply`, and `skill/assets` cannot drift silently.

## Technical Context

**Language/Version**: Python 3.10+  
**Primary Dependencies**: Standard library only  
**Storage**: Existing PR session JSON and audit ledger files  
**Testing**: `unittest`, `ruff`  
**Target Platform**: macOS/Linux CLI runtime  
**Project Type**: CLI and packaged skill  
**Performance Goals**: No measurable overhead beyond existing publish path  
**Constraints**: Preserve ActionResponse schema and final-gate behavior  
**Scale/Scope**: GitHub review-thread reply body rendering only

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Control plane ownership**: PASSED. Reply generation used by GitHub side effects remains in deterministic runtime code.
- **Public CLI contract**: PASSED. Reply body text changes but command shape, machine fields, wait states, and exit codes remain compatible.
- **Evidence-first handling**: PASSED. Existing accepted evidence and pre-side-effect validation stay in place.
- **Packaged Skill Boundary**: PASSED. Skill assets and script stay aligned to runtime output without becoming the authoritative state machine.
- **External intake replaceability**: PASSED. Findings intake and normalized findings are unchanged.
- **Fail-fast verification**: PASSED. Tests cover missing evidence, renderer parity, and publish behavior.

## Project Structure

### Documentation (this feature)

```text
specs/009-reply-template-parity/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── reply-template-contract.md
├── checklists/
│   └── requirements.md
└── tasks.md
```

### Source Code (repository root)

```text
src/gh_address_cr/core/reply_templates.py
src/gh_address_cr/core/workflow.py
src/gh_address_cr/legacy_scripts/generate_reply.py
skill/scripts/generate_reply.py
skill/assets/reply-templates/
tests/
```

**Structure Decision**: Use the existing single Python package plus packaged skill payload. No new runtime package or schema namespace is needed.

## Complexity Tracking

> **No Constitution Check violations.**
