# Implementation Plan: CLI and Skill Synchronization (Phase 2)

**Branch**: `011-agent-efficiency-metrics` | **Date**: 2026-05-30 | **Spec**: [spec.md](./spec.md)

## Goal Description

Refactor the compatibility scripts in `src/gh_address_cr/legacy_scripts/` to be minimalist proxies/delegates ("极简代理化") by completely moving their business logic ("彻底下沉逻辑") to a internal package package `src/gh_address_cr/legacy_handlers/`.

This achieves:
1. Pure thin proxy scripts mapped to the skill payload (`skill/scripts/`).
2. Reduced payload size for the skill (since bulky files like `python_common.py` will not be in `legacy_scripts/` and thus will not be synced to `skill/scripts/`).
3. Logic isolation, clean packaging, and testability.

## User Review Required

> [!NOTE]
> All business logic is moved into the `gh_address_cr` package namespace.
> Bulky utilities (like `python_common.py`) will be completely removed from `skill/scripts/` but remain inside the package namespace (`gh_address_cr.legacy_handlers.python_common`).

## Proposed Changes

### Core Package

#### [NEW] [__init__.py](file:///Users/snow/Documents/GitHub/gh-address-cr-skill/src/gh_address_cr/legacy_handlers/__init__.py)
- Create empty package initializer for internal legacy handlers package.

#### [NEW] [python_common.py](file:///Users/snow/Documents/GitHub/gh-address-cr-skill/src/gh_address_cr/legacy_handlers/python_common.py)
- Move all helper functions and classes from legacy `python_common.py`.

#### [NEW] [All implementation scripts in legacy_handlers/](file:///Users/snow/Documents/GitHub/gh-address-cr-skill/src/gh_address_cr/legacy_handlers/)
- Move the original script files from `legacy_scripts/` here:
  - `audit_report.py`
  - `batch_github_execute.py`
  - `batch_resolve.py`
  - `clean_state.py`
  - `code_review_adapter.py`
  - `generate_reply.py`
  - `ingest_findings.py`
  - `list_threads.py`
  - `mark_handled.py`
  - `post_reply.py`
  - `prepare_code_review.py`
  - `publish_finding.py`
  - `resolve_thread.py`
  - `review_to_findings.py`
  - `run_local_review.py`
  - `run_once.py`
  - `submit_action.py`
  - `submit_feedback.py`
- Modify imports inside these files: replace `from python_common import ...` and `import python_common` with package-relative `from . import python_common`.

### Legacy Scripts (Proxies)

#### [MODIFY] [All scripts in legacy_scripts/](file:///Users/snow/Documents/GitHub/gh-address-cr-skill/src/gh_address_cr/legacy_scripts/)
- Replace the contents of the following files with minimalist delegation templates that call their corresponding logic from `gh_address_cr.legacy_handlers`:
  - `audit_report.py`
  - `batch_github_execute.py`
  - `batch_resolve.py`
  - `clean_state.py`
  - `code_review_adapter.py`
  - `generate_reply.py`
  - `ingest_findings.py`
  - `list_threads.py`
  - `mark_handled.py`
  - `post_reply.py`
  - `prepare_code_review.py`
  - `publish_finding.py`
  - `resolve_thread.py`
  - `review_to_findings.py`
  - `run_local_review.py`
  - `run_once.py`
  - `submit_action.py`
  - `submit_feedback.py`

#### [DELETE] [python_common.py](file:///Users/snow/Documents/GitHub/gh-address-cr-skill/src/gh_address_cr/legacy_scripts/python_common.py)
- Delete the file so it is no longer mapped to the skill payload.

### Packaging & Syncing

- Run `python3 scripts/sync_scripts.py` to synchronize thin proxies to `skill/scripts/` and clean up `skill/scripts/python_common.py`.
- Run `python3 scripts/build_plugin_payload.py` to regenerate the plugin payload under `plugin/`.

## Verification Plan

### Automated Tests
- Run `ruff check src tests` to ensure Ruff linting passes.
- Run `python3 -m unittest discover -s tests` to ensure all 544 unit tests pass successfully.
- Run `python3 scripts/sync_scripts.py --check` to ensure no drift in packaging.
