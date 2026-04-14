#!/usr/bin/env python3
import argparse
import subprocess
import sys
from pathlib import Path


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
            "usage: cli.py review <owner/repo> <pr_number> [--input <path>|-]\n\n"
            "High-level PR review entrypoint.\n\n"
            "Use when you want the full PR review workflow to run automatically.\n"
            "Prefer --input - with stdin for findings produced in the current step.\n"
        )
    if command == "threads":
        return (
            "usage: cli.py threads <owner/repo> <pr_number>\n\n"
            "High-level GitHub review-thread entrypoint.\n\n"
            "Use when only GitHub review threads need processing.\n"
        )
    if command == "findings":
        return (
            "usage: cli.py findings <owner/repo> <pr_number> --input <path>|-\n\n"
            "High-level local findings entrypoint.\n\n"
            "Use when findings already exist as JSON or are piped in through stdin.\n"
        )
    if command == "adapter":
        return (
            "usage: cli.py adapter <owner/repo> <pr_number> <adapter_cmd...>\n\n"
            "High-level adapter entrypoint.\n\n"
            "Use when an adapter command prints findings JSON.\n"
        )
    return ""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Unified Python CLI for gh-address-cr.",
        formatter_class=argparse.RawTextHelpFormatter,
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
