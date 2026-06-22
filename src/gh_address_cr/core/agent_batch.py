"""Batch action-request and response orchestration.

Extracted from agent_protocol.py to isolate the batch lease/skeleton workflow
and batch response submission.
Shared protocol helpers are imported from agent_protocol; agent_protocol re-exports
the public batch entrypoints at its module bottom so callers stay unchanged.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from gh_address_cr import MAX_PARALLEL_CLAIMS, PROTOCOL_VERSION
from gh_address_cr.core import command_templates, protocol_codes
from gh_address_cr.core import session as session_store

# Shared protocol helpers/constants owned by agent_protocol. Safe to import at the top:
# agent_protocol exposes batch entrypoints via lazy call-time wrappers, so it has
# no load-time dependency on agent_batch and either module may be imported first.
from gh_address_cr.core.agent_protocol import (
    _BATCH_CLASSIFICATION_NOTE,
    TERMINAL_RESOLUTIONS,
    _accept_action_response_submission,
    _active_fixer_lease_for_item,
    _handling_boundary_summary_or_none,
    _has_classification_evidence,
    _is_batch_claimable_github_thread,
    _lease_recovery_payload_for_response,
    _lease_submission_rejection_reason,
    _load_response_json_object,
    _prepare_action_response_submission,
    _raise_response_rejected,
    _required_evidence_for,
    _response_skeleton_for_request,
)
from gh_address_cr.core.errors import WorkflowError
from gh_address_cr.core.github_thread_state import is_github_thread_item, is_stale_github_thread_item
from gh_address_cr.core.ids import stable_id as _stable_id
from gh_address_cr.core.io import write_json_atomic
from gh_address_cr.core.leases import LeaseConflictError, claim_lease, expire_leases
from gh_address_cr.core.models import ActionRequest
from gh_address_cr.core.paths import SessionPaths
from gh_address_cr.core.utils import coerce_now as _coerce_now
from gh_address_cr.core.utils import get_session_items as _items
from gh_address_cr.core.utils import get_session_ledger as _ledger
from gh_address_cr.core.utils import normalize_string_list as _normalize_string_list
from gh_address_cr.core.utils import return_expired_items_to_open as _return_expired_items_to_open
from gh_address_cr.core.utils import return_item_to_claimable_state as _return_item_to_claimable_state


def _select_batch_target_items(session, *, agent_id: str, files: list[str] | None):
    """Return ``(item_id, item)`` pairs eligible for batch leasing, honoring the file filter."""
    target_items = []
    for item_id, item in _items(session).items():
        if not is_github_thread_item(item):
            continue
        if files:
            item_path = item.get("path")
            if not item_path or item_path not in files:
                continue
        existing_lease = _active_fixer_lease_for_item(session, item_id, agent_id=agent_id)
        if existing_lease is not None or _is_batch_claimable_github_thread(item):
            target_items.append((item_id, item))
    return target_items


def _ensure_batch_classification_evidence(session, item, *, item_id, agent_id, ledger) -> None:
    """Record a 'fix' classification for a batch-claimed thread if none exists yet."""
    if _has_classification_evidence(item):
        return
    item["classification_evidence"] = {
        "event_type": "classification_recorded",
        "classification": "fix",
        "note": _BATCH_CLASSIFICATION_NOTE,
        "record_id": _stable_id(
            "classification",
            {
                "session_id": session["session_id"],
                "item_id": item_id,
                "agent_id": agent_id,
                "role": "fixer",
            },
        ),
    }
    item["decision"] = "fix"
    ledger.append_event(
        session_id=str(session["session_id"]),
        item_id=item_id,
        lease_id=None,
        agent_id=agent_id,
        role="fixer",
        event_type="classification_recorded",
        payload={
            "classification": "fix",
            "note": _BATCH_CLASSIFICATION_NOTE,
        },
    )


def _build_fixer_action_request(session, repo, pr_number, *, item, lease_id, request_id) -> dict[str, Any]:
    """Build the fixer ActionRequest payload (without the response-skeleton path)."""
    request_item = dict(item)
    request_item["state"] = "claimed"
    request = {
        "schema_version": PROTOCOL_VERSION,
        "request_id": request_id,
        "session_id": session["session_id"],
        "lease_id": lease_id,
        "agent_role": "fixer",
        "item": request_item,
        "allowed_actions": sorted(item.get("allowed_actions") or TERMINAL_RESOLUTIONS),
        "required_evidence": _required_evidence_for(item, "fixer"),
        "repository_context": {"repo": repo, "pr_number": str(pr_number)},
        "forbidden_actions": ["post_github_reply", "resolve_github_thread"],
        "resume_command": f"gh-address-cr agent submit {repo} {pr_number} --input response.json",
    }
    handling_boundary = _handling_boundary_summary_or_none(item, role="fixer")
    if handling_boundary is not None:
        request["handling_boundary"] = handling_boundary
    return request


def _reconcile_existing_lease(session, repo, pr_number, *, item, item_id, existing_lease, agent_id, ledger) -> dict[str, Any]:
    """Repair an already-active fixer lease's request context and return its leased-item row."""
    lease_id = existing_lease["lease_id"]
    request_id = existing_lease.get("request_id") or ""
    request_path = existing_lease.get("request_path")
    request_hash = existing_lease.get("request_hash")
    path_ok = request_path and Path(request_path).is_file()

    _ensure_batch_classification_evidence(session, item, item_id=item_id, agent_id=agent_id, ledger=ledger)

    # Ensure active leases have valid request contexts, otherwise reconstruct them.
    if not request_id or not request_hash or not path_ok:
        request_id = request_id or _stable_id(
            "req",
            {
                "session_id": session["session_id"],
                "item_id": item_id,
                "role": "fixer",
                "agent_id": agent_id,
                "lease_id": lease_id,
            },
        )
        request = _build_fixer_action_request(session, repo, pr_number, item=item, lease_id=lease_id, request_id=request_id)
        new_request_hash = ActionRequest.from_dict(request).stable_hash()
        new_request_path = session_store.workspace_dir(repo, pr_number) / f"action-request-{request_id}.json"
        response_skeleton_path = session_store.workspace_dir(repo, pr_number) / f"action-response-skeleton-{request_id}.json"
        request["response_skeleton_path"] = str(response_skeleton_path)

        write_json_atomic(new_request_path, request)

        existing_lease["request_id"] = request_id
        existing_lease["request_hash"] = new_request_hash
        existing_lease["request_path"] = str(new_request_path)

        if not response_skeleton_path.is_file():
            response_skeleton = _response_skeleton_for_request(request, agent_id=agent_id, item=item)
            write_json_atomic(response_skeleton_path, response_skeleton)

    return {"item_id": item_id, "lease_id": lease_id, "request_id": request_id}


def _lease_new_github_thread(
    session, repo, pr_number, *, item, item_id, agent_id, ledger, current_time, newly_leased_items
) -> dict[str, Any] | None:
    """Claim a fresh fixer lease for a thread, returning its leased-item row or None to skip.

    Registers the lease in ``newly_leased_items`` immediately after ``claim_lease``
    succeeds so the caller's rollback covers it even if a later write in this
    function raises.
    """
    if _has_classification_evidence(item):
        evidence = item.get("classification_evidence")
        decision = evidence.get("classification") if isinstance(evidence, dict) else None
        if not decision:
            decision = item.get("decision")
        if decision != "fix":
            return None

    _ensure_batch_classification_evidence(session, item, item_id=item_id, agent_id=agent_id, ledger=ledger)

    lease_id = f"lease_{uuid4().hex}"
    request_id = _stable_id(
        "req",
        {
            "session_id": session["session_id"],
            "item_id": item_id,
            "role": "fixer",
            "agent_id": agent_id,
            "lease_id": lease_id,
        },
    )
    request = _build_fixer_action_request(session, repo, pr_number, item=item, lease_id=lease_id, request_id=request_id)
    request_hash = ActionRequest.from_dict(request).stable_hash()
    request_path = session_store.workspace_dir(repo, pr_number) / f"action-request-{request_id}.json"
    response_skeleton_path = session_store.workspace_dir(repo, pr_number) / f"action-response-skeleton-{request_id}.json"
    request["response_skeleton_path"] = str(response_skeleton_path)

    claim_lease(
        session,
        item,
        agent_id=agent_id,
        role="fixer",
        request_hash=request_hash,
        lease_id=lease_id,
        now=current_time,
        request_id=request_id,
        request_path=str(request_path),
        resume_token=f"resume:{request_id}",
        allow_same_agent_github_thread_file_overlap=True,
    )
    # Register for rollback before any further writes that could raise mid-claim.
    newly_leased_items.append((lease_id, item))

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
        role="fixer",
        event_type="request_issued",
        payload={
            "request_id": request_id,
            "request_path": str(request_path),
            "response_skeleton_path": str(response_skeleton_path),
        },
    )

    return {"item_id": item_id, "lease_id": lease_id, "request_id": request_id}


def _rollback_newly_leased_items(session, newly_leased_items) -> None:
    """Roll back the leases newly created in this batch on failure."""
    leases = session.setdefault("leases", {})
    for lid, itm in newly_leased_items:
        leases.pop(lid, None)
        _return_item_to_claimable_state(itm)
        if not is_stale_github_thread_item(itm):
            itm["blocking"] = True
        itm["claimed_by"] = None
        itm["claimed_at"] = None
        itm["lease_expires_at"] = None
        itm.pop("active_lease_id", None)


def _load_existing_batch_skeleton(batch_skeleton_path) -> tuple[dict, dict]:
    """Read an existing batch skeleton, returning ``(item_replies, common)`` to merge."""
    existing_items_replies: dict = {}
    existing_common: dict = {}
    if not batch_skeleton_path.is_file():
        return existing_items_replies, existing_common
    try:
        existing_data = json.loads(batch_skeleton_path.read_text(encoding="utf-8"))
        if isinstance(existing_data, dict):
            for itm in existing_data.get("items") or []:
                if isinstance(itm, dict) and itm.get("item_id"):
                    existing_items_replies[itm["item_id"]] = itm.get("fix_reply")
            if isinstance(existing_data.get("common"), dict):
                existing_common = existing_data["common"]
    except Exception as exc:
        raise WorkflowError(
            status="INVALID_BATCH_SKELETON",
            reason_code="INVALID_JSON",
            waiting_on="batch_action_response",
            exit_code=5,
            message=f"Failed to parse existing batch skeleton JSON: {exc}",
        ) from exc
    return existing_items_replies, existing_common


def _build_batch_skeleton(agent_id, leased_items, existing_items_replies, existing_common) -> dict[str, Any]:
    """Assemble the merged batch-response skeleton from the leased items and prior replies."""
    items_list = []
    for item_info in leased_items:
        item_id = item_info["item_id"]
        fix_reply = {"summary": "", "why": ""}
        if item_id in existing_items_replies and isinstance(existing_items_replies[item_id], dict):
            fix_reply.update(existing_items_replies[item_id])
        items_list.append(
            {
                "item_id": item_id,
                "request_id": item_info["request_id"],
                "lease_id": item_info["lease_id"],
                "fix_reply": fix_reply,
            }
        )
    return {
        "schema_version": PROTOCOL_VERSION,
        "agent_id": agent_id,
        "resolution": "fix",
        "common": {
            "files": existing_common.get("files") or [],
            "commit_hash": existing_common.get("commit_hash") or "",
            "validation_commands": existing_common.get("validation_commands") or [
                {
                    "command": "",
                    "result": "passed",
                }
            ],
            "fix_reply": existing_common.get("fix_reply") or {
                "summary": "",
                "why": "",
            },
        },
        "items": items_list,
    }


def _no_eligible_item_error() -> WorkflowError:
    return WorkflowError(
        status=protocol_codes.NO_ELIGIBLE_ITEM,
        reason_code=protocol_codes.NO_ELIGIBLE_ITEM,
        waiting_on="work_item",
        exit_code=4,
        message="No eligible unresolved github review thread exists.",
    )


def issue_batch_action_request(
    repo: str,
    pr_number: str,
    *,
    agent_id: str,
    files: list[str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    current_time = _coerce_now(now)
    session = session_store.load_session(repo, pr_number)
    ledger = _ledger(session)
    expired = expire_leases(session, now=current_time)
    _return_expired_items_to_open(session, expired)

    active_leases_count = sum(
        1
        for lease in session.get("leases", {}).values()
        if isinstance(lease, dict)
        and lease.get("status") == "active"
        and lease.get("role") == "fixer"
        and lease.get("agent_id") == agent_id
    )
    max_to_lease = max(0, MAX_PARALLEL_CLAIMS - active_leases_count)

    target_items = _select_batch_target_items(session, agent_id=agent_id, files=files)
    if not target_items:
        session_store.save_session(repo, pr_number, session)
        raise _no_eligible_item_error()

    leased_items: list[dict[str, Any]] = []
    newly_leased_items: list[tuple[str, dict[str, Any]]] = []
    item_id = None
    try:
        for item_id, item in target_items:
            existing_lease = _active_fixer_lease_for_item(session, item_id, agent_id=agent_id)
            if existing_lease:
                leased_items.append(
                    _reconcile_existing_lease(
                        session,
                        repo,
                        pr_number,
                        item=item,
                        item_id=item_id,
                        existing_lease=existing_lease,
                        agent_id=agent_id,
                        ledger=ledger,
                    )
                )
                continue
            if max_to_lease <= 0:
                continue
            entry = _lease_new_github_thread(
                session,
                repo,
                pr_number,
                item=item,
                item_id=item_id,
                agent_id=agent_id,
                ledger=ledger,
                current_time=current_time,
                newly_leased_items=newly_leased_items,
            )
            if entry is None:
                continue
            leased_items.append(entry)
            max_to_lease -= 1
    except Exception as exc:
        _rollback_newly_leased_items(session, newly_leased_items)
        session_store.save_session(repo, pr_number, session)
        if isinstance(exc, LeaseConflictError):
            raise WorkflowError(
                status="LEASE_REJECTED",
                reason_code=exc.reason_code,
                waiting_on="lease",
                exit_code=5,
                message=str(exc),
                payload={"item_id": item_id} if item_id is not None else {},
            ) from exc
        raise

    if not leased_items:
        session_store.save_session(repo, pr_number, session)
        raise _no_eligible_item_error()

    batch_skeleton_path = session_store.workspace_dir(repo, pr_number) / "batch-response-skeleton.json"
    existing_items_replies, existing_common = _load_existing_batch_skeleton(batch_skeleton_path)
    batch_skeleton = _build_batch_skeleton(agent_id, leased_items, existing_items_replies, existing_common)

    write_json_atomic(batch_skeleton_path, batch_skeleton)
    session_store.save_session(repo, pr_number, session)

    resolve_command = f"gh-address-cr agent resolve {repo} {pr_number} --batch --input {batch_skeleton_path}"
    return {
        "status": "BATCH_ACTION_REQUESTED",
        "repo": repo,
        "pr_number": str(pr_number),
        "response_skeleton_path": str(batch_skeleton_path),
        "lease_count": len(leased_items),
        "leased_items": leased_items,
        "commands": {
            "resolve_batch": resolve_command,
            "publish": f"gh-address-cr agent publish {repo} {pr_number}",
        },
        "next_action": f"Edit {batch_skeleton_path} and submit it with `{resolve_command}`.",
    }


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


def _validate_batch_fix_contract(
    session: dict[str, Any],
    ledger: Any,
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


def _batch_acceptance_payload(response: dict[str, Any], prepared: dict[str, Any], record: Any) -> dict[str, Any]:
    return {
        "item_id": str(prepared["item_id"]),
        "lease_id": str(prepared["lease_id"]),
        "request_id": str(response["request_id"]),
        "evidence_record_id": record.record_id,
    }
