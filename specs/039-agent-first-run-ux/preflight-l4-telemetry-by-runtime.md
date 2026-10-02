# Architecture Preflight: efficiency reports by runtime build (Spec 039 L4)

Trigger: reshapes the telemetry reporting contract (additive report field).
Maintainer note: confirm before touching release versioning. This design does not.

## Problem

The 3.16.0 telemetry regression was found by grouping archived reports by date,
because reports did not say which runtime produced them, and a development checkout
reports the same version as the release.

## Verified install metadata (2026-10-02)

| Install | `direct_url.json` | Metadata version |
|---|---|---|
| Homebrew release | absent | 3.16.0 |
| `pip install git+file://...@branch` | `vcs_info.commit_id` | 3.16.0 |
| `pip install -e .` | `dir_info.editable: true` (plus a local `url`) | stale (3.5.3 while the code was 3.16.0) |
| CI pr-preview | built as `<base>.dev<PR>+<sha>` already | |

| Item | Answer |
|---|---|
| State owner | Unchanged; the report stays advisory. |
| Projection | Additive `runtime` object in `efficiency-report.json`: `version` (from `gh_address_cr.__version__`, never install metadata), `origin` (`package`, `editable`, `vcs`, `local`), `commit` (12-char prefix for `vcs`). The install `url` is never recorded (it can be a local path). |
| Decision function | `core/runtime_build.origin_from_direct_url`. |
| Comparison | `scripts/compare_telemetry_by_runtime.py` groups live and archived reports by runtime label; reports without `runtime` group as `unknown`. Flag kinds drop per-session counts (`error_prone:<op>`, `duration:<op>`, `latency_growth:<op>`). With `--baseline/--candidate` it exits 1 on a median success-rate drop above `--max-success-drop` (default 5 points) or new flag kinds. Output is labels and aggregates only. |
| Release versioning | Untouched (no change to semantic-release, pyproject, or CI version steps). |
| Side effects | None. |
| Tests | `tests/core/test_runtime_build.py`, `tests/test_compare_telemetry_by_runtime.py` (reproduces the 3.15.3 -> 3.16.0 regression shape), journey I2 asserts `report["runtime"]["version"]`. |
