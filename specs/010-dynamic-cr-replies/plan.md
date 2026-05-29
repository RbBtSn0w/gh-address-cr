# Implementation Plan: Dynamic CR Replies & Severity Accuracy

**Branch**: `010-dynamic-cr-replies` | **Date**: 2024-05-24 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/010-dynamic-cr-replies/spec.md`

**Note**: This template is filled in by the `/speckit.plan` command. See `.specify/templates/plan-template.md` for the execution workflow.

## Summary

This feature improves the quality and accuracy of agent-reviewer interactions by standardizing on a P0-P4 severity scale and adopting a "Structured but Rich" reply format. The technical approach involves refactoring `src/gh_address_cr/core/reply_templates.py` to support the expanded severity scale and multi-paragraph technical rationales, updating the markdown templates in `skill/assets/reply-templates/`, and refining the agent prompts in `skill/agents/openai.yaml` to include a formal Severity & Tone Rubric.

## Technical Context

**Language/Version**: Python 3.10+
**Primary Dependencies**: None (Standard Library)
**Storage**: Markdown template files and Python source code.
**Testing**: `python3 -m unittest` for template rendering and severity validation.
**Target Platform**: AI Agent CLI Runtime (Codex/Spec Kit)
**Project Type**: CLI Runtime + Skill Adapter
**Performance Goals**: Instant rendering of dynamic templates.
**Constraints**: MUST maintain audit headers (What changed, Validation, Rationale) while allowing free-form technical depth.
**Scale/Scope**: Updates to 1 core Python module, ~6-8 markdown templates, and 1 agent prompt configuration.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Control plane ownership**: YES. The authoritative logic for rendering and validating the P0-P4 scale resides in `src/gh_address_cr/core/reply_templates.py`.
- **Public CLI contract**: YES. The `ActionResponse` schema remains consistent, but the content quality of `summary` and `why` fields is elevated.
- **Evidence-first handling**: YES. Richer rationales provide stronger evidence of verification and resolution depth.
- **Packaged Skill Boundary**: YES. Formatting templates and agent prompts are kept under `skill/`, while core logic remains in `src/`.
- **External Intake Replaceability**: YES. The findings normalization format is preserved.
- **Fail-Fast Behavior**: YES. The system will fail fast if an invalid severity code is provided by the agent.

## Project Structure

### Documentation (this feature)

```text
specs/010-dynamic-cr-replies/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output (/speckit.plan command)
├── data-model.md        # Phase 1 output (/speckit.plan command)
├── quickstart.md        # Phase 1 output (/speckit.plan command)
├── contracts/           # Phase 1 output (/speckit.plan command)
└── tasks.md             # Phase 2 output (/speckit.tasks command - NOT created by /speckit.plan)
```

### Source Code (repository root)

```text
src/gh_address_cr/
└── core/
    └── reply_templates.py    # Authority for P0-P4 logic and rich rendering

skill/
├── agents/
│   └── openai.yaml           # Severity & Tone Rubric injection
└── assets/
    └── reply-templates/      # Updated P0-P4 markdown templates

tests/
└── core/
    └── test_reply_templates.py # Verification of rich rendering
```

**Structure Decision**: Standard single-project layout following the existing `src/` and `skill/` boundary.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| [e.g., 4th project] | [current need] | [why 3 projects insufficient] |
| [e.g., Repository pattern] | [specific problem] | [why direct DB access insufficient] |
