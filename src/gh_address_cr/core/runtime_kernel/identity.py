"""Stable command identity helpers for runtime-kernel side effects."""

from __future__ import annotations

from typing import Any

from gh_address_cr.core.models import stable_payload_hash

JsonDict = dict[str, Any]


def planned_command_payload(
    *,
    item_id: str,
    thread_id: str,
    source_fact_id: str,
    source_observed_at: str,
    payload_override: JsonDict | None = None,
) -> JsonDict:
    payload: JsonDict = {
        "item_id": item_id,
        "thread_id": thread_id,
        "source_fact_id": source_fact_id,
        "source_observed_at": source_observed_at,
    }
    if payload_override is not None:
        payload = {**payload, **payload_override}
    return payload


def planned_command_digest(
    *,
    command_kind: str,
    reason_code: str,
    item_id: str | None,
    payload: JsonDict,
) -> str:
    return stable_payload_hash(
        {
            "command_kind": command_kind,
            "item_id": item_id,
            "payload": payload,
            "reason_code": reason_code,
        }
    )


def planned_command_id(
    *,
    command_kind: str,
    reason_code: str,
    item_id: str | None,
    payload: JsonDict,
) -> str:
    return f"{command_kind}:{planned_command_digest(command_kind=command_kind, reason_code=reason_code, item_id=item_id, payload=payload)[:16]}"
