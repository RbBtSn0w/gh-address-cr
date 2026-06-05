# Implementation Plan: Runtime Kernel

**Branch**: `018-runtime-kernel` | **Date**: 2026-06-05 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/018-runtime-kernel/spec.md`

**Note**: This template is filled in by the `/speckit.plan` command. See `.specify/templates/plan-template.md` for the execution workflow.

## Summary

Introduce a minimal runtime-kernel slice for GitHub review-thread handling. The slice models review-thread observations and side-effect execution results as typed runtime facts, derives a single deterministic projection of active and terminal review work, evaluates explicit policy decisions over that projection, and produces idempotent command plans without performing side effects in the decision path. Public CLI behavior and structured agent protocol contracts remain stable during adoption.

## Technical Context

**Language/Version**: Python 3.10+  
**Primary Dependencies**: Python standard library dataclasses, enums, JSON hashing helpers already present in `gh_address_cr.core.models`, existing GitHub thread-state helper semantics  
**Storage**: No new persisted authoritative store in this slice; facts and execution results are in-memory inputs for replay/contract tests. Existing session and artifact files remain compatibility/reporting outputs.  
**Testing**: `ruff check src tests`, `python3 -m unittest discover -s tests`, focused unit tests for runtime kernel facts, projection, policy, command plans, and telemetry/reporting boundary  
**Target Platform**: Local-first CLI/runtime package on macOS and Linux with Python 3.10+  
**Project Type**: Python CLI/runtime package with packaged agent skill payload  
**Performance Goals**: Projection, policy, and command-plan generation remain linear in the number of review-thread facts for a PR session and deterministic under input reordering  
**Constraints**: Preserve public command identity, public machine summaries, structured agent protocol schemas, Status-to-Action Map behavior, and packaged skill identity; do not perform GitHub writes or artifact writes inside projection or policy code  
**Scale/Scope**: Minimal independently verifiable GitHub review-thread kernel slice for one PR session; leases, pending reviews, checks, local findings, hosted workflow choices, and full artifact migration are future phases

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Control plane ownership**: PASS. Runtime code owns facts, projections, policy decisions, command planning, and execution evidence. Skill docs and artifacts remain non-authoritative.
- **First-principles runtime kernel**: PASS. The plan defines external facts, command execution-result facts, a review-thread projection, deterministic policy, idempotent command plans, execution evidence, replay tests, and artifact truth boundaries.
- **Public CLI contract**: PASS. This slice does not change the public CLI, public slash command name, reason-code contract, machine summaries, or structured action protocol. Any future exposure must be additive and tested.
- **Evidence-first handling**: PASS. Planned side effects never satisfy completion. Completion requires recorded execution evidence for required reply/resolve work and final-gate eligibility is blocked by unresolved work.
- **Packaged skill boundary**: PASS. Implementation and tests stay under repo-root source/tests. No skill-owned runtime logic is introduced.
- **External intake replaceability**: PASS. The kernel consumes review-thread facts and does not bind to a review producer or findings adapter.
- **Telemetry evidence boundary**: PASS. Telemetry/reporting facts may be represented as diagnostics but cannot satisfy completion or create recursive completion blockers.
- **Architecture plateau discipline**: PASS. The feature reduces scattered conditionals by introducing one projection and one policy boundary instead of adding branch-specific workflow fixes.
- **Fail-fast verification**: PASS. Tests cover malformed facts, determinism, stale/reopened/resolved handling, final-gate blocking, idempotent plans, and non-self-referential reporting boundaries.

## Architecture Preflight

- **Authoritative state owner**: `src/gh_address_cr/core/runtime_kernel/` owns the kernel slice. Existing `session.json` remains authoritative only for existing workflows, not for the new slice unless converted into modeled facts later.
- **External facts or event inputs**: `review_thread_observed` facts describe GitHub review-thread observations. `command_executed` facts record outcomes of planned reply, resolve, retry, or final-gate commands. `reporting_observed` facts are diagnostics only.
- **Projection shape**: `ReviewProjection` contains sorted `ReviewWorkItem` entries, active item IDs, terminal item IDs, stale item IDs, reopened item IDs, evidence-pending item IDs, final-gate blocker IDs, and diagnostics.
- **Policy / status-to-action decision**: `evaluate_review_policy(projection)` returns exactly one status: `blocked`, `ready_for_action`, `waiting_for_external_input`, or `final_gate_eligible`, plus stable reason codes and item IDs.
- **Side-effect command plan / outbox boundary**: `plan_review_commands(projection, decision)` returns idempotent command records such as `reply_thread`, `resolve_thread`, `retry_command`, or `run_final_gate`. It never posts replies, resolves threads, writes artifacts, or mutates sessions.
- **Artifact truth and telemetry/reporting boundary**: Existing artifacts are compatibility/reporting evidence. Reporting writes are excluded from their own overhead/completion semantics; reporting facts cannot complete review work.
- **Recovery and replay tests**: Contract tests replay the same facts, reorder facts, add stale/reopened/resolved facts, and ingest command execution results to prove stable projections, decisions, and command plans.

## Project Structure

### Documentation (this feature)

```text
specs/018-runtime-kernel/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── review-thread-kernel.md
│   ├── command-plan.md
│   └── telemetry-reporting-boundary.md
└── tasks.md
```

### Source Code (repository root)

```text
src/gh_address_cr/
└── core/
    ├── github_thread_state.py
    └── runtime_kernel/
        ├── __init__.py
        ├── events.py
        ├── projections.py
        ├── policies.py
        └── commands.py

tests/
└── test_runtime_kernel.py
```

**Structure Decision**: Add a focused `core/runtime_kernel/` package to keep fact, projection, policy, and command-planning responsibilities separate from existing imperative workflow paths. The first tests live in one focused repo-root test module so the acceptance matrix remains easy to inspect.

## Complexity Tracking

No constitution violations are required. This feature explicitly reduces runtime complexity by creating a modeled boundary for review-thread decisions and command planning.

## Phase 0: Research

Research decisions are captured in [research.md](research.md):

- delivery slice and migration contract
- fact and event identity
- projection semantics for stale, reopened, resolved, and evidence-pending threads
- policy decision table
- idempotent command-plan rules
- telemetry/reporting truth boundary

## Phase 1: Design & Contracts

Design artifacts generated for this phase:

- [data-model.md](data-model.md)
- [contracts/review-thread-kernel.md](contracts/review-thread-kernel.md)
- [contracts/command-plan.md](contracts/command-plan.md)
- [contracts/telemetry-reporting-boundary.md](contracts/telemetry-reporting-boundary.md)
- [quickstart.md](quickstart.md)

## Constitution Check Post-Design

- **Control plane ownership**: PASS. Data model and contracts keep runtime-owned truth separate from compatibility artifacts and skill guidance.
- **First-principles runtime kernel**: PASS. The design follows facts -> projection -> policy -> command plan -> execution evidence.
- **Public CLI contract**: PASS. Contracts define an internal kernel slice and explicitly forbid public CLI behavior changes in this phase.
- **Evidence-first handling**: PASS. Required reply/resolve work remains incomplete until execution results are recorded.
- **Packaged skill boundary**: PASS. No skill payload changes are planned for the minimal slice.
- **External intake replaceability**: PASS. Review-thread facts remain producer-agnostic.
- **Telemetry evidence boundary**: PASS. Reporting writes are excluded from recursive completion and cannot satisfy review work.
- **Architecture plateau discipline**: PASS. The contract removes repeated edge branches by routing stale, reopened, resolved, and evidence-pending handling through projection/policy tables.
- **Fail-fast verification**: PASS. Quickstart and tasks require focused tests plus full repository validation.
