from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

from gh_address_cr.core import paths as core_paths
from gh_address_cr.core.evaluation.archive import MANIFEST_NAME, capture_observation_inputs, project_archive
from gh_address_cr.core.evaluation.catalog import EvaluationCatalog
from gh_address_cr.core.evaluation.comparison import compare_runs
from gh_address_cr.core.evaluation.observations import append_observations, load_observations, validate_observation
from gh_address_cr.core.io import write_json_atomic
from gh_address_cr.github.client import GitHubClient


def _emit(payload: dict[str, Any], fmt: str = "json") -> None:
    if fmt == "markdown":
        print("# Evaluation\n\n```json\n" + json.dumps(payload, indent=2, sort_keys=True) + "\n```")
    else:
        print(json.dumps(payload, sort_keys=True))


def _error(reason_code: str, message: str, exit_code: int) -> int:
    _emit({"status": "FAILED", "reason_code": reason_code, "message": message})
    return exit_code


def _archive_dirs(repo: str | None = None, pr_number: str | None = None) -> list[Path]:
    root = core_paths.state_dir() / "archive"
    if not root.exists():
        return []
    if repo:
        roots = [root / core_paths.normalize_repo(repo)]
    else:
        roots = [path for path in root.iterdir() if path.is_dir()]
    result: list[Path] = []
    for repo_root in roots:
        pr_roots = [repo_root / f"pr-{pr_number}"] if pr_number else list(repo_root.glob("pr-*"))
        for pr_root in pr_roots:
            result.extend(sorted(path.parent for path in pr_root.glob(f"*/{MANIFEST_NAME}")))
    return result


def _observe(args: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="gh-address-cr evaluation observe")
    parser.add_argument("repo")
    parser.add_argument("pr_number")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    parsed = parser.parse_args(args)
    try:
        matching = []
        for run_dir in _archive_dirs(parsed.repo, parsed.pr_number):
            manifest = json.loads((run_dir / MANIFEST_NAME).read_text(encoding="utf-8"))
            if manifest.get("run_id") == parsed.run_id:
                matching.append(manifest)
        if len(matching) != 1:
            return _error("EVALUATION_RUN_NOT_FOUND", "Exactly one archived run must match --run-id.", 4)
        observations = capture_observation_inputs(GitHubClient(), parsed.repo, parsed.pr_number, parsed.run_id)
        for observation in observations:
            validate_observation(observation, matching[0])
        result = append_observations(core_paths.evaluation_observations_file(parsed.repo, parsed.pr_number), observations)
    except ValueError as exc:
        reason = "EVALUATION_INPUT_UNSAFE" if "unsafe" in str(exc).lower() else "EVALUATION_INPUT_INVALID"
        return _error(reason, str(exc), 5)
    except Exception as exc:
        return _error("EVALUATION_OBSERVATION_AMBIGUOUS", str(exc), 5)
    reason = "EVALUATION_OBSERVATION_RECORDED" if result["accepted_count"] else "EVALUATION_OBSERVATION_DUPLICATE"
    _emit({"status": "SUCCESS", "reason_code": reason, **result}, parsed.format)
    return 0


def _rebuild(args: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="gh-address-cr evaluation rebuild")
    parser.add_argument("--repo")
    parser.add_argument("--pr-number")
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    parsed = parser.parse_args(args)
    records = []
    skipped = 0
    try:
        for run_dir in _archive_dirs(parsed.repo, parsed.pr_number):
            manifest = json.loads((run_dir / MANIFEST_NAME).read_text(encoding="utf-8"))
            observations = load_observations(core_paths.evaluation_observations_file(manifest["repo"], manifest["pr_number"]))
            records.append(project_archive(run_dir, observations))
        result = EvaluationCatalog(core_paths.global_evaluation_catalog_file()).rebuild(records)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        if "unsupported" in str(exc).lower() and "schema" in str(exc).lower():
            return _error("UNSUPPORTED_EVALUATION_SCHEMA", str(exc), 2)
        return _error("EVALUATION_REBUILD_FAILED", str(exc), 5)
    _emit({"reason_code": "EVALUATION_REBUILD_COMPLETED", "archive_count": len(records), "skipped_count": skipped, **result}, parsed.format)
    return 0


def _show(args: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="gh-address-cr evaluation show")
    parser.add_argument("repo")
    parser.add_argument("pr_number")
    parser.add_argument("--run-id")
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    parsed = parser.parse_args(args)
    catalog = EvaluationCatalog(core_paths.global_evaluation_catalog_file())
    try:
        record = catalog.find_run(parsed.repo, parsed.pr_number, parsed.run_id)
    except FileNotFoundError:
        return _error("EVALUATION_CATALOG_MISSING", "Run evaluation rebuild first.", 4)
    except sqlite3.DatabaseError as exc:
        return _error("EVALUATION_CATALOG_CORRUPT", str(exc), 5)
    if record is None:
        return _error("EVALUATION_RUN_NOT_FOUND", "No matching evaluation run.", 4)
    _emit(record, parsed.format)
    return 0


def _compare(args: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="gh-address-cr evaluation compare")
    parser.add_argument("--baseline-version", required=True)
    parser.add_argument("--candidate-version", required=True)
    parser.add_argument("--repo")
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    parser.add_argument("--output")
    parsed = parser.parse_args(args)
    catalog = EvaluationCatalog(core_paths.global_evaluation_catalog_file())
    try:
        baseline = catalog.query_runs(parsed.baseline_version)
        candidate = catalog.query_runs(parsed.candidate_version)
    except FileNotFoundError:
        return _error("EVALUATION_CATALOG_MISSING", "Run evaluation rebuild first.", 4)
    except sqlite3.DatabaseError as exc:
        return _error("EVALUATION_CATALOG_CORRUPT", str(exc), 5)
    if parsed.repo:
        baseline = [row for row in baseline if row.get("repo") == parsed.repo]
        candidate = [row for row in candidate if row.get("repo") == parsed.repo]
    started = time.perf_counter()
    result = compare_runs(baseline, candidate)
    report_overhead_ms = round((time.perf_counter() - started) * 1000, 3)
    result.setdefault("operational_health", {})["report_generation_overhead_ms"] = report_overhead_ms
    result["operational_health"]["report_generation_budget_ms"] = 250.0
    if report_overhead_ms > 250.0:
        result["operational_health"]["report_generation_status"] = "degraded"
    else:
        result["operational_health"]["report_generation_status"] = "healthy"
    if parsed.output:
        output = Path(parsed.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        result["report_artifact"] = str(output)
        write_json_atomic(output, result)
    _emit(result, parsed.format)
    return 0


def handle_evaluation_command(subcommand: str | None, first_arg: str | None, passthrough: list[str]) -> int:
    if subcommand in {"-h", "--help"}:
        print("usage: gh-address-cr evaluation {observe,rebuild,show,compare} ...")
        return 0
    if not subcommand:
        print("evaluation requires a subcommand: observe, rebuild, show, or compare", file=sys.stderr)
        return 2
    args = ([first_arg] if first_arg else []) + list(passthrough)
    handlers = {"observe": _observe, "rebuild": _rebuild, "show": _show, "compare": _compare}
    handler = handlers.get(subcommand)
    if handler is None:
        print(f"Unknown evaluation command: {subcommand}", file=sys.stderr)
        return 2
    try:
        return handler(args)
    except SystemExit as exc:
        return int(exc.code or 0)
