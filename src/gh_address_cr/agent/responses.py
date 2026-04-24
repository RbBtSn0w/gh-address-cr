from __future__ import annotations

from typing import Any, Callable

from gh_address_cr.agent.roles import MUTATING_RESOLUTIONS, TERMINAL_RESOLUTIONS
from gh_address_cr.core.models import ActionRequest, ActionResponse, ClaimLease, EvidenceRecord, WorkItem


class ResponseValidationError(ValueError):
    def __init__(self, code: str, message: str, *, evidence: EvidenceRecord | None = None):
        super().__init__(message)
        self.code = code
        self.evidence = evidence


EvidenceSink = Callable[[EvidenceRecord], EvidenceRecord]


REQUIRED_ACTION_RESPONSE_FIELDS = (
    "request_id",
    "lease_id",
    "agent_id",
    "resolution",
    "note",
)

DIRECT_GITHUB_SIDE_EFFECT_KEYS = frozenset(
    {
        "github_side_effects",
        "posted_github_reply",
        "resolved_github_thread",
        "reply_url",
        "thread_resolved",
    }
)


def _classification_is_recorded(item: WorkItem) -> bool:
    evidence = item.classification_evidence
    return bool(evidence and evidence.get("event_type") == "classification_recorded")


def _append_response_rejected(
    *,
    request: ActionRequest,
    response: ActionResponse | None,
    item: WorkItem,
    lease: ClaimLease | None,
    reason_code: str,
    evidence_sink: EvidenceSink | None,
) -> EvidenceRecord:
    evidence = EvidenceRecord.create(
        session_id=request.session_id,
        item_id=item.item_id,
        lease_id=lease.lease_id if lease is not None else request.lease_id,
        agent_id=response.agent_id if response is not None else None,
        role=lease.role if lease is not None else request.agent_role,
        event_type="response_rejected",
        payload={"reason_code": reason_code, "request_id": request.request_id},
    )
    if evidence_sink is not None:
        evidence_sink(evidence)
    return evidence


def _require_non_empty(payload: dict[str, Any], field: str, code: str | None = None) -> None:
    if field not in payload or not payload[field]:
        raise ResponseValidationError(code or f"missing_{field}", f"ActionResponse missing {field}.")


def _validate_validation_commands(commands: Any) -> None:
    if not isinstance(commands, list) or not commands:
        raise ResponseValidationError("missing_validation_commands", "ActionResponse requires validation_commands.")
    for record in commands:
        if not isinstance(record, dict):
            raise ResponseValidationError("invalid_validation_command", "Validation command records must be objects.")
        if not record.get("command") or not record.get("result"):
            raise ResponseValidationError(
                "invalid_validation_command",
                "Validation command records require command and result.",
            )


def validate_action_response(payload: ActionResponse | dict[str, Any], *, item_kind: str | None = None) -> ActionResponse:
    if isinstance(payload, ActionResponse):
        payload = payload.to_dict()
    if not isinstance(payload, dict):
        raise ResponseValidationError("invalid_action_response", "ActionResponse must be a JSON object.")
    side_effect_keys = DIRECT_GITHUB_SIDE_EFFECT_KEYS.intersection(payload.keys())
    if side_effect_keys:
        raise ResponseValidationError(
            "direct_github_side_effect_claimed",
            "Agents must not claim direct GitHub side effects.",
        )
    for field in REQUIRED_ACTION_RESPONSE_FIELDS:
        if field not in payload or payload[field] in (None, "", []):
            raise ResponseValidationError(f"missing_{field}", f"ActionResponse missing {field}.")
    resolution = str(payload["resolution"])
    if resolution not in TERMINAL_RESOLUTIONS:
        raise ResponseValidationError("unsupported_resolution", f"Unsupported resolution: {resolution}.")
    _validate_validation_commands(payload.get("validation_commands"))
    if resolution == "fix":
        _require_non_empty(payload, "files")
        if item_kind == "github_thread":
            _require_non_empty(payload, "fix_reply")
        fix_reply = payload.get("fix_reply")
        if fix_reply is not None:
            if not isinstance(fix_reply, dict):
                raise ResponseValidationError("invalid_fix_reply", "fix_reply must be an object.")
            if not fix_reply.get("summary"):
                raise ResponseValidationError("missing_fix_reply_summary", "fix_reply requires summary.")
    else:
        code = f"missing_{resolution}_reply_markdown"
        _require_non_empty(payload, "reply_markdown", code)
    try:
        return ActionResponse.from_dict(payload)
    except (KeyError, TypeError, ValueError) as exc:
        raise ResponseValidationError("malformed_action_response", str(exc)) from exc


def _validate_required_evidence(request: ActionRequest, response: ActionResponse) -> None:
    evidence_map = {
        "note": bool(response.note),
        "files": bool(response.files),
        "validation_commands": bool(response.validation_commands),
        "reply_markdown": bool(response.reply_markdown),
        "fix_reply": bool(response.fix_reply),
    }
    for field in request.required_evidence:
        if not evidence_map.get(field, False):
            raise ResponseValidationError(f"missing_{field}", f"ActionResponse missing required evidence {field}.")


def validate_response_for_request(
    payload: ActionResponse | dict[str, Any],
    *,
    request: ActionRequest,
    item: WorkItem,
    lease: ClaimLease | None,
    evidence_sink: EvidenceSink | None = None,
) -> ActionResponse:
    try:
        response = validate_action_response(payload, item_kind=item.item_kind)
    except ResponseValidationError as exc:
        if exc.code == "direct_github_side_effect_claimed":
            _append_response_rejected(
                request=request,
                response=None,
                item=item,
                lease=lease,
                reason_code=exc.code,
                evidence_sink=evidence_sink,
            )
        raise
    if lease is None:
        raise ResponseValidationError("missing_lease", "ActionResponse requires an active lease.")
    if lease.status != "active":
        raise ResponseValidationError("inactive_lease", "ActionResponse lease is not active.")
    if response.lease_id != lease.lease_id or response.lease_id != request.lease_id:
        raise ResponseValidationError("lease_id_mismatch", "ActionResponse lease_id does not match the active lease.")
    if lease.item_id != item.item_id or request.item.item_id != item.item_id:
        raise ResponseValidationError("item_id_mismatch", "ActionResponse lease item does not match the request item.")
    if lease.agent_id != response.agent_id:
        raise ResponseValidationError("agent_id_mismatch", "ActionResponse agent_id does not match the active lease.")
    if lease.role != request.agent_role:
        raise ResponseValidationError("role_mismatch", "ActionResponse lease role does not match the request role.")
    if lease.request_hash is not None and lease.request_hash != request.stable_hash():
        raise ResponseValidationError("request_hash_mismatch", "ActionResponse does not match issued request context.")
    if response.resolution in MUTATING_RESOLUTIONS and response.files and not _classification_is_recorded(item):
        evidence = _append_response_rejected(
            request=request,
            response=response,
            item=item,
            lease=lease,
            reason_code="missing_classification_evidence",
            evidence_sink=evidence_sink,
        )
        raise ResponseValidationError(
            "missing_classification_evidence",
            "Code-modifying responses require prior classification evidence.",
            evidence=evidence,
        )
    _validate_required_evidence(request, response)
    return response
