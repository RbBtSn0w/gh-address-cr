from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from gh_address_cr import (
    PROTOCOL_VERSION,
    SUPPORTED_PROTOCOL_VERSIONS,
    SUPPORTED_SKILL_CONTRACT_VERSIONS,
    __version__,
)
from gh_address_cr.core import agent_batch, agent_protocol, protocol_codes
from gh_address_cr.core import session as session_store
from gh_address_cr.core.agent_protocol import (
    _load_response_json_object,
    _normalize_validation_command_records,
    _validate_requested_severity,
    _validate_severity_override_note,
)
from gh_address_cr.core.errors import WorkflowError
from gh_address_cr.core.github_thread_state import (
    GITHUB_THREAD_TERMINAL_STATES,
    is_stale_or_outdated_github_thread,
    normalized_thread_state,
)
from gh_address_cr.core.io import write_json_atomic
from gh_address_cr.core.severity import (
    review_priority_evidence,
)
from gh_address_cr.core.utils import (
    coerce_now as _coerce_now,
)
from gh_address_cr.core.utils import (
    format_timestamp as _format_timestamp,
)
from gh_address_cr.core.utils import (
    get_session_items as _items,
)
from gh_address_cr.core.utils import (
    get_session_ledger as _ledger,
)
from gh_address_cr.core.utils import (
    json_ready as _json_ready,
)
from gh_address_cr.core.utils import (
    normalize_string_list as _normalize_string_list,
)
from gh_address_cr.core.validation_evidence import validation_evidence_has_success
from gh_address_cr.core.workflow_matching import FIX_ALL_STALE_ROUTE_REASON

EVIDENCE_PROFILE_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
FIX_ALL_PER_THREAD_EVIDENCE_REASON = "PER_THREAD_EVIDENCE_REQUIRED"
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
        status=protocol_codes.FAST_FIX_ALL_REJECTED,
        missing_reason_code="BATCH_RESPONSE_FILE_NOT_FOUND",
        invalid_reason_code="INVALID_BATCH_RESPONSE_JSON",
        shape_reason_code="INVALID_BATCH_RESPONSE_SHAPE",
        shape_message="BatchActionResponse must be a JSON object.",
        payload_name="BatchActionResponse",
        waiting_on="batch_action_response",
    )
    _validate_fix_all_input_item_reply_evidence(batch)
    _validate_fix_all_input_stale_threads(repo, pr_number, batch)
    submitted = agent_batch.submit_batch_action_response(repo, pr_number, batch_path=batch_path, now=now)
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
        from gh_address_cr.core import publisher

        published = publisher.publish_github_thread_responses(
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
        raw_fix_reply = item.get("fix_reply")
        fix_reply: dict[str, Any] = raw_fix_reply if isinstance(raw_fix_reply, dict) else {}
        item_summary = str(item.get("summary") or fix_reply.get("summary") or "").strip()
        item_why = str(item.get("why") or fix_reply.get("why") or "").strip()
        if not item_summary or not item_why:
            missing.append(index)
    if missing:
        raise WorkflowError(
            status=protocol_codes.FAST_FIX_ALL_REJECTED,
            reason_code="MISSING_FIX_ALL_ITEM_REPLY_EVIDENCE",
            waiting_on="batch_action_response",
            exit_code=2,
            message=(
                "agent resolve --input <BatchActionResponse> requires each batch item to supply "
                "item-level summary and why. "
                "Common fix_reply summary/why cannot stand in for per-thread reviewer-answer evidence."
            ),
            payload={"missing_item_indexes": missing},
        )


def _validate_fix_all_input_stale_threads(repo: str, pr_number: str, batch: dict[str, Any]) -> None:
    items = batch.get("items")
    if not isinstance(items, list) or not items:
        return

    requested_ids = {str(item.get("item_id") or "").strip() for item in items if isinstance(item, dict)}
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
        f"Use `gh-address-cr agent resolve {repo} {pr_number} "
        "--commit <sha> --files <paths> --validation <cmd=passed> --stale` "
        "for stale or outdated GitHub review threads."
    )
    raise WorkflowError(
        status=protocol_codes.FAST_FIX_ALL_REJECTED,
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
    validation_commands: list[dict[str, Any]],
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
            status=protocol_codes.EVIDENCE_PROFILE_REJECTED,
            reason_code="INVALID_EVIDENCE_PROFILE_NAME",
            waiting_on="evidence_profile",
            exit_code=2,
            message="Evidence profile names may contain only letters, numbers, dot, underscore, and dash.",
        )
    normalized_files = _normalize_string_list(files)
    if not normalized_files:
        raise WorkflowError(
            status=protocol_codes.EVIDENCE_PROFILE_REJECTED,
            reason_code="MISSING_EVIDENCE_PROFILE_FILES",
            waiting_on="evidence_profile",
            exit_code=2,
            message="Evidence profile requires at least one file.",
        )
    normalized_validation = _normalize_validation_command_records(validation_commands)
    if not normalized_validation:
        raise WorkflowError(
            status=protocol_codes.EVIDENCE_PROFILE_REJECTED,
            reason_code="MISSING_EVIDENCE_PROFILE_VALIDATION",
            waiting_on="evidence_profile",
            exit_code=2,
            message="Evidence profile requires at least one validation command.",
        )
    normalized_commit = commit_hash.strip()
    if not normalized_commit:
        raise WorkflowError(
            status=protocol_codes.EVIDENCE_PROFILE_REJECTED,
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
        status=protocol_codes.EVIDENCE_PROFILE_REJECTED,
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
    raw_profiles = session.get("evidence_profiles")
    profiles: dict[str, Any] = raw_profiles if isinstance(raw_profiles, dict) else {}
    return {
        "status": "EVIDENCE_PROFILES_READY",
        "repo": repo,
        "pr_number": str(pr_number),
        "profiles": [_json_ready(profile) for _, profile in sorted(profiles.items()) if isinstance(profile, dict)],
    }


def record_reply_evidence(
    repo: str,
    pr_number: str,
    *,
    reply_url: str,
    author_login: str,
    thread_id: str | None = None,
    item_id: str | None = None,
    agent_id: str = "agent",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Ingest reply evidence for a thread resolved out-of-band (issue #142).

    A reply posted directly through ``gh`` leaves no ledger footprint, so
    ``final-gate`` reports ``FINAL_GATE_MISSING_REPLY_EVIDENCE`` even though the
    thread is resolved on GitHub. This records the same ``reply_posted`` ledger
    event and session mutation the publisher would have written, so the gate can
    reconcile it. ``author_login`` must match the login that runs ``final-gate``
    (``viewer_login()``) for the evidence to count.
    """
    normalized_reply = (reply_url or "").strip()
    if not normalized_reply:
        raise WorkflowError(
            status="REPLY_EVIDENCE_REJECTED",
            reason_code="MISSING_REPLY_URL",
            waiting_on="reply_evidence",
            exit_code=2,
            message="agent evidence add --reply-url requires a non-empty URL.",
        )
    normalized_login = (author_login or "").strip()
    if not normalized_login:
        raise WorkflowError(
            status="REPLY_EVIDENCE_REJECTED",
            reason_code="MISSING_AUTHOR_LOGIN",
            waiting_on="reply_evidence",
            exit_code=2,
            message="agent evidence add --reply-url requires --author-login (or an authenticated gh login).",
        )

    resolved_item_id = (item_id or "").strip()
    thread_ref = (thread_id or "").strip()
    if not resolved_item_id:
        if not thread_ref:
            raise WorkflowError(
                status="REPLY_EVIDENCE_REJECTED",
                reason_code="MISSING_THREAD_REFERENCE",
                waiting_on="reply_evidence",
                exit_code=2,
                message="agent evidence add --reply-url requires --thread-id or --item-id.",
            )
        resolved_item_id = thread_ref if thread_ref.startswith("github-thread:") else f"github-thread:{thread_ref}"

    session = session_store.load_session(repo, pr_number)
    item = _items(session).get(resolved_item_id)
    if not isinstance(item, dict) or item.get("item_kind") != "github_thread":
        raise WorkflowError(
            status="REPLY_EVIDENCE_REJECTED",
            reason_code="UNKNOWN_GITHUB_THREAD",
            waiting_on="reply_evidence",
            exit_code=4,
            message=f"No github_thread item `{resolved_item_id}` exists in the session.",
        )

    timestamp = _format_timestamp(_coerce_now(now))
    payload_thread_id = str(item.get("thread_id") or thread_ref or resolved_item_id.removeprefix("github-thread:"))
    idempotency_key = f"reply_evidence:{resolved_item_id}:{normalized_reply}"
    record = _ledger(session).append_event(
        session_id=str(session["session_id"]),
        item_id=resolved_item_id,
        lease_id=None,
        agent_id=agent_id,
        role="fixer",
        event_type="reply_posted",
        payload={
            "thread_id": payload_thread_id,
            "reply_url": normalized_reply,
            "author_login": normalized_login,
            "idempotency_key": idempotency_key,
            "source": "manual_reconcile",
        },
        timestamp=timestamp,
    )
    item["reply_posted"] = True
    item["reply_url"] = normalized_reply
    item["reply_evidence"] = {"reply_url": normalized_reply, "author_login": normalized_login}
    session_store.save_session(repo, pr_number, session)
    return {
        "status": "REPLY_EVIDENCE_RECORDED",
        "repo": repo,
        "pr_number": str(pr_number),
        "item_id": resolved_item_id,
        "thread_id": payload_thread_id,
        "reply_url": normalized_reply,
        "author_login": normalized_login,
        "evidence_record_id": record.record_id,
    }


def record_validation_evidence(
    repo: str,
    pr_number: str,
    *,
    item_id: str | None = None,
    thread_id: str | None = None,
    commit_hash: str,
    files: list[str],
    validation_commands: list[dict[str, Any]],
    summary: str | None = None,
    why: str | None = None,
    agent_id: str = "agent",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Ingest validation evidence for a thread resolved out-of-band.

    Symmetric to :func:`record_reply_evidence`. When a GitHub review thread is
    resolved outside the runtime (manual ``Resolve``, reviewer dismiss, or
    auto-outdated) after being classified ``fix``, the session has no
    item-level validation evidence, so ``final-gate``'s logic-validation keeps
    blocking with ``missing_required_evidence`` and no claim path exists to
    attach it (``agent resolve --stale`` returns ``NO_MATCHING_GITHUB_THREADS``
    once the thread is resolved). This records the same ``validation_evidence``
    the fix path would have written so the gate can reconcile it.

    Guarded so it cannot become a backdoor around normal resolution:
    - only ``github_thread`` items already in a terminal state are eligible;
    - ``--commit``/``--files``/``--validation`` are all required; and
    - the validation result must be success-like (a failing verdict like
      ``cmd=failed`` is rejected, matching #117).
    """
    normalized_commit = (commit_hash or "").strip()
    if not normalized_commit:
        raise WorkflowError(
            status="VALIDATION_EVIDENCE_REJECTED",
            reason_code="MISSING_VALIDATION_COMMIT",
            waiting_on="validation_evidence",
            exit_code=2,
            message="agent evidence add --item-id requires --commit.",
        )
    normalized_files = _normalize_string_list(files)
    if not normalized_files:
        raise WorkflowError(
            status="VALIDATION_EVIDENCE_REJECTED",
            reason_code="MISSING_VALIDATION_FILES",
            waiting_on="validation_evidence",
            exit_code=2,
            message="agent evidence add --item-id requires --files.",
        )
    normalized_validation = _normalize_validation_command_records(validation_commands)
    if not normalized_validation:
        raise WorkflowError(
            status="VALIDATION_EVIDENCE_REJECTED",
            reason_code="MISSING_VALIDATION_COMMANDS",
            waiting_on="validation_evidence",
            exit_code=2,
            message="agent evidence add --item-id requires --validation.",
        )
    if not validation_evidence_has_success(normalized_validation):
        raise WorkflowError(
            status="VALIDATION_EVIDENCE_REJECTED",
            reason_code="VALIDATION_EVIDENCE_NOT_SUCCESS",
            waiting_on="validation_evidence",
            exit_code=2,
            message="agent evidence add --item-id requires a success-like validation result.",
        )

    resolved_item_id = (item_id or "").strip()
    thread_ref = (thread_id or "").strip()
    if not resolved_item_id:
        if not thread_ref:
            raise WorkflowError(
                status="VALIDATION_EVIDENCE_REJECTED",
                reason_code="MISSING_THREAD_REFERENCE",
                waiting_on="validation_evidence",
                exit_code=2,
                message="agent evidence add --item-id requires --thread-id or --item-id.",
            )
        resolved_item_id = thread_ref if thread_ref.startswith("github-thread:") else f"github-thread:{thread_ref}"

    session = session_store.load_session(repo, pr_number)
    item = _items(session).get(resolved_item_id)
    if not isinstance(item, dict) or item.get("item_kind") != "github_thread":
        raise WorkflowError(
            status="VALIDATION_EVIDENCE_REJECTED",
            reason_code="UNKNOWN_GITHUB_THREAD",
            waiting_on="validation_evidence",
            exit_code=4,
            message=f"No github_thread item `{resolved_item_id}` exists in the session.",
        )
    if normalized_thread_state(item) not in GITHUB_THREAD_TERMINAL_STATES:
        raise WorkflowError(
            status="VALIDATION_EVIDENCE_REJECTED",
            reason_code="THREAD_NOT_TERMINAL",
            waiting_on="validation_evidence",
            exit_code=4,
            message=(
                "Validation evidence reconcile is only for threads already resolved out-of-band; "
                f"`{resolved_item_id}` is not terminal. Use `agent resolve` for claimable threads."
            ),
        )

    timestamp = _format_timestamp(_coerce_now(now))
    payload_thread_id = str(item.get("thread_id") or thread_ref or resolved_item_id.removeprefix("github-thread:"))
    idempotency_key = f"validation_evidence:{resolved_item_id}:{normalized_commit}"
    record = _ledger(session).append_event(
        session_id=str(session["session_id"]),
        item_id=resolved_item_id,
        lease_id=None,
        agent_id=agent_id,
        role="fixer",
        event_type="validation_evidence_recorded",
        payload={
            "thread_id": payload_thread_id,
            "commit_hash": normalized_commit,
            "files": normalized_files,
            "validation_commands": normalized_validation,
            "idempotency_key": idempotency_key,
            "source": "manual_reconcile",
        },
        timestamp=timestamp,
    )
    item["validation_evidence"] = normalized_validation
    fix_reply = {"commit_hash": normalized_commit, "files": normalized_files}
    if summary and summary.strip():
        fix_reply["summary"] = summary.strip()
    if why and why.strip():
        fix_reply["why"] = why.strip()
    item["validation_reconcile"] = fix_reply
    session_store.save_session(repo, pr_number, session)
    return {
        "status": "VALIDATION_EVIDENCE_RECORDED",
        "repo": repo,
        "pr_number": str(pr_number),
        "item_id": resolved_item_id,
        "thread_id": payload_thread_id,
        "commit_hash": normalized_commit,
        "files": normalized_files,
        "validation_commands": normalized_validation,
        "evidence_record_id": record.record_id,
    }


def fast_fix_item(
    repo: str,
    pr_number: str,
    *,
    item_id: str,
    agent_id: str,
    commit_hash: str,
    files: list[str],
    validation_commands: list[dict[str, Any]],
    summary: str,
    why: str,
    severity: str | None = None,
    severity_note: str | None = None,
    review_priority: str | None = None,
    publish: bool = False,
    github_client: Any | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    normalized_severity, requested_priority_evidence = _validate_fast_fix_inputs(
        repo,
        pr_number,
        item_id=item_id,
        files=files,
        validation_commands=validation_commands,
        commit_hash=commit_hash,
        summary=summary,
        why=why,
        severity=severity,
        severity_note=severity_note,
        review_priority=review_priority,
    )
    classification, requested = _prepare_fast_fix_request(
        repo,
        pr_number,
        item_id=item_id,
        agent_id=agent_id,
        why=why,
        review_priority_evidence=requested_priority_evidence,
        now=now,
    )
    response_path, response = _build_fast_fix_response(
        repo,
        pr_number,
        requested=requested,
        item_id=item_id,
        agent_id=agent_id,
        summary=summary,
        why=why,
        commit_hash=commit_hash,
        files=files,
        validation_commands=validation_commands,
        normalized_severity=normalized_severity,
        severity_note=severity_note,
    )
    submitted = agent_protocol.submit_action_response(
        repo,
        pr_number,
        response_path=response_path,
        now=now,
        publish=publish,
        github_client=github_client,
    )

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


def _validate_fast_fix_inputs(
    repo: str,
    pr_number: str,
    *,
    item_id: str,
    files: list[str],
    validation_commands: list[dict[str, Any]],
    commit_hash: str,
    summary: str,
    why: str,
    severity: str | None,
    severity_note: str | None,
    review_priority: str | None,
) -> tuple[str | None, dict[str, Any] | None]:
    normalized_files = _normalize_string_list(files)
    normalized_validation = _normalize_validation_command_records(validation_commands)
    if not normalized_files:
        raise WorkflowError(
            status=protocol_codes.FAST_FIX_REJECTED,
            reason_code="MISSING_FILES",
            waiting_on="fast_fix_input",
            exit_code=2,
            message="agent resolve requires --files or --file.",
            payload={"item_id": item_id},
        )
    if not normalized_validation:
        raise WorkflowError(
            status=protocol_codes.FAST_FIX_REJECTED,
            reason_code="MISSING_VALIDATION_COMMANDS",
            waiting_on="fast_fix_input",
            exit_code=2,
            message="agent resolve requires --validation.",
            payload={"item_id": item_id},
        )
    if not commit_hash.strip():
        raise WorkflowError(
            status=protocol_codes.FAST_FIX_REJECTED,
            reason_code=protocol_codes.MISSING_FIX_REPLY_COMMIT_HASH,
            waiting_on="fast_fix_input",
            exit_code=2,
            message="agent resolve requires --commit for GitHub thread replies.",
            payload={"item_id": item_id},
        )
    if not summary.strip() or not why.strip():
        raise WorkflowError(
            status=protocol_codes.FAST_FIX_REJECTED,
            reason_code="MISSING_SUMMARY_OR_WHY",
            waiting_on="fast_fix_input",
            exit_code=2,
            message="agent resolve requires --summary and --why.",
            payload={"item_id": item_id},
        )
    normalized_severity = _validate_requested_severity(
        severity,
        status=protocol_codes.FAST_FIX_REJECTED,
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
                status=protocol_codes.FAST_FIX_REJECTED,
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
            status=protocol_codes.FAST_FIX_REJECTED,
            reason_code="INVALID_REVIEW_PRIORITY",
            waiting_on="fast_fix_input",
            exit_code=2,
            message="agent resolve --review-priority must be high, medium, or low.",
            payload={"item_id": item_id},
        )
    return normalized_severity, requested_priority_evidence


def _prepare_fast_fix_request(
    repo: str,
    pr_number: str,
    *,
    item_id: str,
    agent_id: str,
    why: str,
    review_priority_evidence: dict[str, Any] | None,
    now: datetime | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    classification = agent_protocol.record_classification(
        repo,
        pr_number,
        item_id=item_id,
        classification="fix",
        agent_id=agent_id,
        note=why,
    )
    requested = agent_protocol.issue_action_request(
        repo,
        pr_number,
        role="fixer",
        agent_id=agent_id,
        item_id=item_id,
        now=now,
    )
    if review_priority_evidence:
        session = session_store.load_session(repo, pr_number)
        item = _items(session).get(item_id)
        if isinstance(item, dict):
            item["review_priority_evidence"] = review_priority_evidence
            session_store.save_session(repo, pr_number, session)
    return classification, requested


def _build_fast_fix_response(
    repo: str,
    pr_number: str,
    *,
    requested: dict[str, Any],
    item_id: str,
    agent_id: str,
    summary: str,
    why: str,
    commit_hash: str,
    files: list[str],
    validation_commands: list[dict[str, Any]],
    normalized_severity: str | None,
    severity_note: str | None,
) -> tuple[Path, dict[str, Any]]:
    normalized_files = _normalize_string_list(files)
    normalized_validation = _normalize_validation_command_records(validation_commands)
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
    write_json_atomic(response_path, response)
    return response_path, response


def decline_item(
    repo: str,
    pr_number: str,
    *,
    item_id: str,
    agent_id: str,
    resolution: str,
    why: str,
    publish: bool = False,
    github_client: Any | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Decline (reject/clarify) a single review-thread item with a reason.

    Composes the same primitives as `fast_fix_item` — `record_classification`
    -> `issue_action_request` -> `submit_action_response` — so single-item
    decline inherits identical lease-ownership and final-gate guarantees
    (spec 029 FR-002/FR-009). No new algorithm.
    """
    if not why or not why.strip():
        raise WorkflowError(
            status=protocol_codes.FAST_FIX_REJECTED,
            reason_code="MISSING_RESOLVE_ARGS",
            waiting_on="decline_input",
            exit_code=2,
            message=f"agent resolve {item_id} requires --why to {resolution} a thread.",
            payload={"item_id": item_id},
        )
    classification = agent_protocol.record_classification(
        repo,
        pr_number,
        item_id=item_id,
        classification=resolution,
        agent_id=agent_id,
        note=why,
    )
    requested = agent_protocol.issue_action_request(
        repo,
        pr_number,
        role="fixer",
        agent_id=agent_id,
        item_id=item_id,
        now=now,
    )
    request = json.loads(Path(requested["request_path"]).read_text(encoding="utf-8"))
    response_path = session_store.workspace_dir(repo, pr_number) / f"decline-response-{request['request_id']}.json"
    response = {
        "schema_version": PROTOCOL_VERSION,
        "request_id": request["request_id"],
        "lease_id": request["lease_id"],
        "agent_id": agent_id,
        "item_id": item_id,
        "resolution": resolution,
        "note": why,
        "reply_markdown": why,
    }
    write_json_atomic(response_path, response)
    submitted = agent_protocol.submit_action_response(
        repo,
        pr_number,
        response_path=response_path,
        now=now,
        publish=publish,
        github_client=github_client,
    )
    return {
        "status": "DECLINE_COMPLETE" if publish else "DECLINE_ACCEPTED",
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
    validation_commands: list[dict[str, Any]],
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
    text = " ".join(str(item.get(key) or "") for key in ("title", "body", "first_body", "path")).lower()
    if TRIVIAL_SENSITIVE_MARKER_RE.search(text):
        return False, "Thread contains non-trivial or sensitive review markers."
    path = str(item.get("path") or "").lower()
    path_trivial = path.endswith(".md") or path.startswith("docs/") or path in {"readme", "readme.md"}
    text_trivial = bool(TRIVIAL_POSITIVE_MARKER_RE.search(text))
    if not (path_trivial or text_trivial):
        return False, "Thread does not look like a documentation or typo-only concern."
    return True, "Thread is eligible for documentation or typo fast path."
THREAD_ALIAS_RE = re.compile(r"^T(\d+)$")


def resolve_thread_alias(repo: str, pr_number: str, token: str | None) -> str | None:
    """Map a lean-output thread alias (``T1``..``Tn``) to its canonical ``item_id``.

    Aliases are assigned in sorted ``github_thread`` item-id order, matching the
    ``--lean`` thread rows, so they stay stable for a session as long as the thread
    set is unchanged. A non-alias token is returned unchanged (no session load), and
    an alias outside the current range raises so a stale handle is never mis-resolved.
    """
    match = THREAD_ALIAS_RE.match(str(token or "").strip())
    if not match:
        return token
    index = int(match.group(1))
    session = session_store.load_session(repo, pr_number)
    thread_ids = [
        str(item.get("item_id") or item_id)
        for item_id, item in sorted(_items(session).items())
        if isinstance(item, dict) and item.get("item_kind") == "github_thread"
    ]
    if 1 <= index <= len(thread_ids):
        return thread_ids[index - 1]
    raise WorkflowError(
        status=protocol_codes.FAST_FIX_REJECTED,
        reason_code="THREAD_ALIAS_NOT_FOUND",
        waiting_on="work_item",
        exit_code=2,
        message=(
            f"Thread alias {token} does not match any current thread; "
            "re-run `address --lean` to refresh the T1..Tn aliases."
        ),
    )
