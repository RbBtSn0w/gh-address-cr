#!/usr/bin/env python3
import argparse
import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
RUN_ONCE = SCRIPT_DIR / "run_once.py"
RUN_LOCAL_REVIEW = SCRIPT_DIR / "run_local_review.py"
INGEST_FINDINGS = SCRIPT_DIR / "ingest_findings.py"
FINAL_GATE = SCRIPT_DIR / "final_gate.py"

VALID_MODES = {"remote", "local", "mixed", "ingest"}
VALID_PRODUCERS = {"code-review", "json", "adapter"}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="High-level control-plane dispatcher for gh-address-cr.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("mode", choices=sorted(VALID_MODES))
    parser.add_argument("parts", nargs="*", help="Mode-dependent positional args.")
    parser.add_argument("--audit-id", default="")
    parser.add_argument("--scan-id", default="")
    parser.add_argument("--source", default="")
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


def parse_dispatch(mode: str, parts: list[str]) -> tuple[str | None, str, str, list[str]]:
    if mode == "remote":
        if len(parts) != 2:
            raise SystemExit("remote expects: <owner/repo> <pr_number>")
        return None, parts[0], parts[1], []

    if mode == "ingest":
        if len(parts) == 2:
            return "json", parts[0], parts[1], []
        if len(parts) >= 3:
            return parts[0], parts[1], parts[2], parts[3:]
        raise SystemExit("ingest expects: [producer] <owner/repo> <pr_number>")

    if len(parts) < 3:
        raise SystemExit(f"{mode} expects: <producer> <owner/repo> <pr_number> [adapter_cmd...]")
    return parts[0], parts[1], parts[2], parts[3:]


def run_command(cmd: list[str], *, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, input=stdin, text=True, capture_output=True)


def emit(result: subprocess.CompletedProcess[str]) -> None:
    if result.stdout:
        sys.stdout.write(result.stdout)
    if result.stderr:
        sys.stderr.write(result.stderr)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    producer, repo, pr_number, extra = parse_dispatch(args.mode, args.parts)

    if producer is not None and producer not in VALID_PRODUCERS:
        return die(f"Unsupported producer: {producer}")
    if args.mode == "remote" and producer is not None:
        return die("remote mode does not accept a producer.")
    if args.mode == "ingest" and producer == "adapter":
        return die("ingest mode does not support producer=adapter.")

    source = args.source or (f"local-agent:{producer}" if producer else "")
    stdin_payload = None

    if args.mode in {"local", "mixed", "ingest"}:
        if producer == "adapter":
            if not extra:
                return die("producer=adapter requires an adapter command.")
        else:
            if extra:
                return die(f"producer={producer} does not accept an adapter command.")
            if args.input is None:
                stdin_payload = sys.stdin.read()
                if not stdin_payload.strip():
                    return die(f"producer={producer} requires findings JSON via --input or stdin.")

    results: list[subprocess.CompletedProcess[str]] = []

    if args.mode in {"remote", "mixed"}:
        cmd = [sys.executable, str(RUN_ONCE)]
        if args.audit_id:
            cmd.extend(["--audit-id", args.audit_id])
        cmd.extend([repo, pr_number])
        results.append(run_command(cmd))

    if args.mode in {"local", "mixed", "ingest"}:
        if producer == "adapter":
            cmd = [sys.executable, str(RUN_LOCAL_REVIEW)]
            if args.scan_id:
                cmd.extend(["--scan-id", args.scan_id])
            if source:
                cmd.extend(["--source", source])
            cmd.extend([repo, pr_number, *extra])
            results.append(run_command(cmd))
        else:
            cmd = [sys.executable, str(INGEST_FINDINGS)]
            if args.scan_id:
                cmd.extend(["--scan-id", args.scan_id])
            if source:
                cmd.extend(["--source", source])
            if args.input is not None:
                cmd.extend(["--input", args.input])
            cmd.extend([repo, pr_number])
            results.append(run_command(cmd, stdin=stdin_payload))

    if args.gate:
        cmd = [sys.executable, str(FINAL_GATE), "--no-auto-clean"]
        if args.audit_id:
            cmd.extend(["--audit-id", args.audit_id])
        cmd.extend([repo, pr_number])
        results.append(run_command(cmd))

    exit_code = 0
    for result in results:
        emit(result)
        if result.returncode != 0 and exit_code == 0:
            exit_code = result.returncode
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
