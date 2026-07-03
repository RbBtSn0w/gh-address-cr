# Implementation Plan: Layered OTel Workflow Modeling

**Branch**: `027-otel-layered-model` | **Date**: 2026-07-03 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/027-otel-layered-model/spec.md`

## Summary

Promote the current "product timeline first" OTel design from an implicit
single-root-span convention into an explicit layered runtime contract:

1. Keep the existing root `gh-address-cr.cli` span as the session-visible
   product timeline anchor.
2. Promote only independently measurable workflow steps to child spans,
   starting with externally visible boundaries that already behave like
   operations: adapter execution, command-session operations, and selected
   high-level workflow boundaries when they own duration, count, or error.
3. Keep phase/checkpoint markers as span events when they are point-in-time
   annotations rather than standalone operations.

The implementation stays within the protected baseline: deterministic runtime
ownership, fail-open telemetry, no new public CLI flags, and no telemetry-owned
workflow state. The design outcome is a default constitutional rule with
explicit, evidence-gated exceptions.

## Technical Context

**Language/Version**: Python 3.10+ (`pyproject.toml`)  
**Primary Dependencies**: `opentelemetry-api`, `opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-http`, `requests`, stdlib `json` / `time` / `contextlib`  
**Storage**: N/A for trace storage; existing repo-local telemetry JSONL artifacts remain separate from span export  
**Testing**: `unittest` via `python3 -m unittest discover -s tests`; existing OTel tests use in-memory span exporters and mocked tracers  
**Target Platform**: Local-first Python CLI used by humans, CI, and AI agents  
**Project Type**: Single-project CLI plus packaged skill payload under `skill/`  
**Performance Goals**: Preserve current fail-open trace export budget; avoid promoting low-value checkpoints into child spans that inflate span volume or latency overhead  
**Constraints**: Preserve current root span contract, public-safe attribute rules, fail-open review workflow behavior, and no telemetry-driven truth/state transitions  
**Scale/Scope**: One root span per CLI invocation today; this feature adds only a bounded set of child spans for mainline workflow, subprocess/adapter boundaries, and command-session or retry/re-entry boundaries

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Control plane ownership**: PASS. Telemetry remains runtime-owned in code
  (`src/gh_address_cr/telemetry.py`, command handlers). No Markdown artifact
  becomes workflow truth.
- **First-principles runtime kernel**: PASS with preflight. The feature changes
  observational modeling only: external facts are command invocation, adapter
  execution, command-session steps, and high-level workflow phases; projections
  remain spans/events plus attributes. No new runtime state machine.
- **Public CLI contract**: PASS. No new command, flag, exit code, machine
  summary field, or Status-to-Action change is required for the first slice.
- **Evidence-first handling**: PASS. Telemetry still observes execution and
  never replaces reply/resolve/final-gate evidence.
- **Packaged skill boundary**: PASS. Phase 1 planning and expected code changes
  stay repo-root. No `skill/` behavior is required for the first slice.
- **External intake replaceability**: PASS. Review-production boundaries remain
  unchanged; this feature only affects workflow observability.
- **Telemetry evidence boundary**: PASS. The design keeps telemetry as observed
  evidence, preserves fail-open behavior, and avoids promoting review state into
  spans. Source attribution and public-safe attributes continue to be enforced
  by existing telemetry safety paths.
- **Architecture plateau discipline**: PASS. The plan narrows state space by
  replacing ad hoc event-only modeling with a three-tier decision rule. If
  candidate child spans proliferate without a stable rule, implementation stops
  and returns to spec rather than adding case-by-case branches.
- **Fail-fast verification**: PASS. The plan includes contract and runtime
  tests for classification, child-span creation, event retention, and no-regression
  behavior of existing root span semantics.

### Architecture Preflight (telemetry modeling blast radius)

| Preflight item | Resolution |
|---|---|
| Authoritative state owner | Runtime code under `src/gh_address_cr/telemetry.py`, `src/gh_address_cr/commands/high_level.py`, `src/gh_address_cr/commands/command_session.py`, and helper modules; no Markdown-owned state |
| External facts / event inputs | CLI invocation, adapter subprocess execution, command-session operation execution, high-level workflow phase transitions, existing retry/re-entry paths |
| Projection / derived state | One root invocation span, selected child spans, retained checkpoint events, and existing public-safe attributes |
| Policy / decision function | Promotion rule: child span only when the step owns independent duration, countability, error boundary, or externally visible product-analysis value; otherwise remain event |
| Side-effect / outbox boundary | Existing OTLP/HTTP exporter only; child spans/events are export-shape changes, not new external side effects |
| Artifact truth boundary | Traces remain observability outputs only; no span, event, or trace artifact becomes runtime truth or session state |
| Recovery / replay / contract tests | In-memory span exporter tests for shape/count/attributes, plus targeted command/session workflow tests and existing CLI smoke checks |

## Project Structure

### Documentation (this feature)

```text
specs/027-otel-layered-model/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── workflow-layering-contract.md
└── tasks.md
```

### Source Code (repository root)

```text
src/gh_address_cr/
├── __main__.py
├── telemetry.py
├── cli.py
├── commands/
│   ├── high_level.py
│   └── command_session.py
└── core/
    ├── telemetry_safety.py
    └── otel_semconv.py

tests/
├── test_otel_telemetry.py
├── test_cli_otel_execution.py
├── test_cli_otel_context.py
├── test_cli_otel_genai.py
├── test_telemetry_acceptance_matrix.py
└── contract/
    └── test_public_contract_stability.py
```

**Structure Decision**: Single-project CLI. The first implementation slice
should confine runtime changes to the shared telemetry helpers and the concrete
workflow call sites that currently emit only events for adapter, command-session
operations, and high-level phases.

## Complexity Tracking

No justified Constitution violations are required for this planning phase.
