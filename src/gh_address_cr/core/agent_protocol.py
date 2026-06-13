from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from gh_address_cr import PROTOCOL_VERSION
from gh_address_cr.core import command_templates, protocol_codes
from gh_address_cr.core import session as session_store
from gh_address_cr.core.agent_protocol_evidence import (
    TERMINAL_RESOLUTIONS,
)
from gh_address_cr.core.agent_protocol_evidence import (
    required_evidence_for as _required_evidence_for_impl,
)
from gh_address_cr.core.errors import WorkflowError
from gh_address_cr.core.github_thread_state import (
    GITHUB_THREAD_CLAIMABLE_STATES,
    is_claimable_github_thread,
    is_github_thread_item,
    is_stale_github_thread_item,
)
from gh_address_cr.core.ids import stable_id as _stable_id
from gh_address_cr.core.io import write_json_atomic
from gh_address_cr.core.leases import (
    LeaseConflictError,
    LeaseSubmissionError,
    accept_lease,
    calculate_lease_recovery_state,
    claim_lease,
    expire_leases,
    release_lease,
    submit_lease,
)
from gh_address_cr.core.models import ActionRequest
from gh_address_cr.core.paths import SessionPaths
from gh_address_cr.core.severity import first_scene_item_severity
from gh_address_cr.core.utils import (
    coerce_now as _coerce_now,
)
from gh_address_cr.core.utils import (
    fix_reply_severity_rejection_reason as _fix_reply_severity_rejection_reason,
)
from gh_address_cr.core.utils import (
    get_field as _get,
)
from gh_address_cr.core.utils import (
    get_session_items as _items,
)
from gh_address_cr.core.utils import (
    get_session_ledger as _ledger,
)
from gh_address_cr.core.utils import (
    normalize_optional_fix_reply_severity as _normalize_optional_fix_reply_severity,
)
from gh_address_cr.core.utils import (
    normalize_string_list as _normalize_string_list,
)
from gh_address_cr.core.utils import (
    return_expired_items_to_open as _return_expired_items_to_open,
)
from gh_address_cr.core.utils import (
    return_item_to_claimable_state as _return_item_to_claimable_state,
)
from gh_address_cr.core.utils import (
    severity_override_note as _severity_override_note,
)
from gh_address_cr.core.validation_evidence import validation_result_is_success
from gh_address_cr.core.work_item_handlers import WorkItemBoundaryError, boundary_summary_for_item
from gh_address_cr.evidence.ledger import EvidenceLedger

MUTATING_ROLES = {"fixer"}


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
        _return_item_to_claimable_state(item)
        if not is_stale_github_thread_item(item):
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
    item_id: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    current_time = _coerce_now(now)
    session = session_store.load_session(repo, pr_number)
    ledger = _ledger(session)
    expired = expire_leases(session, now=current_time)
    _return_expired_items_to_open(session, expired)

    item_id, item = _next_item(session, role, item_id=item_id)
    if item is None:
        session_store.save_session(repo, pr_number, session)
        raise WorkflowError(
            status=protocol_codes.NO_ELIGIBLE_ITEM,
            reason_code=protocol_codes.NO_ELIGIBLE_ITEM,
            waiting_on="work_item",
            exit_code=4,
            message=f"No eligible work item exists for role `{role}`.",
        )

    if role in MUTATING_ROLES and not _has_classification_evidence(item):
        _restore_classification_evidence_from_session(session, item_id, item)
    if role in MUTATING_ROLES and not _has_classification_evidence(item):
        next_action = (
            f"Missing triage classification evidence for {item_id}. Run "
            f"`gh-address-cr agent classify {repo} {pr_number} {item_id} "
            "--classification <fix|clarify|defer|reject> --note <why>` "
            "before requesting a fixer lease."
        )
        ledger.append_event(
            session_id=str(session["session_id"]),
            item_id=item_id,
            lease_id=None,
            agent_id=agent_id,
            role=role,
            event_type="request_rejected",
            payload={"reason_code": protocol_codes.MISSING_CLASSIFICATION},
        )
        session_store.save_session(repo, pr_number, session)
        raise WorkflowError(
            status="REQUEST_REJECTED",
            reason_code=protocol_codes.MISSING_CLASSIFICATION,
            waiting_on="classification",
            exit_code=5,
            message=next_action,
            payload={"item_id": item_id, "next_action": next_action},
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
    handling_boundary = _handling_boundary_summary_or_none(item, role=role)
    if handling_boundary is not None:
        request["handling_boundary"] = handling_boundary
    request_hash = ActionRequest.from_dict(request).stable_hash()
    request_path = session_store.workspace_dir(repo, pr_number) / f"action-request-{request_id}.json"
    response_skeleton_path = session_store.workspace_dir(repo, pr_number) / f"action-response-skeleton-{request_id}.json"
    request["response_skeleton_path"] = str(response_skeleton_path)
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
            allow_same_agent_github_thread_file_overlap=bool(
                role == "fixer" and item.get("item_kind") == "github_thread"
            ),
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
    write_json_atomic(request_path, request)
    response_skeleton = _response_skeleton_for_request(request, agent_id=agent_id, item=item)
    write_json_atomic(response_skeleton_path, response_skeleton)

    ledger.append_event(
        session_id=str(session["session_id"]),
        item_id=item_id,
        lease_id=lease_id,
        agent_id=agent_id,
        role=role,
        event_type="request_issued",
        payload={
            "request_id": request_id,
            "request_path": str(request_path),
            "response_skeleton_path": str(response_skeleton_path),
        },
    )
    session_store.save_session(repo, pr_number, session)
    return {
        "status": "ACTION_REQUESTED",
        "repo": repo,
        "pr_number": str(pr_number),
        "request_path": str(request_path),
        "response_skeleton_path": str(response_skeleton_path),
        "lease_id": lease_id,
        "resume_token": _get(lease, "resume_token"),
        "item_id": item_id,
        **({"handling_boundary": handling_boundary} if handling_boundary is not None else {}),
        "next_action": f"Pass request_path to an agent with the {role} role, then fill response_skeleton_path.",
    }


_BATCH_CLASSIFICATION_NOTE = "Batch fix skeleton requested by agent next --batch."


def _active_fixer_lease_for_item(
    session: dict[str, Any], item_id: str, *, agent_id: str | None = None
) -> dict[str, Any] | None:
    for lease in session.get("leases", {}).values():
        if not isinstance(lease, dict):
            continue
        if lease.get("item_id") != item_id:
            continue
        if lease.get("status") != "active":
            continue
        if lease.get("role") != "fixer":
            continue
        if agent_id is not None and lease.get("agent_id") != agent_id:
            continue
        return lease
    return None


def _is_batch_claimable_github_thread(item: dict[str, Any]) -> bool:
    return is_claimable_github_thread(item) and not is_stale_github_thread_item(item)


def _handling_boundary_summary_or_none(item: dict[str, Any], *, role: str) -> dict[str, Any] | None:
    if role != "fixer" or item.get("item_kind") != "github_thread":
        return None
    try:
        return boundary_summary_for_item(item, role=role)
    except WorkItemBoundaryError:
        return None


def submit_action_response(
    repo: str,
    pr_number: str,
    *,
    response_path: str | Path,
    now: datetime | None = None,
    publish: bool = False,
    github_client: Any | None = None,
    publisher_agent_id: str = "gh-address-cr-publisher",
) -> dict[str, Any]:
    now = _coerce_now(now)
    session = session_store.load_session(repo, pr_number)
    ledger = _ledger(session)
    response = _load_response_json_object(
        response_path,
        status=protocol_codes.ACTION_REJECTED,
        missing_reason_code="RESPONSE_FILE_NOT_FOUND",
        invalid_reason_code="INVALID_RESPONSE_JSON",
        shape_reason_code="INVALID_RESPONSE_SHAPE",
        shape_message="ActionResponse must be a JSON object.",
        payload_name="ActionResponse",
    )

    try:
        if publish:
            _validate_publish_shortcut_target(session, response)
        prepared = _prepare_action_response_submission(session, ledger, response, now=now)
        record = _accept_action_response_submission(session, ledger, response, prepared, now=now)
    except WorkflowError:
        session_store.save_session(repo, pr_number, session)
        raise
    session_store.save_session(repo, pr_number, session)
    payload = {
        "status": "ACTION_ACCEPTED",
        "repo": repo,
        "pr_number": str(pr_number),
        "lease_id": prepared["lease_id"],
        "item_id": prepared["item_id"],
        "evidence_record_id": record.record_id,
        "next_action": f"Run `gh-address-cr agent publish {repo} {pr_number}` to publish accepted evidence.",
    }
    if not publish:
        return payload

    from gh_address_cr.core import publisher

    published = publisher.publish_github_thread_responses(
        repo,
        pr_number,
        github_client=github_client,
        agent_id=publisher_agent_id,
        now=now,
    )
    payload["publish"] = published
    payload["next_action"] = "Accepted evidence was published. Rerun final-gate when all items are handled."
    return payload


def submit_batch_action_response(
    repo: str, pr_number: str, *, batch_path: str | Path, now: datetime | None = None
) -> dict[str, Any]:
    now = _coerce_now(now)
    session = session_store.load_session(repo, pr_number)
    session_paths = SessionPaths(repo, pr_number)
    ledger = _ledger(session)
    prepared_rows: list[tuple[dict[str, Any], dict[str, Any]]] = []
    seen_leases: set[str] = set()
    seen_items: set[str] = set()

    batch: dict[str, Any] | None = None
    try:
        batch = _load_response_json_object(
            batch_path,
            status=protocol_codes.BATCH_ACTION_REJECTED,
            missing_reason_code="BATCH_RESPONSE_FILE_NOT_FOUND",
            invalid_reason_code="INVALID_BATCH_RESPONSE_JSON",
            shape_reason_code="INVALID_BATCH_RESPONSE_SHAPE",
            shape_message="BatchActionResponse must be a JSON object.",
            payload_name="BatchActionResponse",
            waiting_on="batch_action_response",
        )
        responses = _batch_action_responses(batch)
        for response in responses:
            lease_id = str(response.get("lease_id") or "")
            if lease_id in seen_leases:
                _raise_response_rejected(
                    session,
                    ledger,
                    response,
                    "BATCH_DUPLICATE_LEASE",
                    status=protocol_codes.BATCH_ACTION_REJECTED,
                )
            seen_leases.add(lease_id)

            prepared = _prepare_action_response_submission(
                session,
                ledger,
                response,
                now=now,
                rejected_status=protocol_codes.BATCH_ACTION_REJECTED,
            )
            item_id = str(prepared["item_id"])
            if item_id in seen_items:
                _raise_response_rejected(
                    session,
                    ledger,
                    response,
                    "BATCH_DUPLICATE_ITEM",
                    status=protocol_codes.BATCH_ACTION_REJECTED,
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
                    status=protocol_codes.BATCH_ACTION_REJECTED,
                    item_id=item_id,
                    lease_id=lease_id,
                )
            if str(lease.get("role")) != "fixer":
                _raise_response_rejected(
                    session,
                    ledger,
                    response,
                    "BATCH_UNSUPPORTED_ROLE",
                    status=protocol_codes.BATCH_ACTION_REJECTED,
                    item_id=item_id,
                    lease_id=lease_id,
                )
            if str(response.get("resolution")) != "fix":
                _raise_response_rejected(
                    session,
                    ledger,
                    response,
                    "BATCH_UNSUPPORTED_RESOLUTION",
                    status=protocol_codes.BATCH_ACTION_REJECTED,
                    item_id=item_id,
                    lease_id=lease_id,
                )
            _validate_batch_fix_contract(session, ledger, response, item_id=item_id, lease_id=lease_id)
            lease_reason_code = _lease_submission_rejection_reason(response, prepared, now)
            if lease_reason_code:
                lease_recovery = _lease_recovery_payload_for_response(
                    session,
                    response,
                    prepared["lease"],
                    item_id=item_id,
                    request_hash=str(prepared.get("expected_request_hash") or response.get("request_id") or ""),
                    now=now,
                )
                _raise_response_rejected(
                    session,
                    ledger,
                    response,
                    lease_reason_code,
                    status=protocol_codes.BATCH_ACTION_REJECTED,
                    item_id=item_id,
                    lease_id=lease_id,
                    lease_recovery=lease_recovery,
                )
            prepared_rows.append((response, prepared))

        telemetry_seen: set[tuple[str, str, str, str, str, str]] = set()
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
                    rejected_status=protocol_codes.BATCH_ACTION_REJECTED,
                    telemetry_seen=telemetry_seen,
                ),
            )
            for response, prepared in prepared_rows
        ]
    except WorkflowError as exc:
        _augment_batch_recovery_error(exc, session_paths, batch_path=batch_path, agent_id=_batch_agent_id(batch))
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

def _chunks(values: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def _load_response_json_object(
    response_path: str | Path,
    *,
    status: str,
    missing_reason_code: str,
    invalid_reason_code: str,
    shape_reason_code: str,
    shape_message: str,
    payload_name: str,
    waiting_on: str = "action_response",
) -> dict[str, Any]:
    path = Path(response_path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise WorkflowError(
            status=status,
            reason_code=missing_reason_code,
            waiting_on=waiting_on,
            exit_code=2,
            message=f"{payload_name} file does not exist: {path}",
        ) from exc
    except json.JSONDecodeError as exc:
        raise WorkflowError(
            status=status,
            reason_code=invalid_reason_code,
            waiting_on=waiting_on,
            exit_code=2,
            message=f"Invalid {payload_name} JSON: {exc}",
        ) from exc

    if not isinstance(payload, dict):
        raise WorkflowError(
            status=status,
            reason_code=shape_reason_code,
            waiting_on=waiting_on,
            exit_code=2,
            message=shape_message,
        )
    return payload


def _response_skeleton_for_request(request: dict[str, Any], *, agent_id: str, item: dict[str, Any]) -> dict[str, Any]:
    role = str(request.get("agent_role") or "")
    resolution = _classified_resolution(item) if role == "fixer" else None
    resolution = resolution or "<fix|clarify|defer|reject>"
    skeleton: dict[str, Any] = {
        "schema_version": str(request.get("schema_version") or PROTOCOL_VERSION),
        "request_id": str(request["request_id"]),
        "lease_id": str(request["lease_id"]),
        "agent_id": agent_id,
        "item_id": str(item.get("item_id") or ""),
        "resolution": resolution,
        "note": "",
    }
    if role == "fixer" and resolution == "fix":
        skeleton["files"] = []
        skeleton["validation_commands"] = [{"command": "", "result": ""}]
    if item.get("item_kind") == "github_thread":
        if role == "fixer" and resolution == "fix":
            skeleton["fix_reply"] = {
                "summary": "",
                "files": [],
                "why": "",
                "test_command": "",
                "test_result": "",
            }
        else:
            skeleton["reply_markdown"] = ""
    elif resolution != "fix":
        skeleton["reply_markdown"] = ""
    return skeleton


def _classified_resolution(item: dict[str, Any]) -> str | None:
    evidence = item.get("classification_evidence")
    if isinstance(evidence, dict) and evidence.get("classification") in TERMINAL_RESOLUTIONS:
        return str(evidence["classification"])
    decision = str(item.get("decision") or "").strip().lower()
    if decision in TERMINAL_RESOLUTIONS:
        return decision
    return None


def _restore_classification_evidence_from_session(
    session: dict[str, Any], item_id: str, item: dict[str, Any]
) -> None:
    decision = str(item.get("decision") or "").strip().lower()
    if decision in TERMINAL_RESOLUTIONS:
        item["classification_evidence"] = {
            "event_type": "classification_recorded",
            "classification": decision,
            "note": str(item.get("classification_note") or item.get("resolution_note") or "Restored from item decision."),
            "record_id": str(item.get("classification_record_id") or "session-decision"),
        }
        return

    try:
        records = _ledger(session).load(event_type="classification_recorded")
    except ValueError:
        return
    for record in reversed(records):
        if record.item_id != item_id:
            continue
        classification = str(record.payload.get("classification") or "").strip().lower()
        if classification not in TERMINAL_RESOLUTIONS:
            continue
        item["classification_evidence"] = {
            "event_type": "classification_recorded",
            "classification": classification,
            "note": str(record.payload.get("note") or "Restored from evidence ledger."),
            "record_id": record.record_id,
        }
        item["decision"] = classification
        return

def _expand_evidence_ref(session: dict[str, Any], response: dict[str, Any]) -> str | None:
    evidence_ref = str(response.get("evidence_ref") or "").strip()
    if not evidence_ref:
        return None
    profiles = session.get("evidence_profiles")
    if not isinstance(profiles, dict):
        return "EVIDENCE_PROFILE_NOT_FOUND"
    profile = profiles.get(evidence_ref)
    if not isinstance(profile, dict):
        return "EVIDENCE_PROFILE_NOT_FOUND"

    profile_files = _normalize_string_list(profile.get("files"))
    response_files = _normalize_string_list(response.get("files"))
    if not response_files and profile_files:
        response["files"] = profile_files
        response_files = profile_files

    profile_validation = _normalize_validation_command_records(profile.get("validation_commands"))
    if not response.get("validation_commands") and profile_validation:
        response["validation_commands"] = profile_validation

    profile_fix_reply = profile.get("fix_reply") if isinstance(profile.get("fix_reply"), dict) else {}
    if "fix_reply" in response and response.get("fix_reply") is not None and not isinstance(response.get("fix_reply"), dict):
        return "INVALID_FIX_REPLY"
    response_fix_reply = response.get("fix_reply") if isinstance(response.get("fix_reply"), dict) else {}
    merged_fix_reply = dict(profile_fix_reply)
    merged_fix_reply.update(response_fix_reply)
    if profile.get("commit_hash") and not merged_fix_reply.get("commit_hash"):
        merged_fix_reply["commit_hash"] = profile["commit_hash"]
    if response_files and not merged_fix_reply.get("files"):
        merged_fix_reply["files"] = response_files
    if str(response.get("resolution") or "") == "fix" and merged_fix_reply:
        response["fix_reply"] = merged_fix_reply
    return None


def _validate_publish_shortcut_target(session: dict[str, Any], response: dict[str, Any]) -> None:
    lease_id = str(response.get("lease_id") or "")
    lease = session.get("leases", {}).get(lease_id)
    item_id = str(lease.get("item_id") or "") if isinstance(lease, dict) else ""
    item = _items(session).get(item_id) if item_id else None
    if not isinstance(item, dict):
        raise WorkflowError(
            status=protocol_codes.ACTION_REJECTED,
            reason_code="PUBLISH_TARGET_NOT_FOUND",
            waiting_on="action_response",
            exit_code=5,
            message="--publish requires an ActionResponse for an existing GitHub review-thread item.",
            payload={"lease_id": lease_id or None},
        )
    if item.get("item_kind") != "github_thread":
        raise WorkflowError(
            status=protocol_codes.ACTION_REJECTED,
            reason_code="PUBLISH_UNSUPPORTED_RESPONSE",
            waiting_on="action_response",
            exit_code=5,
            message="--publish is only supported for GitHub review-thread responses.",
            payload={"item_id": item_id, "lease_id": lease_id},
        )
    resolution = str(response.get("resolution") or "")
    if resolution and resolution != "fix":
        raise WorkflowError(
            status=protocol_codes.ACTION_REJECTED,
            reason_code="PUBLISH_UNSUPPORTED_RESPONSE",
            waiting_on="action_response",
            exit_code=5,
            message="--publish is only supported for GitHub review-thread fix responses.",
            payload={"item_id": item_id, "lease_id": lease_id},
        )


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
    common_evidence_ref = str(common.get("evidence_ref") or batch.get("evidence_ref") or "").strip()

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

        summary = str(item.get("summary") or item_fix_reply.get("summary") or "").strip()
        why = str(item.get("why") or item_fix_reply.get("why") or "").strip()
        note = str(item.get("note") or summary or why).strip()
        if not note:
            _raise_batch_schema_error("MISSING_BATCH_ITEM_NOTE", f"BatchActionResponse item {index} needs note or summary.")

        files = _normalize_string_list(item.get("files") or item_fix_reply.get("files") or common_files)
        validation_commands = item.get("validation_commands") or common_validation
        fix_reply = dict(common_fix_reply)
        fix_reply.pop("why", None)
        fix_reply.update(item_fix_reply)
        if common_commit_hash and not fix_reply.get("commit_hash"):
            fix_reply["commit_hash"] = common_commit_hash
        if files:
            fix_reply["files"] = files
        if summary:
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
        evidence_ref = str(item.get("evidence_ref") or common_evidence_ref).strip()
        if evidence_ref:
            response["evidence_ref"] = evidence_ref
        if item.get("item_id"):
            response["item_id"] = str(item["item_id"])
        responses.append(response)

    return responses


def _raise_batch_schema_error(reason_code: str, message: str) -> None:
    raise WorkflowError(
        status=protocol_codes.BATCH_ACTION_REJECTED,
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
    now: datetime,
    rejected_status: str = protocol_codes.ACTION_REJECTED,
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

    evidence_ref_reason = _expand_evidence_ref(session, response)
    if evidence_ref_reason:
        _raise_response_rejected(
            session,
            ledger,
            response,
            evidence_ref_reason,
            status=rejected_status,
            item_id=item_id,
            lease_id=lease_id,
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
        lease_recovery = _lease_recovery_payload_for_response(
            session,
            response,
            lease,
            item_id=item_id,
            request_hash=str(response.get("request_id") or ""),
            now=now,
        )
        _raise_response_rejected(
            session,
            ledger,
            response,
            context_reason_code,
            status=rejected_status,
            item_id=item_id,
            lease_id=lease_id,
            lease_recovery=lease_recovery,
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
    rejected_status: str = protocol_codes.ACTION_REJECTED,
    telemetry_seen: set[tuple[str, str, str, str, str, str]] | None = None,
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
        payload = {"item_id": item_id, "lease_id": lease_id}
        if exc.recovery_state:
            payload["lease_recovery"] = exc.recovery_state
        raise WorkflowError(
            status=rejected_status,
            reason_code=exc.reason_code,
            waiting_on="lease",
            exit_code=5,
            message=str(exc),
            payload=payload,
        ) from exc

    if str(lease["role"]) == "verifier" and str(response["resolution"]) == "reject":
        _record_validation_command_telemetry(session, response.get("validation_commands") or [], seen=telemetry_seen)
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

    _record_validation_command_telemetry(session, response.get("validation_commands") or [], seen=telemetry_seen)

    return ledger.append_event(
        session_id=str(session["session_id"]),
        item_id=item_id,
        lease_id=lease_id,
        agent_id=str(response["agent_id"]),
        role=str(lease["role"]),
        event_type="response_accepted",
        # Carry the full applied response so session items remain a rebuildable
        # projection of the ledger (#116), not only a forward-mutated cache.
        payload={
            "resolution": response["resolution"],
            "note": response["note"],
            "response": replayable_action_response(response),
        },
    )


def replayable_action_response(response: dict[str, Any]) -> dict[str, Any]:
    """Subset of an ActionResponse needed to replay `_apply_response_to_item`."""
    snapshot: dict[str, Any] = {
        "resolution": response.get("resolution"),
        "note": response.get("note"),
        "files": response.get("files", []),
        "validation_commands": response.get("validation_commands", []),
    }
    for key in ("reply_markdown", "fix_reply", "evidence_ref"):
        if response.get(key) is not None:
            snapshot[key] = response[key]
    return snapshot


def _record_validation_command_telemetry(
    session: dict[str, Any],
    validation_cmds: Any,
    *,
    seen: set[tuple[str, str, str, str, str, str]] | None = None,
) -> None:
    if not isinstance(validation_cmds, list):
        return
    try:
        import shlex
        import time

        from gh_address_cr.core.telemetry import SessionTelemetry, command_label, is_inline_env_assignment

        telemetry = SessionTelemetry.get_instance()
    except Exception:
        return

    if seen is None:
        seen = set()

    for val_cmd in _normalize_validation_command_records(validation_cmds):
        try:
            cmd_name = val_cmd.get("command")
            if not isinstance(cmd_name, str):
                continue
            try:
                argv = shlex.split(cmd_name)
            except ValueError:
                continue
            while argv and is_inline_env_assignment(argv[0]):
                argv.pop(0)
            if not argv:
                continue
            cmd_label = command_label(argv)
            dedupe_key = (
                cmd_label,
                _validation_command_fingerprint(cmd_name),
                _dedupe_value(val_cmd.get("result")),
                _dedupe_value(val_cmd.get("duration")),
                _dedupe_value(val_cmd.get("start_time")),
                _dedupe_value(val_cmd.get("end_time")),
            )
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)

            exit_code = _validation_result_exit_code(val_cmd.get("result"))
            dur = val_cmd.get("duration")
            start = val_cmd.get("start_time")
            end = val_cmd.get("end_time")

            if start is not None and end is not None:
                start_val = float(start)
                end_val = float(end)
            elif dur is not None:
                end_val = time.time()
                start_val = end_val - float(dur)
            else:
                end_val = time.time()
                start_val = end_val

            telemetry.record(
                command=cmd_label,
                start_time=start_val,
                end_time=end_val,
                exit_code=exit_code,
            )
        except Exception:
            continue


def _dedupe_value(value: Any) -> str:
    return "" if value is None else str(value)


def _validation_command_fingerprint(command: str) -> str:
    return hashlib.sha256(command.encode("utf-8", errors="replace")).hexdigest()


def _validation_result_exit_code(result: Any) -> int:
    return 0 if validation_result_is_success(result) else 1


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
            status=protocol_codes.BATCH_ACTION_REJECTED,
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
            status=protocol_codes.BATCH_ACTION_REJECTED,
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
                status=protocol_codes.BATCH_ACTION_REJECTED,
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
            status=protocol_codes.BATCH_ACTION_REJECTED,
            item_id=item_id,
            lease_id=lease_id,
        )
    if not str(fix_reply.get("why") or "").strip():
        _raise_response_rejected(
            session,
            ledger,
            response,
            "MISSING_BATCH_ITEM_WHY",
            status=protocol_codes.BATCH_ACTION_REJECTED,
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
        return protocol_codes.STALE_REQUEST_CONTEXT
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
    lease_recovery: dict[str, Any] | None = None,
) -> None:
    _record_response_rejected(session, ledger, response, reason_code, item_id=item_id)
    is_batch = status == protocol_codes.BATCH_ACTION_REJECTED
    payload_name = "BatchActionResponse" if is_batch else "ActionResponse"
    message = _response_rejection_message(
        payload_name,
        reason_code,
        repo=str(session.get("repo") or ""),
        pr_number=str(session.get("pr_number") or ""),
    )
    payload = {"item_id": item_id, "lease_id": lease_id or response.get("lease_id")}
    if lease_recovery:
        payload["lease_recovery"] = lease_recovery
    raise WorkflowError(
        status=status,
        reason_code=reason_code,
        waiting_on="batch_action_response" if is_batch else "action_response",
        exit_code=5,
        message=message,
        payload=payload,
    )


def _batch_agent_id(batch: dict[str, Any] | None) -> str | None:
    if not isinstance(batch, dict):
        return None
    common = batch.get("common")
    common_agent_id = common.get("agent_id") if isinstance(common, dict) else None
    agent_id = batch.get("agent_id") or common_agent_id
    text = str(agent_id or "").strip()
    return text or None


def _augment_batch_recovery_error(
    exc: WorkflowError,
    session_paths: SessionPaths,
    *,
    batch_path: str | Path | None = None,
    agent_id: str | None = None,
) -> WorkflowError:
    if exc.status != protocol_codes.BATCH_ACTION_REJECTED:
        return exc
    original_message = str(exc)
    recovery = _batch_recovery_payload(session_paths, batch_path=batch_path, agent_id=agent_id)
    recovery_message = str(recovery.pop("recovery_message"))
    payload = dict(recovery)
    payload.update(exc.payload)
    exc.payload = payload

    lease_recovery = exc.payload.get("lease_recovery")
    lease_msg = None
    if lease_recovery and isinstance(lease_recovery, dict):
        outcome = lease_recovery.get("recovery_outcome")
        resume = lease_recovery.get("resume_command")
        if outcome == "renew" and resume:
            lease_msg = f"Please renew the expired lease by running `{resume}`."
        elif outcome == "reclaim" and resume:
            lease_msg = f"Please reclaim the expired lease by running `{resume}`."
        elif outcome == "refresh_state" and resume:
            lease_msg = f"Please refresh the stale session state by running `{resume}`."

    if lease_msg:
        exc.args = (f"{original_message} {lease_msg} (Once the lease is recovered, you can retry submitting your batch).",)
    else:
        exc.args = (f"{original_message} {recovery_message}",)
    return exc


def _batch_recovery_payload(
    session_paths: SessionPaths,
    *,
    batch_path: str | Path | None = None,
    agent_id: str | None = None,
) -> dict[str, Any]:
    skeleton_path = session_paths.workspace_dir / "batch-response-skeleton.json"
    target_path = Path(batch_path) if batch_path is not None else skeleton_path
    repo = session_paths.repo
    pr_number = session_paths.pr_number
    batch_next_command = command_templates.batch_next(repo, pr_number)
    resolve_batch_command = command_templates.resolve_batch(repo, pr_number, input_path=str(target_path))

    payload: dict[str, Any] = {
        "recovery_action": (
            "edit_batch_response_skeleton" if target_path.is_file() else "regenerate_batch_response_skeleton"
        ),
        "commands": {
            "batch_next": batch_next_command,
            "resolve_batch": resolve_batch_command,
        },
    }
    if agent_id:
        payload["agent_id"] = agent_id
    if target_path.is_file():
        payload["batch_response_skeleton_path"] = str(target_path)
        payload["recovery_message"] = (
            f"BatchActionResponse rejected. Edit {target_path} and submit it with `{resolve_batch_command}`. "
            "The active leases were kept for retry; no partial evidence was accepted."
        )
    else:
        payload["recovery_message"] = (
            f"BatchActionResponse rejected. Regenerate a runtime-owned skeleton with `{batch_next_command}`, "
            f"then submit it with `{resolve_batch_command}`. The active leases were kept for retry; "
            "no partial evidence was accepted."
        )
    return payload


def _lease_recovery_payload_for_response(
    session: dict[str, Any],
    response: dict[str, Any],
    lease: dict[str, Any],
    *,
    item_id: str,
    request_hash: str,
    now: datetime,
) -> dict[str, Any]:
    return calculate_lease_recovery_state(
        session,
        str(lease.get("lease_id") or response.get("lease_id") or ""),
        agent_id=str(response.get("agent_id") or lease.get("agent_id") or ""),
        role=str(lease.get("role") or ""),
        item_id=item_id,
        request_hash=request_hash,
        now=now,
    ).to_dict()


def _response_rejection_message(payload_name: str, reason_code: str, *, repo: str, pr_number: str) -> str:
    if reason_code == "MISSING_RESOLUTION":
        return (
            f"{payload_name} rejected: missing fixer response field \"resolution\". "
            "Add \"resolution\": \"fix|clarify|defer|reject\" to the ActionResponse JSON and rerun "
            f"`gh-address-cr agent submit {repo} {pr_number} --input <response.json>`."
        )
    return f"{payload_name} rejected: {reason_code}"


def _batch_acceptance_payload(response: dict[str, Any], prepared: dict[str, Any], record: Any) -> dict[str, Any]:
    return {
        "item_id": str(prepared["item_id"]),
        "lease_id": str(prepared["lease_id"]),
        "request_id": str(response["request_id"]),
        "evidence_record_id": record.record_id,
    }




def _normalize_validation_command_records(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    commands: list[dict[str, Any]] = []
    for entry in value:
        if isinstance(entry, dict):
            command = str(entry.get("command") or "").strip()
            result = str(entry.get("result") or "").strip()
            summary = str(entry.get("summary") or "").strip()
            duration = entry.get("duration")
            start_time = entry.get("start_time")
            end_time = entry.get("end_time")
        else:
            raw = str(entry or "").strip()
            command, result = _split_validation_command_record(raw)
            summary = ""
            duration = None
            start_time = None
            end_time = None
        if not command or not result:
            continue
        row: dict[str, Any] = {"command": command, "result": result}
        if summary:
            row["summary"] = summary
        if duration is not None:
            row["duration"] = duration
        if start_time is not None:
            row["start_time"] = start_time
        if end_time is not None:
            row["end_time"] = end_time
        commands.append(row)
    return commands


def _split_validation_command_record(raw: str) -> tuple[str, str]:
    command, separator, result = raw.rpartition("=")
    if not separator or not _looks_like_validation_result(result):
        return raw.strip(), "passed"
    return command.strip(), result.strip()


def _looks_like_validation_result(value: str) -> bool:
    normalized = value.strip().lower()
    if not normalized or any(char.isspace() for char in normalized):
        return False
    return normalized in {"pass", "passed", "success", "succeeded", "ok", "fail", "failed", "error", "skipped"}





def _validate_requested_severity(
    value: Any,
    *,
    status: str,
    waiting_on: str,
    payload: dict[str, Any] | None = None,
) -> str | None:
    if value in (None, ""):
        return None
    normalized = _normalize_optional_fix_reply_severity(value)
    if normalized:
        return normalized
    raise WorkflowError(
        status=status,
        reason_code="INVALID_FIX_REPLY_SEVERITY",
        waiting_on=waiting_on,
        exit_code=2,
        message="Explicit severity override must be one of P0, P1, P2, P3, or P4.",
        payload=payload or {},
    )





def _validate_severity_override_note(
    severity: str,
    item: dict[str, Any],
    note: str | None,
    *,
    status: str,
    waiting_on: str,
    payload: dict[str, Any] | None = None,
) -> None:
    first_scene_severity = first_scene_item_severity(item)
    if not first_scene_severity or first_scene_severity == severity:
        return
    if _severity_override_note(note):
        return
    raise WorkflowError(
        status=status,
        reason_code="SEVERITY_OVERRIDE_NOTE_REQUIRED",
        waiting_on=waiting_on,
        exit_code=2,
        message=(
            f"Explicit severity override {severity} conflicts with first-scene severity "
            f"{first_scene_severity}; add a severity note explaining the override."
        ),
        payload=payload or {},
    )





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

def _next_item(session: dict[str, Any], role: str, *, item_id: str | None = None) -> tuple[str, dict[str, Any] | None]:
    active_item_ids = {
        str(lease.get("item_id"))
        for lease in session.get("leases", {}).values()
        if isinstance(lease, dict) and lease.get("status") in {"active", "submitted"}
    }
    if item_id:
        item = _items(session).get(item_id)
        if item_id in active_item_ids or not isinstance(item, dict) or not _item_is_open(item):
            return item_id, None
        return item_id, item
    for item_id, item in _items(session).items():
        if item_id in active_item_ids:
            continue
        if _item_is_open(item):
            return item_id, item
    return "", None





def _item_is_open(item: dict[str, Any]) -> bool:
    if is_github_thread_item(item):
        return is_claimable_github_thread(item)
    return str(item.get("state") or item.get("status") or "open").lower() in (
        GITHUB_THREAD_CLAIMABLE_STATES - {"stale"}
    )


def _has_classification_evidence(item: dict[str, Any]) -> bool:
    evidence = item.get("classification_evidence")
    return isinstance(evidence, dict) and evidence.get("classification") in TERMINAL_RESOLUTIONS


def _required_evidence_for(item: dict[str, Any], role: str) -> list[str]:
    return _required_evidence_for_impl(item, role)


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
            return protocol_codes.MISSING_CLASSIFICATION
        if not response.get("files"):
            return "MISSING_FILES"
        if not response.get("validation_commands"):
            return "MISSING_VALIDATION_COMMANDS"
        if item.get("item_kind") == "github_thread":
            fix_reply = response.get("fix_reply")
            if not fix_reply:
                return "MISSING_FIX_REPLY"
            if not isinstance(fix_reply, dict):
                return "INVALID_FIX_REPLY"
            severity_reason = _fix_reply_severity_rejection_reason(fix_reply, item)
            if severity_reason:
                return severity_reason
            from gh_address_cr.core.publisher import validate_fix_reply_for_submit

            submit_error = validate_fix_reply_for_submit(item, response)
            if submit_error:
                return submit_error
    else:
        if "validation_commands" in response and not _normalize_validation_command_records(response.get("validation_commands")):
            return "INVALID_VALIDATION_COMMANDS"
        if not response.get("reply_markdown"):
            return "MISSING_REPLY_MARKDOWN"
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
            return None, protocol_codes.STALE_REQUEST_CONTEXT
        return expected_hash, None

    lease_request_id = _get(lease, "request_id")
    if lease_request_id:
        if response_request_id != str(lease_request_id):
            return None, protocol_codes.STALE_REQUEST_CONTEXT
        return str(_get(lease, "request_hash")), None

    lease_request_hash = _get(lease, "request_hash")
    if lease_request_hash:
        if response_request_id != str(lease_request_hash):
            return None, protocol_codes.STALE_REQUEST_CONTEXT
        return str(lease_request_hash), None

    return None, "REQUEST_CONTEXT_NOT_FOUND"


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
        if response.get("evidence_ref"):
            item["accepted_response"]["evidence_ref"] = response["evidence_ref"]
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
    if response.get("evidence_ref"):
        item["evidence_ref"] = response["evidence_ref"]


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





def _required_response_field(response: dict[str, Any], field: str, *, status: str = protocol_codes.ACTION_REJECTED) -> str:
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


# Batch action-request orchestration lives in agent_batch, which imports shared
# helpers from this module. To keep `agent_protocol.issue_batch_action_request`
# working without a load-time import cycle, delegate lazily at call time — this is
# robust regardless of which module is imported first.
def issue_batch_action_request(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from gh_address_cr.core.agent_batch import issue_batch_action_request as _impl

    return _impl(*args, **kwargs)
