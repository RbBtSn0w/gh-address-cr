#!/usr/bin/env python3
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from python_common import normalize_repo, state_dir


SCRIPT_DIR = Path(__file__).resolve().parent
COMMAND_TO_SCRIPT = {
    "review": "cr_loop.py",
    "threads": "cr_loop.py",
    "findings": "cr_loop.py",
    "adapter": "cr_loop.py",
    "cr-loop": "cr_loop.py",
    "control-plane": "control_plane.py",
    "code-review-adapter": "code_review_adapter.py",
    "prepare-code-review": "prepare_code_review.py",
    "run-once": "run_once.py",
    "final-gate": "final_gate.py",
    "list-threads": "list_threads.py",
    "post-reply": "post_reply.py",
    "resolve-thread": "resolve_thread.py",
    "run-local-review": "run_local_review.py",
    "ingest-findings": "ingest_findings.py",
    "publish-finding": "publish_finding.py",
    "mark-handled": "mark_handled.py",
    "audit-report": "audit_report.py",
    "generate-reply": "generate_reply.py",
    "batch-resolve": "batch_resolve.py",
    "clean-state": "clean_state.py",
    "session-engine": "session_engine.py",
}

HIGH_LEVEL_COMMANDS = {"review", "threads", "findings", "adapter"}


def rewrite_alias_args(command: str, passthrough_args: list[str]) -> list[str]:
    if command == "review":
        return ["mixed", "code-review", *passthrough_args]
    if command == "threads":
        return ["remote", *passthrough_args]
    if command == "findings":
        return ["local", "json", *passthrough_args]
    if command == "adapter":
        return ["mixed", "adapter", *passthrough_args]
    return passthrough_args


def alias_help(command: str) -> str:
    if command == "review":
        return (
            "usage: cli.py review <owner/repo> <pr_number> [--input <path>|-] [--machine]\n\n"
            "High-level PR review entrypoint.\n\n"
            "Use when you want the full PR review workflow to run automatically.\n"
            "Prefer --input - with stdin for findings produced in the current step.\n"
            "Use --machine for a structured JSON summary.\n"
        )
    if command == "threads":
        return (
            "usage: cli.py threads <owner/repo> <pr_number> [--machine]\n\n"
            "High-level GitHub review-thread entrypoint.\n\n"
            "Use when only GitHub review threads need processing.\n"
            "Use --machine for a structured JSON summary.\n"
        )
    if command == "findings":
        return (
            "usage: cli.py findings <owner/repo> <pr_number> --input <path>|- [--machine]\n\n"
            "High-level local findings entrypoint.\n\n"
            "Use when findings already exist as JSON or are piped in through stdin.\n"
            "Use --machine for a structured JSON summary.\n"
        )
    if command == "adapter":
        return (
            "usage: cli.py adapter <owner/repo> <pr_number> <adapter_cmd...> [--machine]\n\n"
            "High-level adapter entrypoint.\n\n"
            "Use when an adapter command prints findings JSON.\n"
            "Use --machine for a structured JSON summary.\n"
        )
    return ""


def workspace_root(repo: str, pr_number: str) -> Path:
    return state_dir() / normalize_repo(repo) / f"pr-{pr_number}"


def load_session_payload(repo: str, pr_number: str) -> dict:
    path = workspace_root(repo, pr_number) / "session.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def extract_artifact_path(last_error: str) -> str | None:
    prefix = "Internal fixer action required:"
    if prefix in last_error:
        candidate = last_error.split(prefix, 1)[1].strip()
        if candidate:
            return candidate
    match = re.search(r"(\/\S+\.json)", last_error)
    if match:
        return match.group(1)
    return None


def build_machine_summary(command: str, repo: str, pr_number: str, result: subprocess.CompletedProcess[str]) -> dict:
    session = load_session_payload(repo, pr_number)
    loop_state = session.get("loop_state") if isinstance(session, dict) else {}
    if not isinstance(loop_state, dict):
        loop_state = {}
    metrics = session.get("metrics") if isinstance(session, dict) else {}
    if not isinstance(metrics, dict):
        metrics = {}
    items = session.get("items") if isinstance(session, dict) else {}
    if not isinstance(items, dict):
        items = {}

    status = loop_state.get("status") or "FAILED"
    if result.returncode == 0 and status == "IDLE":
        status = "PASSED"
    elif result.returncode == 0 and status not in {"PASSED", "FAILED", "NEEDS_HUMAN", "BLOCKED"}:
        status = "PASSED"
    elif result.returncode == 4:
        status = "NEEDS_HUMAN"
    elif result.returncode == 5:
        status = "BLOCKED"
    elif result.returncode != 0 and status == "IDLE":
        status = "FAILED"

    item_id = loop_state.get("current_item_id")
    item = items.get(item_id, {}) if item_id else {}
    item_kind = item.get("item_kind") if isinstance(item, dict) else None
    artifact_path = extract_artifact_path(str(loop_state.get("last_error") or "")) or str(workspace_root(repo, pr_number))
    next_action = {
        "PASSED": "No action required.",
        "NEEDS_HUMAN": f"Inspect {artifact_path} and resolve manually.",
        "BLOCKED": f"Address the finding in {artifact_path} and rerun {command}.",
        "FAILED": "Inspect stderr and fix the failing command or input.",
    }.get(status, "Continue processing the current PR session.")

    return {
        "status": status,
        "repo": repo,
        "pr_number": pr_number,
        "item_id": item_id,
        "item_kind": item_kind,
        "counts": {
            "blocking_items_count": metrics.get("blocking_items_count", 0),
            "open_local_findings_count": metrics.get("open_local_findings_count", 0),
            "unresolved_github_threads_count": metrics.get("unresolved_github_threads_count", 0),
            "needs_human_items_count": metrics.get("needs_human_items_count", 0),
        },
        "artifact_path": artifact_path,
        "next_action": next_action,
        "exit_code": result.returncode,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Unified Python CLI for gh-address-cr.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--machine",
        action="store_true",
        help="Emit a structured JSON summary for the high-level entrypoint.",
    )
    parser.add_argument(
        "command",
        metavar="{review,threads,findings,adapter}",
        help=(
            "High-level commands:\n"
            "  cli.py review owner/repo 123 --input -\n"
            "  cli.py threads owner/repo 123\n"
            "  cli.py findings owner/repo 123 --input findings.json\n"
            "  cli.py adapter owner/repo 123 python3 tools/review_adapter.py\n"
        ),
    )
    parser.add_argument("args", nargs=argparse.REMAINDER, help="Arguments passed through to the selected subcommand.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command not in COMMAND_TO_SCRIPT:
        print("Unknown command. Use one of: review, threads, findings, adapter.", file=sys.stderr)
        return 2
    if args.command in HIGH_LEVEL_COMMANDS and args.args and args.args[0] in {"-h", "--help"}:
        print(alias_help(args.command), end="")
        return 0
    target = SCRIPT_DIR / COMMAND_TO_SCRIPT[args.command]
    rewritten_args = rewrite_alias_args(args.command, args.args)
    result = subprocess.run([sys.executable, str(target), *rewritten_args], text=True, capture_output=True)
    if args.machine:
        if args.command not in HIGH_LEVEL_COMMANDS:
            print("--machine is only supported for review, threads, findings, and adapter.", file=sys.stderr)
            return 2
        if len(args.args) < 2:
            print("High-level commands require <owner/repo> <pr_number>.", file=sys.stderr)
            return 2
        summary = build_machine_summary(args.command, args.args[0], args.args[1], result)
        sys.stdout.write(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    else:
        if result.stdout:
            sys.stdout.write(result.stdout)
        if result.stderr:
            error_text = result.stderr
            if args.command in HIGH_LEVEL_COMMANDS and "Unsupported producer:" in error_text:
                error_text += "\nproducer expects a category (`code-review`, `json`, `adapter`), not the upstream tool name.\n"
            sys.stderr.write(error_text)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
