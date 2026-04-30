# Implementation Plan: CLI Version Query

**Branch**: `008-cli-version` | **Date**: 2026-04-30 | **Spec**: [specs/008-cli-version/spec.md](specs/008-cli-version/spec.md)
**Input**: Feature specification from `/specs/008-cli-version/spec.md`

## Summary

Add version query capability to the `gh-address-cr` CLI via a global `--version` flag, a `-v` shorthand, and a `version` subcommand. The implementation will use the existing `__version__` variable in `src/gh_address_cr/__init__.py` as the source of truth.

## Technical Context

**Language/Version**: Python 3.10+  
**Primary Dependencies**: `argparse` (standard library)  
**Storage**: N/A  
**Testing**: `unittest`  
**Target Platform**: Darwin (macOS), Linux  
**Project Type**: CLI Tool  
**Performance Goals**: Instant response (< 1s)  
**Constraints**: Must work offline without GitHub authentication  
**Scale/Scope**: Minimal impact, metadata only  

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Control plane ownership**: PASSED. Version query is a deterministic metadata function.
- **Public CLI contract**: PASSED. Adds new entry points without breaking existing ones. Follows standard CLI conventions.
- **Evidence-first handling**: N/A. Does not affect review items or gating.
- **Packaged Skill Boundary**: PASSED. Changes are in `src/gh_address_cr/cli.py`. Skill-root relative paths will be preserved in documentation.
- **External Intake Replaceability**: PASSED. No impact on findings ingestion.
- **Fail-fast verification**: PASSED. Will include unit tests and smoke tests for the new flag/command.

## Project Structure

### Documentation (this feature)

```text
specs/008-cli-version/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output (CLI schema)
└── checklists/          # Requirement checklist
```

### Source Code (repository root)

```text
src/
└── gh_address_cr/
    ├── __init__.py      # Version source
    └── cli.py           # CLI routing and version logic

tests/
├── test_python_wrappers.py  # CLI integration tests
└── test_version_query.py    # New unit tests for version logic
```

**Structure Decision**: Standard single-project structure used by `gh-address-cr`. No new directories required.

## Complexity Tracking

> **No Constitution Check violations.**
