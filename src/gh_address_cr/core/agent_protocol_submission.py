"""Shared ActionResponse/ActionRequest submission pipeline.

Extracted from agent_protocol.py: this is the pipeline both the single-item
entrypoints (agent_protocol.issue_action_request / submit_action_response)
and the batch entrypoints (agent_batch.py) depend on identically. It was
physically embedded in agent_protocol.py before this split, which made
agent_batch.py reach into agent_protocol's "private" underscore-prefixed
names to get at it. It is deliberately the largest extracted module — every
function here is either called directly by both callers or is inside their
shared transitive call closure; splitting it further along request/validate/
accept lines would just relocate accept_action_response_submission's
single-function-spans-everything shape into three modules instead of one.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from gh_address_cr import PROTOCOL_VERSION
from gh_address_cr.agent.roles import TERMINAL_RESOLUTIONS
from gh_address_cr.core import protocol_codes
from gh_address_cr.core import session as session_store
from gh_address_cr.core.agent_protocol_leases import (
    lease_recovery_payload_for_response,
    recover_rebound_github_thread_lease,
    release_irrecoverable_request_lease,
)
from gh_address_cr.core.agent_protocol_validation import (
    normalize_validation_command_records,
    record_validation_command_telemetry,
)
from gh_address_cr.core.errors import WorkflowError
from gh_address_cr.core.github_thread_state import is_claimable_github_thread, is_stale_github_thread_item
from gh_address_cr.core.leases import LeaseSubmissionError, accept_lease, submit_lease
from gh_address_cr.core.models import ActionRequest
from gh_address_cr.core.runtime_kernel.stack import StackContext, compare_revision_binding, unavailable_stack_context
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
    normalize_string_list as _normalize_string_list,
)
from gh_address_cr.core.work_item_handlers import WorkItemBoundaryError, boundary_summary_for_item
from gh_address_cr.evidence.ledger import EvidenceLedger
from gh_address_cr.github.client import GitHubClient


def refresh_stack_context_for_request(
    repo: str,
    pr_number: str,
    session: dict[str, Any],
    *,
    github_client: Any | None = None,
) -> StackContext:
    """Refresh the non-authoritative GitHub observation used to bind a new request."""
    was_known_stacked = session_store.has_observed_stack_membership(session)
    client = github_client or GitHubClient()
    try:
        stack_context = client.get_stack_context(repo, str(pr_number))
    except Exception:
        stack_context = unavailable_stack_context(repo, str(pr_number))
    session_store.cache_pull_request_context(session, stack_context.to_dict())
    if stack_context.availability == "invalid":
        raise WorkflowError(
            status="REQUEST_REJECTED",
            reason_code=protocol_codes.STACK_CONTEXT_INVALID,
            waiting_on="stack_refresh",
            exit_code=5,
            message="ActionRequest was not issued because current stack context is invalid.",
        )
    if stack_context.availability == "unavailable" and was_known_stacked:
        raise WorkflowError(
            status="REQUEST_REJECTED",
            reason_code=protocol_codes.STACK_CONTEXT_UNAVAILABLE,
            waiting_on="stack_refresh",
            exit_code=5,
            message="ActionRequest was not issued because known stacked-PR context could not be refreshed.",
        )
    return stack_context


def is_batch_claimable_github_thread(item: dict[str, Any]) -> bool:
    return is_claimable_github_thread(item) and not is_stale_github_thread_item(item)


def handling_boundary_summary_or_none(item: dict[str, Any], *, role: str) -> dict[str, Any] | None:
    if role != "fixer" or item.get("item_kind") != "github_thread":
        return None
    try:
        return boundary_summary_for_item(item, role=role)
    except WorkItemBoundaryError:
        return None


def _request_repository_context(lease: dict[str, Any]) -> dict[str, Any] | None:
    request_path = str(_get(lease, "request_path") or "")
    if not request_path:
        return None
    try:
        request = json.loads(Path(request_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    repository_context = request.get("repository_context") if isinstance(request, dict) else None
    return dict(repository_context) if isinstance(repository_context, dict) else None


def verify_request_revision_binding(
    repo: str,
    pr_number: str,
    session: dict[str, Any],
    prepared: dict[str, Any],
    response: dict[str, Any],
    *,
    github_client: Any | None,
    ledger: EvidenceLedger,
    rejected_status: str,
    now: datetime,
) -> dict[str, Any] | None:
    """Refresh a stacked request binding before accepting any response evidence."""
    request_context = _request_repository_context(prepared["lease"])
    binding_payload = request_context.get("revision_binding") if isinstance(request_context, dict) else None
    binding = dict(binding_payload) if isinstance(binding_payload, dict) else None
    request_stack_context = request_context.get("stack_context") if isinstance(request_context, dict) else None
    request_stack_availability = (
        str(request_stack_context.get("availability") or "") if isinstance(request_stack_context, dict) else ""
    )
    was_known_stacked = session_store.has_observed_stack_membership(session)
    reason: str | None
    if binding is not None and str(binding.get("pr_number") or "") != str(pr_number):
        reason = protocol_codes.STACK_ACTION_CONTEXT_MISMATCH
    elif binding is None and request_stack_availability == "invalid":
        reason = protocol_codes.STACK_CONTEXT_INVALID
    elif binding is None and request_stack_availability not in {"present", "unavailable"}:
        if not was_known_stacked:
            return None
        reason = protocol_codes.STALE_REQUEST_CONTEXT
    else:
        if github_client is None:
            from gh_address_cr.github.client import GitHubClient

            github_client = GitHubClient()
        try:
            current = github_client.get_stack_context(repo, str(pr_number))
        except Exception:
            current = None
        if not isinstance(current, StackContext):
            reason = protocol_codes.STACK_CONTEXT_UNAVAILABLE if binding is not None or was_known_stacked else None
        else:
            session_store.cache_pull_request_context(session, current.to_dict())
            if binding is not None:
                reason = compare_revision_binding(binding, current)
            elif request_stack_availability == "present":
                reason = protocol_codes.STALE_REQUEST_CONTEXT
            elif current.availability == "present":
                reason = protocol_codes.STALE_REQUEST_CONTEXT
            elif current.availability == "invalid":
                reason = protocol_codes.STACK_CONTEXT_INVALID
            elif current.availability == "unavailable" and was_known_stacked:
                reason = protocol_codes.STACK_CONTEXT_UNAVAILABLE
            else:
                reason = None
    if reason is None:
        return binding
    record_response_rejected(session, ledger, response, reason, item_id=str(prepared["item_id"]))
    if reason in {protocol_codes.STALE_REQUEST_CONTEXT, protocol_codes.STACK_ACTION_CONTEXT_MISMATCH}:
        release_irrecoverable_request_lease(session, prepared, now=now)
    raise WorkflowError(
        status=rejected_status,
        reason_code=reason,
        waiting_on="stack_refresh",
        exit_code=5,
        message=f"ActionResponse rejected: {reason}",
        payload={"item_id": prepared["item_id"], "lease_id": prepared["lease_id"]},
    )


def load_response_json_object(
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


def response_skeleton_for_request(request: dict[str, Any], *, agent_id: str, item: dict[str, Any]) -> dict[str, Any]:
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

    profile_validation = normalize_validation_command_records(profile.get("validation_commands"))
    if not response.get("validation_commands") and profile_validation:
        response["validation_commands"] = profile_validation

    raw_profile_fix_reply = profile.get("fix_reply")
    profile_fix_reply: dict[str, Any] = raw_profile_fix_reply if isinstance(raw_profile_fix_reply, dict) else {}
    if (
        "fix_reply" in response
        and response.get("fix_reply") is not None
        and not isinstance(response.get("fix_reply"), dict)
    ):
        return "INVALID_FIX_REPLY"
    raw_response_fix_reply = response.get("fix_reply")
    response_fix_reply: dict[str, Any] = raw_response_fix_reply if isinstance(raw_response_fix_reply, dict) else {}
    merged_fix_reply = dict(profile_fix_reply)
    merged_fix_reply.update(response_fix_reply)
    if profile.get("commit_hash") and not merged_fix_reply.get("commit_hash"):
        merged_fix_reply["commit_hash"] = profile["commit_hash"]
    if response_files and not merged_fix_reply.get("files"):
        merged_fix_reply["files"] = response_files
    if str(response.get("resolution") or "") == "fix" and merged_fix_reply:
        response["fix_reply"] = merged_fix_reply
    return None


def prepare_action_response_submission(
    session: dict[str, Any],
    ledger: EvidenceLedger,
    response: dict[str, Any],
    *,
    now: datetime,
    rejected_status: str = protocol_codes.ACTION_REJECTED,
) -> dict[str, Any]:
    lease_id = required_response_field(response, "lease_id", status=rejected_status)
    lease = session.get("leases", {}).get(lease_id)
    if not isinstance(lease, dict):
        rebound = recover_rebound_github_thread_lease(
            session,
            response,
            item_id=str(response.get("item_id") or ""),
            current_lease_id=lease_id,
        )
        if rebound is not None:
            lease_id = str(rebound["lease_id"])
            lease = rebound["lease"]
            item_id = str(rebound["item_id"])
            item = rebound["item"]
            evidence_ref_reason = _expand_evidence_ref(session, response)
            if evidence_ref_reason:
                raise_response_rejected(
                    session,
                    ledger,
                    response,
                    evidence_ref_reason,
                    status=rejected_status,
                    item_id=item_id,
                    lease_id=lease_id,
                )
            reason_code = validate_response(response, item)
            if reason_code:
                raise_response_rejected(
                    session,
                    ledger,
                    response,
                    reason_code,
                    status=rejected_status,
                    item_id=item_id,
                    lease_id=lease_id,
                )
            return {
                "lease_id": lease_id,
                "lease": lease,
                "item_id": item_id,
                "item": item,
                "expected_request_hash": str(_get(lease, "request_hash") or ""),
            }
        record_response_rejected(session, ledger, response, "LEASE_NOT_FOUND")
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
        raise_response_rejected(
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
        record_response_rejected(session, ledger, response, "ITEM_NOT_FOUND")
        raise WorkflowError(
            status=rejected_status,
            reason_code="ITEM_NOT_FOUND",
            waiting_on="work_item",
            exit_code=5,
            message=f"Work item not found: {item_id}",
        )

    evidence_ref_reason = _expand_evidence_ref(session, response)
    if evidence_ref_reason:
        raise_response_rejected(
            session,
            ledger,
            response,
            evidence_ref_reason,
            status=rejected_status,
            item_id=item_id,
            lease_id=lease_id,
        )

    reason_code = validate_response(response, item)
    if reason_code:
        raise_response_rejected(
            session,
            ledger,
            response,
            reason_code,
            status=rejected_status,
            item_id=item_id,
            lease_id=lease_id,
        )

    expected_request_hash, context_reason_code = expected_request_hash_for_response(response, lease)
    if context_reason_code:
        lease_recovery = lease_recovery_payload_for_response(
            session,
            response,
            lease,
            item_id=item_id,
            request_hash=str(response.get("request_id") or ""),
            now=now,
        )
        raise_response_rejected(
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


def accept_action_response_submission(
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
        rebound = None
        if exc.reason_code in {"STALE_LEASE", "LEASE_NOT_FOUND"}:
            rebound = recover_rebound_github_thread_lease(
                session,
                response,
                item_id=item_id,
                current_lease_id=lease_id,
            )
        if rebound is None:
            record_response_rejected(session, ledger, response, exc.reason_code, item_id=item_id)
            payload: dict[str, Any] = {"item_id": item_id, "lease_id": lease_id}
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
        lease_id = str(rebound["lease_id"])
        lease = rebound["lease"]
        prepared["lease_id"] = lease_id
        prepared["lease"] = lease
        prepared["expected_request_hash"] = str(_get(lease, "request_hash") or "")
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

    if str(lease["role"]) == "verifier" and str(response["resolution"]) == "reject":
        record_validation_command_telemetry(session, response.get("validation_commands") or [], seen=telemetry_seen)
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

    apply_response_to_item(item, response)

    record_validation_command_telemetry(session, response.get("validation_commands") or [], seen=telemetry_seen)

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
    """Subset of an ActionResponse needed to replay `apply_response_to_item`."""
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


def raise_response_rejected(
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
    record_response_rejected(session, ledger, response, reason_code, item_id=item_id)
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


def _response_rejection_message(payload_name: str, reason_code: str, *, repo: str, pr_number: str) -> str:
    if reason_code == "MISSING_RESOLUTION":
        return (
            f'{payload_name} rejected: missing fixer response field "resolution". '
            'Add "resolution": "fix|clarify|defer|reject" to the ActionResponse JSON and rerun '
            f"`gh-address-cr agent submit {repo} {pr_number} --input <response.json>`."
        )
    return f"{payload_name} rejected: {reason_code}"


def has_classification_evidence(item: dict[str, Any]) -> bool:
    evidence = item.get("classification_evidence")
    return isinstance(evidence, dict) and evidence.get("classification") in TERMINAL_RESOLUTIONS


def _validate_fix_response(response: dict[str, Any], item: dict[str, Any]) -> str | None:
    if not has_classification_evidence(item):
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
    return None


def validate_response(response: dict[str, Any], item: dict[str, Any]) -> str | None:
    for field in ("request_id", "lease_id", "agent_id", "resolution", "note"):
        if not response.get(field):
            return f"MISSING_{field.upper()}"
    if _claims_direct_github_side_effect(response):
        return "DIRECT_GITHUB_SIDE_EFFECT_FORBIDDEN"
    resolution = str(response["resolution"])
    if resolution not in TERMINAL_RESOLUTIONS:
        return "UNSUPPORTED_RESOLUTION"
    if resolution == "fix":
        return _validate_fix_response(response, item)
    else:
        if "validation_commands" in response and not normalize_validation_command_records(
            response.get("validation_commands")
        ):
            return "INVALID_VALIDATION_COMMANDS"
        if not response.get("reply_markdown"):
            return "MISSING_REPLY_MARKDOWN"
    return None


def expected_request_hash_for_response(
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


def apply_response_to_item(item: dict[str, Any], response: dict[str, Any]) -> None:
    """Fold an accepted ActionResponse onto a session item in place.

    Public item-state helper retained for deterministic session/item updates.
    """
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
        if response.get("_runtime_revision_binding"):
            item["accepted_response"]["revision_binding"] = response["_runtime_revision_binding"]
        if response.get("evidence_ref"):
            item["accepted_response"]["evidence_ref"] = response["evidence_ref"]
        return
    item["state"] = "fixed" if resolution == "fix" else resolution
    item["status"] = _local_status_for_resolution(resolution)
    item["blocking"] = False
    item["handled"] = True
    item["handled_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    item["resolution_note"] = response["note"]
    item["validation_evidence"] = response.get("validation_commands", [])
    if response.get("_runtime_revision_binding"):
        item["revision_binding"] = response["_runtime_revision_binding"]
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


def _local_status_for_resolution(resolution: str) -> str:
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


def record_response_rejected(
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


def required_response_field(
    response: dict[str, Any], field: str, *, status: str = protocol_codes.ACTION_REJECTED
) -> str:
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
