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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Unified Python CLI for gh-address-cr.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "command",
        choices=sorted(COMMAND_TO_SCRIPT),
        help=(
            "Subcommand to execute.\n"
            "Preferred high-level commands:\n"
            "  cli.py review owner/repo 123 --input -\n"
            "  cli.py threads owner/repo 123\n"
            "  cli.py findings owner/repo 123 --input findings.json\n"
            "  cli.py adapter owner/repo 123 python3 tools/review_adapter.py\n"
            "\n"
            "Advanced commands:\n"
            "  cli.py cr-loop local json owner/repo 123 --input findings.json\n"
            "  cli.py cr-loop mixed adapter owner/repo 123 python3 tools/review_adapter.py\n"
            "  cli.py cr-loop mixed code-review owner/repo 123 --input -\n"
            "  cli.py control-plane mixed json owner/repo 123 --input findings.json\n"
            "  cli.py control-plane mixed code-review owner/repo 123 --input -\n"
            "  cli.py prepare-code-review mixed owner/repo 123\n"
            "  cli.py run-once owner/repo 123\n"
            "  cli.py final-gate --no-auto-clean owner/repo 123\n"
            "  cli.py session-engine gate owner/repo 123"
        ),
    )
    parser.add_argument("args", nargs=argparse.REMAINDER, help="Arguments passed through to the selected subcommand.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
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
