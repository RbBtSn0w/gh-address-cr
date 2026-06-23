# Spec: Telemetry Shim Cleanup & Exception Handling Refinement

## Context & Motivation
This specification outlines the remediation of key technical debt items identified in Issues 152, 153, and 154:
1. **Type Safety (Issue 152)**: Resolving the 56 mypy type errors across 16 files, with special focus on a latent type safety bug in the central efficiency reporting path (`telemetry.py`).
2. **Decomposition (Issue 153)**: Removing the deprecated 26-name re-export shim in `core/telemetry.py` by migrating all imports of content-safety helpers to `core/telemetry_safety.py`.
3. **Robust Exception & Handler Refinement (Issue 154)**: Decomposing oversized functions (e.g. `HighLevelReviewRuntime.handle`) to reduce complexity below 15, and narrowing or adding proper debug logging to broad `except Exception` blocks.

---

## Architectural Principles Alignment

### Principle I. Control Plane Owns Runtime State
Telemetry and code-review checks are observed output (telemetry events & reports). No telemetry operations may mutate review state transitions or completion logic.

### Principle IV. Packaged Skill Boundary
All paths and instructions must maintain explicit scope boundaries.

### Principle VIII. Telemetry Fail-Open & Attribution
Core review operations must remain fail-open for missing telemetry. Ingestion failures caught by broad exception boundaries must log telemetry failures using `_log_telemetry_failure` to remain visible under the debug flag, instead of silently swallowing.

---

## Proposed Changes

### 1. Fix Telemetry Latent Bug & Mypy Issues
- Annotate variables in `telemetry.py`, `submit_feedback.py`, `high_level.py`, `cr_metrics.py`, `agent_protocol.py`, `agent_batch.py`, `doctor.py` and other modules to resolve type-checking warnings.
- Explicitly declare `report: dict[str, Any]` and append to the `diagnostics: list[str]` list directly instead of mutating `report["diagnostics"]` after dict creation in `telemetry.py` to fix the latent type inference bug.
- Introduce a ratchet check script or CI validation to ensure the mypy error count does not regress.

### 2. Remove Telemetry Re-Export Shim
- Update import statements in `src/gh_address_cr/core/agent_protocol.py`, `src/gh_address_cr/core/command_runner.py`, and `tests/core/test_telemetry.py` to directly import from `gh_address_cr.core.telemetry_safety`.
- Delete the 26-name re-export shim from `src/gh_address_cr/core/telemetry.py`.

### 3. Decompose Handlers & Narrow Exceptions
- Refactor `HighLevelReviewRuntime.handle` in `commands/high_level.py` to split preflight checks, findings ingestion, thread loading, and error handling into separate focused functions.
- Update `check_runtime_version` in `orchestrator/harness.py` to catch specific exceptions `(ValueError, IndexError, AttributeError, NameError)` instead of swallowing all exceptions.
- Add `core_telemetry._log_telemetry_failure(...)` in fail-open telemetry blocks (e.g. in `final_gate.py`) to keep issues visible under debug settings.

---

## Verification Plan
1. **Linting**: Run `ruff check src tests` (verify no McCabe complexity violations when target-complexity is reduced).
2. **Type Checking**: Run `mypy src/gh_address_cr` (verify that error count is zero or significantly reduced).
3. **Tests**: Run `python3 -m unittest discover -s tests` (verify no regressions).
