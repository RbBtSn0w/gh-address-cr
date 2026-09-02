"""Deterministic projection from existing workflow state to one next action."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from gh_address_cr.core import command_templates
from gh_address_cr.core.github_thread_state import is_resolved_github_thread

PRIMARY_ACTION_KINDS = {
    "claim",
    "resolve",
    "publish",
    "wait",
    "run_final_gate",
    "repair_environment",
    "complete",
}

_ENVIRONMENT_WAITING_ON = {
    "active_pr_target",
    "github_cli",
    "network",
    "authentication",
    "authorization",
    "pr_scope",
    "revision",
    "session",
    "state_directory",
}
_SEVERITY_RANK = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}


def _mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _head_sha(session: dict[str, Any]) -> str | None:
    metadata = _mapping(session.get("metadata"))
    context = _mapping(metadata.get("pull_request_context"))
    direct = context.get("head_sha") or context.get("head_oid")
    if direct:
        return str(direct)
    stack = _mapping(context.get("stack_context"))
    selected_pr = _mapping(stack.get("selected_pr"))
    if selected_pr.get("head_oid"):
        return str(selected_pr["head_oid"])
    selected = str(stack.get("selected_pr_number") or selected_pr.get("pr_number") or "")
    stack_details = _mapping(stack.get("stack"))
    members = stack_details.get("members") if isinstance(stack_details.get("members"), list) else stack.get("members")
    members = members if isinstance(members, list) else []
    for member in members:
        if isinstance(member, dict) and str(member.get("pr_number") or "") == selected:
            value = member.get("head_oid")
            return str(value) if value else None
    return None


def build_recommendation_observation(
    session: dict[str, Any],
    action: dict[str, Any],
    *,
    emitted_at: str,
) -> dict[str, Any]:
    """Build non-authoritative recommendation metadata for dedupe telemetry."""
    raw_item_id = action.get("item_id")
    item_id = str(raw_item_id) if isinstance(raw_item_id, str) else None
    raw_items = session.get("items")
    items = raw_items if isinstance(raw_items, dict) else {}
    item = _mapping(items.get(item_id)) if item_id else {}
    evidence_state = {
        "state": item.get("state"),
        "status": item.get("status"),
        "accepted_response": isinstance(item.get("accepted_response"), dict),
        "reply_evidence": isinstance(item.get("reply_evidence"), dict),
    }
    head_sha = _head_sha(session)
    fingerprint_input = {
        "head_sha": head_sha,
        "item_id": item_id,
        "kind": action.get("kind"),
        "evidence_state": evidence_state,
    }
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_input, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "fingerprint": fingerprint,
        "head_sha": head_sha,
        "item_id": item_id,
        "kind": action.get("kind"),
        "evidence_state": evidence_state,
        "emitted_at": emitted_at,
    }


def project_context_summary(session: dict[str, Any], *, selected_item_id: str | None) -> dict[str, Any]:
    """Project bounded context from facts already refreshed by the high-level command."""
    metadata = _mapping(session.get("metadata"))
    observed = _mapping(metadata.get("pull_request_context"))
    stack = _mapping(observed.get("stack_context"))
    serialized_selected = _mapping(stack.get("selected_pr"))
    selected_pr = str(stack.get("selected_pr_number") or serialized_selected.get("pr_number") or "")
    stack_details = _mapping(stack.get("stack"))
    members = stack_details.get("members") if isinstance(stack_details.get("members"), list) else stack.get("members")
    members = members if isinstance(members, list) else []
    member = serialized_selected or next(
        (
            row
            for row in members
            if isinstance(row, dict) and str(row.get("pr_number") or "") == selected_pr
        ),
        {},
    )
    raw_items = session.get("items")
    items = raw_items if isinstance(raw_items, dict) else {}
    selected = _mapping(items.get(selected_item_id)) if selected_item_id else {}
    changed_files = metadata.get("changed_files") if isinstance(metadata.get("changed_files"), list) else []
    check_summary = metadata.get("check_summary") if isinstance(metadata.get("check_summary"), dict) else None
    return {
        "pull_request": {
            "base_ref": member.get("base_ref_name"),
            "head_ref": member.get("head_ref_name"),
            "head_sha": member.get("head_oid") or _head_sha(session),
        },
        "changed_files": changed_files,
        "checks": check_summary or {"availability": "not_loaded", "counts": {}},
        "selected_item": {
            "item_id": selected.get("item_id") if selected else None,
            "path": selected.get("path") if selected else None,
            "line": selected.get("line") if selected else None,
            "comment_excerpt": str(selected.get("body") or "")[:500] if selected else None,
        },
        "relevant_diff": {"availability": "on_demand"},
        "codeowners": {"availability": "on_demand", "advisory": True},
    }


def _action(
    kind: str,
    *,
    command: str | None,
    item_id: str | None,
    why_now: str,
    requires_human: bool = False,
) -> dict[str, Any]:
    if kind not in PRIMARY_ACTION_KINDS:
        raise ValueError(f"Unsupported primary action kind: {kind}")
    return {
        "kind": kind,
        "command": command,
        "item_id": item_id,
        "why_now": why_now,
        "requires_human": requires_human,
    }


def _candidate_items(session: dict[str, Any]) -> list[dict[str, Any]]:
    raw_items = session.get("items")
    items = raw_items.values() if isinstance(raw_items, dict) else []
    return [item for item in items if isinstance(item, dict) and item.get("blocking")]


def _item_sort_key(item: dict[str, Any]) -> tuple[int, int, str]:
    item_kind = str(item.get("item_kind") or "")
    severity = str(item.get("severity") or "").upper()
    return (
        _SEVERITY_RANK.get(severity, 4),
        0 if item_kind == "github_thread" else 1,
        str(item.get("review_priority") or item.get("item_id") or ""),
    )


def project_primary_action(
    *,
    repo: str,
    pr_number: str,
    command: str,
    status: str,
    reason_code: str,
    waiting_on: str | None,
    session: dict[str, Any],
) -> dict[str, Any]:
    """Return exactly one advisory action without mutating authoritative state."""
    if waiting_on in _ENVIRONMENT_WAITING_ON or reason_code.endswith("_FAILED"):
        return _action(
            "repair_environment",
            command=None,
            item_id=None,
            why_now="The workflow cannot safely continue until its environment or target is repaired.",
            requires_human=True,
        )

    candidates = _candidate_items(session)
    publish_ready = sorted(
        (
            item
            for item in candidates
            if item.get("state") == "publish_ready" and isinstance(item.get("accepted_response"), dict)
        ),
        key=_item_sort_key,
    )
    if publish_ready:
        item_id = str(publish_ready[0].get("item_id") or "") or None
        return _action(
            "publish",
            command=command_templates.publish(repo, pr_number),
            item_id=item_id,
            why_now="Accepted evidence is ready to publish before starting another item.",
        )

    unresolved = sorted(
        (
            item
            for item in candidates
            if item.get("item_kind") == "github_thread"
            and not is_resolved_github_thread(item)
            and item.get("state") not in {"published", "resolved", "terminal"}
        ),
        key=_item_sort_key,
    )
    if unresolved:
        selected = unresolved[0]
        item_id = str(selected.get("item_id") or "") or None
        if selected.get("reply_evidence") or selected.get("published_at"):
            return _action(
                "wait",
                command=None,
                item_id=item_id,
                why_now="The remote review thread has not converged after the recorded side effect.",
            )
        return _action(
            "claim",
            command=command_templates.next_fixer_for_item(repo, pr_number, item_id or "<item_id>"),
            item_id=item_id,
            why_now="This is the highest-priority unresolved review thread.",
        )

    local_items = sorted(
        (item for item in candidates if item.get("item_kind") == "local_finding"),
        key=_item_sort_key,
    )
    if local_items:
        item_id = str(local_items[0].get("item_id") or "") or None
        return _action(
            "resolve",
            command=None,
            item_id=item_id,
            why_now="A blocking local finding must be resolved before the final gate.",
        )

    metadata = _mapping(session.get("metadata"))
    check_summary = _mapping(metadata.get("check_summary"))
    check_counts = _mapping(check_summary.get("counts"))
    if int(check_counts.get("pending") or 0) > 0:
        return _action(
            "wait",
            command=None,
            item_id=None,
            why_now="Pull request checks are still pending.",
        )
    if waiting_on in {"checks", "required_checks"}:
        return _action(
            "wait",
            command=None,
            item_id=None,
            why_now="Required checks are still pending.",
        )
    if reason_code in {"WAITING_FOR_EXTERNAL_REVIEW", "WAITING_FOR_FINDINGS", "FINDINGS_REQUIRED"}:
        return _action(
            "resolve",
            command=None,
            item_id=None,
            why_now="Review findings are required before resolution can continue.",
        )
    if command == "final-gate" and status == "PASSED":
        return _action(
            "complete",
            command=None,
            item_id=None,
            why_now="The authoritative final gate passed for the current revision.",
        )
    if status == "PASSED":
        return _action(
            "run_final_gate",
            command=command_templates.final_gate(repo, pr_number),
            item_id=None,
            why_now="Inline resolution is clear; final-gate remains the authoritative completion check.",
        )
    return _action(
        "repair_environment",
        command=None,
        item_id=None,
        why_now="No safe executable action can be derived from the current modeled state.",
        requires_human=True,
    )
