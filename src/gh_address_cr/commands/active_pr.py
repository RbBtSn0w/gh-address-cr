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


class DetachedHeadError(RuntimeError):
    """Raised when the current checkout has no branch to use as PR scope."""


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
        raise DetachedHeadError("Current git branch is detached or empty. Pass --head explicitly.")
    return branch


# Strips userinfo (e.g. an embedded token: https://ghp_xxx@github.com/...) from an
# http(s)://user[:pass]@host URL before it reaches next_action, which is written to
# stdout/stderr -- that's the only scheme where an embedded token is realistic. SSH
# forms are left untouched: `git@host:path` (scp-like, no "://") carries no embedded
# secret, only the fixed "git" login name, and `ssh://git@host/...` needs that same
# `git@` to remain a usable, copy-pasteable remote -- stripping it would silently
# rewrite the URL into one that no longer matches the configured remote.
_URL_USERINFO_RE = re.compile(r"^(https?://)[^/@]+@")


def _strip_url_userinfo(url: str) -> str:
    return _URL_USERINFO_RE.sub(r"\1", url)


def _other_git_remotes(*, exclude: str = "origin") -> dict[str, str]:
    try:
        output = _git_output(["git", "remote", "-v"])
    except RuntimeError:
        return {}
    remotes: dict[str, str] = {}
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 2 or parts[0] == exclude:
            continue
        name, url = parts[0], parts[1]
        # `git remote -v` lists a (fetch) and a (push) line per remote, which can
        # differ (e.g. HTTPS fetch, SSH push). Prefer (fetch) regardless of which
        # line appears first, rather than silently keeping whichever was seen first.
        is_fetch = len(parts) >= 3 and parts[2] == "(fetch)"
        if name not in remotes or is_fetch:
            remotes[name] = _strip_url_userinfo(url)
    return remotes


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


def _resolve_repo_and_head(parsed: argparse.Namespace) -> tuple[dict[str, str | None], RuntimeError | None]:
    """Resolve repo and head independently so a failure in one still reports the other.

    Returns (resolved, error): `resolved` always has repo/head/repo_source/head_source
    (any may be None), suitable for embedding directly as the payload's `resolved`
    field; `error` is the first RuntimeError encountered, if any.
    """
    repo = parsed.repo
    repo_source: str | None = "--repo" if parsed.repo else None
    repo_error: RuntimeError | None = None
    if not repo:
        try:
            repo = _derive_current_repo()
            repo_source = "remote.origin.url"
        except RuntimeError as exc:
            repo_error = exc

    head = parsed.head
    head_source: str | None = "--head" if parsed.head else None
    head_error: RuntimeError | None = None
    if not head:
        try:
            head = _derive_current_branch()
            head_source = "git branch --show-current"
        except RuntimeError as exc:
            head_error = exc

    resolved: dict[str, str | None] = {
        "repo": repo,
        "head": head,
        "repo_source": repo_source,
        "head_source": head_source,
    }
    return resolved, (repo_error or head_error)


def resolve_current_pr_scope(*, repo: str | None = None, head: str | None = None) -> dict:
    """Resolve the current checkout to one open PR without emitting CLI output."""
    parsed = argparse.Namespace(repo=repo, head=head)
    resolved, error = _resolve_repo_and_head(parsed)
    if error is not None:
        return {
            "status": protocol_codes.ACTIVE_PR_LOOKUP_FAILED,
            "repo": resolved["repo"],
            "head": resolved["head"],
            "reason_code": "DETACHED_HEAD" if isinstance(error, DetachedHeadError) else "ACTIVE_PR_TARGET_REQUIRED",
            "waiting_on": "active_pr_target",
            "next_action": f"{error} Pass --repo <owner/repo> and --head <branch> explicitly.",
            "exit_code": 2,
        }
    assert resolved["repo"] is not None and resolved["head"] is not None
    result = run_cmd(
        ["gh", "pr", "list", "--repo", resolved["repo"], "--state", "open", "--head", resolved["head"], "--json", "number,url,headRefName,state"],
        timeout=GH_QUERY_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        diagnostics = classify_github_failure(result.stderr, result.stdout, result.returncode, [])
        return {
            "status": protocol_codes.ACTIVE_PR_LOOKUP_FAILED,
            "repo": resolved["repo"],
            "head": resolved["head"],
            "reason_code": "ACTIVE_PR_QUERY_FAILED",
            "waiting_on": github_waiting_on(diagnostics),
            "next_action": "Fix the GitHub CLI query failure, then rerun `gh-address-cr active-pr`.",
            "exit_code": PR_IO_PREFLIGHT_EXIT,
            "diagnostics": diagnostics,
        }
    try:
        rows = json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        rows = []
    if not isinstance(rows, list) or not rows:
        return {"status": "NO_ACTIVE_PR", "repo": resolved["repo"], "head": resolved["head"], "reason_code": "NO_ACTIVE_PR", "waiting_on": "open_pr", "exit_code": 4}
    if len(rows) != 1 or not isinstance(rows[0], dict):
        return {"status": "AMBIGUOUS_ACTIVE_PR", "repo": resolved["repo"], "head": resolved["head"], "reason_code": "AMBIGUOUS_ACTIVE_PR", "waiting_on": "open_pr", "exit_code": 5}
    row = rows[0]
    number = str(row.get("number") or "")
    return {"status": "ACTIVE_PR_FOUND", "repo": resolved["repo"], "head": resolved["head"], "pr_number": number, "url": row.get("url"), "state": row.get("state"), "reason_code": "ACTIVE_PR_FOUND", "waiting_on": None, "exit_code": 0}


def handle_active_pr_command(passthrough: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="gh-address-cr active-pr")
    parser.add_argument("--repo")
    parser.add_argument("--head")
    parsed, remaining = parser.parse_known_args(passthrough)
    if remaining:
        # No derivation is attempted here -- this fires before any git calls -- so
        # `resolved` only echoes what was explicitly passed, same shape as every
        # other path in this function.
        return _emit_active_pr_payload(
            {
                "status": protocol_codes.ACTIVE_PR_LOOKUP_FAILED,
                "repo": parsed.repo,
                "head": parsed.head,
                "resolved": {
                    "repo": parsed.repo,
                    "head": parsed.head,
                    "repo_source": "--repo" if parsed.repo else None,
                    "head_source": "--head" if parsed.head else None,
                },
                "reason_code": protocol_codes.INVALID_ARGUMENTS,
                "waiting_on": "active_pr_target",
                "next_action": f"Unrecognized arguments: {' '.join(remaining)}. Pass --repo <owner/repo> and --head <branch> only.",
                "exit_code": 2,
            },
            stderr=f"Unrecognized arguments: {' '.join(remaining)}",
        )
    resolved, derivation_error = _resolve_repo_and_head(parsed)
    if derivation_error is not None:
        return _emit_active_pr_payload(
            {
                "status": protocol_codes.ACTIVE_PR_LOOKUP_FAILED,
                "repo": resolved["repo"],
                "head": resolved["head"],
                "resolved": resolved,
                "reason_code": "ACTIVE_PR_TARGET_REQUIRED",
                "waiting_on": "active_pr_target",
                "next_action": f"{derivation_error} Pass --repo <owner/repo> and --head <branch> explicitly.",
                "exit_code": 2,
            },
            stderr=str(derivation_error),
        )
    # _resolve_repo_and_head only returns derivation_error=None once both derivations
    # succeeded, so both are guaranteed non-None here.
    assert resolved["repo"] is not None and resolved["head"] is not None
    repo = resolved["repo"]
    repo_source = resolved["repo_source"]
    head = resolved["head"]
    head_source = resolved["head_source"]

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
                "resolved": {"repo": repo, "head": head, "repo_source": repo_source, "head_source": head_source},
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
                "resolved": {"repo": repo, "head": head, "repo_source": repo_source, "head_source": head_source},
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
                "resolved": {"repo": repo, "head": head, "repo_source": repo_source, "head_source": head_source},
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
        next_action = f"No OPEN PR for `{head}` in {repo} (repo from {repo_source}, head from {head_source}). "
        other_remotes = _other_git_remotes()
        if other_remotes:
            candidates = "; ".join(f"{name} → {url}" for name, url in other_remotes.items())
            if parsed.repo:
                next_action += f"Other remotes: {candidates}. Try a different --repo value if the PR lives there."
            else:
                next_action += f"Other remotes: {candidates}. Pass --repo explicitly if the PR lives there."
        else:
            next_action += f"Open a PR or run `gh pr list --repo {repo} --state open --head {head}` to inspect candidates."
        return _emit_active_pr_payload(
            {
                "status": "NO_ACTIVE_PR",
                "repo": repo,
                "head": head,
                "resolved": {"repo": repo, "head": head, "repo_source": repo_source, "head_source": head_source},
                "reason_code": "NO_ACTIVE_PR",
                "waiting_on": "open_pr",
                "next_action": next_action,
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
                "resolved": {"repo": repo, "head": head, "repo_source": repo_source, "head_source": head_source},
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
                "resolved": {"repo": repo, "head": head, "repo_source": repo_source, "head_source": head_source},
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
            "resolved": {
                "repo": repo,
                "head": head,
                "pr_number": pr_number,
                "repo_source": repo_source,
                "head_source": head_source,
            },
            "pr_number": pr_number,
            "url": pr.get("url"),
            "state": pr.get("state"),
            "reason_code": "ACTIVE_PR_FOUND",
            "waiting_on": None,
            "next_action": f"Run `gh-address-cr address {repo} {pr_number} --lean`.",
            "exit_code": 0,
        }
    )
