from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from gh_address_cr import PROTOCOL_VERSION
from gh_address_cr.agent.roles import TERMINAL_RESOLUTIONS
from gh_address_cr.core import protocol_codes
from gh_address_cr.core import session as session_store
from gh_address_cr.core.agent_protocol_evidence import required_evidence_for
from gh_address_cr.core.agent_protocol_leases import active_fixer_lease_for_item
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
    release_claimed_lease,
    release_lease,
)
from gh_address_cr.core.models import ActionRequest
from gh_address_cr.core.runtime_kernel.stack import STACK_MANAGEMENT_ACTIONS, repository_context_for_stack
from gh_address_cr.core.untrusted_content import request_item_projection
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
    publish_outcome_status,
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


def _reenter_own_fixer_lease(
    repo: str,
    pr_number: str,
    session: dict[str, Any],
    *,
    role: str,
    agent_id: str,
    item_id: str | None,
    github_client: Any | None,
) -> dict[str, Any] | None:
    """Hand an agent back the request for the fixer lease it already holds.

    `agent next --batch` already does this (`_reconcile_existing_lease`); the
    single-item path instead raised LEASE_LOCKED_ITEM at the lease's own owner. When
    an agent loses its request files the lease stays active, so it could neither submit
    nor claim again and had to wait out the TTL.

    Only the owner is re-entered: `active_fixer_lease_for_item` matches on agent *and*
    role and only `active` status, so another agent, another role, and a `submitted`
    lease (evidence already sent) all fall through to LEASE_LOCKED_ITEM unchanged.
    Runs after `expire_leases`, so an expired lease is never resurrected.

    The request keeps its original request_id and lease_id. Submit re-reads the request
    file and requires response.request_id to match, so a fresh id would strand any
    response the agent already wrote.
    """
    if role != "fixer" or not item_id:
        return None
    lease = active_fixer_lease_for_item(session, item_id, agent_id=agent_id)
    if lease is None:
        return None
    item = _items(session).get(item_id)
    if not isinstance(item, dict):
        return None
    request_id = str(lease.get("request_id") or "")
    request_path = lease.get("request_path")
    if not request_id or not request_path:
        # No request identity to hand back; leave it to the lock path rather than
        # invent one that no response could match.
        return None

    request_path = Path(str(request_path))
    skeleton_path = request_path.with_name(f"action-response-skeleton-{request_id}.json")
    identity = {"request_id": request_id, "lease_id": str(lease["lease_id"])}
    request = _payload_for_lease(request_path, **identity, validate=ActionRequest.from_dict)
    if request is None:
        # The request itself is gone (or unreadable), so it has to be rebuilt.
        request = _rebuild_fixer_request(repo, pr_number, session, item=item, lease=lease, github_client=github_client)
        request["response_skeleton_path"] = str(skeleton_path)
        write_json_atomic(request_path, request)
        # The stack revision binding is part of the hash, so a rebuilt request can hash
        # differently from the original. Submit recomputes the hash from the file, but
        # keep the lease's copy in step with what is now on disk.
        lease["request_hash"] = ActionRequest.from_dict(request).stable_hash()
        # `evidence-ledger.md` promises agents a `request_issued` event whenever an
        # ActionRequest is written. Only the rebuild writes one; handing back an intact
        # request records nothing, or every re-entry would claim a side effect that did
        # not happen. `rebuilt` keeps the trail honest about which of the two occurred.
        _ledger(session).append_event(
            session_id=str(session["session_id"]),
            item_id=item_id,
            lease_id=str(lease["lease_id"]),
            agent_id=agent_id,
            role=role,
            event_type="request_issued",
            payload={
                "request_id": request_id,
                "request_path": str(request_path),
                "response_skeleton_path": str(skeleton_path),
                "rebuilt": True,
            },
        )
        session_store.save_session(repo, pr_number, session)
    if _payload_for_lease(skeleton_path, **identity) is None:
        # Derived from the request now on disk. Regenerating the skeleton does not touch
        # the request or the hash the lease stores for it: when only the skeleton was
        # lost, rebuilding the request here moved that hash without rewriting the file,
        # and the two then disagreed on submit.
        write_json_atomic(skeleton_path, response_skeleton_for_request(request, agent_id=agent_id, item=item))

    # Same shape as a fresh claim: callers read the top-level handling_boundary without
    # opening the request file.
    handling_boundary = handling_boundary_summary_or_none(item, role="fixer")
    return {
        "status": "ACTION_REQUESTED",
        "repo": repo,
        "pr_number": str(pr_number),
        "request_path": str(request_path),
        "response_skeleton_path": str(skeleton_path),
        "lease_id": str(lease["lease_id"]),
        "resume_token": _get(lease, "resume_token"),
        "item_id": item_id,
        **({"handling_boundary": handling_boundary} if handling_boundary is not None else {}),
        "next_action": (
            f"You already hold this {role} lease. Pass request_path to an agent with the {role} role, "
            "then fill response_skeleton_path."
        ),
    }


def _payload_for_lease(
    path: Path,
    *,
    request_id: str,
    lease_id: str,
    validate: Any | None = None,
) -> dict[str, Any] | None:
    """The JSON object on disk when it belongs to this lease, else None.

    One predicate for the request and for its response skeleton. Applying it to the
    request only was an asymmetry, not a decision: a corrupt or foreign skeleton was
    handed back untouched while the request beside it would have been rebuilt.

    Usable means all of:

    - it parses, and is an object;
    - it passes `validate`, when one is given. For the request that is
      `ActionRequest.from_dict`, the parser submit itself uses, so what re-entry
      accepts cannot drift from what submit accepts. "Any JSON object" is not enough:
      `{}` parses, then skeleton generation indexes required keys and raises KeyError
      instead of rebuilding. A skeleton has no such parser -- it is deliberately
      incomplete until the agent fills it in -- so it is checked on identity alone;
    - it carries this lease's `request_id` and `lease_id`. A file can be perfectly
      valid and still belong to another lease, and handing that back points the agent
      at the wrong request.

    A skeleton the agent has already filled in still matches, so re-entry keeps it;
    only an unusable one is regenerated and the agent's evidence is never discarded.
    """
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return None
        if validate is not None:
            validate(payload)
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError, AttributeError):
        return None
    if str(payload.get("request_id")) != request_id or str(payload.get("lease_id")) != lease_id:
        return None
    return payload


def _rebuild_fixer_request(
    repo: str,
    pr_number: str,
    session: dict[str, Any],
    *,
    item: dict[str, Any],
    lease: dict[str, Any],
    github_client: Any | None,
) -> dict[str, Any]:
    """Rebuild a lost fixer ActionRequest under the lease's existing request/lease ids."""
    request_item = request_item_projection(item)
    request_item["state"] = "claimed"
    stack_context = refresh_stack_context_for_request(repo, str(pr_number), session, github_client=github_client)
    request = {
        "schema_version": PROTOCOL_VERSION,
        "request_id": str(lease["request_id"]),
        "session_id": session["session_id"],
        "lease_id": str(lease["lease_id"]),
        "agent_role": "fixer",
        "item": request_item,
        "allowed_actions": sorted(item.get("allowed_actions") or TERMINAL_RESOLUTIONS),
        "required_evidence": required_evidence_for(item, "fixer"),
        "repository_context": repository_context_for_stack(repo, pr_number, stack_context.to_dict()),
        "forbidden_actions": ["post_github_reply", "resolve_github_thread", *STACK_MANAGEMENT_ACTIONS],
        "resume_command": f"gh-address-cr agent submit {repo} {pr_number} --input response.json",
    }
    handling_boundary = handling_boundary_summary_or_none(item, role="fixer")
    if handling_boundary is not None:
        request["handling_boundary"] = handling_boundary
    return request


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
        reentered = _reenter_own_fixer_lease(
            repo, pr_number, session, role=role, agent_id=agent_id, item_id=item_id, github_client=github_client
        )
        if reentered is not None:
            return reentered
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
    request_item = request_item_projection(item)
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


@contextmanager
def claimed_fixer_lease(
    repo: str,
    pr_number: str,
    *,
    item_id: str,
    agent_id: str,
    now: datetime | None = None,
    github_client: Any | None = None,
) -> Iterator[dict[str, Any]]:
    """Claim a fixer lease for a one-shot composition, releasing it if the body raises a WorkflowError.

    The rollback belongs here, around the claim, and deliberately **not** inside
    `submit_action_response`. The two-step `agent next` -> `agent submit` flow keeps
    its lease across a rejected submit on purpose: the agent still holds the
    `response_skeleton_path` and resubmits against the same `lease_id` once the
    evidence is corrected. Releasing there would break that retry.

    A one-shot `agent resolve` is the opposite case. It claims internally, so a
    rejection hands the agent nothing to retry with while the lease keeps the item
    locked until its TTL -- the #273 dead end, where `agent resolve` then answers
    `LEASE_LOCKED_ITEM`, `agent next` answers `NO_ELIGIBLE_ITEM`, and
    `agent reclaim` reports `expired_count=0`.

    Only `WorkflowError` triggers the rollback. An unexpected exception leaves the
    lease in place for `agent leases` to show, because an unmodelled failure is not
    evidence that the claim is safe to undo.

    And only a lease *this* call created is rolled back. `issue_action_request` re-enters
    an active fixer lease the agent already holds rather than minting a second one, so a
    one-shot composition run on an item the agent claimed earlier through `agent next`
    would otherwise release that lease on failure -- destroying exactly the retry handle
    the two-step flow is documented above to preserve.
    """
    preexisting = active_fixer_lease_for_item(session_store.load_session(repo, pr_number), item_id, agent_id=agent_id)
    preexisting_lease_id = str(preexisting["lease_id"]) if isinstance(preexisting, dict) else None
    requested = issue_action_request(
        repo,
        pr_number,
        role="fixer",
        agent_id=agent_id,
        item_id=item_id,
        now=now,
        github_client=github_client,
    )
    try:
        yield requested
    except WorkflowError as exc:
        if str(requested["lease_id"]) == preexisting_lease_id:
            # Re-entered, not claimed: the agent held this lease before the call and keeps it.
            raise
        # Any WorkflowError rolls back, not only ACTION_REJECTED, so record which one:
        # a fixed "action_rejected" would mislabel the lease events `agent leases` shows.
        release_claimed_lease(
            repo,
            pr_number,
            lease_id=str(requested["lease_id"]),
            now=now,
            reason=f"action_rejected:{exc.reason_code}",
        )
        raise


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
    # Only claim "published" when the publisher actually covered this item. A no-op
    # publish (NO_PUBLISH_READY_ITEMS) or one that skipped it keeps the default
    # "run agent publish" next_action, so callers that read this payload -- and the
    # `fast_fix_item` result built on it -- agree with the outcome-derived status.
    published_status = publish_outcome_status(
        "SUBMIT", publish=True, published=published, item_ids=[str(prepared["item_id"])]
    )
    if published_status.endswith("_COMPLETE"):
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
