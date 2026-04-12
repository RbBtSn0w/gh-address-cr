#!/usr/bin/env python3
import argparse
import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
COMMAND_TO_SCRIPT = {
    "control-plane": "control_plane.py",
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
            "Examples:\n"
            "  cli.py control-plane mixed json owner/repo 123 --input findings.json\n"
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
    result = subprocess.run([sys.executable, str(target), *args.args], text=True, capture_output=True)
    if result.stdout:
        sys.stdout.write(result.stdout)
    if result.stderr:
        sys.stderr.write(result.stderr)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
