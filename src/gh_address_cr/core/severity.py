from __future__ import annotations

import re
from typing import Any

VALID_SEVERITIES = {"P0", "P1", "P2", "P3", "P4"}

_EXPLICIT_P_SCALE_PATTERNS = (
    re.compile(r"(?i)\b(?:severity|priority)\s*[:=\-]?\s*`?\[?(P[01234])\]?`?\b"),
    re.compile(r"(?i)(?<![A-Z0-9])\[(P[01234])\](?![A-Z0-9])"),
    re.compile(r"(?i)(?<![A-Z0-9])(P[01234])\s+badge\b"),
    re.compile(r"(?i)\bbadge/(P[01234])(?:[-_/?#&.]|$)"),
)
_REVIEW_PRIORITY_PATTERNS = (
    re.compile(r"(?i)\b(high|medium|low)[-_\s]+priority\b"),
    re.compile(r"(?i)\bpriority\s*[:=\-]\s*(high|medium|low)\b"),
)


def normalize_severity(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().upper()
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
    priority = None
    for pattern in _REVIEW_PRIORITY_PATTERNS:
        match = pattern.search(body)
        if match:
            priority = match.group(1).lower()
            break
    if priority is None:
        return None
    evidence = {
        "value": priority,
        "source": source,
        "raw_marker": priority,
    }
    if observed_from:
        evidence["observed_from"] = observed_from
    return evidence


def review_priority_evidence(
    value: Any,
    *,
    source: str,
    raw_marker: str | None = None,
    observed_from: str | None = None,
) -> dict[str, str] | None:
    priority = str(value or "").strip().lower()
    if priority not in {"high", "medium", "low"}:
        return None
    evidence = {
        "value": priority,
        "source": source,
        "raw_marker": str(raw_marker or priority).strip() or priority,
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


def review_priority_for_publish(item: dict[str, Any] | None) -> tuple[str | None, str | None]:
    if not isinstance(item, dict):
        return None, None
    evidence = item.get("review_priority_evidence")
    if not isinstance(evidence, dict):
        return None, None
    priority = str(evidence.get("value") or "").strip().lower()
    if priority not in {"high", "medium", "low"}:
        return None, None
    source = str(evidence.get("source") or "").strip()
    if source:
        return priority, f"Reviewer-provided priority from {source} was preserved as raw priority evidence."
    return priority, "Reviewer-provided priority was preserved as raw priority evidence."
