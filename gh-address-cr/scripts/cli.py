#!/usr/bin/env python3
import argparse
import json
import re
import shutil
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
    "review-to-findings": "review_to_findings.py",
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
OUTPUT_FLAGS = {"--machine", "--human"}
HIGH_LEVEL_GH_COMMANDS = {"review", "threads", "adapter"}
INPUT_REQUIRED_COMMANDS = {"review", "findings"}


def normalize_output_args(args: argparse.Namespace) -> bool:
    inline_flags = {arg for arg in args.args if arg in OUTPUT_FLAGS}
    requested_flags = set(inline_flags)
    if args.machine:
        requested_flags.add("--machine")
    if args.human:
        requested_flags.add("--human")
    if requested_flags == {"--machine", "--human"}:
        print("--machine and --human are mutually exclusive.", file=sys.stderr)
        return False
    if args.command not in HIGH_LEVEL_COMMANDS and requested_flags:
        print("--machine and --human are only supported for review, threads, findings, and adapter.", file=sys.stderr)
        return False
    args.machine = "--machine" in requested_flags
    args.human = "--human" in requested_flags
    args.args = [arg for arg in args.args if arg not in OUTPUT_FLAGS]
    return True


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
            "usage: cli.py review <owner/repo> <pr_number> --input <path>|- [--human|--machine]\n\n"
            "High-level PR review entrypoint.\n\n"
            "Use when you want the full PR review workflow to run automatically.\n"
            "This command does not generate findings; it only consumes findings JSON and orchestrates session/gate handling.\n"
            "Provide findings JSON via --input <path> or --input - with stdin.\n"
            "Missing --input fails immediately instead of waiting on stdin.\n"
            "Default output is a structured JSON summary. Use --human for narrative text.\n"
            "--machine remains a compatibility alias for the default machine summary.\n"
        )
    if command == "threads":
        return (
            "usage: cli.py threads <owner/repo> <pr_number> [--human|--machine]\n\n"
            "High-level GitHub review-thread entrypoint.\n\n"
            "Use when only GitHub review threads need processing.\n"
            "Default output is a structured JSON summary. Use --human for narrative text.\n"
            "--machine remains a compatibility alias for the default machine summary.\n"
        )
    if command == "findings":
        return (
            "usage: cli.py findings <owner/repo> <pr_number> --input <path>|- [--human|--machine]\n\n"
            "High-level local findings entrypoint.\n\n"
            "Use when findings already exist as JSON or are piped in through stdin.\n"
            "Missing --input fails immediately instead of waiting on stdin.\n"
            "Default output is a structured JSON summary. Use --human for narrative text.\n"
            "--machine remains a compatibility alias for the default machine summary.\n"
        )
    if command == "adapter":
        return (
            "usage: cli.py adapter <owner/repo> <pr_number> <adapter_cmd...> [--human|--machine]\n\n"
            "High-level adapter entrypoint.\n\n"
            "Use when an adapter command prints findings JSON.\n"
            "Default output is a structured JSON summary. Use --human for narrative text.\n"
            "--machine remains a compatibility alias for the default machine summary.\n"
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
    stderr_text = result.stderr or ""
    last_error = str(loop_state.get("last_error") or "")
    combined_error = "\n".join(part for part in [last_error, stderr_text] if part)

    reason_code = "COMMAND_FAILED"
    waiting_on = None
    next_action = "Inspect stderr and fix the failing command or input."
    if status == "PASSED":
        reason_code = "PASSED"
        next_action = "No action required."
    elif "requires findings JSON" in combined_error or "requires findings input" in combined_error:
        reason_code = "MISSING_FINDINGS_INPUT"
        waiting_on = "findings_input"
        next_action = (
            f"`{command}` does not generate findings. "
            f"Provide findings JSON with `python3 gh-address-cr/scripts/cli.py {command} {repo} {pr_number} --input <path>|-`."
        )
    elif "Missing GitHub CLI" in combined_error or "gh executable" in combined_error:
        reason_code = "MISSING_GH_CLI"
        waiting_on = "github_cli"
        next_action = "Install GitHub CLI and ensure `gh` is available on PATH, then rerun the command."
    elif status == "NEEDS_HUMAN":
        reason_code = "NEEDS_HUMAN_REVIEW"
        waiting_on = "human_review"
        next_action = f"Inspect {artifact_path} and resolve manually."
    elif status == "BLOCKED" and ("Internal fixer action required:" in combined_error or "Interaction Required" in combined_error):
        reason_code = "WAITING_FOR_FIX"
        waiting_on = "human_fix"
        next_action = f"Address the finding in {artifact_path} and rerun {command}."
    elif status == "BLOCKED":
        reason_code = "BLOCKED"
        waiting_on = "manual_intervention"
        next_action = f"Inspect {artifact_path} and rerun {command} after fixing the blocking issue."
    elif "Gate FAILED" in combined_error:
        reason_code = "BLOCKING_ITEMS_REMAIN"
        waiting_on = "unresolved_items"
        next_action = "Continue processing unresolved items until the final gate passes."

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
        "reason_code": reason_code,
        "waiting_on": waiting_on,
        "next_action": next_action,
        "exit_code": result.returncode,
    }


def build_preflight_summary(
    command: str,
    repo: str,
    pr_number: str,
    *,
    exit_code: int,
    reason_code: str,
    waiting_on: str | None,
    next_action: str,
) -> dict:
    return {
        "status": "FAILED",
        "repo": repo,
        "pr_number": pr_number,
        "item_id": None,
        "item_kind": None,
        "counts": {
            "blocking_items_count": 0,
            "open_local_findings_count": 0,
            "unresolved_github_threads_count": 0,
            "needs_human_items_count": 0,
        },
        "artifact_path": str(workspace_root(repo, pr_number)),
        "reason_code": reason_code,
        "waiting_on": waiting_on,
        "next_action": next_action,
        "exit_code": exit_code,
    }


def has_option(args: list[str], flag: str) -> bool:
    return flag in args


def output_preflight_error(args: argparse.Namespace, repo: str, pr_number: str, message: str, *, reason_code: str, waiting_on: str | None, next_action: str, exit_code: int = 2) -> int:
    if not args.human:
        summary = build_preflight_summary(
            args.command,
            repo,
            pr_number,
            exit_code=exit_code,
            reason_code=reason_code,
            waiting_on=waiting_on,
            next_action=next_action,
        )
        sys.stdout.write(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(message, file=sys.stderr)
    return exit_code


def preflight_high_level(args: argparse.Namespace) -> int | None:
    repo = args.args[0]
    pr_number = args.args[1]

    if args.command in INPUT_REQUIRED_COMMANDS and not has_option(args.args, "--input"):
        return output_preflight_error(
            args,
            repo,
            pr_number,
            f"{args.command} requires findings JSON. This command does not generate findings. Pass --input <path> or --input - and provide findings through stdin.",
            reason_code="MISSING_FINDINGS_INPUT",
            waiting_on="findings_input",
            next_action=f"`{args.command}` does not generate findings. Provide findings JSON with `python3 gh-address-cr/scripts/cli.py {args.command} {repo} {pr_number} --input <path>|-`.",
        )

    if args.command == "adapter" and len(args.args) < 3:
        return output_preflight_error(
            args,
            repo,
            pr_number,
            "adapter requires <adapter_cmd...> after <owner/repo> <pr_number>.",
            reason_code="MISSING_ADAPTER_COMMAND",
            waiting_on="adapter_command",
            next_action=f"Provide an adapter command after `python3 gh-address-cr/scripts/cli.py adapter {repo} {pr_number}`.",
        )

    if args.command in HIGH_LEVEL_GH_COMMANDS and shutil.which("gh") is None:
        return output_preflight_error(
            args,
            repo,
            pr_number,
            "Missing GitHub CLI `gh` on PATH. Install it or add it to PATH before running this command.",
            reason_code="MISSING_GH_CLI",
            waiting_on="github_cli",
            next_action="Install GitHub CLI and ensure `gh` is available on PATH, then rerun the command.",
        )
    return None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Unified Python CLI for gh-address-cr.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--machine",
        action="store_true",
        help="Compatibility alias for the default structured JSON summary.",
    )
    parser.add_argument(
        "--human",
        action="store_true",
        help="Emit human-oriented text instead of the default machine summary.",
    )
    parser.add_argument(
        "command",
        metavar="{review,threads,findings,adapter,review-to-findings}",
        help=(
            "High-level commands:\n"
            "  cli.py review owner/repo 123 --input - [--human]\n"
            "  cli.py threads owner/repo 123 [--human]\n"
            "  cli.py findings owner/repo 123 --input findings.json [--human]\n"
            "  cli.py adapter owner/repo 123 python3 tools/review_adapter.py [--human]\n"
            "Notes:\n"
            "  review consumes findings JSON; it does not generate findings.\n"
            "  High-level commands are the agent-safe public surface.\n"
            "Utility commands:\n"
            "  cli.py review-to-findings owner/repo 123 --input review.md\n"
        ),
    )
    parser.add_argument("args", nargs=argparse.REMAINDER, help="Arguments passed through to the selected subcommand.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command not in COMMAND_TO_SCRIPT:
        supported_commands = ", ".join(sorted(COMMAND_TO_SCRIPT))
        print(f"Unknown command. Supported commands: {supported_commands}.", file=sys.stderr)
        return 2
    if not normalize_output_args(args):
        return 2
    if args.command in HIGH_LEVEL_COMMANDS and args.args and args.args[0] in {"-h", "--help"}:
        print(alias_help(args.command), end="")
        return 0
    if args.command in HIGH_LEVEL_COMMANDS and len(args.args) < 2:
        print("High-level commands require <owner/repo> <pr_number>.", file=sys.stderr)
        return 2
    if args.command in HIGH_LEVEL_COMMANDS:
        preflight_rc = preflight_high_level(args)
        if preflight_rc is not None:
            return preflight_rc
    target = SCRIPT_DIR / COMMAND_TO_SCRIPT[args.command]
    rewritten_args = rewrite_alias_args(args.command, args.args)
    result = subprocess.run([sys.executable, str(target), *rewritten_args], text=True, capture_output=True)
    if args.command in HIGH_LEVEL_COMMANDS and not args.human:
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
