from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from gh_address_cr import PROTOCOL_VERSION
from gh_address_cr.agent.roles import TERMINAL_RESOLUTIONS
from gh_address_cr.core import protocol_codes
from gh_address_cr.core import session as session_store
from gh_address_cr.core.agent_protocol_evidence import required_evidence_for
from gh_address_cr.core.agent_protocol_submission import (
    accept_action_response_submission,
    handling_boundary_summary_or_none,
    has_classification_evidence,
    load_response_json_object,
    prepare_action_response_submission,
    refresh_stack_context_for_request,
    response_skeleton_for_request,
    verify_request_revision_binding,
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
    calculate_lease_recovery_state,
    claim_lease,
    expire_leases,
    release_lease,
)
from gh_address_cr.core.models import ActionRequest
from gh_address_cr.core.runtime_kernel.stack import STACK_MANAGEMENT_ACTIONS, repository_context_for_stack
from gh_address_cr.core.utils import (
    coerce_now as _coerce_now,
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
    return_expired_items_to_open as _return_expired_items_to_open,
)
from gh_address_cr.core.utils import (
    return_item_to_claimable_state as _return_item_to_claimable_state,
)

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
    github_client: Any | None = None,
) -> dict[str, Any]:
    current_time = _coerce_now(now)
    session = session_store.load_session(repo, pr_number)
    ledger = _ledger(session)
    expired = expire_leases(session, now=current_time)
    _return_expired_items_to_open(session, expired)

    item_id, item = _next_item(session, role, item_id=item_id)
    if item is None:
        locked_lease = _active_lease_for_item(session, item_id) if item_id else None
        if item_id and locked_lease is not None:
            lease_id = str(locked_lease.get("lease_id") or "")
            recovery = calculate_lease_recovery_state(
                session,
                lease_id,
                agent_id=agent_id,
                role=role,
                item_id=item_id,
                request_hash=str(locked_lease.get("request_hash") or ""),
                now=current_time,
            ).to_dict()
            session_store.save_session(repo, pr_number, session)
            raise WorkflowError(
                status=protocol_codes.LEASE_LOCKED_ITEM,
                reason_code=protocol_codes.LEASE_LOCKED_ITEM,
                waiting_on="lease",
                exit_code=4,
                message=(
                    f"`{item_id}` is locked by active lease `{lease_id}` owned by "
                    f"`{recovery.get('agent_id') or 'unknown'}` ({recovery.get('lease_status') or 'unknown'}). "
                    f"Run `gh-address-cr agent leases {repo} {pr_number}` to inspect the owner and recovery state."
                ),
                payload={"item_id": item_id, "lease_recovery": recovery},
            )
        session_store.save_session(repo, pr_number, session)
        raise WorkflowError(
            status=protocol_codes.NO_ELIGIBLE_ITEM,
            reason_code=protocol_codes.NO_ELIGIBLE_ITEM,
            waiting_on="work_item",
            exit_code=4,
            message=f"No eligible work item exists for role `{role}`.",
        )

    if role in MUTATING_ROLES and not has_classification_evidence(item):
        _restore_classification_evidence_from_session(session, item_id, item)
    if role in MUTATING_ROLES and not has_classification_evidence(item):
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
    stack_context = refresh_stack_context_for_request(
        repo,
        str(pr_number),
        session,
        github_client=github_client,
    )
    request = {
        "schema_version": PROTOCOL_VERSION,
        "request_id": request_id,
        "session_id": session["session_id"],
        "lease_id": lease_id,
        "agent_role": role,
        "item": request_item,
        "allowed_actions": sorted(item.get("allowed_actions") or TERMINAL_RESOLUTIONS),
        "required_evidence": required_evidence_for(item, role),
        "repository_context": repository_context_for_stack(
            repo,
            pr_number,
            stack_context.to_dict(),
        ),
        "forbidden_actions": ["post_github_reply", "resolve_github_thread", *STACK_MANAGEMENT_ACTIONS],
        "resume_command": f"gh-address-cr agent submit {repo} {pr_number} --input response.json",
    }
    handling_boundary = handling_boundary_summary_or_none(item, role=role)
    if handling_boundary is not None:
        request["handling_boundary"] = handling_boundary
    request_hash = ActionRequest.from_dict(request).stable_hash()
    request_path = session_store.workspace_dir(repo, pr_number) / f"action-request-{request_id}.json"
    response_skeleton_path = (
        session_store.workspace_dir(repo, pr_number) / f"action-response-skeleton-{request_id}.json"
    )
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
    response_skeleton = response_skeleton_for_request(request, agent_id=agent_id, item=item)
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
    response = load_response_json_object(
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
        prepared = prepare_action_response_submission(session, ledger, response, now=now)
        binding = verify_request_revision_binding(
            repo,
            pr_number,
            session,
            prepared,
            response,
            github_client=github_client,
            ledger=ledger,
            rejected_status=protocol_codes.ACTION_REJECTED,
            now=now,
        )
        if binding is not None:
            response["_runtime_revision_binding"] = binding
        record = accept_action_response_submission(session, ledger, response, prepared, now=now)
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


def _active_lease_for_item(session: dict[str, Any], item_id: str) -> dict[str, Any] | None:
    for lease in session.get("leases", {}).values():
        if not isinstance(lease, dict):
            continue
        if str(lease.get("item_id")) != str(item_id):
            continue
        if lease.get("status") not in {"active", "submitted"}:
            continue
        return lease
    return None


def _restore_classification_evidence_from_session(session: dict[str, Any], item_id: str, item: dict[str, Any]) -> None:
    decision = str(item.get("decision") or "").strip().lower()
    if decision in TERMINAL_RESOLUTIONS:
        item["classification_evidence"] = {
            "event_type": "classification_recorded",
            "classification": decision,
            "note": str(
                item.get("classification_note") or item.get("resolution_note") or "Restored from item decision."
            ),
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
