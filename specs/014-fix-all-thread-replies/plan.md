# Implementation Plan: Fix-All Thread Replies

**Branch**: `014-fix-all-thread-replies` | **Date**: 2026-06-02 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/014-fix-all-thread-replies/spec.md`

**Note**: This template is filled in by the `/speckit.plan` command. See `.specify/templates/plan-template.md` for the execution workflow.

## Summary

Restore the one-to-one reviewer reply contract for GitHub review threads. The
default addressing path will steer agents to `BatchActionResponse` skeletons
with per-thread `summary` and `why`, while `agent fix-all` becomes a narrow
shortcut for explicitly homogeneous repeated nits or requires per-item evidence
before mixed or uncertain thread groups can be accepted and published.

## Technical Context

**Language/Version**: Python 3.10+  
**Primary Dependencies**: Python standard library plus current package dependencies from `pyproject.toml`  
**Storage**: Cache-backed PR session files managed by the runtime; no new storage backend  
**Testing**: `ruff check src tests`, `python3 -m unittest discover -s tests`, targeted workflow/docs tests, CLI smoke checks  
**Target Platform**: Cross-platform Python CLI runtime and installable skill payload  
**Project Type**: Single Python CLI package plus packaged skill guidance  
**Performance Goals**: Preserve low-token review-thread handling for homogeneous repeated nits while preventing generic replies for distinct reviewer questions  
**Constraints**: Runtime owns session state, leases, evidence acceptance, publishing, and final-gate; public command names and product identity remain `gh-address-cr`; no direct GitHub side effects from the skill layer  
**Scale/Scope**: One runtime workflow surface, machine summaries, skill guidance, docs, and regression tests for multi-thread GitHub review handling

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Control plane ownership**: PASS. The plan keeps classification, leases,
  evidence acceptance, reply rendering, GitHub publication, and final-gate
  behavior in deterministic runtime code. Skill changes are guidance only.
- **Public CLI contract**: PASS. The plan preserves `review`, `address`,
  `threads`, `agent submit-batch`, `agent fix-all`, `agent publish`, and
  `final-gate`, while changing `fix-all` semantics through documented,
  tested fail-fast rules.
- **Evidence-first handling**: PASS. Every review-thread fix must retain
  classification, active lease ownership, per-thread response evidence,
  validation evidence, reply evidence, and final-gate proof.
- **Packaged skill boundary**: PASS. The installed skill remains a Thin
  Adapter and Behavioral Policy Layer. Runtime acceptance and publishing logic
  remain under `src/gh_address_cr/`.
- **External intake replaceability**: PASS. Normalized findings intake and
  review producer boundaries are unchanged; this feature only affects GitHub
  review-thread response evidence.
- **Fail-fast verification**: PASS. The plan requires tests for default
  guidance, per-item evidence preservation, generic `fix-all` rejection, and
  distinct targeted publish bodies.

## Project Structure

### Documentation (this feature)

```text
specs/014-fix-all-thread-replies/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── agent-thread-replies.md
├── checklists/
│   └── requirements.md
└── tasks.md
```

### Source Code (repository root)

```text
src/gh_address_cr/
├── cli.py                         # address/threads guidance and fix-all arguments
├── core/
│   ├── workflow.py                # evidence acceptance, fix-all constraints, publish body rendering
│   ├── gate.py                    # final-gate next-action guidance if needed
│   └── reply_templates.py         # existing reply rendering contract
└── agent/
    └── responses.py               # response validation compatibility where relevant

tests/
├── test_control_plane_workflow.py  # fix-all, submit-batch, lease, acceptance regressions
├── test_native_workflow.py         # publish body distinctness and targeted rationale
├── test_python_wrappers.py         # CLI wrapper/help command surface
└── test_skill_docs.py              # packaged guidance and protocol docs

skill/
├── SKILL.md
├── agents/
│   └── openai.yaml
└── references/
    ├── agent-protocol.md
    └── status-action-map.md
```

**Structure Decision**: Use the existing single Python CLI package. Runtime
workflow changes live under `src/gh_address_cr/`; repo-root tests prove public
behavior; skill-root changes only describe the updated agent policy using
skill-root-relative paths where needed.

## Complexity Tracking

No constitution violations.

## Phase 0: Research

See [research.md](./research.md).

## Phase 1: Design And Contracts

- [data-model.md](./data-model.md): review-thread question, per-thread reply
  evidence, shared fix evidence, homogeneous batch, and per-item evidence input.
- [contracts/agent-thread-replies.md](./contracts/agent-thread-replies.md):
  agent-facing command and evidence contract for `submit-batch`, `fix-all`,
  default addressing guidance, and publishing.
- [quickstart.md](./quickstart.md): implementation and verification scenarios
  for mixed-question rejection, per-item evidence acceptance, homogeneous
  repeated nit handling, docs consistency, and full verification.

## Post-Design Constitution Check

- **Control plane ownership**: PASS. Design artifacts keep all state mutation,
  reply generation, and GitHub side effects in the runtime.
- **Public CLI contract**: PASS. The contract narrows `fix-all` without
  removing current command names; changed behavior is documented and testable.
- **Evidence-first handling**: PASS. Per-thread response evidence becomes a
  required proof for ordinary multi-thread handling.
- **Packaged skill boundary**: PASS. Skill docs remain policy and routing
  guidance only.
- **External intake replaceability**: PASS. Producer intake is not changed.
- **Fail-fast verification**: PASS. Quickstart and contract require tests for
  mixed-question rejection, per-item evidence preservation, and published reply
  distinctness.
