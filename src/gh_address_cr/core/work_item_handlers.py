from __future__ import annotations

from typing import Any

from gh_address_cr.core.models import WorkItemHandlingBoundary


class WorkItemBoundaryError(ValueError):
    def __init__(self, reason_code: str, detail: str | None = None):
        self.reason_code = reason_code
        message = reason_code if detail is None else f"{reason_code}: {detail}"
        super().__init__(message)


GITHUB_THREAD_FIX_BOUNDARY = WorkItemHandlingBoundary(
    boundary_id="github-thread-fix",
    item_kinds=("github_thread",),
    applicability="matched",
    priority=100,
    required_evidence=("classification", "files", "validation", "reply"),
    completion_criteria=("accepted_evidence", "published_reply", "resolved_thread", "final_gate"),
    terminal_failure_reasons=("UNSUPPORTED_WORK_ITEM", "BOUNDARY_CONFLICT", "MISSING_REQUIRED_EVIDENCE"),
    next_actions=("issue_action_request",),
)

DEFAULT_BOUNDARIES = (GITHUB_THREAD_FIX_BOUNDARY,)


def select_handling_boundary(
    item: dict[str, Any],
    *,
    role: str,
    boundaries: tuple[WorkItemHandlingBoundary, ...] = DEFAULT_BOUNDARIES,
) -> WorkItemHandlingBoundary:
    matches = [boundary for boundary in boundaries if _matches(boundary, item, role=role)]
    if not matches:
        raise WorkItemBoundaryError("UNSUPPORTED_WORK_ITEM", str(item.get("item_id") or ""))
    matches.sort(key=lambda boundary: boundary.priority, reverse=True)
    if len(matches) > 1 and matches[0].priority == matches[1].priority:
        raise WorkItemBoundaryError("BOUNDARY_CONFLICT", str(item.get("item_id") or ""))
    return matches[0]


def boundary_summary_for_item(item: dict[str, Any], *, role: str) -> dict[str, Any]:
    boundary = select_handling_boundary(item, role=role)
    return {
        "item_id": str(item.get("item_id") or ""),
        "item_kind": str(item.get("item_kind") or ""),
        "boundary_id": boundary.boundary_id,
        "applicability": boundary.applicability,
        "required_evidence": list(boundary.required_evidence),
        "completion_criteria": list(boundary.completion_criteria),
        "terminal_failure_reasons": list(boundary.terminal_failure_reasons),
        "next_action": boundary.next_actions[0] if boundary.next_actions else None,
    }


def _matches(boundary: WorkItemHandlingBoundary, item: dict[str, Any], *, role: str) -> bool:
    if item.get("item_kind") not in boundary.item_kinds:
        return False
    if boundary.boundary_id == "github-thread-fix":
        evidence = item.get("classification_evidence") or {}
        return role == "fixer" and evidence.get("classification") == "fix"
    return True
