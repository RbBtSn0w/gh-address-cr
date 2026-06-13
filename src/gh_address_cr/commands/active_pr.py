from __future__ import annotations

import argparse
import json
import re
import shutil
import sys

from gh_address_cr.core import protocol_codes
from gh_address_cr.core.command_runner import run_cmd
from gh_address_cr.github.diagnostics import classify_github_failure, github_waiting_on

PR_IO_PREFLIGHT_EXIT = 5
# Local git introspection is fast; bound it so a wedged git process cannot hang the CLI.
GIT_COMMAND_TIMEOUT_SECONDS = 15.0
# `gh pr list` is a network call; allow more headroom but still cap it.
GH_QUERY_TIMEOUT_SECONDS = 30.0


def _emit_active_pr_payload(payload: dict, *, stderr: str | None = None) -> int:
    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    if stderr:
        print(stderr, file=sys.stderr)
    return int(payload["exit_code"])


def _git_output(command: list[str]) -> str:
    # git is local and deterministic, so do not retry; just bound the wall-clock time.
    result = run_cmd(command, retries=1, timeout=GIT_COMMAND_TIMEOUT_SECONDS)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f"{' '.join(command)} failed.")
    return result.stdout.strip()


def _derive_current_branch() -> str:
    branch = _git_output(["git", "branch", "--show-current"])
    if not branch:
        raise RuntimeError("Current git branch is detached or empty. Pass --head explicitly.")
    return branch


def _derive_current_repo() -> str:
    remote_url = _git_output(["git", "config", "--get", "remote.origin.url"])
    normalized = remote_url.strip().rstrip("/").removesuffix(".git")
    patterns = (
        r"^git@github\.com:(?P<repo>[^/]+/[^/]+)$",
        r"^ssh://git@github\.com/(?P<repo>[^/]+/[^/]+)$",
        r"^https?://github\.com/(?P<repo>[^/]+/[^/]+)$",
    )
    for pattern in patterns:
        match = re.match(pattern, normalized)
        if match:
            return match.group("repo")
    raise RuntimeError(f"Could not derive owner/repo from remote.origin.url: {remote_url}")


def handle_active_pr_command(passthrough: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="gh-address-cr active-pr")
    parser.add_argument("--repo")
    parser.add_argument("--head")
    parsed, _ = parser.parse_known_args(passthrough)
    try:
        repo = parsed.repo or _derive_current_repo()
        head = parsed.head or _derive_current_branch()
    except RuntimeError as exc:
        return _emit_active_pr_payload(
            {
                "status": protocol_codes.ACTIVE_PR_LOOKUP_FAILED,
                "repo": parsed.repo,
                "head": parsed.head,
                "reason_code": "ACTIVE_PR_TARGET_REQUIRED",
                "waiting_on": "active_pr_target",
                "next_action": f"{exc} Pass --repo <owner/repo> and --head <branch> explicitly.",
                "exit_code": 2,
            },
            stderr=str(exc),
        )

    command = [
        "gh",
        "pr",
        "list",
        "--repo",
        repo,
        "--state",
        "open",
        "--head",
        head,
        "--json",
        "number,url,headRefName,state",
    ]
    if shutil.which("gh") is None:
        return _emit_active_pr_payload(
            {
                "status": protocol_codes.ACTIVE_PR_LOOKUP_FAILED,
                "repo": repo,
                "head": head,
                "reason_code": "GH_NOT_FOUND",
                "waiting_on": "github_cli",
                "next_action": "Install GitHub CLI and ensure `gh` is available on PATH, then rerun active-pr.",
                "exit_code": PR_IO_PREFLIGHT_EXIT,
            },
            stderr="Missing GitHub CLI `gh` on PATH.",
        )
    result = run_cmd(command, timeout=GH_QUERY_TIMEOUT_SECONDS)
    if result.returncode != 0:
        diagnostics = classify_github_failure(result.stderr, result.stdout, result.returncode, command)
        return _emit_active_pr_payload(
            {
                "status": protocol_codes.ACTIVE_PR_LOOKUP_FAILED,
                "repo": repo,
                "head": head,
                "reason_code": "ACTIVE_PR_QUERY_FAILED",
                "waiting_on": github_waiting_on(diagnostics),
                "next_action": "Fix the GitHub CLI query failure, then rerun `gh-address-cr active-pr`.",
                "exit_code": PR_IO_PREFLIGHT_EXIT,
                "diagnostics": diagnostics,
            },
            stderr=result.stderr.strip() or result.stdout.strip() or "GitHub active PR lookup failed.",
        )
    try:
        pull_requests = json.loads(result.stdout or "[]")
    except json.JSONDecodeError as exc:
        return _emit_active_pr_payload(
            {
                "status": protocol_codes.ACTIVE_PR_LOOKUP_FAILED,
                "repo": repo,
                "head": head,
                "reason_code": "ACTIVE_PR_INVALID_JSON",
                "waiting_on": "github_cli",
                "next_action": "Inspect `gh pr list` output; it must be a JSON array.",
                "exit_code": PR_IO_PREFLIGHT_EXIT,
            },
            stderr=f"GitHub active PR lookup returned invalid JSON: {exc}",
        )
    if not isinstance(pull_requests, list):
        pull_requests = []

    if not pull_requests:
        return _emit_active_pr_payload(
            {
                "status": "NO_ACTIVE_PR",
                "repo": repo,
                "head": head,
                "reason_code": "NO_ACTIVE_PR",
                "waiting_on": "open_pr",
                "next_action": f"Open a PR or run `gh pr list --repo {repo} --state open --head {head}` to inspect candidates.",
                "pull_requests": [],
                "exit_code": 4,
            }
        )
    if len(pull_requests) > 1:
        return _emit_active_pr_payload(
            {
                "status": "AMBIGUOUS_ACTIVE_PR",
                "repo": repo,
                "head": head,
                "reason_code": "AMBIGUOUS_ACTIVE_PR",
                "waiting_on": "open_pr",
                "next_action": "Multiple OPEN PRs match this branch. Pass the intended PR number to review/address.",
                "pull_requests": pull_requests,
                "exit_code": 5,
            },
            stderr="Multiple OPEN PRs matched the active branch.",
        )

    pr = pull_requests[0] if isinstance(pull_requests[0], dict) else {}
    pr_number = str(pr.get("number") or "").strip()
    if not pr_number or not pr_number.isdigit():
        return _emit_active_pr_payload(
            {
                "status": protocol_codes.ACTIVE_PR_LOOKUP_FAILED,
                "repo": repo,
                "head": head,
                "reason_code": "ACTIVE_PR_INVALID_RESPONSE",
                "waiting_on": "github_cli",
                "next_action": f"Inspect `gh pr list --repo {repo} --state open --head {head}` output; each row must include a PR number.",
                "pull_requests": pull_requests,
                "exit_code": PR_IO_PREFLIGHT_EXIT,
            },
            stderr="GitHub active PR lookup returned a row without a valid PR number.",
        )
    return _emit_active_pr_payload(
        {
            "status": "ACTIVE_PR_FOUND",
            "repo": repo,
            "head": head,
            "pr_number": pr_number,
            "url": pr.get("url"),
            "state": pr.get("state"),
            "reason_code": "ACTIVE_PR_FOUND",
            "waiting_on": None,
            "next_action": f"Run `gh-address-cr address {repo} {pr_number} --lean`.",
            "exit_code": 0,
        }
    )
