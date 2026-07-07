# Implementation Plan: Workflow Gap Recovery

**Branch**: `028-workflow-gap-recovery` | **Date**: 2026-07-07 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/028-workflow-gap-recovery/spec.md`

**Note**: This plan covers issues `#195` through `#200` as one runtime recovery and diagnostics hardening feature.

## Summary

Unify the runtime recovery surface for blocked PR-closure workflows by making
three existing but fragmented capabilities coherent:

1. Treat terminal GitHub-thread evidence gaps as explicit reconcile flows
   instead of dead-end `final-gate` failures.
2. Surface lease ownership and recovery actions directly when batch claims block
   later item-by-item handling.
3. Distinguish advisory environment diagnostics from real blockers for local
   telemetry coverage and wrapped GitHub CLI permission failures.

The first implementation slice keeps the current public command family,
preserves deterministic runtime ownership, and prefers explicit machine-readable
reason codes plus next-action templates over adding hidden fallback logic.

## Technical Context

**Language/Version**: Python 3.10+ (`pyproject.toml`)  
**Primary Dependencies**: stdlib `argparse`/`json`/`datetime`, `requests`, `packaging`, `opentelemetry-*`  
**Storage**: Repo-local PR session JSON plus evidence ledger JSONL artifacts  
**Testing**: `python3 -m unittest discover -s tests`, targeted CLI/runtime contract tests, `ruff check src tests scripts/build_plugin_payload.py`  
**Target Platform**: Local-first cross-platform Python CLI used by humans, CI, and AI agents  
**Project Type**: Single-project CLI plus packaged skill payload under `skill/`  
**Performance Goals**: Preserve fail-open PR closure flow, keep recovery diagnostics single-hop, and avoid adding extra GitHub round-trips to the common successful path  
**Constraints**: Preserve high-level CLI stability, deterministic session ownership, packaged-skill thin-adapter rules, and `final-gate` as the authoritative completion surface  
**Scale/Scope**: Focused runtime-kernel and CLI recovery work across `final-gate`, `agent resolve`, `agent evidence add`, lease reporting, preflight GitHub diagnostics, and completion guidance

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Control plane ownership**: PASS. Session truth, evidence reconciliation,
  lease recovery, and diagnostic severity remain runtime-owned in repo-root
  code; Markdown only documents the supported surfaces.
- **First-principles runtime kernel**: PASS with preflight. The change touches
  protected kernel surfaces: final-gate facts/projection/policy, lease
  recovery projection, and machine-readable next actions. The plan keeps
  external facts explicit and artifacts non-authoritative.
- **Public CLI contract**: PASS. Existing high-level commands remain the main
  surface. Any new behavior is expressed as reason-code/next-action refinement
  or additive reconcile capability, not by replacing `review`/`address`/`final-gate`.
- **Evidence-first handling**: PASS. GitHub threads still require durable reply
  and, when applicable, validation evidence. The plan only adds supported ways
  to reconcile missing evidence for terminal items.
- **Packaged skill boundary**: PASS. Runtime behavior changes stay in repo-root
  code/tests. `skill/` updates are documentation-only and keep the thin adapter
  model intact.
- **External intake replaceability**: PASS. No coupling to a specific review
  producer is introduced; the feature starts after findings/threads already
  exist in the session.
- **Telemetry evidence boundary**: PASS. Telemetry remains observed evidence.
  The plan changes severity wording and guidance for local `runtime-only`
  coverage, not the ownership of review-resolution truth.
- **Architecture plateau discipline**: PASS. The plan reduces state-space
  ambiguity by converging recovery outcomes into explicit blocker classes and
  recovery templates instead of adding more mode-specific exceptions.
- **Fail-fast verification**: PASS. Targeted contract and regression tests are
  required for final-gate routing, evidence reconciliation, lease diagnostics,
  and environment-aware GitHub/telemetry diagnostics.

### Architecture Preflight (runtime recovery blast radius)

| Preflight item | Resolution |
|---|---|
| Authoritative state owner | Runtime session and ledger code under `src/gh_address_cr/core/`, plus CLI/command adapters that expose machine-readable summaries |
| External facts / event inputs | GitHub thread state, pending reviews, checks, session items, reply evidence, validation evidence, lease rows, `gh` preflight stderr diagnostics, telemetry coverage reports |
| Projection / derived state | Final-gate blocker classes, terminal-item reconcile eligibility, lease recovery state, telemetry attention items, permission mismatch diagnostics |
| Policy / decision function | Final-gate failure ordering, Status-to-Action mapping, lease recovery outcome calculation, telemetry advisory-vs-blocking guidance, GitHub preflight category mapping |
| Side-effect / outbox boundary | Existing `agent publish`, `agent evidence add`, `agent reclaim`, and session persistence; no Markdown-authored side effects |
| Artifact truth boundary | `audit_summary.md`, `efficiency-report.json`, machine summaries, and skill docs remain reporting/evidence only, never authoritative session truth |
| Recovery / replay / contract tests | Existing and new tests must cover closed-thread evidence gaps, stale/claimed lease collisions, lease-owned no-eligible-item diagnostics, runtime-only local telemetry, and GitHub permission mismatch classification |

## Project Structure

### Documentation (this feature)

```text
specs/028-workflow-gap-recovery/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── environment-diagnostics.md
│   └── recovery-surface.md
└── tasks.md
```

### Source Code (repository root)

```text
src/gh_address_cr/
├── cli.py
├── commands/
│   ├── agent.py
│   └── final_gate.py
├── core/
│   ├── gate.py
│   ├── github_thread_state.py
│   ├── leases.py
│   ├── runtime_kernel/
│   │   └── final_gate.py
│   ├── telemetry_reporting.py
│   ├── workflow.py
│   └── workflow_matching.py
├── github/
│   ├── client.py
│   └── diagnostics.py
└── evidence/

skill/
├── SKILL.md
└── references/
    ├── completion-contract.md
    └── status-action-map.md

tests/
├── contract/
├── test_final_gate.py
├── test_issue142_stale_lease_deadlock.py
├── test_resolved_thread_validation_gap.py
├── test_agent_resolve_guards.py
├── test_control_plane_fix_all_workflow.py
├── test_python_wrappers.py
└── test_skill_docs.py
```

**Structure Decision**: Single-project CLI. The change stays within the
existing runtime kernel, command adapters, diagnostics helpers, and
packaged-skill reference docs. No new top-level subsystem is needed.

## Complexity Tracking

No justified Constitution violations are required for this planning phase.
