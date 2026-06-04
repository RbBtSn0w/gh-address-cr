from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from gh_address_cr import (
    MAX_PARALLEL_CLAIMS,
    PROTOCOL_VERSION,
    SUPPORTED_PROTOCOL_VERSIONS,
    SUPPORTED_SKILL_CONTRACT_VERSIONS,
    __version__,
)
from gh_address_cr.core import session as session_store
from gh_address_cr.core.github_thread_state import (
    GITHUB_THREAD_CLAIMABLE_STATES,
    is_claimable_github_thread,
    is_github_thread_item,
    is_stale_or_outdated_github_thread,
    is_stale_github_thread_item,
    returned_claimable_state,
)
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
from gh_address_cr.core.reply_templates import (
    clarify_reply as render_clarify_reply,
    defer_reply as render_defer_reply,
    fix_reply as render_fix_reply,
)
from gh_address_cr.core.severity import (
    first_scene_item_severity,
    normalize_severity,
    review_priority_evidence,
    review_priority_for_publish,
)
from gh_address_cr.evidence.ledger import EvidenceLedger, SideEffectAttempt
from gh_address_cr.github.client import GitHubClient
from gh_address_cr.github.diagnostics import github_waiting_on
from gh_address_cr.github.errors import GitHubError


MUTATING_ROLES = {"fixer"}
TERMINAL_RESOLUTIONS = {"fix", "clarify", "defer", "reject"}
EVIDENCE_PROFILE_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
FIX_ALL_PER_THREAD_EVIDENCE_REASON = "PER_THREAD_EVIDENCE_REQUIRED"
FIX_ALL_STALE_ROUTE_REASON = "STALE_THREADS_REQUIRE_RESOLVE_STALE"
TRIVIAL_POSITIVE_MARKERS = (
    "typo",
    "spelling",
    "grammar",
    "documentation",
    "docs",
    "readme",
    "comment",
    "wording",
)
TRIVIAL_SENSITIVE_MARKERS = (
    "security",
    "unsafe",
    "auth",
    "token",
    "secret",
    "password",
    "permission",
    "api",
    "schema",
    "data loss",
    "concurrency",
    "race",
    "performance",
    "memory",
)
TRIVIAL_POSITIVE_MARKER_RE = re.compile(
    r"(?<![A-Za-z0-9])("
    + "|".join(re.escape(marker).replace(r"\ ", r"\s+") for marker in TRIVIAL_POSITIVE_MARKERS)
    + r")(?![A-Za-z0-9])"
)
TRIVIAL_SENSITIVE_MARKER_RE = re.compile(
    r"(?<![A-Za-z0-9])("
    + "|".join(re.escape(marker).replace(r"\ ", r"\s+") for marker in TRIVIAL_SENSITIVE_MARKERS)
    + r")(?![A-Za-z0-9])"
)


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
            status="NO_ELIGIBLE_ITEM",
            reason_code="NO_ELIGIBLE_ITEM",
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
            payload={"reason_code": "MISSING_CLASSIFICATION"},
        )
        session_store.save_session(repo, pr_number, session)
        raise WorkflowError(
            status="REQUEST_REJECTED",
            reason_code="MISSING_CLASSIFICATION",
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
    request_path.write_text(json.dumps(request, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    response_skeleton = _response_skeleton_for_request(request, agent_id=agent_id, item=item)
    response_skeleton_path.write_text(json.dumps(response_skeleton, indent=2, sort_keys=True) + "\n", encoding="utf-8")

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
        if publish:
            _validate_publish_shortcut_target(session, response)
        prepared = _prepare_action_response_submission(session, ledger, response)
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

    published = publish_github_thread_responses(
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
    ledger = _ledger(session)
    batch = _load_response_json_object(
        batch_path,
        status="BATCH_ACTION_REJECTED",
        missing_reason_code="BATCH_RESPONSE_FILE_NOT_FOUND",
        invalid_reason_code="INVALID_BATCH_RESPONSE_JSON",
        shape_reason_code="INVALID_BATCH_RESPONSE_SHAPE",
        shape_message="BatchActionResponse must be a JSON object.",
        payload_name="BatchActionResponse",
        waiting_on="batch_action_response",
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
                    rejected_status="BATCH_ACTION_REJECTED",
                    telemetry_seen=telemetry_seen,
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


def fast_fix_from_batch_input(
    repo: str,
    pr_number: str,
    *,
    batch_path: str | Path,
    publish: bool = False,
    github_client: Any | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    batch = _load_response_json_object(
        batch_path,
        status="FAST_FIX_ALL_REJECTED",
        missing_reason_code="BATCH_RESPONSE_FILE_NOT_FOUND",
        invalid_reason_code="INVALID_BATCH_RESPONSE_JSON",
        shape_reason_code="INVALID_BATCH_RESPONSE_SHAPE",
        shape_message="BatchActionResponse must be a JSON object.",
        payload_name="BatchActionResponse",
        waiting_on="batch_action_response",
    )
    _validate_fix_all_input_item_reply_evidence(batch)
    _validate_fix_all_input_stale_threads(repo, pr_number, batch)
    submitted = submit_batch_action_response(repo, pr_number, batch_path=batch_path, now=now)
    payload = {
        "status": "FAST_FIX_ALL_ACCEPTED",
        "repo": repo,
        "pr_number": str(pr_number),
        "submit": submitted,
        "accepted_count": int(submitted.get("accepted_count") or 0),
        "item_ids": submitted.get("item_ids") or [],
        "next_action": submitted["next_action"],
    }
    if publish:
        published = publish_github_thread_responses(
            repo,
            pr_number,
            github_client=github_client,
            agent_id="gh-address-cr-publisher",
            now=now,
        )
        payload["status"] = "FAST_FIX_ALL_COMPLETE"
        payload["publish"] = published
        payload["next_action"] = "Accepted evidence was published. Rerun final-gate when all items are handled."
    return payload


def _validate_fix_all_input_item_reply_evidence(batch: dict[str, Any]) -> None:
    items = batch.get("items")
    if not isinstance(items, list) or not items:
        return
    missing: list[int] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        fix_reply = item.get("fix_reply") if isinstance(item.get("fix_reply"), dict) else {}
        item_summary = str(item.get("summary") or fix_reply.get("summary") or "").strip()
        item_why = str(item.get("why") or fix_reply.get("why") or "").strip()
        if not item_summary or not item_why:
            missing.append(index)
    if missing:
        raise WorkflowError(
            status="FAST_FIX_ALL_REJECTED",
            reason_code="MISSING_FIX_ALL_ITEM_REPLY_EVIDENCE",
            waiting_on="batch_action_response",
            exit_code=2,
            message=(
                "agent fix-all --input requires each batch item to supply item-level summary and why. "
                "Common fix_reply summary/why cannot stand in for per-thread reviewer-answer evidence."
            ),
            payload={"missing_item_indexes": missing},
        )


def _validate_fix_all_input_stale_threads(repo: str, pr_number: str, batch: dict[str, Any]) -> None:
    items = batch.get("items")
    if not isinstance(items, list) or not items:
        return

    requested_ids = {
        str(item.get("item_id") or "").strip()
        for item in items
        if isinstance(item, dict)
    }
    requested_ids.discard("")
    if not requested_ids:
        return

    session = session_store.load_session(repo, pr_number)
    stale_or_outdated = [
        item_id
        for item_id in sorted(requested_ids)
        if is_stale_or_outdated_github_thread(_items(session).get(item_id) or {})
    ]
    if not stale_or_outdated:
        return

    next_action = (
        f"Use `gh-address-cr agent resolve-stale {repo} {pr_number} "
        "--commit <sha> --files <paths> --validation <cmd=passed> --match-files` "
        "for stale or outdated GitHub review threads."
    )
    raise WorkflowError(
        status="FAST_FIX_ALL_REJECTED",
        reason_code=FIX_ALL_STALE_ROUTE_REASON,
        waiting_on="stale_resolution_input",
        exit_code=4,
        message=next_action,
        payload={"item_ids": stale_or_outdated},
    )


def record_evidence_profile(
    repo: str,
    pr_number: str,
    *,
    name: str,
    agent_id: str,
    commit_hash: str,
    files: list[str],
    validation_commands: list[dict[str, str]],
    summary: str | None = None,
    why: str | None = None,
    test_command: str | None = None,
    test_result: str | None = None,
    severity: str | None = None,
    severity_note: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    profile_name = name.strip()
    if not profile_name or not EVIDENCE_PROFILE_NAME_RE.match(profile_name):
        raise WorkflowError(
            status="EVIDENCE_PROFILE_REJECTED",
            reason_code="INVALID_EVIDENCE_PROFILE_NAME",
            waiting_on="evidence_profile",
            exit_code=2,
            message="Evidence profile names may contain only letters, numbers, dot, underscore, and dash.",
        )
    normalized_files = _normalize_string_list(files)
    if not normalized_files:
        raise WorkflowError(
            status="EVIDENCE_PROFILE_REJECTED",
            reason_code="MISSING_EVIDENCE_PROFILE_FILES",
            waiting_on="evidence_profile",
            exit_code=2,
            message="Evidence profile requires at least one file.",
        )
    normalized_validation = _normalize_validation_command_records(validation_commands)
    if not normalized_validation:
        raise WorkflowError(
            status="EVIDENCE_PROFILE_REJECTED",
            reason_code="MISSING_EVIDENCE_PROFILE_VALIDATION",
            waiting_on="evidence_profile",
            exit_code=2,
            message="Evidence profile requires at least one validation command.",
        )
    normalized_commit = commit_hash.strip()
    if not normalized_commit:
        raise WorkflowError(
            status="EVIDENCE_PROFILE_REJECTED",
            reason_code="MISSING_EVIDENCE_PROFILE_COMMIT",
            waiting_on="evidence_profile",
            exit_code=2,
            message="Evidence profile requires a commit hash.",
        )

    session = session_store.load_session(repo, pr_number)
    timestamp = _format_timestamp(_coerce_now(now))
    fix_reply = {
        "commit_hash": normalized_commit,
        "files": normalized_files,
    }
    if summary and summary.strip():
        fix_reply["summary"] = summary.strip()
    if why and why.strip():
        fix_reply["why"] = why.strip()
    if test_command and test_command.strip():
        fix_reply["test_command"] = test_command.strip()
    if test_result and test_result.strip():
        fix_reply["test_result"] = test_result.strip()
    normalized_severity = _validate_requested_severity(
        severity,
        status="EVIDENCE_PROFILE_REJECTED",
        waiting_on="evidence_profile",
    )
    if normalized_severity:
        fix_reply["severity"] = normalized_severity
    if severity_note and severity_note.strip():
        fix_reply["severity_note"] = severity_note.strip()

    profile = {
        "name": profile_name,
        "commit_hash": normalized_commit,
        "files": normalized_files,
        "validation_commands": normalized_validation,
        "fix_reply": fix_reply,
        "created_at": timestamp,
        "created_by": agent_id,
    }
    profiles = session.setdefault("evidence_profiles", {})
    if not isinstance(profiles, dict):
        raise WorkflowError(
            status="INVALID_SESSION",
            reason_code="INVALID_EVIDENCE_PROFILES_SHAPE",
            waiting_on="session",
            exit_code=5,
            message="Session evidence_profiles must be a JSON object.",
        )
    profiles[profile_name] = profile
    record = _ledger(session).append_event(
        session_id=str(session["session_id"]),
        item_id="",
        lease_id=None,
        agent_id=agent_id,
        role="fixer",
        event_type="evidence_profile_recorded",
        payload={"name": profile_name, "commit_hash": normalized_commit, "files": normalized_files},
        timestamp=timestamp,
    )
    session_store.save_session(repo, pr_number, session)
    return {
        "status": "EVIDENCE_PROFILE_RECORDED",
        "repo": repo,
        "pr_number": str(pr_number),
        "name": profile_name,
        "evidence_record_id": record.record_id,
        "profile": _json_ready(profile),
    }


def list_evidence_profiles(repo: str, pr_number: str) -> dict[str, Any]:
    session = session_store.load_session(repo, pr_number)
    profiles = session.get("evidence_profiles") if isinstance(session.get("evidence_profiles"), dict) else {}
    return {
        "status": "EVIDENCE_PROFILES_READY",
        "repo": repo,
        "pr_number": str(pr_number),
        "profiles": [_json_ready(profile) for _, profile in sorted(profiles.items()) if isinstance(profile, dict)],
    }


def fast_fix_item(
    repo: str,
    pr_number: str,
    *,
    item_id: str,
    agent_id: str,
    commit_hash: str,
    files: list[str],
    validation_commands: list[dict[str, str]],
    summary: str,
    why: str,
    severity: str | None = None,
    severity_note: str | None = None,
    review_priority: str | None = None,
    publish: bool = False,
    github_client: Any | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    normalized_files = _normalize_string_list(files)
    normalized_validation = _normalize_validation_command_records(validation_commands)
    if not normalized_files:
        raise WorkflowError(
            status="FAST_FIX_REJECTED",
            reason_code="MISSING_FILES",
            waiting_on="fast_fix_input",
            exit_code=2,
            message="agent fix requires --files or --file.",
            payload={"item_id": item_id},
        )
    if not normalized_validation:
        raise WorkflowError(
            status="FAST_FIX_REJECTED",
            reason_code="MISSING_VALIDATION_COMMANDS",
            waiting_on="fast_fix_input",
            exit_code=2,
            message="agent fix requires --validation.",
            payload={"item_id": item_id},
        )
    if not commit_hash.strip():
        raise WorkflowError(
            status="FAST_FIX_REJECTED",
            reason_code="MISSING_FIX_REPLY_COMMIT_HASH",
            waiting_on="fast_fix_input",
            exit_code=2,
            message="agent fix requires --commit for GitHub thread replies.",
            payload={"item_id": item_id},
        )
    if not summary.strip() or not why.strip():
        raise WorkflowError(
            status="FAST_FIX_REJECTED",
            reason_code="MISSING_SUMMARY_OR_WHY",
            waiting_on="fast_fix_input",
            exit_code=2,
            message="agent fix requires --summary and --why.",
            payload={"item_id": item_id},
        )
    normalized_severity = _validate_requested_severity(
        severity,
        status="FAST_FIX_REJECTED",
        waiting_on="fast_fix_input",
        payload={"item_id": item_id},
    )
    if normalized_severity:
        session = session_store.load_session(repo, pr_number)
        item = _items(session).get(item_id)
        if isinstance(item, dict):
            _validate_severity_override_note(
                normalized_severity,
                item,
                severity_note,
                status="FAST_FIX_REJECTED",
                waiting_on="fast_fix_input",
                payload={"item_id": item_id},
            )
    requested_priority_evidence = review_priority_evidence(
        review_priority,
        source="agent_fix",
        raw_marker=review_priority,
    )
    if review_priority and requested_priority_evidence is None:
        raise WorkflowError(
            status="FAST_FIX_REJECTED",
            reason_code="INVALID_REVIEW_PRIORITY",
            waiting_on="fast_fix_input",
            exit_code=2,
            message="agent fix --review-priority must be high, medium, or low.",
            payload={"item_id": item_id},
        )

    try:
        classification = record_classification(
            repo,
            pr_number,
            item_id=item_id,
            classification="fix",
            agent_id=agent_id,
            note=why,
        )
        requested = issue_action_request(
            repo,
            pr_number,
            role="fixer",
            agent_id=agent_id,
            item_id=item_id,
            now=now,
        )
        if requested_priority_evidence:
            session = session_store.load_session(repo, pr_number)
            item = _items(session).get(item_id)
            if isinstance(item, dict):
                item["review_priority_evidence"] = requested_priority_evidence
                session_store.save_session(repo, pr_number, session)
        request = json.loads(Path(requested["request_path"]).read_text(encoding="utf-8"))
        response_path = session_store.workspace_dir(repo, pr_number) / f"fast-fix-response-{request['request_id']}.json"
        fix_reply = {
            "summary": summary,
            "why": why,
            "commit_hash": commit_hash.strip(),
            "files": normalized_files,
        }
        if normalized_severity:
            fix_reply["severity"] = normalized_severity
        if severity_note and severity_note.strip():
            fix_reply["severity_note"] = severity_note.strip()
        response = {
            "schema_version": PROTOCOL_VERSION,
            "request_id": request["request_id"],
            "lease_id": request["lease_id"],
            "agent_id": agent_id,
            "item_id": item_id,
            "resolution": "fix",
            "note": summary,
            "files": normalized_files,
            "validation_commands": normalized_validation,
            "fix_reply": fix_reply,
        }
        response_path.write_text(json.dumps(response, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        submitted = submit_action_response(
            repo,
            pr_number,
            response_path=response_path,
            now=now,
            publish=publish,
            github_client=github_client,
        )
    except WorkflowError:
        raise

    return {
        "status": "FAST_FIX_COMPLETE" if publish else "FAST_FIX_ACCEPTED",
        "repo": repo,
        "pr_number": str(pr_number),
        "item_id": item_id,
        "classification": classification,
        "request_path": requested["request_path"],
        "response_path": str(response_path),
        "submit": submitted,
        "next_action": submitted["next_action"],
    }


def trivial_fix_item(
    repo: str,
    pr_number: str,
    *,
    item_id: str,
    agent_id: str,
    commit_hash: str,
    files: list[str],
    validation_commands: list[dict[str, str]],
    summary: str,
    why: str,
    publish: bool = False,
    github_client: Any | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    session = session_store.load_session(repo, pr_number)
    item = _items(session).get(item_id)
    eligible, reason = _trivial_thread_eligibility(item)
    if not eligible:
        raise WorkflowError(
            status="TRIVIAL_FIX_REJECTED",
            reason_code="TRIVIAL_THREAD_NOT_ELIGIBLE",
            waiting_on="trivial_fix_input",
            exit_code=2,
            message=reason,
            payload={"item_id": item_id},
        )
    result = fast_fix_item(
        repo,
        pr_number,
        item_id=item_id,
        agent_id=agent_id,
        commit_hash=commit_hash,
        files=files,
        validation_commands=validation_commands,
        summary=summary,
        why=why,
        publish=publish,
        github_client=github_client,
        now=now,
    )
    result["status"] = "TRIVIAL_FIX_COMPLETE" if publish else "TRIVIAL_FIX_ACCEPTED"
    result["trivial_eligibility"] = "docs_or_typo"
    return result


def _trivial_thread_eligibility(item: dict[str, Any] | None) -> tuple[bool, str]:
    if not isinstance(item, dict):
        return False, "Trivial fast path requires an existing review-thread item."
    if item.get("item_kind") != "github_thread":
        return False, "Trivial fast path only handles GitHub review threads."
    text = " ".join(
        str(item.get(key) or "")
        for key in ("title", "body", "first_body", "path")
    ).lower()
    if TRIVIAL_SENSITIVE_MARKER_RE.search(text):
        return False, "Thread contains non-trivial or sensitive review markers."
    path = str(item.get("path") or "").lower()
    path_trivial = path.endswith(".md") or path.startswith("docs/") or path in {"readme", "readme.md"}
    text_trivial = bool(TRIVIAL_POSITIVE_MARKER_RE.search(text))
    if not (path_trivial or text_trivial):
        return False, "Thread does not look like a documentation or typo-only concern."
    return True, "Thread is eligible for documentation or typo fast path."


def fast_fix_matching_threads(
    repo: str,
    pr_number: str,
    *,
    agent_id: str,
    commit_hash: str,
    files: list[str],
    validation_commands: list[dict[str, str]],
    include_stale: bool = False,
    stale_only: bool = False,
    severity: str | None = None,
    severity_note: str | None = None,
    homogeneous_reason: str | None = None,
    concern_label: str | None = None,
    publish: bool = False,
    github_client: Any | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    current_time = _coerce_now(now)
    status_prefix = "STALE_RESOLUTION" if stale_only else "FAST_FIX_ALL"
    rejected_status = f"{status_prefix}_REJECTED"
    input_waiting_on = "stale_resolution_input" if stale_only else "fast_fix_input"
    command_name = "agent resolve-stale" if stale_only else "agent fix-all"
    normalized_files = _normalize_string_list(files)
    normalized_validation = _normalize_validation_command_records(validation_commands)
    if not normalized_files:
        raise WorkflowError(
            status=rejected_status,
            reason_code="MISSING_FILES",
            waiting_on=input_waiting_on,
            exit_code=2,
            message=f"{command_name} requires --files or a commit with changed files.",
        )
    if not normalized_validation:
        raise WorkflowError(
            status=rejected_status,
            reason_code="MISSING_VALIDATION_COMMANDS",
            waiting_on=input_waiting_on,
            exit_code=2,
            message=f"{command_name} requires --validation.",
        )
    if not commit_hash.strip():
        raise WorkflowError(
            status=rejected_status,
            reason_code="MISSING_FIX_REPLY_COMMIT_HASH",
            waiting_on=input_waiting_on,
            exit_code=2,
            message=f"{command_name} requires --commit.",
        )
    normalized_severity = _validate_requested_severity(
        severity,
        status=rejected_status,
        waiting_on=input_waiting_on,
    )
    normalized_homogeneous_reason = str(homogeneous_reason or "").strip()
    normalized_concern_label = str(concern_label or "").strip()

    session = session_store.load_session(repo, pr_number)
    github_items = [
        item
        for item in _items(session).values()
        if item.get("item_kind") == "github_thread"
    ]
    if not github_items:
        raise WorkflowError(
            status=f"{status_prefix}_NO_MATCH",
            reason_code="SESSION_THREADS_REQUIRED",
            waiting_on="github_threads",
            exit_code=4,
            message=f"Run `gh-address-cr address {repo} {pr_number} --lean` first to sync GitHub review threads.",
        )

    normalized_file_set = {path.strip() for path in normalized_files if path.strip()}
    matches = [
        item
        for item in github_items
        if _matches_fast_fix_thread(item, normalized_file_set, include_stale=include_stale, stale_only=stale_only)
    ]
    if not matches:
        raise WorkflowError(
            status=f"{status_prefix}_NO_MATCH",
            reason_code="NO_MATCHING_GITHUB_THREADS",
            waiting_on="github_threads",
            exit_code=4,
            message="No matching claimable GitHub review threads were found for the supplied files.",
            payload={"files": sorted(normalized_file_set)},
        )
    if not stale_only and any(is_stale_or_outdated_github_thread(item) for item in matches):
        next_action = (
            f"Use `gh-address-cr agent resolve-stale {repo} {pr_number} "
            "--commit <sha> --files <paths> --validation <cmd=passed> --match-files` "
            "for stale or outdated GitHub review threads."
        )
        raise WorkflowError(
            status=rejected_status,
            reason_code=FIX_ALL_STALE_ROUTE_REASON,
            waiting_on="stale_resolution_input",
            exit_code=4,
            message=next_action,
            payload={"matched_count": len(matches), "files": sorted(normalized_file_set)},
        )
    if not stale_only and not normalized_homogeneous_reason:
        next_action = (
            f"Use `gh-address-cr agent submit-batch {repo} {pr_number} --input batch-response.json` "
            "with per-thread summary/why entries, or rerun fix-all with `--homogeneous-reason <why>` "
            "only for a homogeneous repeated concern."
        )
        raise WorkflowError(
            status=rejected_status,
            reason_code=FIX_ALL_PER_THREAD_EVIDENCE_REASON,
            waiting_on="batch_action_response",
            exit_code=4,
            message=next_action,
            payload={"matched_count": len(matches), "files": sorted(normalized_file_set)},
        )
    if not stale_only and normalized_homogeneous_reason and not _has_homogeneous_thread_bodies(matches):
        next_action = (
            f"Use `gh-address-cr agent submit-batch {repo} {pr_number} --input batch-response.json` "
            "with per-thread summary/why entries. The matched threads have missing or distinct thread bodies, "
            "so fix-all cannot prove a homogeneous repeated concern."
        )
        raise WorkflowError(
            status=rejected_status,
            reason_code=FIX_ALL_PER_THREAD_EVIDENCE_REASON,
            waiting_on="batch_action_response",
            exit_code=4,
            message=next_action,
            payload={"matched_count": len(matches), "files": sorted(normalized_file_set)},
        )

    accepted_count = 0
    batches: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    item_ids: list[str] = []
    for batch_items in _chunks(matches, MAX_PARALLEL_CLAIMS):
        batch_responses: list[dict[str, Any]] = []
        for item in batch_items:
            item_id = str(item["item_id"])
            why = normalized_homogeneous_reason or _fast_fix_why(
                commit_hash,
                normalized_files,
                stale=bool(is_stale_github_thread_item(item)),
            )
            summary = (
                f"Addressed repeated review concern for {item_id}."
                if normalized_homogeneous_reason
                else f"Fixed {item_id} in {commit_hash.strip()}."
            )
            try:
                if normalized_severity:
                    _validate_severity_override_note(
                        normalized_severity,
                        item,
                        severity_note,
                        status=rejected_status,
                        waiting_on=input_waiting_on,
                        payload={"item_id": item_id},
                    )
                record_classification(
                    repo,
                    pr_number,
                    item_id=item_id,
                    classification="fix",
                    agent_id=agent_id,
                    note=why,
                )
                requested = issue_action_request(
                    repo,
                    pr_number,
                    role="fixer",
                    agent_id=agent_id,
                    item_id=item_id,
                    now=current_time,
                )
            except WorkflowError as exc:
                failed.append(_fast_fix_failed_row(item_id, exc))
                continue
            batch_responses.append(
                {
                    "item_id": item_id,
                    "request_id": requested["resume_token"].removeprefix("resume:"),
                    "lease_id": requested["lease_id"],
                    "summary": summary,
                    "why": why,
                }
            )
        if not batch_responses:
            continue
        batch_path = session_store.workspace_dir(repo, pr_number) / f"fast-fix-all-batch-{uuid4().hex}.json"
        common_fix_reply = {
            "commit_hash": commit_hash.strip(),
            "summary": (
                f"Addressed homogeneous repeated review concern: {normalized_concern_label}."
                if normalized_concern_label
                else f"Fixed related GitHub review threads in {commit_hash.strip()}."
            ),
            "files": normalized_files,
        }
        if normalized_severity:
            common_fix_reply["severity"] = normalized_severity
        if severity_note and severity_note.strip():
            common_fix_reply["severity_note"] = severity_note.strip()
        batch_path.write_text(
            json.dumps(
                {
                    "schema_version": PROTOCOL_VERSION,
                    "agent_id": agent_id,
                    "resolution": "fix",
                    "common": {
                        "files": normalized_files,
                        "validation_commands": normalized_validation,
                        "fix_reply": common_fix_reply,
                    },
                    "items": batch_responses,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        batch_result = submit_batch_action_response(repo, pr_number, batch_path=batch_path, now=current_time)
        accepted_count += int(batch_result.get("accepted_count") or 0)
        item_ids.extend(str(item_id) for item_id in batch_result.get("item_ids") or [])
        batches.append(batch_result)

    publish_result = None
    if publish and accepted_count:
        publish_result = publish_github_thread_responses(
            repo,
            pr_number,
            github_client=github_client,
            agent_id="gh-address-cr-publisher",
            now=current_time,
        )

    status = "STALE_RESOLUTION_ACCEPTED" if stale_only else "FAST_FIX_ALL_ACCEPTED"
    if publish:
        status = "STALE_RESOLUTION_COMPLETE" if stale_only else "FAST_FIX_ALL_COMPLETE"
    payload = {
        "repo": repo,
        "pr_number": str(pr_number),
        "commit_hash": commit_hash.strip(),
        "files": normalized_files,
        "matched_count": len(matches),
        "accepted_count": accepted_count,
        "failed_count": len(failed),
        "item_ids": item_ids,
        "failed": failed,
        "batches": batches,
        "publish": publish_result,
        "next_action": (
            "Accepted evidence was published. Rerun final-gate when all items are handled."
            if publish
            else f"Run `gh-address-cr agent publish {repo} {pr_number}` to publish accepted evidence."
        ),
    }
    if failed:
        partial_status = f"{status_prefix}_PARTIAL" if accepted_count else f"{status_prefix}_NO_ACCEPTED"
        next_action = (
            f"Accepted {accepted_count} item(s); inspect failed rows, resolve lease/input blockers, then rerun."
            if accepted_count
            else "No matching items were accepted. Inspect failed rows, resolve lease/input blockers, then rerun."
        )
        payload["next_action"] = next_action
        raise WorkflowError(
            status=partial_status,
            reason_code=partial_status,
            waiting_on="lease" if any(row.get("waiting_on") == "lease" for row in failed) else "work_item",
            exit_code=5,
            message=next_action,
            payload=payload,
        )
    payload["status"] = status
    return payload


def _matches_fast_fix_thread(
    item: dict[str, Any],
    files: set[str],
    *,
    include_stale: bool,
    stale_only: bool,
) -> bool:
    if not item.get("item_id") or not item.get("path"):
        return False
    item_path = str(item.get("path"))
    if item_path not in files:
        return False
    stale = is_stale_github_thread_item(item)
    if stale_only:
        return stale and is_claimable_github_thread(item)
    if stale and not include_stale:
        return False
    return is_claimable_github_thread(item)


def _has_homogeneous_thread_bodies(items: list[dict[str, Any]]) -> bool:
    bodies = [_normalized_thread_body(item) for item in items]
    return all(bodies) and len(set(bodies)) == 1


def _normalized_thread_body(item: dict[str, Any]) -> str:
    first_body = str(item.get("first_body") or "").strip()
    if first_body:
        source_text = first_body
    elif str(item.get("comment_source") or "").strip().casefold() == "latest":
        # latest-only rows may contain reviewer follow-up text in `body`; do not treat that as origin evidence.
        source_text = ""
    else:
        source_text = str(item.get("body") or "")
    return " ".join(source_text.split()).casefold()


def _fast_fix_failed_row(item_id: str, exc: WorkflowError) -> dict[str, Any]:
    return {
        "item_id": item_id,
        "status": exc.status,
        "reason_code": exc.reason_code,
        "waiting_on": exc.waiting_on,
        "next_action": str(exc),
        "exit_code": exc.exit_code,
    }


def _fast_fix_why(commit_hash: str, files: list[str], *, stale: bool) -> str:
    file_list = ", ".join(files)
    if stale:
        return f"Commit {commit_hash.strip()} updates {file_list}, matching this stale review thread."
    return f"Commit {commit_hash.strip()} updates {file_list}, matching this review thread."


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
                "commit_hash": "",
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
            status="ACTION_REJECTED",
            reason_code="PUBLISH_TARGET_NOT_FOUND",
            waiting_on="action_response",
            exit_code=5,
            message="--publish requires an ActionResponse for an existing GitHub review-thread item.",
            payload={"lease_id": lease_id or None},
        )
    if item.get("item_kind") != "github_thread":
        raise WorkflowError(
            status="ACTION_REJECTED",
            reason_code="PUBLISH_UNSUPPORTED_RESPONSE",
            waiting_on="action_response",
            exit_code=5,
            message="--publish is only supported for GitHub review-thread responses.",
            payload={"item_id": item_id, "lease_id": lease_id},
        )
    resolution = str(response.get("resolution") or "")
    if resolution and resolution != "fix":
        raise WorkflowError(
            status="ACTION_REJECTED",
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
        raise WorkflowError(
            status=rejected_status,
            reason_code=exc.reason_code,
            waiting_on="lease",
            exit_code=5,
            message=str(exc),
            payload={"item_id": item_id, "lease_id": lease_id},
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
        payload={"resolution": response["resolution"], "note": response["note"]},
    )


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
    normalized = str(result or "passed").strip().lower()
    success_prefixes = ("passed", "pass", "success", "succeeded", "ok")
    return 0 if normalized.startswith(success_prefixes) else 1


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
    is_batch = status == "BATCH_ACTION_REJECTED"
    payload_name = "BatchActionResponse" if is_batch else "ActionResponse"
    message = _response_rejection_message(
        payload_name,
        reason_code,
        repo=str(session.get("repo") or ""),
        pr_number=str(session.get("pr_number") or ""),
    )
    raise WorkflowError(
        status=status,
        reason_code=reason_code,
        waiting_on="batch_action_response" if is_batch else "action_response",
        exit_code=5,
        message=message,
        payload={"item_id": item_id, "lease_id": lease_id or response.get("lease_id")},
    )


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
    _configure_publish_telemetry(repo, pr_number)
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
    publisher_login = _publisher_login(client, fallback=agent_id)

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
        item["reply_evidence"] = {"reply_url": reply_url, "author_login": publisher_login}

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


def _configure_publish_telemetry(repo: str, pr_number: str) -> None:
    try:
        from gh_address_cr.core.telemetry import SessionTelemetry

        SessionTelemetry.get_instance().configure_context(repo, pr_number)
    except Exception:
        return


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


def _publisher_login(client: Any, *, fallback: str) -> str:
    viewer_login = getattr(client, "viewer_login", None)
    if callable(viewer_login):
        try:
            login = str(viewer_login() or "").strip()
        except GitHubError:
            login = ""
        if login:
            return login
    return fallback


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

    if resolution != "fix":
        if not isinstance(reply_markdown, str) or not reply_markdown.strip():
            return None, "MISSING_PUBLISH_REPLY"
        if resolution == "clarify":
            return render_clarify_reply([reply_markdown.strip()]), None
        if resolution == "defer":
            return render_defer_reply([reply_markdown.strip()]), None
        return reply_markdown, None
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
    severity, severity_error = _fix_reply_severity_for_publish(fix_reply, item)
    if severity_error:
        return None, severity_error
    why = str(fix_reply.get("why") or "Addressed the CR with targeted changes and validation evidence.").strip()
    summary = str(fix_reply.get("summary") or "").strip() or None
    review_priority, review_priority_note = review_priority_for_publish(item)
    try:
        return render_fix_reply(
            severity,
            [commit_hash, ",".join(files), test_command, test_result, why],
            summary=summary,
            review_priority=review_priority,
            review_priority_note=review_priority_note,
        ), None
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


def _normalize_optional_fix_reply_severity(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return normalize_severity(value)


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


def _severity_override_note(fix_reply_or_note: dict[str, Any] | str | None) -> str:
    if isinstance(fix_reply_or_note, dict):
        return str(
            fix_reply_or_note.get("severity_note")
            or fix_reply_or_note.get("severity_override_note")
            or ""
        ).strip()
    return str(fix_reply_or_note or "").strip()


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


def _fix_reply_explicit_severity(fix_reply: dict[str, Any]) -> tuple[str | None, str | None]:
    if "severity" not in fix_reply or fix_reply.get("severity") in (None, ""):
        return None, None
    severity = _normalize_optional_fix_reply_severity(fix_reply.get("severity"))
    if not severity:
        return None, "INVALID_FIX_REPLY_SEVERITY"
    return severity, None


def _fix_reply_severity_rejection_reason(fix_reply: dict[str, Any], item: dict[str, Any]) -> str | None:
    explicit_severity, error = _fix_reply_explicit_severity(fix_reply)
    if error:
        return error
    if not explicit_severity:
        return None
    first_scene_severity = first_scene_item_severity(item)
    if (
        first_scene_severity
        and first_scene_severity != explicit_severity
        and not _severity_override_note(fix_reply)
    ):
        return "SEVERITY_OVERRIDE_NOTE_REQUIRED"
    return None


def _fix_reply_severity_for_publish(fix_reply: dict[str, Any], item: dict[str, Any]) -> tuple[str | None, str | None]:
    explicit_severity, error = _fix_reply_explicit_severity(fix_reply)
    if error:
        return None, error
    if explicit_severity:
        conflict = _fix_reply_severity_rejection_reason(fix_reply, item)
        if conflict:
            return None, conflict
        return explicit_severity, None
    return first_scene_item_severity(item), None


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
    payload = {"item_id": item_id, "retryable": exc.retryable, "repo": repo, "pr_number": str(pr_number)}
    if exc.diagnostics:
        payload["diagnostics"] = exc.diagnostics
    return WorkflowError(
        status="PUBLISH_BLOCKED",
        reason_code=exc.reason_code,
        waiting_on=github_waiting_on(exc.diagnostics),
        exit_code=5,
        message=f"GitHub publish failed for {item_id}: {exc}",
        payload=payload,
    )


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
    if is_github_thread_item(item):
        return is_claimable_github_thread(item)
    return str(item.get("state") or item.get("status") or "open").lower() in (
        GITHUB_THREAD_CLAIMABLE_STATES - {"stale"}
    )


def _has_classification_evidence(item: dict[str, Any]) -> bool:
    evidence = item.get("classification_evidence")
    return isinstance(evidence, dict) and evidence.get("classification") in TERMINAL_RESOLUTIONS


def _required_evidence_for(item: dict[str, Any], role: str) -> list[str]:
    evidence = item.get("classification_evidence")
    classification = evidence.get("classification") if isinstance(evidence, dict) else None
    if classification in TERMINAL_RESOLUTIONS and classification != "fix":
        return ["note", "reply_markdown"]
    if role == "fixer":
        fields = ["note", "files", "validation_commands"]
        if item.get("item_kind") == "github_thread":
            fields.append("fix_reply")
        return fields
    return ["note", "reply_markdown"]


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
        if item.get("item_kind") == "github_thread":
            fix_reply = response.get("fix_reply")
            if not fix_reply:
                return "MISSING_FIX_REPLY"
            if not isinstance(fix_reply, dict):
                return "INVALID_FIX_REPLY"
            severity_reason = _fix_reply_severity_rejection_reason(fix_reply, item)
            if severity_reason:
                return severity_reason
            _, publish_error = _publish_reply_body(item, response)
            if publish_error:
                return publish_error
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


def _return_expired_items_to_open(session: dict[str, Any], expired: list[Any]) -> None:
    items = _items(session)
    for lease in expired:
        item = items.get(str(_get(lease, "item_id")))
        if isinstance(item, dict) and str(item.get("state")).lower() == "claimed":
            _return_item_to_claimable_state(item)
            item.pop("active_lease_id", None)


def _return_item_to_claimable_state(item: dict[str, Any]) -> None:
    state, status = returned_claimable_state(item)
    item["state"] = state
    item["status"] = status


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
