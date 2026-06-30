from __future__ import annotations

from typing import Any, Mapping, Sequence

from gh_address_cr.core.evaluation.models import stable_fingerprint


def project_concern(run_id: str, item: Mapping[str, Any], observations: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    required = {
        "CLASSIFICATION_EVIDENCE_MISSING": bool(item.get("classification_verified") or item.get("classification_evidence")),
        "REPLY_EVIDENCE_MISSING": bool(item.get("reply_evidence")),
        "RESOLVE_EVIDENCE_MISSING": bool(item.get("resolve_evidence")) or not bool(item.get("resolve_required", True)),
        "PUBLISH_EVIDENCE_MISSING": bool(item.get("publish_evidence")) or not bool(item.get("publish_required", True)),
        "FINAL_GATE_NOT_PASSED": bool(item.get("final_gate_passed")),
    }
    deficits = [code for code, present in required.items() if not present]
    provisional = "verified" if not deficits else "not_verified"
    linked = [row for row in observations if row.get("item_id") == item.get("item_id") or row.get("related_item_id") == item.get("item_id")]
    negative_codes = {
        "reopened": "DURABLE_REOPENED",
        "equivalent_recurrence": "DURABLE_EQUIVALENT_RECURRENCE",
        "manual_recovery": "DURABLE_MANUAL_RECOVERY",
        "final_gate_regression": "DURABLE_FINAL_GATE_REGRESSION",
    }
    negative = next((row for row in linked if row.get("outcome_kind") in negative_codes), None)
    positive = next((row for row in linked if row.get("outcome_kind") == "no_reopen"), None)
    current_cycle_evidence = []
    for event_type, value in (
        ("classification", item.get("classification_evidence")),
        ("reply", item.get("reply_evidence")),
        ("resolve", item.get("resolve_evidence")),
        ("publish", item.get("publish_evidence")),
    ):
        if isinstance(value, Mapping):
            current_cycle_evidence.append(
                {
                    "record_id": value.get("record_id"),
                    "event_type": event_type,
                    "source": value.get("source", "runtime"),
                    "observed_at": value.get("observed_at"),
                }
            )
    if provisional != "verified":
        durable_state, durable_reason = "unknown", "DURABLE_OBSERVATION_UNSUPPORTED"
    elif negative:
        durable_state, durable_reason = "negative", negative_codes[str(negative["outcome_kind"])]
    elif positive:
        durable_state, durable_reason = "verified", "DURABLE_VERIFIED"
    else:
        durable_state, durable_reason = "unknown", "DURABLE_OBSERVATION_MISSING"
    semantic = {
        "run_id": run_id,
        "item_id": str(item.get("item_id") or ""),
        "classification": str(item.get("classification") or (item.get("classification_evidence") or {}).get("classification") or "unknown"),
        "provisional_state": provisional,
        "provisional_deficits": deficits,
        "provisional_boundary": "current-cycle-final-gate",
        "durable_state": durable_state,
        "durable_reason": durable_reason,
        "durable_boundary": (
            None
            if not linked
            else {
                "source": linked[-1].get("source", "unknown"),
                "observed_at": linked[-1].get("observed_at"),
                "correlation_method": linked[-1].get("correlation_method"),
            }
        ),
        "observation_ids": sorted(str(row.get("observation_id") or "") for row in linked),
        "manual_recovery_count": sum(row.get("outcome_kind") == "manual_recovery" for row in linked),
        "reopen_count": sum(row.get("outcome_kind") in {"reopened", "equivalent_recurrence"} for row in linked),
        "actionable_rejection_count": int(item.get("actionable_rejection_count") or 0),
        "expected_control_flow_rejection_count": int(item.get("expected_control_flow_rejection_count") or 0),
        "first_pass": provisional == "verified" and not bool(item.get("retry_count") or item.get("manual_recovery_count")),
        "evidence": [*current_cycle_evidence, *[
            {
                "observation_id": str(row.get("observation_id") or ""),
                "source": str(row.get("source") or "unknown"),
                "observed_at": row.get("observed_at"),
                "correlation_method": row.get("correlation_method"),
            }
            for row in sorted(linked, key=lambda value: str(value.get("observation_id") or ""))
        ]],
    }
    return {"schema_version": "evaluation.v1", "evaluation_id": stable_fingerprint(semantic, prefix="evaluation_"), **semantic}
