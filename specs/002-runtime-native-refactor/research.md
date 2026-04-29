# Research: Runtime Native Refactor

## Migration Analysis: Legacy Scripts

### Core State & Session Engine (`session_engine.py`, `python_common.py`)
- **Logic**: Manages `session.json` state, `ALLOWED_TRANSITIONS`, audit logging, and filesystem path resolution (state dir, workspace dir).
- **Target**: `src/gh_address_cr/core/session.py` (State & File IO), `src/gh_address_cr/core/workflow.py` (State Machine & Logic).
- **Refactor**: Remove CLI parsing from these modules. Separate filesystem path generation from logic. Use `Path` objects consistently.

### GitHub IO (`post_reply.py`, `resolve_thread.py`, `list_threads.py`)
- **Logic**: Direct HTTP calls to GitHub API (GraphQL/REST). Handles response parsing and terminal formatting.
- **Target**: `src/gh_address_cr/github/client.py`.
- **Refactor**: Abstract API calls into a `GitHubClient` class. Use structured error handling. Remove dependency on `python_common` and `session_engine`.

### Intake & Findings (`ingest_findings.py`, `review_to_findings.py`)
- **Logic**: Parsing JSON/NDJSON, normalizing finding shapes (path, line, body), and deduping.
- **Target**: `src/gh_address_cr/intake/findings.py`.
- **Refactor**: Create a functional normalization pipeline. Decouple from stdin/file IO to allow programmatic usage.

### Final Gate (`final_gate.py`)
- **Logic**: Validating resolved threads, reply evidence, and pending reviews.
- **Target**: `src/gh_address_cr/core/gate.py`.
- **Refactor**: Implement as a policy checker that takes a `Session` object and returns a `GateResult`.

## Technical Decisions

### Decision: Module Hierarchy
- **Rationale**: To prevent circular dependencies, `core` should be the base. `github` and `intake` should be independent packages that `core.workflow` coordinates.

### Decision: Data Classes vs Dictionaries
- **Rationale**: Use `TypedDict` for JSON parity with existing session files, but consider `dataclasses` for internal logic if complex state transitions require it. Given behavioral parity requirements, `TypedDict` or `dict` is safer for the initial migration.

### Decision: Backward Compatibility
- **Rationale**: Shims in `legacy_scripts` will import the new native modules and call them. This allows the packaged skill's `SKILL.md` to remain unchanged while using the new runtime logic.

## Research Findings

- `python_common.py` contains many global variables and side-effect-heavy path logic. This must be moved to a clean `core/paths.py` or similar.
- `session_engine.py` is >1200 lines and contains both low-level IO and high-level workflow. This must be split carefully.
- The `AuditLog` format must be preserved exactly to ensure compatibility with existing reporting tools.
