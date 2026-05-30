# Implementation Plan: CLI and Skill Synchronization

**Branch**: `011-agent-efficiency-metrics` | **Date**: 2026-05-30 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/012-cli-skill-sync/spec.md`

## Summary

Implement a Python synchronization script (`scripts/sync_scripts.py`) to serve as the single source of truth mapper, copying CLI compatibility scripts from `src/gh_address_cr/legacy_scripts/` to `skill/scripts/` while injecting necessary bootstrap headers and `# noqa` directives. Integrate checking into CI workflows and unit tests to ensure that any drift in script content or formatting breaks the build immediately.

## Technical Context

**Language/Version**: Python 3.10+
**Primary Dependencies**: Standard library (`argparse`, `sys`, `pathlib`, `shutil`)
**Storage**: Filesystem
**Testing**: `unittest` (standard library)
**Target Platform**: Local development / CI runner
**Project Type**: script / developer tooling
**Performance Goals**: < 2 seconds execution time for sync/check
**Constraints**: Source directory must remain free of local path hacks so that linter and formatter checks run cleanly.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Control plane ownership**: Yes. The synchronization logic resides in a python script (`scripts/sync_scripts.py`), not in markdown instructions.
- **Public CLI contract**: Yes. It does not alter public CLI command signatures.
- **Evidence-first handling**: Yes. The exit code of `--check` is the evidence of code alignment.
- **Packaged skill boundary**: Yes. Compatibility scripts are cleanly mapped from the repository source root to the `skill/` package.
- **External intake replaceability**: Yes. Does not affect findings intake.
- **Fail-fast verification**: Yes. Any synchronization drift is reported as a test and CI failure.

## Project Structure

### Documentation (this feature)

```text
specs/012-cli-skill-sync/
├── spec.md
├── plan.md
└── tasks.md
```

### Source Code (repository root)

```text
scripts/
├── sync_scripts.py      # NEW: Synchronization script
└── build_plugin_payload.py

tests/
└── test_plugin_packaging.py
```

**Structure Decision**: Single project (scripts + tests). We use a top-level `scripts/` directory for developer-facing scripts like `sync_scripts.py`, matching existing conventions (`build_plugin_payload.py`).

## Complexity Tracking

No violations.
