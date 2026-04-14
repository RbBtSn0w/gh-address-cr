#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
SESSION_ENGINE = SCRIPT_DIR / "session_engine.py"


def load_payload(input_path: str) -> str:
    if input_path == "-":
        return sys.stdin.read()
    return Path(input_path).read_text(encoding="utf-8")


def parse_records(raw: str) -> list[dict]:
    payload = raw.strip()
    if not payload:
        return []
    if payload.startswith("["):
        data = json.loads(payload)
        if not isinstance(data, list):
            raise SystemExit("Expected a JSON array.")
        return data
    if payload.startswith("{"):
        data = json.loads(payload)
        if not isinstance(data, dict):
            raise SystemExit("Expected a JSON object.")
        for key in ("findings", "issues", "results"):
            if isinstance(data.get(key), list):
                return data[key]
        return [data]
    return [json.loads(line) for line in payload.splitlines() if line.strip()]


def normalize_finding(record: dict) -> dict:
    if not isinstance(record, dict):
        raise SystemExit("Each finding must be a JSON object.")

    path = record.get("path") or record.get("file") or record.get("filename")
    line = record.get("line") or record.get("start_line") or record.get("position")
    title = record.get("title") or record.get("rule") or record.get("check") or "Imported review finding"
    body = record.get("body") or record.get("message") or record.get("description") or title

    if not path:
        raise SystemExit("Each finding must include path/file/filename.")
    if line in (None, ""):
        raise SystemExit("Each finding must include line/start_line/position.")

    try:
        normalized_line = int(line)
    except (TypeError, ValueError) as exc:
        raise SystemExit(f"Invalid line value: {line}") from exc

    normalized = {
        "title": str(title),
        "body": str(body),
        "path": str(path),
        "line": normalized_line,
    }

    optional_fields = (
        "start_line",
        "end_line",
        "severity",
        "category",
        "confidence",
        "head_sha",
    )
    for field in optional_fields:
        if field in record and record[field] not in (None, ""):
            normalized[field] = record[field]
    return normalized


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ingest findings JSON from stdin or a file into the PR session."
    )
    parser.add_argument("--scan-id", default="")
    parser.add_argument("--source", default="local-agent:imported")
    parser.add_argument("--sync", action="store_true", help="Close missing local findings from the same source.")
    parser.add_argument(
        "--input",
        default="-",
        help="Input file containing findings JSON. Use '-' or omit to read from stdin.",
    )
    parser.add_argument("repo")
    parser.add_argument("pr_number")
    args = parser.parse_args()

    if not SESSION_ENGINE.exists():
        print(f"Missing session engine: {SESSION_ENGINE}", file=sys.stderr)
        return 1

    findings = [normalize_finding(record) for record in parse_records(load_payload(args.input))]

    subprocess.run(
        [sys.executable, str(SESSION_ENGINE), "init", args.repo, args.pr_number],
        check=True,
        stdout=subprocess.DEVNULL,
    )

    ingest_cmd = [
        sys.executable,
        str(SESSION_ENGINE),
        "ingest-local",
        args.repo,
        args.pr_number,
        "--source",
        args.source,
    ]
    if args.scan_id:
        ingest_cmd.extend(["--scan-id", args.scan_id])
    if args.sync:
        ingest_cmd.append("--sync")

    ingest_result = subprocess.run(
        ingest_cmd,
        input=json.dumps(findings),
        text=True,
        capture_output=True,
    )
    if ingest_result.stdout:
        sys.stdout.write(ingest_result.stdout)
    if ingest_result.stderr:
        sys.stderr.write(ingest_result.stderr)
    return ingest_result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
