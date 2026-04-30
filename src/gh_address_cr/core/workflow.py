from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from gh_address_cr import __version__, PROTOCOL_VERSION, SUPPORTED_PROTOCOL_VERSIONS, SUPPORTED_SKILL_CONTRACT_VERSIONS
from gh_address_cr.core import session as session_store
from gh_address_cr.core.leases import (
    LeaseConflictError,
    LeaseSubmissionError,
    accept_lease,
    claim_lease,
    expire_leases,
    release_lease,
    submit_lease,
)
from gh_address_cr.core.models import ActionRequest
from gh_address_cr.core.reply_templates import fix_reply as render_fix_reply
from gh_address_cr.evidence.ledger import EvidenceLedger, SideEffectAttempt
from gh_address_cr.github.client import GitHubClient
from gh_address_cr.github.errors import GitHubError


MUTATING_ROLES = {"fixer"}
TERMINAL_RESOLUTIONS = {"fix", "clarify", "defer", "reject"}


class WorkflowError(RuntimeError):
    def __init__(
        self,
        *,
        status: str,
        reason_code: str,
        exit_code: int,
        message: str,
        waiting_on: str | None = None,
        payload: dict[str, Any] | None = None,
    ):
        self.status = status
        self.reason_code = reason_code
        self.exit_code = exit_code
        self.waiting_on = waiting_on
        self.payload = payload or {}
        super().__init__(message)

    def to_summary(self, *, repo: str, pr_number: str) -> dict[str, Any]:
        return {
            "status": self.status,
            "repo": repo,
            "pr_number": pr_number,
            "reason_code": self.reason_code,
            "waiting_on": self.waiting_on,
            "next_action": str(self),
            "exit_code": self.exit_code,
            **self.payload,
        }


def runtime_compatibility() -> dict[str, Any]:
    return {
        "status": "compatible",
        "runtime_package": "gh-address-cr",
        "runtime_version": __version__,
        "required_protocol_version": PROTOCOL_VERSION,
        "supported_protocol_versions": list(SUPPORTED_PROTOCOL_VERSIONS),
        "supported_skill_contract_versions": list(SUPPORTED_SKILL_CONTRACT_VERSIONS),
        "entrypoints": ["gh-address-cr", "python3 -m gh_address_cr"],
        "remediation": None,
    }


def record_classification(
    repo: str,
    pr_number: str,
    *,
    item_id: str,
    classification: str,
    agent_id: str,
    note: str,
) -> dict[str, Any]:
    normalized = classification.strip().lower()
    if normalized not in TERMINAL_RESOLUTIONS:
        raise WorkflowError(
            status="CLASSIFICATION_REJECTED",
            reason_code="UNSUPPORTED_CLASSIFICATION",
            waiting_on="classification",
            exit_code=5,
            message=f"Unsupported classification: {classification}",
            payload={"item_id": item_id},
        )
    if not note.strip():
        raise WorkflowError(
            status="CLASSIFICATION_REJECTED",
            reason_code="MISSING_CLASSIFICATION_NOTE",
            waiting_on="classification",
            exit_code=5,
            message="Classification evidence requires a note.",
            payload={"item_id": item_id},
        )

    session = session_store.load_session(repo, pr_number)
    item = _items(session).get(item_id)
    if not isinstance(item, dict):
        raise WorkflowError(
            status="CLASSIFICATION_REJECTED",
            reason_code="ITEM_NOT_FOUND",
            waiting_on="work_item",
            exit_code=5,
            message=f"Work item not found: {item_id}",
            payload={"item_id": item_id},
        )

    ledger = _ledger(session)
    record = ledger.append_event(
        session_id=str(session["session_id"]),
        item_id=item_id,
        lease_id=None,
        agent_id=agent_id,
        role="triage",
        event_type="classification_recorded",
        payload={"classification": normalized, "note": note},
    )
    item["classification_evidence"] = {
        "event_type": "classification_recorded",
        "classification": normalized,
        "note": note,
        "record_id": record.record_id,
    }
    item["decision"] = normalized
    item["updated_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    released_lease_id = _release_active_triage_lease(session, item_id, agent_id=agent_id)
    if released_lease_id:
        item["state"] = "open"
        item["status"] = "OPEN"
        item["blocking"] = True
        item["claimed_by"] = None
        item["claimed_at"] = None
        item["lease_expires_at"] = None
        item.pop("active_lease_id", None)
    session_store.save_session(repo, pr_number, session)
    return {
        "status": "CLASSIFICATION_RECORDED",
        "repo": repo,
        "pr_number": str(pr_number),
        "item_id": item_id,
        "classification": normalized,
        "evidence_record_id": record.record_id,
        "released_lease_id": released_lease_id,
    }


def issue_action_request(
    repo: str,
    pr_number: str,
    *,
    role: str,
    agent_id: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    current_time = _coerce_now(now)
    session = session_store.load_session(repo, pr_number)
    ledger = _ledger(session)
    expired = expire_leases(session, now=current_time)
    _return_expired_items_to_open(session, expired)

    item_id, item = _next_item(session, role)
    if item is None:
        session_store.save_session(repo, pr_number, session)
        raise WorkflowError(
            status="NO_ELIGIBLE_ITEM",
            reason_code="NO_ELIGIBLE_ITEM",
            waiting_on="work_item",
            exit_code=4,
            message=f"No eligible work item exists for role `{role}`.",
        )

    if role in MUTATING_ROLES and not _has_classification_evidence(item):
        ledger.append_event(
            session_id=str(session["session_id"]),
            item_id=item_id,
            lease_id=None,
            agent_id=agent_id,
            role=role,
            event_type="request_rejected",
            payload={"reason_code": "MISSING_CLASSIFICATION"},
        )
        session_store.save_session(repo, pr_number, session)
        raise WorkflowError(
            status="REQUEST_REJECTED",
            reason_code="MISSING_CLASSIFICATION",
            waiting_on="classification",
            exit_code=5,
            message="Record classification evidence before issuing a mutating fixer request.",
            payload={"item_id": item_id},
        )

    lease_id = f"lease_{uuid4().hex}"
    request_id = _stable_id(
        "req",
        {
            "session_id": session["session_id"],
            "item_id": item_id,
            "role": role,
            "agent_id": agent_id,
            "lease_id": lease_id,
        },
    )
    request_item = dict(item)
    request_item["state"] = "claimed"
    request = {
        "schema_version": PROTOCOL_VERSION,
        "request_id": request_id,
        "session_id": session["session_id"],
        "lease_id": lease_id,
        "agent_role": role,
        "item": request_item,
        "allowed_actions": sorted(item.get("allowed_actions") or TERMINAL_RESOLUTIONS),
        "required_evidence": _required_evidence_for(item, role),
        "repository_context": {"repo": repo, "pr_number": str(pr_number)},
        "forbidden_actions": ["post_github_reply", "resolve_github_thread"],
        "resume_command": f"gh-address-cr agent submit {repo} {pr_number} --input response.json",
    }
    request_hash = ActionRequest.from_dict(request).stable_hash()
    request_path = session_store.workspace_dir(repo, pr_number) / f"action-request-{request_id}.json"
    try:
        lease = claim_lease(
            session,
            item,
            agent_id=agent_id,
            role=role,
            request_hash=request_hash,
            lease_id=lease_id,
            now=current_time,
            request_id=request_id,
            request_path=str(request_path),
            resume_token=f"resume:{request_id}",
        )
    except LeaseConflictError as exc:
        session_store.save_session(repo, pr_number, session)
        raise WorkflowError(
            status="LEASE_REJECTED",
            reason_code=exc.reason_code,
            waiting_on="lease",
            exit_code=5,
            message=str(exc),
            payload={"item_id": item_id},
        ) from exc

    item["state"] = "claimed"
    item["active_lease_id"] = lease_id
    request_path.write_text(json.dumps(request, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    ledger.append_event(
        session_id=str(session["session_id"]),
        item_id=item_id,
        lease_id=lease_id,
        agent_id=agent_id,
        role=role,
        event_type="request_issued",
        payload={"request_id": request_id, "request_path": str(request_path)},
    )
    session_store.save_session(repo, pr_number, session)
    return {
        "status": "ACTION_REQUESTED",
        "repo": repo,
        "pr_number": str(pr_number),
        "request_path": str(request_path),
        "lease_id": lease_id,
        "resume_token": _get(lease, "resume_token"),
        "item_id": item_id,
        "next_action": f"Pass request_path to an agent with the {role} role.",
    }


def submit_action_response(
    repo: str, pr_number: str, *, response_path: str | Path, now: datetime | None = None
) -> dict[str, Any]:
    now = _coerce_now(now)
    session = session_store.load_session(repo, pr_number)
    ledger = _ledger(session)
    response = _load_response_json_object(
        response_path,
        status="ACTION_REJECTED",
        missing_reason_code="RESPONSE_FILE_NOT_FOUND",
        invalid_reason_code="INVALID_RESPONSE_JSON",
        shape_reason_code="INVALID_RESPONSE_SHAPE",
        shape_message="ActionResponse must be a JSON object.",
        payload_name="ActionResponse",
    )

    try:
        prepared = _prepare_action_response_submission(session, ledger, response)
        record = _accept_action_response_submission(session, ledger, response, prepared, now=now)
    except WorkflowError:
        session_store.save_session(repo, pr_number, session)
        raise
    session_store.save_session(repo, pr_number, session)
    return {
        "status": "ACTION_ACCEPTED",
        "repo": repo,
        "pr_number": str(pr_number),
        "lease_id": prepared["lease_id"],
        "item_id": prepared["item_id"],
        "evidence_record_id": record.record_id,
        "next_action": f"Run `gh-address-cr agent publish {repo} {pr_number}` to publish accepted evidence.",
    }


def submit_batch_action_response(
    repo: str, pr_number: str, *, batch_path: str | Path, now: datetime | None = None
) -> dict[str, Any]:
    now = _coerce_now(now)
    session = session_store.load_session(repo, pr_number)
    ledger = _ledger(session)
    batch = _load_response_json_object(
        batch_path,
        status="BATCH_ACTION_REJECTED",
        missing_reason_code="BATCH_RESPONSE_FILE_NOT_FOUND",
        invalid_reason_code="INVALID_BATCH_RESPONSE_JSON",
        shape_reason_code="INVALID_BATCH_RESPONSE_SHAPE",
        shape_message="BatchActionResponse must be a JSON object.",
        payload_name="BatchActionResponse",
    )
    responses = _batch_action_responses(batch)
    prepared_rows: list[tuple[dict[str, Any], dict[str, Any]]] = []
    seen_leases: set[str] = set()
    seen_items: set[str] = set()

    try:
        for response in responses:
            lease_id = str(response.get("lease_id") or "")
            if lease_id in seen_leases:
                _raise_response_rejected(
                    session,
                    ledger,
                    response,
                    "BATCH_DUPLICATE_LEASE",
                    status="BATCH_ACTION_REJECTED",
                )
            seen_leases.add(lease_id)

            prepared = _prepare_action_response_submission(
                session,
                ledger,
                response,
                rejected_status="BATCH_ACTION_REJECTED",
            )
            item_id = str(prepared["item_id"])
            if item_id in seen_items:
                _raise_response_rejected(
                    session,
                    ledger,
                    response,
                    "BATCH_DUPLICATE_ITEM",
                    status="BATCH_ACTION_REJECTED",
                    item_id=item_id,
                    lease_id=lease_id,
                )
            seen_items.add(item_id)

            item = prepared["item"]
            lease = prepared["lease"]
            if item.get("item_kind") != "github_thread":
                _raise_response_rejected(
                    session,
                    ledger,
                    response,
                    "BATCH_UNSUPPORTED_ITEM_KIND",
                    status="BATCH_ACTION_REJECTED",
                    item_id=item_id,
                    lease_id=lease_id,
                )
            if str(lease.get("role")) != "fixer":
                _raise_response_rejected(
                    session,
                    ledger,
                    response,
                    "BATCH_UNSUPPORTED_ROLE",
                    status="BATCH_ACTION_REJECTED",
                    item_id=item_id,
                    lease_id=lease_id,
                )
            if str(response.get("resolution")) != "fix":
                _raise_response_rejected(
                    session,
                    ledger,
                    response,
                    "BATCH_UNSUPPORTED_RESOLUTION",
                    status="BATCH_ACTION_REJECTED",
                    item_id=item_id,
                    lease_id=lease_id,
                )
            _validate_batch_fix_contract(session, ledger, response, item_id=item_id, lease_id=lease_id)
            lease_reason_code = _lease_submission_rejection_reason(response, prepared, now)
            if lease_reason_code:
                _raise_response_rejected(
                    session,
                    ledger,
                    response,
                    lease_reason_code,
                    status="BATCH_ACTION_REJECTED",
                    item_id=item_id,
                    lease_id=lease_id,
                )
            prepared_rows.append((response, prepared))

        accepted = [
            _batch_acceptance_payload(
                response,
                prepared,
                _accept_action_response_submission(
                    session,
                    ledger,
                    response,
                    prepared,
                    now=now,
                    rejected_status="BATCH_ACTION_REJECTED",
                ),
            )
            for response, prepared in prepared_rows
        ]
    except WorkflowError:
        session_store.save_session(repo, pr_number, session)
        raise

    session_store.save_session(repo, pr_number, session)
    return {
        "status": "BATCH_ACTION_ACCEPTED",
        "repo": repo,
        "pr_number": str(pr_number),
        "accepted_count": len(accepted),
        "accepted": accepted,
        "item_ids": [row["item_id"] for row in accepted],
        "next_action": f"Run `gh-address-cr agent publish {repo} {pr_number}` to publish accepted evidence.",
    }


def _load_response_json_object(
    response_path: str | Path,
    *,
    status: str,
    missing_reason_code: str,
    invalid_reason_code: str,
    shape_reason_code: str,
    shape_message: str,
    payload_name: str,
) -> dict[str, Any]:
    path = Path(response_path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise WorkflowError(
            status=status,
            reason_code=missing_reason_code,
            waiting_on="action_response",
            exit_code=2,
            message=f"{payload_name} file does not exist: {path}",
        ) from exc
    except json.JSONDecodeError as exc:
        raise WorkflowError(
            status=status,
            reason_code=invalid_reason_code,
            waiting_on="action_response",
            exit_code=2,
            message=f"Invalid {payload_name} JSON: {exc}",
        ) from exc

    if not isinstance(payload, dict):
        raise WorkflowError(
            status=status,
            reason_code=shape_reason_code,
            waiting_on="action_response",
            exit_code=2,
            message=shape_message,
        )
    return payload


def _batch_action_responses(batch: dict[str, Any]) -> list[dict[str, Any]]:
    common = batch.get("common") or {}
    if not isinstance(common, dict):
        _raise_batch_schema_error("INVALID_BATCH_COMMON", "BatchActionResponse.common must be a JSON object.")

    items = batch.get("items")
    if not isinstance(items, list) or not items:
        _raise_batch_schema_error("BATCH_ITEMS_REQUIRED", "BatchActionResponse requires a non-empty items list.")

    agent_id = str(batch.get("agent_id") or common.get("agent_id") or "").strip()
    if not agent_id:
        _raise_batch_schema_error("MISSING_BATCH_AGENT_ID", "BatchActionResponse requires agent_id.")

    resolution = str(batch.get("resolution") or common.get("resolution") or "fix").strip().lower()
    if resolution != "fix":
        _raise_batch_schema_error("BATCH_UNSUPPORTED_RESOLUTION", "BatchActionResponse only supports fix evidence.")

    schema_version = str(batch.get("schema_version") or "1.0")
    common_fix_reply = common.get("fix_reply") or {}
    if not isinstance(common_fix_reply, dict):
        _raise_batch_schema_error("INVALID_BATCH_FIX_REPLY", "BatchActionResponse.common.fix_reply must be an object.")

    common_files = common.get("files") or common_fix_reply.get("files")
    common_validation = common.get("validation_commands")
    common_commit_hash = str(common.get("commit_hash") or common_fix_reply.get("commit_hash") or "").strip()

    responses: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            _raise_batch_schema_error("INVALID_BATCH_ITEM", f"BatchActionResponse item {index} must be an object.")
        item_fix_reply = item.get("fix_reply") or {}
        if not isinstance(item_fix_reply, dict):
            _raise_batch_schema_error(
                "INVALID_BATCH_ITEM_FIX_REPLY",
                f"BatchActionResponse item {index} fix_reply must be an object.",
            )

        item_resolution = str(item.get("resolution") or resolution).strip().lower()
        if item_resolution != "fix":
            _raise_batch_schema_error(
                "BATCH_UNSUPPORTED_RESOLUTION",
                f"BatchActionResponse item {index} only supports fix evidence.",
            )

        request_id = str(item.get("request_id") or "").strip()
        lease_id = str(item.get("lease_id") or "").strip()
        if not request_id:
            _raise_batch_schema_error("MISSING_BATCH_ITEM_REQUEST_ID", f"BatchActionResponse item {index} needs request_id.")
        if not lease_id:
            _raise_batch_schema_error("MISSING_BATCH_ITEM_LEASE_ID", f"BatchActionResponse item {index} needs lease_id.")

        summary = str(item.get("summary") or item.get("note") or item_fix_reply.get("summary") or "").strip()
        why = str(item.get("why") or item_fix_reply.get("why") or summary).strip()
        note = str(item.get("note") or summary or why).strip()
        if not note:
            _raise_batch_schema_error("MISSING_BATCH_ITEM_NOTE", f"BatchActionResponse item {index} needs note or summary.")

        files = _normalize_string_list(item.get("files") or item_fix_reply.get("files") or common_files)
        validation_commands = item.get("validation_commands") or common_validation
        fix_reply = dict(common_fix_reply)
        fix_reply.update(item_fix_reply)
        if common_commit_hash and not fix_reply.get("commit_hash"):
            fix_reply["commit_hash"] = common_commit_hash
        if files:
            fix_reply["files"] = files
        if summary and not fix_reply.get("summary"):
            fix_reply["summary"] = summary
        if why:
            fix_reply["why"] = why

        response = {
            "schema_version": schema_version,
            "request_id": request_id,
            "lease_id": lease_id,
            "agent_id": str(item.get("agent_id") or agent_id),
            "resolution": "fix",
            "note": note,
            "files": files,
            "validation_commands": validation_commands,
            "fix_reply": fix_reply,
        }
        if item.get("item_id"):
            response["item_id"] = str(item["item_id"])
        responses.append(response)

    return responses


def _raise_batch_schema_error(reason_code: str, message: str) -> None:
    raise WorkflowError(
        status="BATCH_ACTION_REJECTED",
        reason_code=reason_code,
        waiting_on="batch_action_response",
        exit_code=2,
        message=message,
    )


def _prepare_action_response_submission(
    session: dict[str, Any],
    ledger: EvidenceLedger,
    response: dict[str, Any],
    *,
    rejected_status: str = "ACTION_REJECTED",
) -> dict[str, Any]:
    lease_id = _required_response_field(response, "lease_id", status=rejected_status)
    lease = session.get("leases", {}).get(lease_id)
    if not isinstance(lease, dict):
        _record_response_rejected(session, ledger, response, "LEASE_NOT_FOUND")
        raise WorkflowError(
            status=rejected_status,
            reason_code="LEASE_NOT_FOUND",
            waiting_on="lease",
            exit_code=5,
            message=f"Lease not found: {lease_id}",
        )

    item_id = str(lease["item_id"])
    declared_item_id = response.get("item_id")
    if declared_item_id and str(declared_item_id) != item_id:
        _raise_response_rejected(
            session,
            ledger,
            response,
            "ITEM_ID_MISMATCH",
            status=rejected_status,
            item_id=item_id,
            lease_id=lease_id,
        )

    item = _items(session).get(item_id)
    if not isinstance(item, dict):
        _record_response_rejected(session, ledger, response, "ITEM_NOT_FOUND")
        raise WorkflowError(
            status=rejected_status,
            reason_code="ITEM_NOT_FOUND",
            waiting_on="work_item",
            exit_code=5,
            message=f"Work item not found: {item_id}",
        )

    reason_code = _validate_response(response, item)
    if reason_code:
        _raise_response_rejected(
            session,
            ledger,
            response,
            reason_code,
            status=rejected_status,
            item_id=item_id,
            lease_id=lease_id,
        )

    expected_request_hash, context_reason_code = _expected_request_hash_for_response(response, lease)
    if context_reason_code:
        _raise_response_rejected(
            session,
            ledger,
            response,
            context_reason_code,
            status=rejected_status,
            item_id=item_id,
            lease_id=lease_id,
        )

    return {
        "lease_id": lease_id,
        "lease": lease,
        "item_id": item_id,
        "item": item,
        "expected_request_hash": expected_request_hash,
    }


def _accept_action_response_submission(
    session: dict[str, Any],
    ledger: EvidenceLedger,
    response: dict[str, Any],
    prepared: dict[str, Any],
    *,
    now: datetime,
    rejected_status: str = "ACTION_REJECTED",
) -> Any:
    lease_id = str(prepared["lease_id"])
    lease = prepared["lease"]
    item_id = str(prepared["item_id"])
    item = prepared["item"]
    try:
        submit_lease(
            session,
            lease_id,
            agent_id=str(response["agent_id"]),
            role=str(lease["role"]),
            item_id=item_id,
            request_hash=str(prepared["expected_request_hash"]),
            now=now,
        )
        accept_lease(session, lease_id, now=now)
    except LeaseSubmissionError as exc:
        _record_response_rejected(session, ledger, response, exc.reason_code, item_id=item_id)
        raise WorkflowError(
            status=rejected_status,
            reason_code=exc.reason_code,
            waiting_on="lease",
            exit_code=5,
            message=str(exc),
            payload={"item_id": item_id, "lease_id": lease_id},
        ) from exc

    if str(lease["role"]) == "verifier" and str(response["resolution"]) == "reject":
        item["state"] = "open"
        item["blocking"] = True
        item["verification_rejection_note"] = response["note"]
        record = ledger.append_event(
            session_id=str(session["session_id"]),
            item_id=item_id,
            lease_id=lease_id,
            agent_id=str(response["agent_id"]),
            role=str(lease["role"]),
            event_type="verification_rejected",
            payload={"note": response["note"], "validation_commands": response.get("validation_commands", [])},
        )
        raise WorkflowError(
            status="VERIFICATION_REJECTED",
            reason_code="VERIFICATION_REJECTED",
            waiting_on="fixer",
            exit_code=5,
            message="Verifier rejected the submitted evidence; the item is open again.",
            payload={"item_id": item_id, "lease_id": lease_id, "evidence_record_id": record.record_id},
        )

    _apply_response_to_item(item, response)
    return ledger.append_event(
        session_id=str(session["session_id"]),
        item_id=item_id,
        lease_id=lease_id,
        agent_id=str(response["agent_id"]),
        role=str(lease["role"]),
        event_type="response_accepted",
        payload={"resolution": response["resolution"], "note": response["note"]},
    )


def _validate_batch_fix_contract(
    session: dict[str, Any],
    ledger: EvidenceLedger,
    response: dict[str, Any],
    *,
    item_id: str,
    lease_id: str,
) -> None:
    files = _normalize_string_list(response.get("files"))
    if not files:
        _raise_response_rejected(
            session,
            ledger,
            response,
            "MISSING_BATCH_FILES",
            status="BATCH_ACTION_REJECTED",
            item_id=item_id,
            lease_id=lease_id,
        )
    validation_commands = response.get("validation_commands")
    if not isinstance(validation_commands, list) or not validation_commands:
        _raise_response_rejected(
            session,
            ledger,
            response,
            "MISSING_BATCH_VALIDATION_COMMANDS",
            status="BATCH_ACTION_REJECTED",
            item_id=item_id,
            lease_id=lease_id,
        )
    for command in validation_commands:
        if not isinstance(command, dict) or not command.get("command") or not command.get("result"):
            _raise_response_rejected(
                session,
                ledger,
                response,
                "INVALID_BATCH_VALIDATION_COMMAND",
                status="BATCH_ACTION_REJECTED",
                item_id=item_id,
                lease_id=lease_id,
            )
    fix_reply = response.get("fix_reply")
    if not isinstance(fix_reply, dict):
        _raise_response_rejected(
            session,
            ledger,
            response,
            "MISSING_BATCH_FIX_REPLY",
            status="BATCH_ACTION_REJECTED",
            item_id=item_id,
            lease_id=lease_id,
        )
    if not str(fix_reply.get("commit_hash") or "").strip():
        _raise_response_rejected(
            session,
            ledger,
            response,
            "MISSING_BATCH_COMMIT_HASH",
            status="BATCH_ACTION_REJECTED",
            item_id=item_id,
            lease_id=lease_id,
        )
    if not str(fix_reply.get("why") or "").strip():
        _raise_response_rejected(
            session,
            ledger,
            response,
            "MISSING_BATCH_ITEM_WHY",
            status="BATCH_ACTION_REJECTED",
            item_id=item_id,
            lease_id=lease_id,
        )


def _lease_submission_rejection_reason(
    response: dict[str, Any],
    prepared: dict[str, Any],
    now: datetime,
) -> str | None:
    lease = prepared["lease"]
    status = str(_get(lease, "status") or "")
    if status == "submitted":
        return "DUPLICATE_SUBMISSION"
    if status in {"accepted", "rejected", "expired", "released"}:
        return "STALE_LEASE"
    if status != "active":
        return "STALE_LEASE"

    expires_at = _get(lease, "expires_at")
    if isinstance(expires_at, str):
        expires_at = _coerce_now(expires_at)
    if expires_at is not None and expires_at <= now:
        return "EXPIRED_LEASE"
    if str(_get(lease, "agent_id")) != str(response["agent_id"]):
        return "WRONG_AGENT"
    if str(_get(lease, "item_id")) != str(prepared["item_id"]):
        return "WRONG_ITEM"
    if str(_get(lease, "request_hash")) != str(prepared["expected_request_hash"]):
        return "STALE_REQUEST_CONTEXT"
    return None


def _raise_response_rejected(
    session: dict[str, Any],
    ledger: EvidenceLedger,
    response: dict[str, Any],
    reason_code: str,
    *,
    status: str,
    item_id: str | None = None,
    lease_id: str | None = None,
) -> None:
    _record_response_rejected(session, ledger, response, reason_code, item_id=item_id)
    raise WorkflowError(
        status=status,
        reason_code=reason_code,
        waiting_on="action_response",
        exit_code=5,
        message=f"ActionResponse rejected: {reason_code}",
        payload={"item_id": item_id, "lease_id": lease_id or response.get("lease_id")},
    )


def _batch_acceptance_payload(response: dict[str, Any], prepared: dict[str, Any], record: Any) -> dict[str, Any]:
    return {
        "item_id": str(prepared["item_id"]),
        "lease_id": str(prepared["lease_id"]),
        "request_id": str(response["request_id"]),
        "evidence_record_id": record.record_id,
    }


def publish_github_thread_responses(
    repo: str,
    pr_number: str,
    *,
    github_client: Any | None = None,
    agent_id: str = "gh-address-cr-publisher",
    now: datetime | None = None,
) -> dict[str, Any]:
    current_time = _coerce_now(now)
    timestamp = _format_timestamp(current_time)
    session = session_store.load_session(repo, pr_number)
    ledger = _ledger(session)
    client = github_client or GitHubClient()
    publish_items = _publish_ready_items(session)
    if not publish_items:
        return {
            "status": "NO_PUBLISH_READY_ITEMS",
            "repo": repo,
            "pr_number": str(pr_number),
            "published_count": 0,
        }

    plans: list[dict[str, Any]] = []
    for item_id, item in publish_items:
        response = item.get("accepted_response")
        if not isinstance(response, dict):
            _record_publish_blocked(session, ledger, item_id, agent_id, "MISSING_ACCEPTED_RESPONSE")
            session_store.save_session(repo, pr_number, session)
            raise WorkflowError(
                status="PUBLISH_BLOCKED",
                reason_code="MISSING_ACCEPTED_RESPONSE",
                waiting_on="action_response",
                exit_code=5,
                message=f"Publish-ready item has no accepted response: {item_id}",
                payload={"item_id": item_id},
            )
        thread_id = _github_thread_id(item_id, item)
        if not thread_id:
            _record_publish_blocked(session, ledger, item_id, agent_id, "MISSING_THREAD_ID")
            session_store.save_session(repo, pr_number, session)
            raise WorkflowError(
                status="PUBLISH_BLOCKED",
                reason_code="MISSING_THREAD_ID",
                waiting_on="github_thread",
                exit_code=5,
                message=f"Publish-ready item has no GitHub thread id: {item_id}",
                payload={"item_id": item_id},
            )
        reply_body, error = _publish_reply_body(item, response)
        if not reply_body:
            _record_publish_blocked(session, ledger, item_id, agent_id, error or "MISSING_PUBLISH_REPLY")
            session_store.save_session(repo, pr_number, session)
            raise WorkflowError(
                status="PUBLISH_BLOCKED",
                reason_code=error or "MISSING_PUBLISH_REPLY",
                waiting_on="reply_evidence",
                exit_code=5,
                message=f"Publish-ready item has no valid GitHub reply body: {item_id}",
                payload={"item_id": item_id},
            )
        plans.append(
            {"item_id": item_id, "item": item, "response": response, "thread_id": thread_id, "reply_body": reply_body}
        )

    published: list[str] = []
    for plan in plans:
        item_id = str(plan["item_id"])
        item = plan["item"]
        thread_id = str(plan["thread_id"])
        lease_id = item.get("active_lease_id")
        reply_url = item.get("reply_url") if item.get("reply_posted") else None
        reply_key = _side_effect_key(session, item_id, "github_reply")
        resolve_key = _side_effect_key(session, item_id, "github_resolve")
        existing_reply_url = ledger.successful_side_effect_url(reply_key, "github_reply")
        if existing_reply_url:
            reply_url = existing_reply_url
        if not reply_url:
            try:
                reply_url = client.post_reply(repo, str(pr_number), thread_id, str(plan["reply_body"]))
            except GitHubError as exc:
                _record_side_effect_attempt(
                    ledger,
                    session=session,
                    item_id=item_id,
                    lease_id=lease_id,
                    agent_id=agent_id,
                    side_effect_type="github_reply",
                    idempotency_key=reply_key,
                    status="failed",
                    timestamp=timestamp,
                    last_error=str(exc),
                )
                session_store.save_session(repo, pr_number, session)
                raise _publish_error(repo, pr_number, item_id, exc) from exc
            _record_side_effect_attempt(
                ledger,
                session=session,
                item_id=item_id,
                lease_id=lease_id,
                agent_id=agent_id,
                side_effect_type="github_reply",
                idempotency_key=reply_key,
                status="succeeded",
                timestamp=timestamp,
                external_url=reply_url,
            )
            ledger.append_event(
                session_id=str(session["session_id"]),
                item_id=item_id,
                lease_id=lease_id,
                agent_id=agent_id,
                role="publisher",
                event_type="reply_posted",
                payload={"thread_id": thread_id, "reply_url": reply_url, "idempotency_key": reply_key},
                timestamp=timestamp,
            )
        item["reply_posted"] = True
        item["reply_url"] = reply_url
        item["reply_evidence"] = {"reply_url": reply_url, "author_login": agent_id}

        existing_resolve = ledger.successful_side_effect_url(resolve_key, "github_resolve")
        if not existing_resolve and not item.get("thread_resolved"):
            try:
                client.resolve_thread(repo, str(pr_number), thread_id)
            except GitHubError as exc:
                _record_side_effect_attempt(
                    ledger,
                    session=session,
                    item_id=item_id,
                    lease_id=lease_id,
                    agent_id=agent_id,
                    side_effect_type="github_resolve",
                    idempotency_key=resolve_key,
                    status="failed",
                    timestamp=timestamp,
                    last_error=str(exc),
                )
                session_store.save_session(repo, pr_number, session)
                raise _publish_error(repo, pr_number, item_id, exc) from exc
            _record_side_effect_attempt(
                ledger,
                session=session,
                item_id=item_id,
                lease_id=lease_id,
                agent_id=agent_id,
                side_effect_type="github_resolve",
                idempotency_key=resolve_key,
                status="succeeded",
                timestamp=timestamp,
                external_url=thread_id,
            )
            ledger.append_event(
                session_id=str(session["session_id"]),
                item_id=item_id,
                lease_id=lease_id,
                agent_id=agent_id,
                role="publisher",
                event_type="thread_resolved",
                payload={"thread_id": thread_id, "idempotency_key": resolve_key},
                timestamp=timestamp,
            )

        item["state"] = "closed"
        item["status"] = "CLOSED"
        item["blocking"] = False
        item["handled"] = True
        item["thread_resolved"] = True
        item["handled_at"] = timestamp
        item["claimed_by"] = None
        item["claimed_at"] = None
        item["lease_expires_at"] = None
        item.pop("active_lease_id", None)
        ledger.append_event(
            session_id=str(session["session_id"]),
            item_id=item_id,
            lease_id=lease_id,
            agent_id=agent_id,
            role="publisher",
            event_type="response_published",
            payload={"thread_id": thread_id, "reply_url": reply_url},
            timestamp=timestamp,
        )
        published.append(item_id)

    session_store.save_session(repo, pr_number, session)
    return {
        "status": "PUBLISH_COMPLETE",
        "repo": repo,
        "pr_number": str(pr_number),
        "published_count": len(published),
        "published_items": published,
    }


def list_leases(repo: str, pr_number: str) -> dict[str, Any]:
    session = session_store.load_session(repo, pr_number)
    return {
        "status": "LEASES_READY",
        "repo": repo,
        "pr_number": str(pr_number),
        "leases": [_json_ready(lease) for lease in session.get("leases", {}).values()],
    }


def reclaim_leases(repo: str, pr_number: str, *, now: datetime | None = None) -> dict[str, Any]:
    current_time = _coerce_now(now)
    session = session_store.load_session(repo, pr_number)
    ledger = _ledger(session)
    expired = expire_leases(session, now=current_time)
    _return_expired_items_to_open(session, expired)
    for lease in expired:
        ledger.append_event(
            session_id=str(session["session_id"]),
            item_id=str(_get(lease, "item_id")),
            lease_id=str(_get(lease, "lease_id")),
            agent_id=str(_get(lease, "agent_id")),
            role=str(_get(lease, "role")),
            event_type="lease_expired",
            payload={"reason": "reclaimed"},
        )
    session_store.save_session(repo, pr_number, session)
    return {
        "status": "LEASES_RECLAIMED",
        "repo": repo,
        "pr_number": str(pr_number),
        "expired_count": len(expired),
        "leases": [_json_ready(lease) for lease in expired],
    }


def _publish_ready_items(session: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    ready: list[tuple[str, dict[str, Any]]] = []
    for item_id, item in _items(session).items():
        if item.get("item_kind") != "github_thread":
            continue
        if str(item.get("state") or "").lower() == "publish_ready":
            ready.append((item_id, item))
    return ready


def _github_thread_id(item_id: str, item: dict[str, Any]) -> str:
    for key in ("thread_id", "origin_ref"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    if item_id.startswith("github-thread:"):
        return item_id.removeprefix("github-thread:").strip()
    return ""


def _publish_reply_body(item: dict[str, Any], response: dict[str, Any]) -> tuple[str | None, str | None]:
    resolution = str(response.get("resolution") or item.get("publish_resolution") or "")
    reply_markdown = response.get("reply_markdown")
    if resolution != "fix" and isinstance(reply_markdown, str) and reply_markdown.strip():
        return reply_markdown, None
    if resolution != "fix":
        return None, "MISSING_PUBLISH_REPLY"
    fix_reply = response.get("fix_reply")
    if not isinstance(fix_reply, dict):
        return None, "MISSING_PUBLISH_REPLY"
    commit_hash = str(fix_reply.get("commit_hash") or "").strip()
    if not commit_hash:
        return None, "MISSING_FIX_REPLY_COMMIT_HASH"
    files = _normalize_string_list(fix_reply.get("files") or response.get("files"))
    if not files:
        return None, "MISSING_FIX_REPLY_FILES"
    validation_commands = _normalize_validation_commands(response.get("validation_commands"))
    test_command = str(fix_reply.get("test_command") or " && ".join(validation_commands)).strip()
    test_result = str(fix_reply.get("test_result") or ("passed" if validation_commands else "")).strip()
    if not test_command:
        return None, "MISSING_FIX_REPLY_TEST_COMMAND"
    if not test_result:
        return None, "MISSING_FIX_REPLY_TEST_RESULT"
    severity = _normalize_fix_reply_severity(fix_reply.get("severity") or item.get("severity") or "P2")
    why = str(fix_reply.get("why") or "Addressed the CR with targeted changes and validation evidence.").strip()
    try:
        return render_fix_reply(severity, [commit_hash, ",".join(files), test_command, test_result, why]), None
    except SystemExit as exc:
        return None, str(exc) or "MISSING_PUBLISH_REPLY"


def _normalize_string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, list):
        return [str(part).strip() for part in value if str(part).strip()]
    return []


def _normalize_validation_commands(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if not isinstance(value, list):
        return []
    commands: list[str] = []
    for entry in value:
        command = entry.get("command") if isinstance(entry, dict) else entry
        command_text = str(command or "").strip()
        if command_text:
            commands.append(command_text)
    return commands


def _normalize_fix_reply_severity(value: Any) -> str:
    severity = str(value or "").strip().upper()
    return severity if severity in {"P1", "P2", "P3"} else "P2"


def _release_active_triage_lease(session: dict[str, Any], item_id: str, *, agent_id: str) -> str | None:
    for lease_id, lease in session.get("leases", {}).items():
        if not isinstance(lease, dict):
            continue
        if lease.get("item_id") != item_id:
            continue
        if lease.get("role") != "triage":
            continue
        if lease.get("status") not in {"active", "submitted"}:
            continue
        release_lease(session, str(lease_id), reason="classification_recorded")
        _ledger(session).append_event(
            session_id=str(session["session_id"]),
            item_id=item_id,
            lease_id=str(lease_id),
            agent_id=agent_id,
            role="triage",
            event_type="classification_lease_released",
            payload={"reason": "classification_recorded"},
        )
        return str(lease_id)
    return None


def _side_effect_key(session: dict[str, Any], item_id: str, side_effect_type: str) -> str:
    return f"{session['session_id']}:{item_id}:{side_effect_type}"


def _record_side_effect_attempt(
    ledger: EvidenceLedger,
    *,
    session: dict[str, Any],
    item_id: str,
    lease_id: str | None,
    agent_id: str,
    side_effect_type: str,
    idempotency_key: str,
    status: str,
    timestamp: str,
    external_url: str | None = None,
    last_error: str | None = None,
) -> None:
    attempt = SideEffectAttempt.new(
        session_id=str(session["session_id"]),
        item_id=item_id,
        side_effect_type=side_effect_type,
        idempotency_key=idempotency_key,
        status=status,
        retry_count=0,
        last_error=last_error,
        external_url=external_url,
        timestamp=timestamp,
    )
    ledger.record_side_effect_attempt(
        attempt=attempt,
        lease_id=lease_id,
        agent_id=agent_id,
        timestamp=timestamp,
    )


def _record_publish_blocked(
    session: dict[str, Any],
    ledger: EvidenceLedger,
    item_id: str,
    agent_id: str,
    reason_code: str,
) -> None:
    ledger.append_event(
        session_id=str(session["session_id"]),
        item_id=item_id,
        lease_id=None,
        agent_id=agent_id,
        role="publisher",
        event_type="publish_blocked",
        payload={"reason_code": reason_code},
    )


def _publish_error(repo: str, pr_number: str, item_id: str, exc: GitHubError) -> WorkflowError:
    return WorkflowError(
        status="PUBLISH_BLOCKED",
        reason_code=exc.reason_code,
        waiting_on="github",
        exit_code=5,
        message=f"GitHub publish failed for {item_id}: {exc}",
        payload={"item_id": item_id, "retryable": exc.retryable, "repo": repo, "pr_number": str(pr_number)},
    )


def _next_item(session: dict[str, Any], role: str) -> tuple[str, dict[str, Any] | None]:
    active_item_ids = {
        str(lease.get("item_id"))
        for lease in session.get("leases", {}).values()
        if isinstance(lease, dict) and lease.get("status") in {"active", "submitted"}
    }
    for item_id, item in _items(session).items():
        if item_id in active_item_ids:
            continue
        if _item_is_open(item):
            return item_id, item
    return "", None


def _items(session: dict[str, Any]) -> dict[str, dict[str, Any]]:
    items = session.setdefault("items", {})
    if isinstance(items, dict):
        return {str(key): value for key, value in items.items() if isinstance(value, dict)}
    raise WorkflowError(
        status="INVALID_SESSION",
        reason_code="INVALID_ITEMS_SHAPE",
        waiting_on="session",
        exit_code=5,
        message="Session items must be a JSON object.",
    )


def _item_is_open(item: dict[str, Any]) -> bool:
    return str(item.get("state") or item.get("status") or "open").lower() in {"open", "blocked", "waiting_for_fix"}


def _has_classification_evidence(item: dict[str, Any]) -> bool:
    evidence = item.get("classification_evidence")
    return isinstance(evidence, dict) and evidence.get("classification") in TERMINAL_RESOLUTIONS


def _required_evidence_for(item: dict[str, Any], role: str) -> list[str]:
    if role == "fixer":
        fields = ["note", "files", "validation_commands"]
        if item.get("item_kind") == "github_thread":
            fields.append("fix_reply")
        return fields
    return ["note", "reply_markdown", "validation_commands"]


def _validate_response(response: dict[str, Any], item: dict[str, Any]) -> str | None:
    for field in ("request_id", "lease_id", "agent_id", "resolution", "note"):
        if not response.get(field):
            return f"MISSING_{field.upper()}"
    if _claims_direct_github_side_effect(response):
        return "DIRECT_GITHUB_SIDE_EFFECT_FORBIDDEN"
    resolution = str(response["resolution"])
    if resolution not in TERMINAL_RESOLUTIONS:
        return "UNSUPPORTED_RESOLUTION"
    if resolution == "fix":
        if not _has_classification_evidence(item):
            return "MISSING_CLASSIFICATION"
        if not response.get("files"):
            return "MISSING_FILES"
        if not response.get("validation_commands"):
            return "MISSING_VALIDATION_COMMANDS"
        if item.get("item_kind") == "github_thread" and not response.get("fix_reply"):
            return "MISSING_FIX_REPLY"
    else:
        if not response.get("reply_markdown"):
            return "MISSING_REPLY_MARKDOWN"
        if not response.get("validation_commands"):
            return "MISSING_VALIDATION_COMMANDS"
    return None


def _expected_request_hash_for_response(
    response: dict[str, Any], lease: dict[str, Any]
) -> tuple[str | None, str | None]:
    response_request_id = str(response["request_id"])
    request_path = _get(lease, "request_path")
    if request_path:
        path = Path(str(request_path))
        if not path.is_file():
            return None, "REQUEST_CONTEXT_NOT_FOUND"
        try:
            request = json.loads(path.read_text(encoding="utf-8"))
            expected_hash = ActionRequest.from_dict(request).stable_hash()
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            return None, "INVALID_REQUEST_CONTEXT"
        if response_request_id != str(request.get("request_id") or ""):
            return None, "STALE_REQUEST_CONTEXT"
        return expected_hash, None

    lease_request_id = _get(lease, "request_id")
    if lease_request_id:
        if response_request_id != str(lease_request_id):
            return None, "STALE_REQUEST_CONTEXT"
        return str(_get(lease, "request_hash")), None

    if response_request_id != str(_get(lease, "request_hash")):
        return None, "STALE_REQUEST_CONTEXT"
    return str(_get(lease, "request_hash")), None


def _apply_response_to_item(item: dict[str, Any], response: dict[str, Any]) -> None:
    resolution = str(response["resolution"])
    if item.get("item_kind") == "github_thread":
        item["state"] = "publish_ready"
        item["status"] = "OPEN"
        item["blocking"] = True
        item["publish_resolution"] = resolution
        item["accepted_response"] = {
            "note": response["note"],
            "resolution": resolution,
            "files": response.get("files", []),
            "validation_commands": response.get("validation_commands", []),
            "reply_markdown": response.get("reply_markdown"),
            "fix_reply": response.get("fix_reply"),
        }
        return
    item["state"] = "fixed" if resolution == "fix" else resolution
    item["status"] = _legacy_local_status_for_resolution(resolution)
    item["blocking"] = False
    item["handled"] = True
    item["handled_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    item["resolution_note"] = response["note"]
    item["validation_evidence"] = response.get("validation_commands", [])
    item["claimed_by"] = None
    item["claimed_at"] = None
    item["lease_expires_at"] = None
    if response.get("files"):
        item["files"] = response["files"]
    if response.get("reply_markdown"):
        item["reply_markdown"] = response["reply_markdown"]
    if response.get("fix_reply"):
        item["fix_reply"] = response["fix_reply"]


def _legacy_local_status_for_resolution(resolution: str) -> str:
    if resolution == "fix":
        return "CLOSED"
    if resolution == "clarify":
        return "CLARIFIED"
    if resolution == "defer":
        return "DEFERRED"
    if resolution == "reject":
        return "DROPPED"
    return resolution.upper()


def _claims_direct_github_side_effect(response: dict[str, Any]) -> bool:
    forbidden_keys = {
        "github_side_effects",
        "reply_posted",
        "reply_url",
        "thread_resolved",
        "resolved_thread_id",
    }
    return any(key in response for key in forbidden_keys)


def _record_response_rejected(
    session: dict[str, Any],
    ledger: EvidenceLedger,
    response: dict[str, Any],
    reason_code: str,
    *,
    item_id: str | None = None,
) -> None:
    lease_id = response.get("lease_id")
    lease = session.get("leases", {}).get(lease_id) if lease_id else None
    if isinstance(lease, dict) and item_id is None:
        item_id = str(lease.get("item_id"))
    ledger.append_event(
        session_id=str(session["session_id"]),
        item_id=item_id or "",
        lease_id=lease_id,
        agent_id=str(response.get("agent_id") or "unknown"),
        role=str(lease.get("role") if isinstance(lease, dict) else "unknown"),
        event_type="response_rejected",
        payload={"reason_code": reason_code},
    )


def _return_expired_items_to_open(session: dict[str, Any], expired: list[Any]) -> None:
    items = _items(session)
    for lease in expired:
        item = items.get(str(_get(lease, "item_id")))
        if isinstance(item, dict) and str(item.get("state")).lower() == "claimed":
            item["state"] = "open"
            item.pop("active_lease_id", None)


def _ledger(session: dict[str, Any]) -> EvidenceLedger:
    return EvidenceLedger(
        session.get("ledger_path") or session_store.default_ledger_path(str(session["repo"]), str(session["pr_number"]))
    )


def _required_response_field(response: dict[str, Any], field: str, *, status: str = "ACTION_REJECTED") -> str:
    value = response.get(field)
    if not value:
        raise WorkflowError(
            status=status,
            reason_code=f"MISSING_{field.upper()}",
            waiting_on="action_response",
            exit_code=2,
            message=f"ActionResponse is missing `{field}`.",
        )
    return str(value)


def _stable_id(prefix: str, payload: dict[str, Any]) -> str:
    return f"{prefix}_{_hash_payload(payload)[:20]}"


def _hash_payload(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(_json_ready(payload), sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _coerce_now(value: datetime | str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _json_ready(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_ready(inner) for key, inner in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_ready(inner) for inner in value]
    if hasattr(value, "__dict__"):
        return _json_ready(vars(value))
    return value


def _get(obj: Any, field: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(field, default)
    return getattr(obj, field, default)
