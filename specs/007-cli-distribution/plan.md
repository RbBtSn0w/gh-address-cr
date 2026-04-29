# Implementation Plan: CLI Distribution Packaging & Publishing

**Branch**: `007-cli-distribution` | **Date**: 2026-04-28 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/007-cli-distribution/spec.md`

## Summary

This feature transforms the existing CLI skeleton into a robust, distributable Python package published exclusively to PyPI. It involves fixing missing runtime dependencies (`packaging` in `pyproject.toml`), establishing automated CI release workflows (wheel/sdist generation and PyPI upload), adding an installation smoke test, and documenting end-user installation via modern isolated tools (`pipx`, `uv`).

## Technical Context

**Language/Version**: Python 3.10+
**Primary Dependencies**: `packaging` (missing from pyproject.toml dependencies)
**Storage**: N/A
**Testing**: `unittest`, plus new CI matrix smoke test for installation
**Target Platform**: Any platform supporting Python 3.10+ (Linux, macOS, Windows)
**Project Type**: CLI Application
**Performance Goals**: N/A
**Constraints**: Must install cleanly without `ModuleNotFoundError`
**Scale/Scope**: Repository configuration (`pyproject.toml`, `.github/workflows`) and `README.md` updates

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Control plane ownership**: N/A (Does not modify runtime state or GitHub side effects).
- **Public CLI contract**: N/A (Preserves existing CLI commands, ensures they can actually be executed by users).
- **Evidence-first handling**: N/A.
- **Packaged skill boundary**: Modifies repo-root configurations (CI, Python package config) to enable the distribution of the CLI. The actual `gh-address-cr/` skill folder remains untouched.
- **External intake replaceability**: N/A.
- **Fail-fast verification**: The new CI smoke test acts as a fail-fast mechanism to catch missing dependencies or broken wheels before a release is published.

## Project Structure

### Documentation (this feature)

```text
specs/007-cli-distribution/
├── plan.md              # This file
├── research.md          # Phase 0 output
└── tasks.md             # Phase 2 output
```
*(No `data-model.md` or `contracts/` needed as this feature does not alter data entities or public APIs).*

### Source Code (repository root)

```text
.github/
└── workflows/
    ├── ci.yml           # Updated to include pip install smoke test
    └── release.yml      # Updated to build wheel/sdist and publish to PyPI

pyproject.toml           # Updated to declare `packaging` dependency
README.md                # Updated to include `pipx` and `uv` installation instructions
```

**Structure Decision**: Modifying existing root configuration files and documentation. No new modules or architectures introduced.

## Complexity Tracking

*(No Constitution Check violations or complex architectural alternatives identified.)*
