#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

from ingest_findings import normalize_finding, parse_records


def load_payload(input_path: str) -> str:
    if input_path == "-":
        return sys.stdin.read()
    return Path(input_path).read_text(encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Normalize structured code-review findings into adapter output JSON."
    )
    parser.add_argument(
        "--input",
        default="-",
        help="Input file containing findings JSON. Use '-' or omit to read from stdin.",
    )
    args = parser.parse_args()

    findings = [normalize_finding(record) for record in parse_records(load_payload(args.input))]
    json.dump(findings, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
