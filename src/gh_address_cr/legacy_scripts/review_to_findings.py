#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

from gh_address_cr.intake.findings import parse_finding_blocks
from python_common import findings_file


def load_payload(input_path: str) -> str:
    if input_path == "-":
        return sys.stdin.read()
    return Path(input_path).read_text(encoding="utf-8")


def parse_findings(raw: str) -> list[dict]:
    return parse_finding_blocks(raw)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert Markdown review blocks into standardized findings JSON.",
    )
    parser.add_argument("--input", default="-", help="Review input file. Use '-' or omit to read from stdin.")
    parser.add_argument(
        "--output",
        default="",
        help="Optional output file. Defaults to the cache-backed findings path for the target PR.",
    )
    parser.add_argument(
        "--workspace",
        default="",
        help="Optional PR workspace directory. Used as the cache-backed default output location.",
    )
    parser.add_argument("repo")
    parser.add_argument("pr_number")
    args = parser.parse_args()

    findings = parse_findings(load_payload(args.input))

    if args.output == "-":
        output_path = None
    elif args.output:
        output_path = Path(args.output)
    elif args.workspace:
        output_path = Path(args.workspace) / "code-review-findings.json"
    else:
        output_path = findings_file(args.repo, args.pr_number)
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(findings, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    json.dump(findings, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
