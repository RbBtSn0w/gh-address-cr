# Implementation Plan: Agent Orchestrator MVP

**Branch**: `004-agent-orchestrator-mvp` | **Date**: 2026-04-26 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/004-agent-orchestrator-mvp/spec.md`

## Summary

Build a PR-scoped multi-agent coordinator MVP that handles task scheduling, claim leases, and resume logic. The orchestrator will act as a thin deterministic loop calling the authoritative Runtime CLI and issuing standard `ActionRequest` packets to worker agents, avoiding generic agent platform features and respecting final-gate boundaries.

## Technical Context

**Language/Version**: Python 3.10+
**Primary Dependencies**: Existing `gh-address-cr` runtime package (`src/gh_address_cr/`)
**Storage**: Existing PR-scoped session state and cache artifacts
**Testing**: Python `unittest`, `ruff`
**Target Platform**: Developer machines and CI environments running the CLI
**Project Type**: CLI orchestration layer
**Performance Goals**: Fast local state polling; overhead <100ms per step
**Constraints**: Keep deterministic state in Runtime CLI; Orchestrator only tracks volatile queues and leases.
**Scale/Scope**: PR-scoped coordination covering 3+ items and 2+ agent roles.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Control plane ownership**: PASS. The orchestrator delegates state, IO, and gates to the Runtime CLI.
- **Public CLI contract**: PASS. It uses existing `ActionRequest` schemas and machine summary fields, preserving the Status-to-Action Map.
- **Evidence-first handling**: PASS. Validates `ActionResponse` evidence before submission.
- **Packaged skill boundary**: PASS. Code belongs in `src/gh_address_cr/`, separate from the thin adapter skill.
- **External intake replaceability**: PASS. Operates downstream of intake, relying purely on the Normalized Findings Contract.
- **Fail-fast verification**: PASS. Includes fail-fast checks for lease conflicts, invalid responses, and corrupted session resumption.

## Project Structure

### Documentation (this feature)

```text
specs/004-agent-orchestrator-mvp/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── orchestrator-cli.md
│   ├── worker-packet.md
│   └── lease-lifecycle.md
└── tasks.md
```

### Source Code (repository root)

```text
src/gh_address_cr/
├── cli.py
├── orchestrator/
│   ├── __init__.py
│   ├── harness.py
│   ├── session.py
│   ├── queue.py
│   └── worker.py

tests/
├── test_orchestrator_harness.py
├── test_orchestrator_session.py
└── test_lease_scheduling.py
```

**Structure Decision**: Added a new `orchestrator` package under `src/gh_address_cr/` to separate multi-agent coordination logic from core PR state, ensuring the CLI remains the single source of truth.

## Complexity Tracking

*(No violations)*
