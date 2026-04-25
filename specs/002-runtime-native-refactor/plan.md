# Implementation Plan: Runtime Native Refactor

**Branch**: `002-runtime-native-refactor` | **Date**: 2026-04-24 | **Spec**: [specs/002-runtime-native-refactor/spec.md](spec.md)
**Input**: Feature specification from `/specs/002-runtime-native-refactor/spec.md`

## Summary

This feature focuses on eliminating the control plane's dependency on `legacy_scripts` by migrating core logic into a native, structured package hierarchy under `src/gh_address_cr/`. The technical approach involves incremental migration of the session state machine (including native support for Principle VI claim leases), GitHub IO encapsulation, findings intake, and final-gate logic, followed by updating the CLI to use these native modules.

## Technical Context

**Language/Version**: Python 3.10+
**Primary Dependencies**: None (Standard Library)
**Storage**: Local JSON files (Evidence Ledger, Session state with Lease metadata)
**Testing**: Python `unittest`
**Target Platform**: CLI / GitHub Actions
**Project Type**: CLI tool / Runtime engine
**Performance Goals**: Parity with legacy implementation (±5% execution time)
**Constraints**: Zero runtime imports from `legacy_scripts` for core packages.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Control plane ownership**: ✅ Yes. Moves authoritative state machine and side-effect logic to the `core` package.
- **Public CLI contract**: ✅ Yes. Preserves all public CLI commands and machine-readable output formats.
- **Evidence-first handling**: ✅ Yes. The native implementation will continue to use the `EvidenceLedger` for all state transitions.
- **Multi-Agent Lease Support**: ✅ Yes. Native support for Principle VI claim leases will be built into `core.workflow`.
- **Packaged skill boundary**: ✅ Yes. Runtime logic is physically separated from legacy shim code.
- **Fail-fast verification**: ✅ Yes. Comprehensive unit tests and integration tests will verify the refactored logic.

## Project Structure

### Documentation (this feature)

```text
specs/002-runtime-native-refactor/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
└── tasks.md             # Phase 2 output
```

### Source Code (repository root)

```text
src/gh_address_cr/
├── core/
│   ├── session.py       # Migrated from session_engine.py
│   ├── workflow.py      # Core coordination logic
│   └── gate.py          # Migrated final-gate logic
├── github/
│   ├── __init__.py      # Encapsulated GitHub IO
│   └── client.py
├── intake/
│   ├── __init__.py      # Findings normalization
│   └── findings.py
└── legacy_scripts/      # Shims only (no runtime dependencies from core)

tests/                   # Updated to use native packages
├── test_session.py
├── test_github_io.py
└── test_gate.py
```

**Structure Decision**: Option 1: Single project (DEFAULT). The migration targets specific internal packages while maintaining the existing repository layout.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

*(No violations identified)*
