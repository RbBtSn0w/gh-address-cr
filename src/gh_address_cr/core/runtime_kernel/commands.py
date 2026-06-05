"""Side-effect command planning for runtime-kernel decisions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from gh_address_cr.core.runtime_kernel.identity import (
    planned_command_digest,
    planned_command_id,
    planned_command_payload,
)
from gh_address_cr.core.runtime_kernel.policies import PolicyDecision
from gh_address_cr.core.runtime_kernel.projections import ReviewProjection, ReviewWorkItem


JsonDict = dict[str, Any]


@dataclass(frozen=True)
class PlannedCommand:
    command_id: str
    command_kind: str
    idempotency_key: str
    reason_code: str
    item_id: str | None = None
    payload: JsonDict = field(default_factory=dict)

    def to_dict(self) -> JsonDict:
        body: JsonDict = {
            "command_id": self.command_id,
            "command_kind": self.command_kind,
            "idempotency_key": self.idempotency_key,
            "reason_code": self.reason_code,
            "payload": dict(self.payload),
        }
        if self.item_id is not None:
            body["item_id"] = self.item_id
        return body


def _planned_command(
    command_kind: str,
    reason_code: str,
    *,
    item: ReviewWorkItem | None = None,
    payload_override: JsonDict | None = None,
) -> PlannedCommand:
    payload: JsonDict = {}
    item_id = None
    if item is not None:
        item_id = item.item_id
        payload = planned_command_payload(
            item_id=item.item_id,
            thread_id=item.thread_id,
            source_fact_id=item.source_fact_id,
            source_observed_at=item.source_observed_at,
        )
    if payload_override is not None:
        payload = {**payload, **payload_override}
    digest = planned_command_digest(
        command_kind=command_kind,
        reason_code=reason_code,
        item_id=item_id,
        payload=payload,
    )
    return PlannedCommand(
        command_id=planned_command_id(
            command_kind=command_kind,
            reason_code=reason_code,
            item_id=item_id,
            payload=payload,
        ),
        command_kind=command_kind,
        item_id=item_id,
        idempotency_key=digest,
        reason_code=reason_code,
        payload=payload,
    )


def plan_review_commands(projection: ReviewProjection, decision: PolicyDecision) -> tuple[PlannedCommand, ...]:
    if decision.status == "final_gate_eligible":
        return (_planned_command("run_final_gate", "FINAL_GATE_ELIGIBLE"),)

    if decision.status != "ready_for_action":
        return ()

    items_by_id = {item.item_id: item for item in projection.work_items}
    planned: list[PlannedCommand] = []
    for item_id in decision.item_ids:
        item = items_by_id.get(item_id)
        if item is None:
            continue
        failed_command_kinds = {str(record.get("command_kind")) for record in item.failed_commands}
        for failed in item.failed_commands:
            planned.append(
                _planned_command(
                    "retry_command",
                    "SIDE_EFFECT_RETRY_REQUIRED",
                    item=item,
                    payload_override={
                        "failed_command_id": failed.get("command_id"),
                        "retry_command_kind": failed.get("command_kind"),
                    },
                )
            )
        for command_kind in item.required_commands:
            if command_kind in failed_command_kinds:
                continue
            planned.append(_planned_command(command_kind, "REVIEW_THREAD_ACTION_REQUIRED", item=item))

    return tuple(sorted(planned, key=lambda command: (command.item_id or "", command.command_kind, command.command_id)))
