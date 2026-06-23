# Tech Debt Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve Open Issues 152, 153, and 154 by fixing mypy type errors, removing the telemetry re-export shim, refactoring the `HighLevelReviewRuntime.handle` command, and narrowing broad exceptions.

**Architecture:** 
1. Mypy type fixes: add precise type annotations (`dict[str, Any]`, `list[Any]`, `cast`) to prevent union-attr and dict-item type warnings. Fix the latent dict timing bug in `telemetry.py` by operating directly on typed variables.
2. Telemetry decomposition: rewrite internal imports to pull content-safety helpers directly from `telemetry_safety.py`, then delete the 26-name re-export shim from `telemetry.py`.
3. Handler refactoring & exception narrowing: split `HighLevelReviewRuntime.handle` into focused helper methods (`_preflight_check`, `_ingest_and_evaluate`, `_handle_exception`). Replace top-level Exception swallowing in non-boundary paths with specific exception catches, logging telemetry errors where appropriate.

**Tech Stack:** Python 3.10+, Ruff, Mypy

## Global Constraints
- Target python version: Python 3.10+
- McCabe complexity threshold: max-complexity = 15 (reduced from 20)
- All public/cli interfaces must remain backwards compatible.

---

### Task 1: Mypy Type Safety & Latent Bug Fix (Issue 152)

**Files:**
- Modify: `src/gh_address_cr/core/telemetry.py`
- Modify: `src/gh_address_cr/commands/submit_feedback.py`
- Modify: `src/gh_address_cr/commands/high_level.py`
- Modify: `src/gh_address_cr/core/cr_metrics.py`
- Modify: `src/gh_address_cr/core/agent_protocol.py`
- Modify: `src/gh_address_cr/core/agent_batch.py`
- Modify: `src/gh_address_cr/commands/doctor.py`
- Modify: `src/gh_address_cr/core/runtime_kernel/session_projection.py`
- Modify: `src/gh_address_cr/core/runtime_kernel/final_gate.py`
- Modify: `src/gh_address_cr/core/workflow.py`
- Modify: `src/gh_address_cr/commands/final_gate.py`
- Modify: `src/gh_address_cr/commands/agent.py`

**Interfaces:**
- Consumes: None
- Produces: Mypy type-safe codebase with zero errors

- [ ] **Step 1: Implement fixes for telemetry.py latent bug and other warnings**
  Declare `report: dict[str, Any]` and append to the `diagnostics` local list of strings rather than mutating `report["diagnostics"]` which triggers mypy object errors.
- [ ] **Step 2: Implement type annotations in submit_feedback.py**
  Annotate `context: dict[str, Any]` in `load_feedback_context` and update parameter type of `format_lookup_error` to `Exception | SystemExit` or `BaseException`.
- [ ] **Step 3: Implement type annotations in high_level.py**
  Annotate `metrics: dict[str, Any]` and `items: dict[str, Any]` in `_native_summary` and `_native_thread_rows` / `_blocking_local_items` to resolve `union-attr` errors.
- [ ] **Step 4: Annotate cr_metrics.py dictionary literal**
  Annotate `span_ms: dict[str, int | None]` or `dict[str, Any]` in `cr_metrics.py` to allow `None` values.
- [ ] **Step 5: Fix type warnings in agent_protocol.py, agent_batch.py, doctor.py, and session_projection.py**
  Annotate `profile_fix_reply`, `response_fix_reply`, and `payload` with `dict[str, Any]` or `list[Any]`. Check and handle `session` being `None` in `session_projection.py`.
- [ ] **Step 6: Update validation_commands type signature in workflow.py**
  Change `validation_commands: list[dict[str, str]]` to `list[dict[str, Any]]` (or `list[dict[str, str | float]]`) in `record_evidence_profile`, `record_validation_evidence`, `fast_fix_item`, and `trivial_fix_item`.
- [ ] **Step 7: Run Mypy to verify errors are resolved**
  Run: `mypy src/gh_address_cr`
  Expected: Found 0 errors or significantly reduced count.

---

### Task 2: Remove Telemetry Re-Export Shim & Migrate Imports (Issue 153)

**Files:**
- Modify: `src/gh_address_cr/core/telemetry.py`
- Modify: `src/gh_address_cr/core/agent_protocol.py`
- Modify: `src/gh_address_cr/core/command_runner.py`
- Modify: `tests/core/test_telemetry.py`

**Interfaces:**
- Consumes: `gh_address_cr.core.telemetry_safety` exports
- Produces: De-shimmed `telemetry.py`

- [ ] **Step 1: Migrate agent_protocol.py imports**
  Import `command_label` and `is_inline_env_assignment` directly from `gh_address_cr.core.telemetry_safety` instead of `telemetry`.
- [ ] **Step 2: Migrate command_runner.py imports**
  Import `command_label` directly from `gh_address_cr.core.telemetry_safety`.
- [ ] **Step 3: Migrate tests/core/test_telemetry.py imports**
  Import `command_label` and `is_inline_env_assignment` directly from `gh_address_cr.core.telemetry_safety`.
- [ ] **Step 4: Delete the shim from telemetry.py**
  Remove lines 22-47 (the import block from `gh_address_cr.core.telemetry_safety` with `noqa: F401`).
- [ ] **Step 5: Run tests and type-checks to verify**
  Run: `mypy src/gh_address_cr && python3 -m unittest discover -s tests`
  Expected: Success.

---

### Task 3: Decompose Handlers & Narrow Exceptions (Issue 154)

**Files:**
- Modify: `src/gh_address_cr/commands/high_level.py`
- Modify: `src/gh_address_cr/orchestrator/harness.py`
- Modify: `src/gh_address_cr/commands/final_gate.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: None
- Produces: Decomposed `HighLevelReviewRuntime.handle` function with complexity < 15, and refined exception swallowing logic.

- [ ] **Step 1: Decompose HighLevelReviewRuntime.handle**
  Extract parameter checks and findings ingestion into helper functions `_preflight_check` and `_ingest_and_evaluate`.
- [ ] **Step 2: Lower McCabe complexity threshold in pyproject.toml**
  Set `max-complexity = 15` under `[tool.ruff.lint.mccabe]`.
- [ ] **Step 3: Narrow exception catch in orchestrator/harness.py check_runtime_version**
  Catch `(ValueError, IndexError, AttributeError, NameError)` instead of `Exception`.
- [ ] **Step 4: Add logging to final_gate.py fail-open telemetry catches**
  Call `core_telemetry._log_telemetry_failure` inside fail-open `except Exception:` blocks in `final_gate.py`.
- [ ] **Step 5: Run Ruff, Mypy, and unit tests to verify**
  Run: `ruff check src tests && mypy src/gh_address_cr && python3 -m unittest discover -s tests`
  Expected: Success, all checks pass.
