#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path

from python_common import findings_file


FINDING_FENCE = re.compile(r"^```(?:finding|review-finding)\s*$", re.IGNORECASE)
CLOSING_FENCE = re.compile(r"^```\s*$")
FIELD_ALIASES = {
    "file": "path",
    "filename": "path",
    "start_line": "line",
    "position": "line",
    "rule": "title",
    "check": "title",
    "message": "body",
    "description": "body",
}
ALLOWED_FIELDS = {"title", "path", "line", "body", "severity", "category", "confidence", "head_sha"}


def load_payload(input_path: str) -> str:
    if input_path == "-":
        return sys.stdin.read()
    return Path(input_path).read_text(encoding="utf-8")


def extract_blocks(raw: str) -> list[str]:
    blocks: list[str] = []
    lines = raw.splitlines()
    current: list[str] | None = None

    for line in lines:
        if current is None:
            if FINDING_FENCE.match(line):
                current = []
            continue

        if CLOSING_FENCE.match(line):
            blocks.append("\n".join(current))
            current = None
            continue
        current.append(line)

    if current is not None:
        raise SystemExit("Unterminated finding block. Close it with ```.")
    return blocks


def parse_block(block: str) -> dict:
    fields: dict[str, str] = {}
    body_lines: list[str] = []
    in_body = False

    for raw_line in block.splitlines():
        line = raw_line.rstrip()
        if in_body:
            body_lines.append(line)
            continue
        if not line.strip():
            continue
        if ":" not in line:
            raise SystemExit(f"Invalid finding line: {line!r}")
        key, value = line.split(":", 1)
        key = FIELD_ALIASES.get(key.strip().lower(), key.strip().lower())
        value = value.lstrip()
        if key not in ALLOWED_FIELDS:
            raise SystemExit(f"Unsupported finding field: {key}")
        if key == "body":
            in_body = True
            if value and value not in {"|", ">"}:
                body_lines.append(value)
            continue
        fields[key] = value

    if "title" not in fields or not str(fields["title"]).strip():
        raise SystemExit("Each finding block must include a title.")
    if "path" not in fields or not str(fields["path"]).strip():
        raise SystemExit("Each finding block must include a path.")
    if not body_lines:
        raise SystemExit("Each finding block must include a body.")

    body = "\n".join(body_lines).rstrip()
    if not body:
        raise SystemExit("Each finding block must include a non-empty body.")

    line_value = fields.get("line")
    if line_value is None or not str(line_value).strip():
        raise SystemExit("Each finding block must include a line.")
    try:
        line = int(str(line_value).strip())
    except ValueError as exc:
        raise SystemExit(f"Invalid line value: {line_value!r}") from exc

    finding = {
        "title": fields["title"].strip(),
        "path": fields["path"].strip(),
        "line": line,
        "body": body,
    }
    for optional in ("severity", "category", "confidence", "head_sha"):
        if optional in fields and fields[optional] not in {"", None}:
            finding[optional] = fields[optional]
    return finding


def parse_findings(raw: str) -> list[dict]:
    payload = raw.strip()
    if not payload:
        return []
    blocks = extract_blocks(payload)
    if not blocks:
        raise SystemExit("No finding blocks found. Use fenced ```finding blocks.")
    return [parse_block(block) for block in blocks]


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
