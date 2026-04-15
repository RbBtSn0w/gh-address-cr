#!/usr/bin/env python3
from __future__ import annotations
import argparse
import subprocess
import sys
from pathlib import Path

import uuid
from python_common import findings_file, parse_dispatch, shield_adapter_passthrough, snapshot_file, VALID_MODES, VALID_PRODUCERS
SCRIPT_DIR = Path(__file__).resolve().parent
RUN_ONCE = SCRIPT_DIR / "run_once.py"
RUN_LOCAL_REVIEW = SCRIPT_DIR / "run_local_review.py"
INGEST_FINDINGS = SCRIPT_DIR / "ingest_findings.py"
FINAL_GATE = SCRIPT_DIR / "final_gate.py"
CODE_REVIEW_ADAPTER = SCRIPT_DIR / "code_review_adapter.py"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    argv = shield_adapter_passthrough(argv)
    parser = argparse.ArgumentParser(
        description="High-level control-plane dispatcher for gh-address-cr.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("mode", choices=sorted(VALID_MODES))
    parser.add_argument("parts", nargs="*", help="Mode-dependent positional args.")
    parser.add_argument("--audit-id", default="")
    parser.add_argument("--scan-id", default="")
    parser.add_argument("--source", default=None)
    parser.add_argument("--sync", action="store_true", help="Close missing local findings from the same source.")
    parser.add_argument(
        "--input",
        default=None,
        help="Findings JSON file. Use '-' to read from stdin for json/code-review producers.",
    )
    parser.add_argument(
        "--gate",
        action="store_true",
        help="Run final-gate after the bootstrap path.",
    )
    parse_fn = getattr(parser, "parse_intermixed_args", parser.parse_args)
    return parse_fn(argv)


def die(message: str) -> int:
    print(message, file=sys.stderr)
    return 2


# parse_dispatch is now imported from python_common


def run_command(cmd: list[str], *, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, input=stdin, text=True, capture_output=True)


def emit(result: subprocess.CompletedProcess[str]) -> None:
    if result.stdout:
        sys.stdout.write(result.stdout)
    if result.stderr:
        sys.stderr.write(result.stderr)


def run_or_return(cmd: list[str], *, stdin: str | None = None) -> subprocess.CompletedProcess[str] | None:
    result = run_command(cmd, stdin=stdin)
    emit(result)
    if result.returncode != 0:
        return result
    return None


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    producer, repo, pr_number, extra = parse_dispatch(args.mode, args.parts)

    if producer is not None and producer not in VALID_PRODUCERS:
        return die(
            f"Unsupported producer: {producer}\n"
            "producer expects a category (`code-review`, `json`, `adapter`), not the upstream tool name."
        )
    if args.mode == "remote" and producer is not None:
        return die("remote mode does not accept a producer.")
    if args.mode == "ingest" and producer != "json":
        return die("ingest mode only supports producer=json.")

    if args.sync and not args.source:
        return die("`--sync` requires an explicit --source so missing findings stay scoped to one producer.")

    source = args.source or (f"local-agent:{producer}" if producer else "")
    stdin_payload = None
    persisted_input_path: Path | None = None

    if args.mode in {"local", "mixed", "ingest"}:
        if producer == "adapter":
            if not extra:
                return die("producer=adapter requires an adapter command.")
        else:
            if extra:
                return die(f"producer={producer} does not accept an adapter command.")
            if args.input == "-":
                stdin_payload = sys.stdin.read()
                if not stdin_payload.strip():
                    return die(f"producer={producer} requires findings JSON via --input or stdin.")
            elif args.input is None:
                stdin_payload = sys.stdin.read()
                if not stdin_payload.strip():
                    return die(f"producer={producer} requires findings JSON via --input or stdin.")

    try:
        if args.mode in {"remote", "mixed"}:
            cmd = [sys.executable, str(RUN_ONCE)]
            if args.audit_id:
                cmd.extend(["--audit-id", args.audit_id])
            cmd.extend([repo, pr_number])
            result = run_or_return(cmd)
            if result is not None:
                return result.returncode

        if args.mode in {"local", "mixed", "ingest"}:
            if producer == "adapter":
                cmd = [sys.executable, str(RUN_LOCAL_REVIEW)]
                if args.scan_id:
                    cmd.extend(["--scan-id", args.scan_id])
                if source:
                    cmd.extend(["--source", source])
                if args.sync:
                    cmd.append("--sync")
                cmd.extend([repo, pr_number, *extra])
                result = run_or_return(cmd)
                if result is not None:
                    return result.returncode
            elif producer == "code-review":
                input_arg = args.input
                if stdin_payload is not None:
                    persisted_input_path = findings_file(repo, pr_number, f"findings-stdin-code-review-{uuid.uuid4().hex}.json")
                    persisted_input_path.write_text(stdin_payload, encoding="utf-8")
                    input_arg = str(persisted_input_path)
                cmd = [sys.executable, str(RUN_LOCAL_REVIEW)]
                if args.scan_id:
                    cmd.extend(["--scan-id", args.scan_id])
                if source:
                    cmd.extend(["--source", source])
                if args.sync:
                    cmd.append("--sync")
                cmd.extend(
                    [
                        repo,
                        pr_number,
                        sys.executable,
                        str(CODE_REVIEW_ADAPTER),
                        "--input",
                        input_arg or "-",
                    ]
                )
                result = run_or_return(cmd)
                if result is not None:
                    return result.returncode
            else:
                cmd = [sys.executable, str(INGEST_FINDINGS)]
                if args.scan_id:
                    cmd.extend(["--scan-id", args.scan_id])
                if source:
                    cmd.extend(["--source", source])
                if args.sync:
                    cmd.append("--sync")
                if args.input is not None:
                    cmd.extend(["--input", args.input])
                cmd.extend([repo, pr_number])
                result = run_or_return(cmd, stdin=stdin_payload)
                if result is not None:
                    return result.returncode

        if args.gate:
            cmd = [sys.executable, str(FINAL_GATE), "--no-auto-clean"]
            if args.audit_id:
                cmd.extend(["--audit-id", args.audit_id])
            if args.mode in {"remote", "mixed"}:
                cmd.extend(["--snapshot", str(snapshot_file(repo, pr_number))])
            cmd.extend([repo, pr_number])
            result = run_or_return(cmd)
            if result is not None:
                return result.returncode

        return 0
    finally:
        if persisted_input_path and persisted_input_path.exists():
            persisted_input_path.unlink()


if __name__ == "__main__":
    raise SystemExit(main())
