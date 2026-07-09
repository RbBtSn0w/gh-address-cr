from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from gh_address_cr import MAX_PARALLEL_CLAIMS, PROTOCOL_VERSION
from gh_address_cr.core import agent_batch, agent_protocol, command_templates, leases, protocol_codes
from gh_address_cr.core import session as session_store
from gh_address_cr.core.agent_protocol import (
    _normalize_validation_command_records,
    _validate_requested_severity,
    _validate_severity_override_note,
)
from gh_address_cr.core.errors import WorkflowError
from gh_address_cr.core.github_thread_state import (
    is_claimable_github_thread,
    is_resolved_github_thread,
    is_stale_github_thread_item,
    is_stale_or_outdated_github_thread,
)
from gh_address_cr.core.io import write_json_atomic
from gh_address_cr.core.utils import coerce_now as _coerce_now
from gh_address_cr.core.utils import get_session_items as _items
from gh_address_cr.core.utils import normalize_string_list as _normalize_string_list

FIX_ALL_PER_THREAD_EVIDENCE_REASON = "PER_THREAD_EVIDENCE_REQUIRED"
FIX_ALL_STALE_ROUTE_REASON = "STALE_THREADS_REQUIRE_RESOLVE_STALE"

MATCHING_THREAD_SUCCESS_STATUS = {
    ("FAST_FIX_ALL", False): "FAST_FIX_ALL_ACCEPTED",
    ("FAST_FIX_ALL", True): "FAST_FIX_ALL_COMPLETE",
    ("STALE_RESOLUTION", False): "STALE_RESOLUTION_ACCEPTED",
    ("STALE_RESOLUTION", True): "STALE_RESOLUTION_COMPLETE",
    ("DECLINE_ALL", False): "DECLINE_ALL_ACCEPTED",
    ("DECLINE_ALL", True): "DECLINE_ALL_COMPLETE",
}
MATCHING_THREAD_FAILURE_STATUS = {
    ("FAST_FIX_ALL", False): "FAST_FIX_ALL_NO_ACCEPTED",
    ("FAST_FIX_ALL", True): "FAST_FIX_ALL_PARTIAL",
    ("STALE_RESOLUTION", False): "STALE_RESOLUTION_NO_ACCEPTED",
    ("STALE_RESOLUTION", True): "STALE_RESOLUTION_PARTIAL",
    ("DECLINE_ALL", False): "DECLINE_ALL_NO_ACCEPTED",
    ("DECLINE_ALL", True): "DECLINE_ALL_PARTIAL",
}


@dataclass
class _FastFixContext:
    """Normalized inputs and derived status labels for a fast-fix/stale-resolution run."""

    status_prefix: str
    rejected_status: str
    input_waiting_on: str
    command_name: str
    normalized_files: list[str]
    normalized_validation: list[dict[str, str]]
    normalized_severity: str | None
    normalized_homogeneous_reason: str
    normalized_concern_label: str
    resolution: str = "fix"


def _build_fast_fix_context(
    *,
    files: list[str],
    validation_commands: list[dict[str, Any]],
    commit_hash: str,
    severity: str | None,
    homogeneous_reason: str | None,
    concern_label: str | None,
    stale_only: bool,
    resolution: str = "fix",
) -> _FastFixContext:
    """Validate and normalize the raw fast-fix/decline inputs, raising WorkflowError on bad input."""
    is_decline = resolution != "fix"
    if stale_only:
        status_prefix = "STALE_RESOLUTION"
        command_name = "agent resolve --stale"
    elif is_decline:
        status_prefix = "DECLINE_ALL"
        command_name = f"agent resolve --disposition {resolution}"
    else:
        status_prefix = "FAST_FIX_ALL"
        command_name = "agent resolve"
    rejected_status = f"{status_prefix}_REJECTED"
    if stale_only:
        input_waiting_on = "stale_resolution_input"
    elif is_decline:
        input_waiting_on = "decline_input"
    else:
        input_waiting_on = "fast_fix_input"
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
    if is_decline:
        if not str(homogeneous_reason or "").strip():
            raise WorkflowError(
                status=rejected_status,
                reason_code="MISSING_HOMOGENEOUS_REASON",
                waiting_on=input_waiting_on,
                exit_code=2,
                message=f"{command_name} requires --why for the shared decline reply.",
            )
    else:
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
                reason_code=protocol_codes.MISSING_FIX_REPLY_COMMIT_HASH,
                waiting_on=input_waiting_on,
                exit_code=2,
                message=f"{command_name} requires --commit.",
            )
    normalized_severity = _validate_requested_severity(
        severity,
        status=rejected_status,
        waiting_on=input_waiting_on,
    )
    return _FastFixContext(
        status_prefix=status_prefix,
        rejected_status=rejected_status,
        input_waiting_on=input_waiting_on,
        command_name=command_name,
        normalized_files=normalized_files,
        normalized_validation=normalized_validation,
        normalized_severity=normalized_severity,
        normalized_homogeneous_reason=str(homogeneous_reason or "").strip(),
        normalized_concern_label=str(concern_label or "").strip(),
        resolution=resolution,
    )


def _resolve_fast_fix_matches(
    repo: str,
    pr_number: str,
    ctx: _FastFixContext,
    *,
    include_stale: bool,
    stale_only: bool,
    agent_id: str | None = None,
) -> tuple[list[dict[str, Any]], set[str]]:
    """Load session threads and return the matching items plus the normalized file set."""
    session = session_store.load_session(repo, pr_number)
    github_items = [item for item in _items(session).values() if item.get("item_kind") == "github_thread"]
    if not github_items:
        raise WorkflowError(
            status=f"{ctx.status_prefix}_NO_MATCH",
            reason_code="SESSION_THREADS_REQUIRED",
            waiting_on="github_threads",
            exit_code=4,
            message=f"Run `gh-address-cr address {repo} {pr_number} --lean` first to sync GitHub review threads.",
        )

    self_leased_item_ids: set[str] = set()
    if stale_only and agent_id:
        self_leased_item_ids = {
            str(lease.get("item_id"))
            for lease in (session.get("leases") or {}).values()
            if isinstance(lease, dict)
            and lease.get("status") in {"active", "submitted"}
            and str(lease.get("agent_id")) == str(agent_id)
            and str(lease.get("role")) == "fixer"
        }

    normalized_file_set = {path.strip() for path in ctx.normalized_files if path.strip()}
    matches = [
        item
        for item in github_items
        if _matches_fast_fix_thread(
            item,
            normalized_file_set,
            include_stale=include_stale,
            stale_only=stale_only,
            self_leased=str(item.get("item_id")) in self_leased_item_ids,
        )
    ]
    if not matches:
        raise WorkflowError(
            status=f"{ctx.status_prefix}_NO_MATCH",
            reason_code="NO_MATCHING_GITHUB_THREADS",
            waiting_on="github_threads",
            exit_code=4,
            message="No matching claimable GitHub review threads were found for the supplied files.",
            payload={"files": sorted(normalized_file_set)},
        )
    return matches, normalized_file_set


def _enforce_fast_fix_routing(
    repo: str,
    pr_number: str,
    matches: list[dict[str, Any]],
    normalized_file_set: set[str],
    ctx: _FastFixContext,
    *,
    stale_only: bool,
) -> None:
    """Reject runs that must instead route through stale resolution or per-thread batch evidence."""
    if stale_only:
        return
    if any(is_stale_or_outdated_github_thread(item) for item in matches):
        next_action = (
            f"Use `gh-address-cr agent resolve {repo} {pr_number} "
            "--commit <sha> --files <paths> --validation <cmd=passed> --stale` "
            "for stale or outdated GitHub review threads."
        )
        raise WorkflowError(
            status=ctx.rejected_status,
            reason_code=FIX_ALL_STALE_ROUTE_REASON,
            waiting_on="stale_resolution_input",
            exit_code=4,
            message=next_action,
            payload={"matched_count": len(matches), "files": sorted(normalized_file_set)},
        )
    if not ctx.normalized_homogeneous_reason:
        commands = _batch_response_commands(repo, pr_number, normalized_file_set)
        next_action = (
            f"Run `{commands['batch_next']}` to claim the matching GitHub review threads and write a "
            "BatchActionResponse skeleton, then fill per-thread summary/why entries and submit it. "
            "Rerun `agent resolve --why <why>` only for a homogeneous repeated concern."
        )
        raise WorkflowError(
            status=ctx.rejected_status,
            reason_code=FIX_ALL_PER_THREAD_EVIDENCE_REASON,
            waiting_on="batch_action_response",
            exit_code=4,
            message=next_action,
            payload={
                "matched_count": len(matches),
                "files": sorted(normalized_file_set),
                "commands": commands,
            },
        )
    if not _has_homogeneous_thread_bodies(matches):
        if ctx.resolution != "fix":
            classify_command = command_templates.classify(repo, str(pr_number))
            next_action = (
                "The matched threads have missing or distinct thread bodies, so a single shared "
                f"--{ctx.resolution} reply cannot prove a homogeneous repeated concern. Decline each "
                f"thread individually: `agent classify <item_id> --classification {ctx.resolution} "
                "--note <why>`, then `agent next` and `agent submit` with a per-thread reply_markdown; "
                "or narrow --files to threads that share the same concern."
            )
            raise WorkflowError(
                status=ctx.rejected_status,
                reason_code=FIX_ALL_PER_THREAD_EVIDENCE_REASON,
                waiting_on="decline_input",
                exit_code=4,
                message=next_action,
                payload={
                    "matched_count": len(matches),
                    "files": sorted(normalized_file_set),
                    "commands": {
                        "classify": classify_command,
                        "next": command_templates.next_fixer(repo, str(pr_number)),
                        "submit": command_templates.submit(repo, str(pr_number)),
                    },
                },
            )
        commands = _batch_response_commands(repo, pr_number, normalized_file_set)
        next_action = (
            f"Run `{commands['batch_next']}` to claim the matching GitHub review threads and write a "
            "BatchActionResponse skeleton with per-thread summary/why entries. The matched threads have missing "
            "or distinct thread bodies, so resolve cannot prove a homogeneous repeated concern."
        )
        raise WorkflowError(
            status=ctx.rejected_status,
            reason_code=FIX_ALL_PER_THREAD_EVIDENCE_REASON,
            waiting_on="batch_action_response",
            exit_code=4,
            message=next_action,
            payload={
                "matched_count": len(matches),
                "files": sorted(normalized_file_set),
                "commands": commands,
            },
        )


def _batch_response_commands(repo: str, pr_number: str, files: set[str]) -> dict[str, str]:
    return {
        "batch_next": command_templates.batch_next(repo, str(pr_number), files=sorted(files)),
        "resolve_batch": command_templates.resolve_batch(repo, str(pr_number), input_path="<batch-response.json>"),
    }


def _chunks(values: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def _build_fast_fix_batch_response(
    repo: str,
    pr_number: str,
    item: dict[str, Any],
    ctx: _FastFixContext,
    *,
    agent_id: str,
    commit_hash: str,
    severity_note: str | None,
    current_time: datetime,
) -> dict[str, Any]:
    """Classify and claim a single matched thread, returning its batch-response row."""
    item_id = str(item["item_id"])
    why = ctx.normalized_homogeneous_reason or _fast_fix_why(
        commit_hash,
        ctx.normalized_files,
        stale=bool(is_stale_github_thread_item(item)),
    )
    summary = (
        f"Addressed repeated review concern for {item_id}."
        if ctx.normalized_homogeneous_reason
        else f"Fixed {item_id} in {commit_hash.strip()}."
    )
    if ctx.normalized_severity:
        _validate_severity_override_note(
            ctx.normalized_severity,
            item,
            severity_note,
            status=ctx.rejected_status,
            waiting_on=ctx.input_waiting_on,
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
    return {
        "item_id": item_id,
        "request_id": requested["resume_token"].removeprefix("resume:"),
        "lease_id": requested["lease_id"],
        "summary": summary,
        "why": why,
    }


def _write_fast_fix_batch_file(
    repo: str,
    pr_number: str,
    batch_responses: list[dict[str, Any]],
    ctx: _FastFixContext,
    *,
    agent_id: str,
    commit_hash: str,
    severity_note: str | None,
) -> Path:
    """Serialize a single chunk of claimed responses to a batch-input file and return its path."""
    batch_path = session_store.workspace_dir(repo, pr_number) / f"fast-fix-all-batch-{uuid4().hex}.json"
    common_fix_reply = {
        "commit_hash": commit_hash.strip(),
        "summary": (
            f"Addressed homogeneous repeated review concern: {ctx.normalized_concern_label}."
            if ctx.normalized_concern_label
            else f"Fixed related GitHub review threads in {commit_hash.strip()}."
        ),
        "files": ctx.normalized_files,
    }
    if ctx.normalized_severity:
        common_fix_reply["severity"] = ctx.normalized_severity
    if severity_note and severity_note.strip():
        common_fix_reply["severity_note"] = severity_note.strip()
    write_json_atomic(
        batch_path,
        {
            "schema_version": PROTOCOL_VERSION,
            "agent_id": agent_id,
            "resolution": "fix",
            "common": {
                "files": ctx.normalized_files,
                "validation_commands": ctx.normalized_validation,
                "fix_reply": common_fix_reply,
            },
            "items": batch_responses,
        },
    )
    return batch_path


def _process_fast_fix_matches(
    repo: str,
    pr_number: str,
    matches: list[dict[str, Any]],
    ctx: _FastFixContext,
    *,
    agent_id: str,
    commit_hash: str,
    severity_note: str | None,
    current_time: datetime,
) -> tuple[int, list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """Claim and submit the matched threads in parallel-claim chunks."""
    accepted_count = 0
    batches: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    item_ids: list[str] = []
    for batch_items in _chunks(matches, MAX_PARALLEL_CLAIMS):
        batch_responses: list[dict[str, Any]] = []
        for item in batch_items:
            try:
                batch_responses.append(
                    _build_fast_fix_batch_response(
                        repo,
                        pr_number,
                        item,
                        ctx,
                        agent_id=agent_id,
                        commit_hash=commit_hash,
                        severity_note=severity_note,
                        current_time=current_time,
                    )
                )
            except WorkflowError as exc:
                failed.append(_fast_fix_failed_row(str(item["item_id"]), exc))
        if not batch_responses:
            continue
        batch_path = _write_fast_fix_batch_file(
            repo,
            pr_number,
            batch_responses,
            ctx,
            agent_id=agent_id,
            commit_hash=commit_hash,
            severity_note=severity_note,
        )
        batch_result = agent_batch.submit_batch_action_response(
            repo, pr_number, batch_path=batch_path, now=current_time
        )
        accepted_count += int(batch_result.get("accepted_count") or 0)
        item_ids.extend(str(item_id) for item_id in batch_result.get("item_ids") or [])
        batches.append(batch_result)
    return accepted_count, batches, failed, item_ids


def fast_fix_matching_threads(
    repo: str,
    pr_number: str,
    *,
    agent_id: str,
    commit_hash: str,
    files: list[str],
    validation_commands: list[dict[str, Any]],
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
    ctx = _build_fast_fix_context(
        files=files,
        validation_commands=validation_commands,
        commit_hash=commit_hash,
        severity=severity,
        homogeneous_reason=homogeneous_reason,
        concern_label=concern_label,
        stale_only=stale_only,
    )
    matches, normalized_file_set = _resolve_fast_fix_matches(
        repo, pr_number, ctx, include_stale=include_stale, stale_only=stale_only, agent_id=agent_id
    )
    _enforce_fast_fix_routing(repo, pr_number, matches, normalized_file_set, ctx, stale_only=stale_only)

    if stale_only:
        session = session_store.load_session(repo, pr_number)
        released_any = False
        for item_id in {str(match.get("item_id")) for match in matches}:
            if leases.release_self_stale_lease(session, item_id, agent_id=agent_id, now=current_time):
                released_any = True
        if released_any:
            session_store.save_session(repo, pr_number, session)

    accepted_count, batches, failed, item_ids = _process_fast_fix_matches(
        repo,
        pr_number,
        matches,
        ctx,
        agent_id=agent_id,
        commit_hash=commit_hash,
        severity_note=severity_note,
        current_time=current_time,
    )

    return _finalize_matching_threads(
        repo,
        pr_number,
        matches,
        ctx,
        accepted_count=accepted_count,
        failed=failed,
        item_ids=item_ids,
        publish=publish,
        github_client=github_client,
        current_time=current_time,
        extra_payload={
            "commit_hash": commit_hash.strip(),
            "batches": batches,
        },
    )


def decline_matching_threads(
    repo: str,
    pr_number: str,
    *,
    agent_id: str,
    files: list[str],
    resolution: str,
    homogeneous_reason: str | None = None,
    concern_label: str | None = None,
    include_stale: bool = False,
    stale_only: bool = False,
    publish: bool = False,
    github_client: Any | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Decline (reject/clarify) every matching GitHub review thread with one shared reply."""
    if resolution not in {"reject", "clarify"}:
        raise WorkflowError(
            status="DECLINE_ALL_REJECTED",
            reason_code="UNSUPPORTED_DECLINE_RESOLUTION",
            waiting_on="resolve_mode",
            exit_code=2,
            message="Homogeneous decline supports only --reject or --clarify.",
        )
    current_time = _coerce_now(now)
    ctx = _build_fast_fix_context(
        files=files,
        validation_commands=[],
        commit_hash="",
        severity=None,
        homogeneous_reason=homogeneous_reason,
        concern_label=concern_label,
        stale_only=stale_only,
        resolution=resolution,
    )
    matches, normalized_file_set = _resolve_fast_fix_matches(
        repo, pr_number, ctx, include_stale=include_stale, stale_only=stale_only
    )
    _enforce_fast_fix_routing(repo, pr_number, matches, normalized_file_set, ctx, stale_only=stale_only)

    accepted_count, accepted_rows, failed, item_ids = _process_decline_matches(
        repo, pr_number, matches, ctx, agent_id=agent_id, current_time=current_time
    )

    return _finalize_matching_threads(
        repo,
        pr_number,
        matches,
        ctx,
        accepted_count=accepted_count,
        failed=failed,
        item_ids=item_ids,
        publish=publish,
        github_client=github_client,
        current_time=current_time,
        extra_payload={
            "resolution": resolution,
            "homogeneous_reason": ctx.normalized_homogeneous_reason,
            "accepted": accepted_rows,
        },
    )


def _finalize_matching_threads(
    repo: str,
    pr_number: str,
    matches: list[dict[str, Any]],
    ctx: _FastFixContext,
    *,
    accepted_count: int,
    failed: list[dict[str, Any]],
    item_ids: list[str],
    publish: bool,
    github_client: Any | None,
    current_time: datetime,
    extra_payload: dict[str, Any],
) -> dict[str, Any]:
    publish_result = _publish_matching_thread_responses(
        repo,
        pr_number,
        publish=publish,
        accepted_count=accepted_count,
        github_client=github_client,
        current_time=current_time,
    )
    payload = {
        "repo": repo,
        "pr_number": str(pr_number),
        "files": ctx.normalized_files,
        "matched_count": len(matches),
        "accepted_count": accepted_count,
        "failed_count": len(failed),
        "item_ids": item_ids,
        "failed": failed,
        **extra_payload,
        "publish": publish_result,
        "next_action": _matching_thread_next_action(repo, pr_number, publish=publish),
    }
    if failed:
        status = _matching_thread_failure_status(ctx, accepted_count=accepted_count)
        next_action = _matching_thread_failure_next_action(accepted_count)
        payload["next_action"] = next_action
        raise WorkflowError(
            status=status,
            reason_code=status,
            waiting_on="lease" if any(row.get("waiting_on") == "lease" for row in failed) else "work_item",
            exit_code=5,
            message=next_action,
            payload=payload,
        )
    payload["status"] = _matching_thread_success_status(ctx, publish=publish)
    return payload


def _publish_matching_thread_responses(
    repo: str,
    pr_number: str,
    *,
    publish: bool,
    accepted_count: int,
    github_client: Any | None,
    current_time: datetime,
) -> dict[str, Any] | None:
    if not (publish and accepted_count):
        return None
    from gh_address_cr.core import publisher

    return publisher.publish_github_thread_responses(
        repo,
        pr_number,
        github_client=github_client,
        agent_id="gh-address-cr-publisher",
        now=current_time,
    )


def _matching_thread_success_status(ctx: _FastFixContext, *, publish: bool) -> str:
    return MATCHING_THREAD_SUCCESS_STATUS[(ctx.status_prefix, publish)]


def _matching_thread_failure_status(ctx: _FastFixContext, *, accepted_count: int) -> str:
    return MATCHING_THREAD_FAILURE_STATUS[(ctx.status_prefix, bool(accepted_count))]


def _matching_thread_next_action(repo: str, pr_number: str, *, publish: bool) -> str:
    if publish:
        return "Accepted evidence was published. Rerun final-gate when all items are handled."
    return f"Run `gh-address-cr agent publish {repo} {pr_number}` to publish accepted evidence."


def _matching_thread_failure_next_action(accepted_count: int) -> str:
    if accepted_count:
        return f"Accepted {accepted_count} item(s); inspect failed rows, resolve lease/input blockers, then rerun."
    return "No matching items were accepted. Inspect failed rows, resolve lease/input blockers, then rerun."


def _process_decline_matches(
    repo: str,
    pr_number: str,
    matches: list[dict[str, Any]],
    ctx: _FastFixContext,
    *,
    agent_id: str,
    current_time: datetime,
) -> tuple[int, list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """Classify, claim, and single-submit a decline reply for each matched thread."""
    accepted_count = 0
    accepted_rows: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    item_ids: list[str] = []
    for item in matches:
        item_id = str(item["item_id"])
        try:
            accepted_rows.append(
                _submit_decline_thread(repo, pr_number, item, ctx, agent_id=agent_id, current_time=current_time)
            )
        except WorkflowError as exc:
            failed.append(_fast_fix_failed_row(item_id, exc))
            continue
        accepted_count += 1
        item_ids.append(item_id)
    return accepted_count, accepted_rows, failed, item_ids


def _submit_decline_thread(
    repo: str,
    pr_number: str,
    item: dict[str, Any],
    ctx: _FastFixContext,
    *,
    agent_id: str,
    current_time: datetime,
) -> dict[str, Any]:
    """Record classification, claim a fixer lease, and submit one decline reply for a thread."""
    item_id = str(item["item_id"])
    reply = ctx.normalized_homogeneous_reason
    agent_protocol.record_classification(
        repo,
        pr_number,
        item_id=item_id,
        classification=ctx.resolution,
        agent_id=agent_id,
        note=reply,
    )
    requested = agent_protocol.issue_action_request(
        repo,
        pr_number,
        role="fixer",
        agent_id=agent_id,
        item_id=item_id,
        now=current_time,
    )
    request = json.loads(Path(requested["request_path"]).read_text(encoding="utf-8"))
    response_path = session_store.workspace_dir(repo, pr_number) / f"decline-response-{request['request_id']}.json"
    response = {
        "schema_version": PROTOCOL_VERSION,
        "request_id": request["request_id"],
        "lease_id": request["lease_id"],
        "agent_id": agent_id,
        "item_id": item_id,
        "resolution": ctx.resolution,
        "note": reply,
        "reply_markdown": reply,
    }
    write_json_atomic(response_path, response)
    submitted = agent_protocol.submit_action_response(repo, pr_number, response_path=response_path, now=current_time)
    return {
        "item_id": item_id,
        "request_id": request["request_id"],
        "response_path": str(response_path),
        "submit": submitted,
    }


def _matches_fast_fix_thread(
    item: dict[str, Any],
    files: set[str],
    *,
    include_stale: bool,
    stale_only: bool,
    self_leased: bool = False,
) -> bool:
    if not item.get("item_id") or not item.get("path"):
        return False
    item_path = str(item.get("path"))
    if item_path not in files:
        return False
    stale = is_stale_github_thread_item(item)
    if stale_only:
        if not stale:
            return False
        if self_leased:
            return not is_resolved_github_thread(item)
        return is_claimable_github_thread(item)
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
