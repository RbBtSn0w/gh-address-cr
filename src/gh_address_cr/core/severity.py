from __future__ import annotations

import re
from typing import Any


VALID_SEVERITIES = {"P1", "P2", "P3"}

_EXPLICIT_P_SCALE_PATTERNS = (
    re.compile(r"(?i)\b(?:severity|priority)\s*[:=\-]?\s*`?\[?(P[123])\]?`?\b"),
    re.compile(r"(?i)(?<![A-Z0-9])\[?(P[123])\]?(?:\s+badge)?(?![A-Z0-9])"),
)
_REVIEW_PRIORITY_RE = re.compile(r"(?i)\b(high|medium|low)(?:[-_\s]+priority)?\b")


def normalize_severity(value: Any) -> str | None:
    normalized = str(value or "").strip().upper()
    return normalized if normalized in VALID_SEVERITIES else None


def severity_evidence(
    value: Any,
    *,
    source: str,
    raw_marker: str | None = None,
    observed_from: str | None = None,
) -> dict[str, str] | None:
    normalized = normalize_severity(value)
    if not normalized:
        return None
    evidence = {
        "value": normalized,
        "source": source,
        "raw_marker": str(raw_marker or normalized).strip() or normalized,
    }
    if observed_from:
        evidence["observed_from"] = observed_from
    return evidence


def extract_severity_evidence(
    text: Any,
    *,
    source: str,
    observed_from: str | None = None,
) -> dict[str, str] | None:
    body = str(text or "")
    if not body.strip():
        return None
    for pattern in _EXPLICIT_P_SCALE_PATTERNS:
        match = pattern.search(body)
        if not match:
            continue
        marker = match.group(1).upper()
        return severity_evidence(marker, source=source, raw_marker=marker, observed_from=observed_from)
    return None


def extract_review_priority_evidence(
    text: Any,
    *,
    source: str,
    observed_from: str | None = None,
) -> dict[str, str] | None:
    body = str(text or "")
    if not body.strip():
        return None
    match = _REVIEW_PRIORITY_RE.search(body)
    if not match:
        return None
    priority = match.group(1).lower()
    evidence = {
        "value": priority,
        "source": source,
        "raw_marker": priority,
    }
    if observed_from:
        evidence["observed_from"] = observed_from
    return evidence


def apply_severity_evidence(item: dict[str, Any], evidence: dict[str, str] | None) -> None:
    if not evidence:
        item.pop("severity", None)
        item.pop("severity_evidence", None)
        return
    item["severity"] = evidence["value"]
    item["severity_evidence"] = dict(evidence)


def first_scene_item_severity(item: dict[str, Any]) -> str | None:
    evidence = item.get("severity_evidence")
    if not isinstance(evidence, dict):
        return None
    return normalize_severity(evidence.get("value"))

