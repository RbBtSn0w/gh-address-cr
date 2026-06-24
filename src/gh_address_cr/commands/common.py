from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from gh_address_cr.core import paths as core_paths

IMPLICIT_SCOPE_VALUE_OPTIONS = {
    "--agent-id",
    "--audit-id",
    "--classification",
    "--commit",
    "--concern-label",
    "--file",
    "--files",
    "--format",
    "--handoff-sha256",
    "--head",
    "--homogeneous-reason",
    "--input",
    "--item-id",
    "--max-iterations",
    "--name",
    "--note",
    "--now",
    "--repo",
    "--review-priority",
    "--role",
    "--scan-id",
    "--severity",
    "--severity-note",
    "--severity-override-note",
    "--snapshot",
    "--source",
    "--test-command",
    "--test-result",
    "--validation",
    "--validation-cmd",
    "--why",
}


def prepend_optional(value: str | None, args: list[str]) -> list[str]:
    return [*([value] if value else []), *args]


def output_workflow_error(exc: Any, *, repo: str, pr_number: str) -> int:
    sys.stdout.write(json.dumps(exc.to_summary(repo=repo, pr_number=pr_number), indent=2, sort_keys=True) + "\n")
    print(str(exc), file=sys.stderr)
    return int(exc.exit_code)


def output_generic_agent_error(repo: str, pr_number: str, reason_code: str, message: str) -> int:
    payload = {
        "status": "FAILED",
        "repo": repo,
        "pr_number": pr_number,
        "reason_code": reason_code,
        "waiting_on": "session",
        "next_action": message,
        "exit_code": 5,
    }
    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(message, file=sys.stderr)
    return 5


def root_passthrough_args(args: argparse.Namespace) -> list[str]:
    return [*([args.repo] if args.repo else []), *([args.pr_number] if args.pr_number else []), *args.args]


def active_cached_sessions() -> list[tuple[str, str, Path]]:
    try:
        root = core_paths.state_dir()
        if not root.exists():
            return []
        sessions: list[tuple[str, str, Path]] = []
        for owner_dir in sorted(path for path in root.iterdir() if path.is_dir()):
            if owner_dir.name == "archive" or "__" not in owner_dir.name:
                continue
            owner, repo_name = owner_dir.name.split("__", 1)
            repo = f"{owner}/{repo_name}"
            for pr_dir in sorted(path for path in owner_dir.iterdir() if path.is_dir() and path.name.startswith("pr-")):
                pr_number = pr_dir.name.removeprefix("pr-")
                session_path = pr_dir / "session.json"
                if pr_number and cached_session_is_active(session_path):
                    sessions.append((repo, pr_number, session_path))
        return sessions
    except OSError:
        # Filesystem unavailable mid-scan: treat as "no cached sessions".
        # Narrowed from Exception so genuine logic errors surface instead of being masked.
        return []


def cached_session_is_active(session_path: Path) -> bool:
    if not session_path.is_file():
        return False
    try:
        payload = json.loads(session_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict):
        return False
    return payload.get("status") == "ACTIVE"


def resolve_active_cached_scope() -> tuple[str, str] | dict:
    sessions = active_cached_sessions()
    if not sessions:
        return {
            "status": "PR_SCOPE_UNRESOLVED",
            "reason_code": "NO_ACTIVE_PR_SCOPE",
            "waiting_on": "pr_scope",
            "next_action": "Pass <owner/repo> <pr_number> explicitly or create exactly one cached PR session.",
            "candidates": [],
            "exit_code": 2,
        }
    if len(sessions) > 1:
        return {
            "status": "PR_SCOPE_UNRESOLVED",
            "reason_code": "AMBIGUOUS_PR_SCOPE",
            "waiting_on": "pr_scope",
            "next_action": "Multiple cached PR sessions exist. Pass <owner/repo> <pr_number> explicitly.",
            "candidates": [
                {"repo": repo, "pr_number": pr_number, "session_file": str(path)} for repo, pr_number, path in sessions
            ],
            "exit_code": 2,
        }
    repo, pr_number, _path = sessions[0]
    return repo, pr_number


def emit_scope_resolution_error(payload: dict) -> int:
    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(payload["next_action"], file=sys.stderr)
    return int(payload["exit_code"])


def scope_positionals(args: list[str], *, value_options: set[str] | None = None) -> list[str]:
    value_options = value_options or IMPLICIT_SCOPE_VALUE_OPTIONS
    positional: list[str] = []
    skip_next = False
    for index, arg in enumerate(args):
        if skip_next:
            skip_next = False
            continue
        if arg == "--":
            positional.extend(args[index + 1 :])
            break
        if arg.startswith("--"):
            option = arg.split("=", 1)[0]
            if option in value_options and "=" not in arg:
                skip_next = True
            continue
        if arg.startswith("-"):
            continue
        positional.append(arg)
    return positional


def maybe_prepend_implicit_scope(
    args: list[str],
    *,
    value_options: set[str] | None = None,
    allow_trailing_positionals: bool = False,
) -> tuple[list[str], dict | None]:
    # Let argparse handle help requests instead of resolving (or failing to
    # resolve) the cached PR scope first.
    if "-h" in args or "--help" in args:
        return args, None
    positional = scope_positionals(args, value_options=value_options)
    if len(positional) >= 2:
        return args, None
    if positional and not allow_trailing_positionals:
        return args, {
            "status": "PR_SCOPE_UNRESOLVED",
            "reason_code": "PARTIAL_PR_SCOPE",
            "waiting_on": "pr_scope",
            "next_action": "Pass both <owner/repo> and <pr_number>, or omit both to use the single cached PR session.",
            "candidates": [],
            "exit_code": 2,
        }
    resolved = resolve_active_cached_scope()
    if isinstance(resolved, dict):
        return args, resolved
    repo, pr_number = resolved
    return [repo, pr_number, *args], None


def agent_args_with_scope(repo: str | None, passthrough: list[str]) -> tuple[list[str], dict | None]:
    args = prepend_optional(repo, passthrough)
    return maybe_prepend_implicit_scope(
        args,
        value_options={*IMPLICIT_SCOPE_VALUE_OPTIONS, "--summary"},
        allow_trailing_positionals=True,
    )
