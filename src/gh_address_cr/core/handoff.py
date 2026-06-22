"""External producer handoff metadata helpers.

The ``session["handoff"]`` block is non-event-sourced metadata for producer
deduplication and bookkeeping. It is not authoritative runtime truth, does not
participate in runtime-kernel replay, and cannot satisfy final-gate evidence.
"""

from __future__ import annotations

import hashlib
from typing import Any

from gh_address_cr.intake.findings import canonical_findings_payload


def ensure_handoff_state(session: dict[str, Any]) -> dict[str, Any]:
    handoff = session.get("handoff")
    if not isinstance(handoff, dict):
        handoff = {}
        session["handoff"] = handoff
    handoff.setdefault("last_consumed_sha256", None)
    producer_results = handoff.get("producer_results")
    if not isinstance(producer_results, dict):
        producer_results = {}
        handoff["producer_results"] = producer_results
    return handoff


def record_producer_result(
    session: dict[str, Any],
    *,
    source: str,
    findings: list[dict[str, Any]],
    sync_enabled: bool,
    submitted_at: str,
    payload_sha256: str | None = None,
) -> dict[str, Any]:
    handoff = ensure_handoff_state(session)
    producer_results = handoff["producer_results"]
    result = {
        "status": "submitted",
        "source": source,
        "findings_count": len(findings),
        "payload_sha256": payload_sha256
        or hashlib.sha256(canonical_findings_payload(findings).encode("utf-8")).hexdigest(),
        "sync_enabled": bool(sync_enabled),
        "submitted_at": submitted_at,
    }
    producer_results[source] = result
    return result
