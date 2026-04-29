# Implementation Plan: Thin Skill Orchestration

**Branch**: `003-thin-skill-orchestration` | **Date**: 2026-04-25 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/003-thin-skill-orchestration/spec.md`

**Note**: This plan covers Stage 4 thin skill productization and Stage 5 multi-agent orchestration readiness. It deliberately stops before a full autonomous runner implementation.

## Summary

Thin the packaged `gh-address-cr` skill into a concise adapter for the deterministic runtime, define a stable status-to-action map for agents, and productize contract-first multi-agent coordination around the existing CLI, structured agent protocol, claim leases, evidence ledger, replaceable findings intake, and final gate. The implementation approach is documentation-and-contract first: update the shipped skill surface, advanced references, repo README, and executable validators so no authoritative workflow behavior remains only in prose or low-level scripts.

## Technical Context

**Language/Version**: Python 3.10+ for runtime and validators; Markdown for packaged skill and reference contracts  
**Primary Dependencies**: Existing `gh-address-cr` runtime package, GitHub CLI (`gh`) for runtime operations, Python standard library, `unittest`, `ruff`  
**Storage**: Existing PR-scoped session state, audit artifacts, evidence ledger files, action request/response artifacts, and documentation fixtures  
**Testing**: `ruff check gh-address-cr tests`, `python3 -m unittest discover -s tests`, targeted docs/contract tests, CLI smoke checks  
**Target Platform**: Developer machines and CI environments that run the packaged skill plus the installed runtime CLI  
**Project Type**: CLI/runtime product with a packaged AI-agent skill adapter  
**Performance Goals**: No additional GitHub side effects or session mutations are introduced by adapter guidance; status/action validation runs as lightweight local tests; the public review path remains within current runtime performance baselines  
**Constraints**: Keep `review` as the default public entrypoint; keep low-level scripts as implementation details; preserve machine summary fields, reason codes, wait states, exit codes, normalized findings, leases, evidence, and final-gate authority; do not ship a generic agent framework or built-in review engine  
**Scale/Scope**: PR-scoped review resolution sessions; simulated orchestration must cover at least 3 independent items and 4 distinct roles; producer intake remains replaceable through normalized findings

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Control plane ownership**: PASS. `contracts/adapter-boundary.md` assigns session state, GitHub side effects, lease mutation, evidence acceptance, and final-gate authority to the runtime; `data-model.md` marks runtime-owned entities with forbidden skill/agent mutators.
- **Public CLI contract**: PASS. `contracts/status-action-map.md` derives adapter behavior from runtime machine summaries and preserves `review`, high-level command semantics, `reason_code`, `waiting_on`, `next_action`, and stop conditions.
- **Evidence-first handling**: PASS. `contracts/role-coordination.md` and `quickstart.md` preserve `fix` / `clarify` / `defer` / `reject`, role evidence, verifier rejection, serialized publishing, and final-gate proof.
- **Packaged skill boundary**: PASS. `contracts/adapter-boundary.md` defines skill-root versus repo-root ownership and validation expectations for path-scope language.
- **Fail-fast verification**: PASS. `quickstart.md` and the contracts require checks for malformed summaries, missing/incompatible runtime, invalid producer output, direct side-effect attempts, stale leases, and documentation contradictions.
- **Agent protocol and lease compatibility**: PASS. `contracts/role-coordination.md` defines capability manifests, active claim leases, conflict keys, stale/duplicate rejection, verifier rejection, and serialized publishing.

No constitution violations are introduced.

## Project Structure

### Documentation (this feature)

```text
specs/003-thin-skill-orchestration/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── status-action-map.md
│   ├── role-coordination.md
│   ├── adapter-boundary.md
│   └── review-producer-intake.md
└── tasks.md
```

### Source Code (repository root)

```text
gh-address-cr/
├── SKILL.md
├── agents/
│   └── openai.yaml
└── references/
    ├── cr-triage-checklist.md
    ├── evidence-ledger.md
    ├── local-review-adapter.md
    └── mode-producer-matrix.md

src/gh_address_cr/
├── agent/
│   ├── manifests.py
│   ├── requests.py
│   ├── responses.py
│   └── roles.py
├── cli.py
└── core/
    ├── workflow.py
    ├── leases.py
    └── gate.py

tests/
├── test_agent_protocol.py
├── test_control_plane_workflow.py
├── test_final_gate.py
├── test_runtime_packaging.py
├── test_skill_docs.py
└── test_skill_runtime_shim.py
```

**Structure Decision**: This feature uses the existing single-repository layout. Packaged skill changes stay under `gh-address-cr/`; runtime contract checks and validators stay under `tests/` and `src/gh_address_cr/`; product documentation stays in `README.md` and feature artifacts under `specs/003-thin-skill-orchestration/`. Existing runtime protocol modules are listed as contract surfaces, not as authorization to add a scheduler, agent spawner, generic runner, or built-in review engine in this stage.

## Phase 0: Research Plan

Research resolves the design choices that determine task shape:

1. Thin skill entrypoint shape and acceptable first-read size.
2. Stable runtime status taxonomy and adapter status-to-action behavior.
3. Multi-agent role and lease coordination without introducing runner lock-in.
4. Review producer intake boundary and narrative-output rejection.
5. Documentation boundary validation for repo-root versus skill-root paths.
6. Validation strategy for proving no authoritative control-plane behavior remains only in skill prose.

## Phase 1: Design Plan

Design artifacts will define:

1. Data model for adapter-facing status handling, role coordination, capability checks, claim leases, evidence, and orchestration runbooks.
2. Contracts for status-to-action mapping, role coordination, adapter boundary, and review producer intake.
3. Quickstart for manual multi-agent orchestration using the existing runtime contract without a custom runner.
4. Agent context update in `AGENTS.md` to point at this plan while the feature is active.

## Post-Design Constitution Check

- **Control plane ownership**: PASS. `adapter-boundary.md`, `role-coordination.md`, and `data-model.md` keep runtime state, side effects, evidence, leases, and final gate under runtime ownership.
- **Public CLI contract**: PASS. `status-action-map.md` keeps the runtime machine summary as the source of truth and blocks adapter-owned state derivation.
- **Evidence-first handling**: PASS. `role-coordination.md` and `quickstart.md` require role evidence, verifier outcomes, reply evidence, resolve state, and final-gate proof.
- **Packaged skill boundary**: PASS. `adapter-boundary.md` defines packaged skill, repo-root, and runtime ownership with path-scope validation.
- **Fail-fast verification**: PASS. `quickstart.md` lists the planned validation suite and fail-loud scenarios for malformed summaries, producer output, runtime compatibility, stale leases, and direct side effects.
- **Agent protocol and lease compatibility**: PASS. `role-coordination.md` keeps work assignment lease-first and publishing serialized; no runner-specific scheduling behavior is introduced.

## Complexity Tracking

No constitution violations require justification.
