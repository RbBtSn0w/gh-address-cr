from __future__ import annotations

import json
import re
import textwrap
from typing import Any


class FindingsFormatError(ValueError):
    pass


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


def parse_records(raw: str) -> list[dict[str, Any]]:
    payload = raw.strip()
    if not payload:
        return []
    if payload.startswith("["):
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            return _parse_ndjson(payload, exc)
        if not isinstance(data, list):
            raise FindingsFormatError("Expected a JSON array.")
        return data
    if payload.startswith("{"):
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            return _parse_ndjson(payload, exc)
        if not isinstance(data, dict):
            raise FindingsFormatError("Expected a JSON object.")
        for key in ("findings", "issues", "results"):
            if isinstance(data.get(key), list):
                return data[key]
        return [data]
    return _parse_ndjson(payload, None)


def _parse_ndjson(payload: str, original_error: json.JSONDecodeError | None) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    lines = [line for line in payload.splitlines() if line.strip()]
    if not lines and original_error is not None:
        raise FindingsFormatError(str(original_error)) from original_error
    for line_number, line in enumerate(lines, start=1):
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise FindingsFormatError(f"Invalid NDJSON input on line {line_number}: {exc}") from exc
        records.append(record)
    return records


def normalize_finding(record: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise FindingsFormatError("Each finding must be a JSON object.")

    path = record.get("path") or record.get("file") or record.get("filename")
    line = record.get("line") or record.get("start_line") or record.get("position")
    title = record.get("title") or record.get("rule") or record.get("check") or "Imported review finding"
    body = record.get("body") or record.get("message") or record.get("description") or title

    if not path:
        raise FindingsFormatError("Each finding must include path/file/filename.")
    if line in (None, ""):
        raise FindingsFormatError("Each finding must include line/start_line/position.")
    try:
        normalized_line = int(line)
    except (TypeError, ValueError) as exc:
        raise FindingsFormatError(f"Invalid line value: {line}") from exc

    normalized: dict[str, Any] = {
        "title": str(title),
        "path": str(path),
        "line": normalized_line,
        "body": str(body),
    }
    for field in ("start_line", "end_line", "severity", "category", "confidence", "head_sha"):
        if field in record and record[field] not in (None, ""):
            normalized[field] = record[field]
    return normalized


def extract_finding_blocks(raw: str) -> list[str]:
    blocks: list[str] = []
    current: list[str] | None = None
    for line in raw.splitlines():
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
        raise FindingsFormatError("Unterminated finding block. Close it with ```.")
    return blocks


def parse_finding_block(block: str) -> dict[str, Any]:
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
            raise FindingsFormatError(f"Invalid finding line: {line!r}")
        key, value = line.split(":", 1)
        key = FIELD_ALIASES.get(key.strip().lower(), key.strip().lower())
        value = value.lstrip()
        if key not in ALLOWED_FIELDS:
            raise FindingsFormatError(f"Unsupported finding field: {key}")
        if key == "body":
            if value in {"|", ">"}:
                in_body = True
            elif value:
                body_lines.append(value)
                in_body = True
            else:
                in_body = True
            continue
        fields[key] = value

    for required in ("title", "path", "line"):
        if required not in fields or not str(fields[required]).strip():
            raise FindingsFormatError(f"Each finding block must include a {required}.")
    if not body_lines:
        raise FindingsFormatError("Each finding block must include a body.")
    body = textwrap.dedent("\n".join(body_lines)).strip()
    if not body:
        raise FindingsFormatError("Each finding block must include a non-empty body.")
    try:
        line_number = int(fields["line"])
    except ValueError as exc:
        raise FindingsFormatError(f"Invalid line value: {fields['line']!r}") from exc

    finding: dict[str, Any] = {
        "title": fields["title"].strip(),
        "path": fields["path"].strip(),
        "line": line_number,
        "body": body,
    }
    for optional in ("severity", "category", "confidence", "head_sha"):
        if optional in fields and fields[optional] not in {"", None}:
            finding[optional] = fields[optional]
    return finding


def parse_finding_blocks(raw: str) -> list[dict[str, Any]]:
    payload = raw.strip()
    if not payload:
        return []
    blocks = extract_finding_blocks(payload)
    if not blocks:
        raise FindingsFormatError("No fixed `finding` blocks found. Use fenced ```finding blocks.")
    return [parse_finding_block(block) for block in blocks]
