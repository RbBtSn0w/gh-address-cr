# Implementation Plan: Agent Efficiency Metrics

> **Historical note:** Superseded by issue #80 legacy workflow removal for
> implementation paths. Command telemetry now belongs to native runtime modules,
> not `core/cr_loop.py`.

**Branch**: `011-agent-efficiency-metrics` | **Date**: 2026-05-29 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/011-agent-efficiency-metrics/spec.md`

## Summary

Implement a telemetry tracking layer to automatically record start, end, and duration metrics for skill and CLI tool invocations within the `gh-address-cr` control plane. This layer will calculate efficiency based on explicit thresholds (>60s execution or >20% error rate), track retry counts, and automatically append a human-readable efficiency summary to the task completion reply.

## Technical Context

**Language/Version**: Python 3.10+
**Primary Dependencies**: Standard library (`subprocess`, `time`, `json`, `datetime`)
**Storage**: N/A (In-memory aggregation during session run)
**Testing**: `unittest` (standard library)
**Target Platform**: CLI/Local runner environment
**Project Type**: Control Plane CLI
**Performance Goals**: < 2% overhead on total session execution time
**Constraints**: Telemetry must fail-open (silent failures) and must not disrupt or crash the main PR review loop.
**Scale/Scope**: Session-scoped tracking (dozens to hundreds of invocations per run).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Control plane ownership**: Yes. The tracking layer and state aggregation will be owned by deterministic python code within `src/gh_address_cr`, not by agent markdown instructions.
- **Public CLI contract**: Yes. We are not breaking `review`, `final-gate`, or reason codes. We are appending a summary to the completion reply.
- **Evidence-first handling**: Yes. The efficiency report itself is the evidence of workflow health.
- **Packaged skill boundary**: Yes. Python telemetry logic will reside in `src/gh_address_cr`. We may update `skill/agents/openai.yaml` to inform the agent that it shouldn't worry about logging its own timestamps, keeping the behavioral policy layer thin.
- **External intake replaceability**: Yes. Does not affect findings parsing.
- **Fail-fast verification**: Yes. We will add unit tests for metric collection, aggregation, and threshold calculation. The telemetry runner will wrap operations in try/except blocks to fail-open at runtime.

## Project Structure

### Documentation (this feature)

```text
specs/011-agent-efficiency-metrics/
├── plan.md              
├── research.md          
├── data-model.md        
├── quickstart.md        
├── contracts/           
└── tasks.md             
```

### Source Code (repository root)

```text
src/
└── gh_address_cr/
    ├── core/
    │   ├── cr_loop.py           # Existing: Intercept run_cmd invocations here
    │   ├── reply_templates.py   # Existing: Append summary to replies
    │   └── telemetry.py         # NEW: Centralized metric aggregation and threshold logic
    └── agent/
        └── responses.py         # Existing: Hook into submit action for reply modification

tests/
└── core/
    ├── test_cr_loop.py          # Existing: Update tests
    ├── test_reply_templates.py  # Existing: Update tests
    └── test_telemetry.py        # NEW: Unit tests for execution metrics tracking
```

**Structure Decision**: Single Python project structure. A new dedicated `telemetry.py` module within the `core` package will handle the collection and aggregation of efficiency metrics, minimizing clutter in the existing `cr_loop` and `workflow` modules.
