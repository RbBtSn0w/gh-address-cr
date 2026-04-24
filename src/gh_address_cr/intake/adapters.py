from __future__ import annotations

import hashlib
import json
from typing import Any

from gh_address_cr.github.threads import normalize_threads
from gh_address_cr.intake.findings import FindingsFormatError, normalize_finding, parse_finding_blocks, parse_records


class AdapterError(ValueError):
    pass


def _item_id(source: str, finding: dict[str, Any]) -> str:
    raw = json.dumps(
        {
            "source": source,
            "title": finding.get("title"),
            "path": finding.get("path"),
            "line": finding.get("line"),
            "body": finding.get("body"),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"local-finding:{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]}"


def _with_local_item_fields(source: str, finding: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(finding)
    normalized["item_id"] = _item_id(source, normalized)
    normalized["item_kind"] = "local_finding"
    normalized["source"] = source
    return normalized


def normalize_adapter_payload(source: str, raw: str) -> list[dict[str, Any]]:
    if source in {"review-to-findings", "finding-blocks"}:
        findings = parse_finding_blocks(raw)
    elif source in {"json", "code-review", "adapter"}:
        findings = [normalize_finding(record) for record in parse_records(raw)]
    elif source in {"github", "github-threads"}:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise AdapterError(f"Invalid GitHub thread JSON: {exc}") from exc
        return normalize_threads(payload)
    else:
        raise AdapterError(f"Unsupported findings adapter source: {source}")
    return [_with_local_item_fields(source, finding) for finding in findings]


def normalize_github_thread_fixture(payload: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        return normalize_threads(payload["input"])
    except (KeyError, TypeError, ValueError, FindingsFormatError) as exc:
        raise AdapterError(f"Invalid GitHub thread fixture: {exc}") from exc
