# Implementation Plan: Remove Legacy Compatibility

**Branch**: `013-remove-legacy-compat` | **Date**: 2026-06-02 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/013-remove-legacy-compat/spec.md`

## Summary

Remove the historical runtime script compatibility surface so supported users
flow through the current `gh-address-cr` CLI contracts without legacy dispatcher
evaluation. Current high-level and documented utility commands remain available,
but obsolete low-level command names and script-package dispatch must fail fast
before session mutation or GitHub side effects.

## Technical Context

**Language/Version**: Python 3.10+  
**Primary Dependencies**: Python standard library plus `packaging` from `pyproject.toml`  
**Storage**: Cache-backed PR session files managed by the runtime; no new storage  
**Testing**: `ruff check src tests`, `python3 -m unittest discover -s tests`, CLI smoke checks  
**Target Platform**: Cross-platform Python CLI runtime  
**Project Type**: Single Python CLI package plus installable skill payload  
**Performance Goals**: Supported commands perform zero legacy-script dispatcher checks before native handling  
**Constraints**: Preserve current public commands, machine summaries, reason codes, final-gate evidence, normalized findings intake, and packaged skill boundary  
**Scale/Scope**: One runtime package, one packaged skill payload, repository tests and current feature artifacts

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Control plane ownership**: PASS. Runtime code remains the owner of session
  state, GitHub side effects, reply evidence, loop safety, and final-gate
  behavior. The feature removes script-dispatch compatibility, not runtime
  ownership.
- **Public CLI contract**: PASS. Current documented public commands are
  preserved. Obsolete low-level command names are removed from supported usage
  and must fail loudly as unsupported commands.
- **Evidence-first handling**: PASS. Supported review handling still requires
  verification, classification, reply/resolve evidence, and final-gate success.
  Unsupported legacy usage fails before side effects.
- **Packaged skill boundary**: PASS. `skill/` remains a thin Behavioral Policy
  Layer. Runtime decisions stay in `src/gh_address_cr/`; skill docs must not
  reference removed script paths as active instructions.
- **External intake replaceability**: PASS. `review-to-findings`, `findings`,
  and adapter flows continue to use normalized findings as the active intake
  boundary.
- **Fail-fast verification**: PASS. Tests will cover removal of runtime script
  dispatcher support, unsupported low-level command rejection, current command
  smoke parity, active guidance cleanup, and plugin payload consistency.

## Project Structure

### Documentation (this feature)

```text
specs/013-remove-legacy-compat/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── cli-legacy-removal.md
├── checklists/
│   └── requirements.md
└── tasks.md
```

### Source Code (repository root)

```text
src/gh_address_cr/
├── cli.py                         # public CLI routing and fail-fast unsupported usage
├── legacy_handlers/               # internal helper implementations retained for current tests and utilities
├── legacy_scripts/                # historical wrapper package targeted for removal
├── core/
├── intake/
└── github/

tests/
├── test_runtime_packaging.py       # packaging/public command contract
├── test_native_runtime_boundary.py # no legacy-script dependency contract
├── test_python_wrappers.py         # CLI help and utility command behavior
├── test_skill_docs.py              # active guidance cleanup
└── test_plugin_packaging.py        # generated payload consistency

skill/
├── SKILL.md
├── agents/
└── references/

plugin/gh-address-cr/
└── skills/gh-address-cr/           # generated payload from skill/
```

**Structure Decision**: Use the existing single Python CLI package. Remove
historical script compatibility from runtime routing, keep current behavior in
native runtime modules or internal helper implementations, and keep repo-root
tests as the executable contract.

## Complexity Tracking

No constitution violations.

## Phase 0: Research

See [research.md](./research.md).

## Phase 1: Design And Contracts

- [data-model.md](./data-model.md): current workflow surface, superseded path,
  unsupported usage outcome, and historical artifact states.
- [contracts/cli-legacy-removal.md](./contracts/cli-legacy-removal.md): command
  behavior for supported current commands and rejected historical commands.
- [quickstart.md](./quickstart.md): verification scenarios for implementation
  and release-readiness.

## Post-Design Constitution Check

- **Control plane ownership**: PASS. All state mutation remains in runtime
  workflow/core modules.
- **Public CLI contract**: PASS. The contract distinguishes current supported
  commands from historical low-level commands.
- **Evidence-first handling**: PASS. Unsupported usage rejection occurs before
  any review side effects; supported review handling remains gated.
- **Packaged skill boundary**: PASS. Skill payload updates are documentation
  and policy only.
- **External intake replaceability**: PASS. Normalized findings intake remains
  unchanged.
- **Fail-fast verification**: PASS. The task plan will require failing tests
  before implementation and full verification before PR creation.
