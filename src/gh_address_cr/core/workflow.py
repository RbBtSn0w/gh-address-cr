from __future__ import annotations

import json
import re
from datetime import datetime
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
from gh_address_cr.core import agent_protocol
from gh_address_cr.core import session as session_store
from gh_address_cr.core.agent_protocol import (
    _chunks,
    _coerce_now,
    _format_timestamp,
    _items,
    _json_ready,
    _ledger,
    _load_response_json_object,
    _normalize_string_list,
    _normalize_validation_command_records,
    _validate_requested_severity,
    _validate_severity_override_note,
)
from gh_address_cr.core.errors import WorkflowError
from gh_address_cr.core.github_thread_state import (
    is_claimable_github_thread,
    is_stale_or_outdated_github_thread,
    is_stale_github_thread_item,
)
from gh_address_cr.core.severity import (
    review_priority_evidence,
)


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
    submitted = agent_protocol.submit_batch_action_response(repo, pr_number, batch_path=batch_path, now=now)
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
        submitted = agent_protocol.submit_action_response(
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
                agent_protocol.record_classification(
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
        batch_result = agent_protocol.submit_batch_action_response(repo, pr_number, batch_path=batch_path, now=current_time)
        accepted_count += int(batch_result.get("accepted_count") or 0)
        item_ids.extend(str(item_id) for item_id in batch_result.get("item_ids") or [])
        batches.append(batch_result)

    publish_result = None
    if publish and accepted_count:
        from gh_address_cr.core import publisher

        publish_result = publisher.publish_github_thread_responses(
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
