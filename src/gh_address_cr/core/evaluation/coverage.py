from __future__ import annotations

from typing import Any, Mapping

EXPECTED_REJECTIONS = {
    "WAITING_FOR_EXTERNAL_REVIEW",
    "WAITING_FOR_USER",
    "NO_ACTIONABLE_ITEMS",
    "LEASE_HELD_BY_OTHER_WORKER",
}


def classify_rejection(reason_code: str) -> str:
    return "expected" if reason_code in EXPECTED_REJECTIONS else "actionable"


def evaluate_coverage(evidence: Mapping[str, list[Any]]) -> dict[str, dict[str, Any]]:
    deficits = {
        "workflow": "WORKFLOW_EVIDENCE_MISSING",
        "timing": "TIMING_INTERVALS_MISSING",
        "token": "TOKEN_EVIDENCE_MISSING",
        "outcome": "DURABLE_OBSERVATION_MISSING",
    }
    result: dict[str, dict[str, Any]] = {}
    for dimension, deficit in deficits.items():
        rows = list(evidence.get(dimension) or [])
        invalid = any(isinstance(row, Mapping) and row.get("valid") is False for row in rows)
        unsupported = any(isinstance(row, Mapping) and row.get("supported") is False for row in rows)
        if invalid:
            status = "invalid"
        elif unsupported:
            status = "partial"
        else:
            status = "complete" if rows else "unavailable"
        result[dimension] = {
            "status": status,
            "evidence_count": len(rows),
            "sources": sorted({str(row.get("source", "unknown")) if isinstance(row, Mapping) else "runtime" for row in rows}),
            "deficits": (
                [f"{dimension.upper()}_EVIDENCE_INVALID"]
                if invalid
                else ([f"{dimension.upper()}_EVIDENCE_PARTIAL"] if unsupported else ([] if rows else [deficit]))
            ),
        }
    return result
