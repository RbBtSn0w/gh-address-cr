"""Final-gate aggregation for PR-scoped review sessions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping


FINAL_GATE_UNRESOLVED_REMOTE_THREADS = "FINAL_GATE_UNRESOLVED_REMOTE_THREADS"
FINAL_GATE_MISSING_REPLY_EVIDENCE = "FINAL_GATE_MISSING_REPLY_EVIDENCE"
FINAL_GATE_PENDING_CURRENT_LOGIN_REVIEW = "FINAL_GATE_PENDING_CURRENT_LOGIN_REVIEW"
FINAL_GATE_BLOCKING_LOCAL_ITEMS = "FINAL_GATE_BLOCKING_LOCAL_ITEMS"
FINAL_GATE_MISSING_VALIDATION_EVIDENCE = "FINAL_GATE_MISSING_VALIDATION_EVIDENCE"

PASS_EXIT_CODE = 0
FAIL_EXIT_CODE = 5

GITHUB_TERMINAL_STATES = {
    "closed",
    "fixed",
    "clarified",
    "deferred",
    "rejected",
    "resolved",
    "stale",
    "verified",
    "published",
}
LOCAL_TERMINAL_STATES = {
    "closed",
    "fixed",
    "clarified",
    "deferred",
    "rejected",
    "verified",
    "published",
}

COUNT_KEYS = (
    "unresolved_github_threads_count",
    "pending_review_count",
    "blocking_items_count",
    "github_threads_missing_reply_count",
    "missing_validation_evidence_count",
    "blocking_local_items_count",
    "pending_current_login_review_count",
    "unresolved_remote_threads_count",
)

FAILURE_ORDER = (
    (FINAL_GATE_UNRESOLVED_REMOTE_THREADS, "unresolved_remote_threads_count", "remote_threads"),
    (FINAL_GATE_MISSING_REPLY_EVIDENCE, "github_threads_missing_reply_count", "reply_evidence"),
    (FINAL_GATE_PENDING_CURRENT_LOGIN_REVIEW, "pending_current_login_review_count", "pending_review"),
    (FINAL_GATE_BLOCKING_LOCAL_ITEMS, "blocking_local_items_count", "local_items"),
    (FINAL_GATE_MISSING_VALIDATION_EVIDENCE, "missing_validation_evidence_count", "validation_evidence"),
)


@dataclass(frozen=True)
class GateResult:
    repo: str
    pr_number: str
    counts: dict[str, int]
    failure_codes: list[str]

    @property
    def passed(self) -> bool:
        return not self.failure_codes

    @property
    def reason_code(self) -> str | None:
        return self.failure_codes[0] if self.failure_codes else None

    @property
    def waiting_on(self) -> str | None:
        if not self.reason_code:
            return None
        for code, _, waiting_on in FAILURE_ORDER:
            if code == self.reason_code:
                return waiting_on
        return "final_gate"

    @property
    def exit_code(self) -> int:
        return PASS_EXIT_CODE if self.passed else FAIL_EXIT_CODE

    def to_machine_summary(self) -> dict[str, Any]:
        return {
            "status": "PASSED" if self.passed else "FAILED",
            "repo": self.repo,
            "pr_number": self.pr_number,
            "item_id": None,
            "item_kind": None,
            "counts": dict(self.counts),
            "artifact_path": None,
            "reason_code": self.reason_code,
            "waiting_on": self.waiting_on,
            "next_action": _next_action(self.reason_code),
            "exit_code": self.exit_code,
            "failure_codes": list(self.failure_codes),
        }


def evaluate_final_gate(
    session: Mapping[str, Any],
    *,
    remote_threads: Iterable[Mapping[str, Any]] = (),
    pending_reviews: Iterable[Mapping[str, Any]] = (),
    current_login: str | None = None,
) -> GateResult:
    items = _session_items(session)
    github_items = [item for item in items if _item_kind(item) == "github_thread"]
    local_items = [item for item in items if _item_kind(item) == "local_finding"]

    remote_thread_rows = list(remote_threads)
    remote_by_id = {
        thread_id: thread
        for thread in remote_thread_rows
        if (thread_id := _thread_identifier(thread))
    }
    unresolved_remote_threads = [thread for thread in remote_thread_rows if not _thread_is_resolved(thread)]
    pending_current_login_reviews = [
        review for review in pending_reviews if _is_current_login_pending_review(review, current_login)
    ]
    blocking_local_items = [item for item in local_items if _is_local_blocking(item)]
    blocking_items = [item for item in items if _is_blocking_item(item)]
    missing_reply_items = [
        item for item in github_items if _github_thread_requires_reply_evidence(item, remote_by_id) and not _has_reply_evidence(item, current_login)
    ]
    missing_validation_items = [
        item for item in local_items if _is_terminal_local_item(item) and not _has_validation_evidence(item)
    ]

    counts = {
        "unresolved_github_threads_count": len(unresolved_remote_threads),
        "pending_review_count": len(pending_current_login_reviews),
        "blocking_items_count": len(blocking_items),
        "github_threads_missing_reply_count": len(missing_reply_items),
        "missing_validation_evidence_count": len(missing_validation_items),
        "blocking_local_items_count": len(blocking_local_items),
        "pending_current_login_review_count": len(pending_current_login_reviews),
        "unresolved_remote_threads_count": len(unresolved_remote_threads),
    }
    failure_codes = [code for code, count_key, _ in FAILURE_ORDER if counts[count_key] > 0]

    return GateResult(
        repo=str(session.get("repo") or ""),
        pr_number=str(session.get("pr_number") or ""),
        counts={key: counts[key] for key in COUNT_KEYS},
        failure_codes=failure_codes,
    )


def _session_items(session: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw_items = session.get("items") or {}
    if isinstance(raw_items, Mapping):
        return [item for item in raw_items.values() if isinstance(item, Mapping)]
    return [item for item in raw_items if isinstance(item, Mapping)]


def _item_kind(item: Mapping[str, Any]) -> str:
    return str(item.get("item_kind") or item.get("kind") or "").lower()


def _state(item: Mapping[str, Any]) -> str:
    return str(item.get("state") or item.get("status") or "").lower()


def _thread_identifier(row: Mapping[str, Any]) -> str | None:
    for key in ("thread_id", "remote_thread_id", "github_thread_id", "id", "node_id"):
        value = row.get(key)
        if value:
            return str(value)
    item_id = row.get("item_id")
    if isinstance(item_id, str) and item_id.startswith("github-thread:"):
        return item_id.split(":", 1)[1]
    return None


def _thread_is_resolved(thread: Mapping[str, Any]) -> bool:
    if "isResolved" in thread:
        return bool(thread["isResolved"])
    if "is_resolved" in thread:
        return bool(thread["is_resolved"])
    return _state(thread) in GITHUB_TERMINAL_STATES


def _github_thread_requires_reply_evidence(
    item: Mapping[str, Any],
    remote_by_id: Mapping[str, Mapping[str, Any]],
) -> bool:
    thread_id = _thread_identifier(item)
    if thread_id and thread_id in remote_by_id:
        return _thread_is_resolved(remote_by_id[thread_id])
    return _state(item) in GITHUB_TERMINAL_STATES


def _has_reply_evidence(item: Mapping[str, Any], current_login: str | None) -> bool:
    evidence = item.get("reply_evidence")
    if isinstance(evidence, Mapping):
        reply_url = evidence.get("reply_url") or evidence.get("url") or evidence.get("external_url")
        author_login = evidence.get("author_login") or evidence.get("login")
        if not author_login and isinstance(evidence.get("author"), Mapping):
            author_login = evidence["author"].get("login")
        return bool(reply_url) and _login_matches(author_login, current_login)

    reply_url = item.get("reply_url") or item.get("reply_evidence_url")
    reply_posted = item.get("reply_posted", True)
    author_login = item.get("reply_author_login")
    return bool(reply_url) and bool(reply_posted) and _login_matches(author_login, current_login)


def _login_matches(author_login: Any, current_login: str | None) -> bool:
    if not current_login or not author_login:
        return True
    return str(author_login) == current_login


def _is_current_login_pending_review(review: Mapping[str, Any], current_login: str | None) -> bool:
    if str(review.get("state") or "").upper() != "PENDING":
        return False
    if not current_login:
        return True
    return _review_login(review) == current_login


def _review_login(review: Mapping[str, Any]) -> str | None:
    if review.get("author_login"):
        return str(review["author_login"])
    if isinstance(review.get("user"), Mapping) and review["user"].get("login"):
        return str(review["user"]["login"])
    if isinstance(review.get("author"), Mapping) and review["author"].get("login"):
        return str(review["author"]["login"])
    if review.get("login"):
        return str(review["login"])
    return None


def _is_local_blocking(item: Mapping[str, Any]) -> bool:
    if "blocking" in item:
        return bool(item["blocking"])
    return _state(item) not in LOCAL_TERMINAL_STATES


def _is_blocking_item(item: Mapping[str, Any]) -> bool:
    if _item_kind(item) == "local_finding":
        return _is_local_blocking(item)
    return bool(item.get("blocking"))


def _is_terminal_local_item(item: Mapping[str, Any]) -> bool:
    return _state(item) in LOCAL_TERMINAL_STATES


def _has_validation_evidence(item: Mapping[str, Any]) -> bool:
    for key in ("validation_evidence", "validation_commands", "validation_results"):
        if _has_content(item.get(key)):
            return True
    evidence = item.get("evidence")
    if isinstance(evidence, Mapping):
        return _has_content(evidence.get("validation")) or _has_content(evidence.get("validation_evidence"))
    return False


def _has_content(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, Mapping):
        return bool(value)
    if isinstance(value, Iterable):
        return any(True for _ in value)
    return bool(value)


def _next_action(reason_code: str | None) -> str:
    if reason_code is None:
        return "Completion may be claimed."
    if reason_code == FINAL_GATE_UNRESOLVED_REMOTE_THREADS:
        return "Resolve all remote GitHub review threads, then rerun final-gate."
    if reason_code == FINAL_GATE_MISSING_REPLY_EVIDENCE:
        return "Record durable reply evidence for terminal GitHub threads, then rerun final-gate."
    if reason_code == FINAL_GATE_PENDING_CURRENT_LOGIN_REVIEW:
        return "Submit or dismiss pending reviews for the current GitHub login, then rerun final-gate."
    if reason_code == FINAL_GATE_BLOCKING_LOCAL_ITEMS:
        return "Close or explicitly defer blocking local items, then rerun final-gate."
    if reason_code == FINAL_GATE_MISSING_VALIDATION_EVIDENCE:
        return "Record validation evidence for terminal local findings, then rerun final-gate."
    return "Inspect final-gate diagnostics, fix blockers, then rerun final-gate."
