from __future__ import annotations

from typing import Any, Callable

from gh_address_cr.agent.manifests import ManifestValidationError, ensure_manifest_eligible
from gh_address_cr.agent.roles import AgentRole, GITHUB_SIDE_EFFECT_FORBIDDEN_ACTIONS, is_ai_agent_role, parse_role
from gh_address_cr.core.models import ActionRequest, CapabilityManifest, EvidenceRecord, WorkItem


class RequestValidationError(ValueError):
    def __init__(self, code: str, message: str, *, evidence: EvidenceRecord | None = None):
        super().__init__(message)
        self.code = code
        self.evidence = evidence


EvidenceSink = Callable[[EvidenceRecord], EvidenceRecord]


REQUIRED_ACTION_REQUEST_FIELDS = (
    "request_id",
    "session_id",
    "lease_id",
    "agent_role",
    "item",
    "allowed_actions",
    "required_evidence",
)


def _classification_is_recorded(item: WorkItem) -> bool:
    evidence = item.classification_evidence
    return bool(evidence and evidence.get("event_type") == "classification_recorded")


def _append_request_rejected(
    *,
    session_id: str,
    item: WorkItem,
    lease_id: str | None,
    agent_id: str | None,
    role: AgentRole | str | None,
    reason_code: str,
    evidence_sink: EvidenceSink | None,
) -> EvidenceRecord:
    evidence = EvidenceRecord.create(
        session_id=session_id,
        item_id=item.item_id,
        lease_id=lease_id,
        agent_id=agent_id,
        role=role,
        event_type="request_rejected",
        payload={"reason_code": reason_code},
    )
    if evidence_sink is not None:
        evidence_sink(evidence)
    return evidence


def reject_request_without_classification(
    *,
    session_id: str,
    item: WorkItem,
    lease_id: str | None,
    agent_id: str | None,
    evidence_sink: EvidenceSink | None = None,
) -> EvidenceRecord:
    return _append_request_rejected(
        session_id=session_id,
        item=item,
        lease_id=lease_id,
        agent_id=agent_id,
        role=AgentRole.FIXER,
        reason_code="missing_classification_evidence",
        evidence_sink=evidence_sink,
    )


def validate_action_request(payload: ActionRequest | dict[str, Any]) -> ActionRequest:
    if isinstance(payload, ActionRequest):
        payload = payload.to_dict()
    if not isinstance(payload, dict):
        raise RequestValidationError("invalid_action_request", "ActionRequest must be a JSON object.")
    for field in REQUIRED_ACTION_REQUEST_FIELDS:
        if field not in payload:
            raise RequestValidationError(f"missing_{field}", f"ActionRequest missing {field}.")
    item_payload = payload["item"]
    if not isinstance(item_payload, dict):
        raise RequestValidationError("invalid_item", "ActionRequest item must be a JSON object.")
    if not item_payload.get("item_id"):
        raise RequestValidationError("missing_item_id", "ActionRequest item missing item_id.")
    try:
        role = parse_role(payload["agent_role"])
    except ValueError as exc:
        raise RequestValidationError("unsupported_agent_role", str(exc)) from exc
    if not payload["allowed_actions"]:
        raise RequestValidationError("empty_allowed_actions", "ActionRequest allowed_actions must not be empty.")
    if not payload["required_evidence"]:
        raise RequestValidationError("empty_required_evidence", "ActionRequest required_evidence must not be empty.")
    if "fix" in payload["allowed_actions"] and not payload.get("lease_id"):
        raise RequestValidationError("missing_lease_id", "Mutating ActionRequest must include a lease_id.")
    if is_ai_agent_role(role):
        forbidden = set(payload.get("forbidden_actions") or ())
        missing_forbidden = set(GITHUB_SIDE_EFFECT_FORBIDDEN_ACTIONS) - forbidden
        if missing_forbidden:
            raise RequestValidationError(
                "missing_forbidden_github_actions",
                "AI-agent requests must forbid direct GitHub reply and resolve operations.",
            )
    resume_command = payload.get("resume_command") or ""
    if "gh-address-cr/scripts/cli.py" in resume_command:
        raise RequestValidationError(
            "skill_shim_resume_command",
            "ActionRequest resume_command must target the runtime CLI, not the skill-local shim.",
        )
    try:
        return ActionRequest.from_dict(payload)
    except (KeyError, TypeError, ValueError) as exc:
        raise RequestValidationError("malformed_action_request", str(exc)) from exc


def build_action_request(
    *,
    request_id: str,
    session_id: str,
    lease_id: str,
    agent_role: AgentRole | str,
    item: WorkItem | dict[str, Any],
    allowed_actions: list[str] | tuple[str, ...],
    required_evidence: list[str] | tuple[str, ...],
    repository_context: dict[str, Any],
    resume_command: str,
    manifest: CapabilityManifest | dict[str, Any],
    active_claims_for_agent: int = 0,
    evidence_sink: EvidenceSink | None = None,
) -> ActionRequest:
    item = item if isinstance(item, WorkItem) else WorkItem.from_dict(item)
    role = parse_role(agent_role)
    for action in allowed_actions:
        try:
            ensure_manifest_eligible(
                manifest,
                role,
                action,
                "action_request.v1",
                "1.0",
                active_claims_for_agent,
            )
        except ManifestValidationError as exc:
            raise RequestValidationError(exc.code, str(exc)) from exc
    if role == AgentRole.FIXER and "fix" in allowed_actions and not _classification_is_recorded(item):
        evidence = reject_request_without_classification(
            session_id=session_id,
            item=item,
            lease_id=lease_id,
            agent_id=None,
            evidence_sink=evidence_sink,
        )
        raise RequestValidationError("missing_classification_evidence", "Fixer requests require classification evidence.", evidence=evidence)
    forbidden_actions = list(GITHUB_SIDE_EFFECT_FORBIDDEN_ACTIONS) if is_ai_agent_role(role) else []
    request = ActionRequest(
        schema_version="1.0",
        request_id=request_id,
        session_id=session_id,
        lease_id=lease_id,
        agent_role=role,
        item=item,
        allowed_actions=tuple(allowed_actions),
        required_evidence=tuple(required_evidence),
        repository_context=dict(repository_context),
        resume_command=resume_command,
        forbidden_actions=tuple(forbidden_actions),
    )
    return validate_action_request(request)
