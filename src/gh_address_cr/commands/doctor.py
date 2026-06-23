from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

from gh_address_cr.core import session as session_store
from gh_address_cr.core.command_runner import run_cmd
from gh_address_cr.github.diagnostics import classify_github_failure

# Bound the `gh` network probes the doctor runs; a wedged CLI should not hang the check.
GH_DOCTOR_TIMEOUT_SECONDS = 30.0


def _doctor_check(name: str, passed: bool, *, detail: str | None = None, diagnostics: dict | None = None) -> dict:
    row: dict[str, Any] = {
        "name": name,
        "status": "passed" if passed else "failed",
    }
    if detail:
        row["detail"] = detail
    if diagnostics:
        row["diagnostics"] = diagnostics
    return row


def _run_doctor_gh_check(name: str, command: list[str]) -> dict:
    result = run_cmd(command, timeout=GH_DOCTOR_TIMEOUT_SECONDS)
    if result.returncode == 0:
        detail = result.stdout.strip()
        return _doctor_check(name, True, detail=detail or None)
    diagnostics = classify_github_failure(result.stderr, result.stdout, result.returncode, command)
    return _doctor_check(
        name,
        False,
        detail=result.stderr.strip() or result.stdout.strip() or None,
        diagnostics=diagnostics,
    )


def _doctor_writable_dir_check(name: str, path: Path) -> dict:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".gh-address-cr-doctor-write-test"
        probe.write_text("ok\n", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        diagnostics = classify_github_failure(str(exc), "", None, [name, str(path)])
        return _doctor_check(name, False, detail=str(path), diagnostics=diagnostics)
    return _doctor_check(name, True, detail=str(path))


def handle_doctor_command(args: argparse.Namespace) -> int:
    repo = args.repo
    pr_number = args.pr_number
    checks: list[dict] = []

    gh_path = shutil.which("gh")
    checks.append(_doctor_check("gh_available", bool(gh_path), detail=gh_path or "GitHub CLI `gh` not found on PATH."))
    if gh_path:
        checks.append(_run_doctor_gh_check("gh_auth", ["gh", "auth", "status"]))
        checks.append(_run_doctor_gh_check("gh_viewer", ["gh", "api", "user"]))
        if repo:
            checks.append(_run_doctor_gh_check("repo_access", ["gh", "repo", "view", repo, "--json", "nameWithOwner"]))
    elif repo:
        checks.append(
            _doctor_check(
                "repo_access",
                False,
                detail="Repository access check requires GitHub CLI `gh`.",
            )
        )

    try:
        checks.append(_doctor_writable_dir_check("state_dir", session_store.state_dir()))
    except session_store.SessionError as exc:
        checks.append(_doctor_check("state_dir", False, detail=str(exc)))
    if repo and pr_number:
        try:
            checks.append(_doctor_writable_dir_check("workspace_dir", session_store.workspace_dir(repo, pr_number)))
        except session_store.SessionError as exc:
            checks.append(_doctor_check("workspace_dir", False, detail=str(exc)))

    failed = [check for check in checks if check["status"] != "passed"]
    summary = {
        "status": "FAILED" if failed else "PASSED",
        "reason_code": "DOCTOR_FAILED" if failed else "DOCTOR_PASSED",
        "repo": repo,
        "pr_number": str(pr_number) if pr_number else None,
        "checks": checks,
        "next_action": "Fix failed doctor checks, then rerun the original command." if failed else "Rerun the blocked gh-address-cr command.",
        "exit_code": 5 if failed else 0,
    }
    sys.stdout.write(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    return int(summary["exit_code"])
