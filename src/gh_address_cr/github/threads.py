from __future__ import annotations

from typing import Any, Callable

from gh_address_cr.evidence.audit import resolve_guard_error
from gh_address_cr.evidence.ledger import EvidenceLedger, SideEffectAttempt


def _connection_nodes(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        nodes = value.get("nodes")
        if isinstance(nodes, list):
            return [node for node in nodes if isinstance(node, dict)]
    if isinstance(value, list):
        return [node for node in value if isinstance(node, dict)]
    return []


def _thread_comments(node: dict[str, Any]) -> list[dict[str, Any]]:
    comments = _connection_nodes(node.get("comments"))
    if comments:
        return comments
    first = _connection_nodes(node.get("firstComment"))
    latest = _connection_nodes(node.get("latestComment"))
    if latest and (not first or latest[-1] != first[0]):
        return [*first, *latest]
    return first or latest


def _author_login(comment: dict[str, Any]) -> str | None:
    author = comment.get("author")
    if isinstance(author, dict) and isinstance(author.get("login"), str):
        return author["login"]
    return None


def _viewer_reply_evidence(comments: list[dict[str, Any]], viewer_login: str | None) -> dict[str, str] | None:
    if not viewer_login:
        return None
    reply_url = None
    for comment in comments[1:]:
        if _author_login(comment) != viewer_login:
            continue
        url = comment.get("url")
        if isinstance(url, str) and url.strip():
            reply_url = url
    if not reply_url:
        return None
    return {"reply_url": reply_url, "author_login": viewer_login}


def normalize_thread(node: dict[str, Any], *, viewer_login: str | None = None) -> dict[str, Any]:
    thread_id = str(node["id"])
    comments = _thread_comments(node)
    latest_comment = comments[-1] if comments else {}
    first_comment = comments[0] if comments else {}
    body = latest_comment.get("body") or first_comment.get("body") or ""
    url = latest_comment.get("url") or first_comment.get("url")
    return {
        "item_id": f"github-thread:{thread_id}",
        "item_kind": "github_thread",
        "source": "github",
        "thread_id": thread_id,
        "title": f"GitHub review thread {thread_id}",
        "body": str(body),
        "path": node.get("path"),
        "line": node.get("line"),
        "url": url,
        "is_resolved": bool(node.get("isResolved", node.get("is_resolved", False))),
        "is_outdated": bool(node.get("isOutdated", node.get("is_outdated", False))),
        "reply_evidence": _viewer_reply_evidence(comments, viewer_login),
    }


def normalize_threads(payload: dict[str, Any] | list[dict[str, Any]], *, viewer_login: str | None = None) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [normalize_thread(node, viewer_login=viewer_login) for node in payload]

    selected_viewer = viewer_login or payload.get("viewer_login")
    if isinstance(payload.get("threads"), list):
        return [normalize_thread(node, viewer_login=selected_viewer) for node in payload["threads"]]

    review_threads = (
        ((payload.get("data") or {}).get("repository") or {})
        .get("pullRequest", {})
        .get("reviewThreads", {})
    )
    nodes = review_threads.get("nodes") if isinstance(review_threads, dict) else None
    if isinstance(nodes, list):
        return [normalize_thread(node, viewer_login=selected_viewer) for node in nodes]
    raise ValueError("GitHub thread payload must include threads or reviewThreads.nodes.")


class ThreadStateProvider:
    def __init__(self, load_threads: Callable[[], dict[str, Any] | list[dict[str, Any]]], *, viewer_login: str | None = None):
        self._load_threads = load_threads
        self.viewer_login = viewer_login

    def normalized_threads(self) -> list[dict[str, Any]]:
        return normalize_threads(self._load_threads(), viewer_login=self.viewer_login)


class ResolvePublisher:
    def __init__(self, ledger: EvidenceLedger, *, resolve_thread: Callable[[str], bool]):
        self.ledger = ledger
        self._resolve_thread = resolve_thread

    def resolve_thread(
        self,
        *,
        session_id: str,
        item_id: str,
        lease_id: str | None,
        agent_id: str,
        thread_id: str,
        idempotency_key: str,
        reply_evidence: dict[str, Any] | None,
        timestamp: str,
    ) -> dict[str, Any]:
        existing = self.ledger.successful_side_effect_url(idempotency_key, "github_resolve")
        if existing:
            return {"status": "succeeded", "resolved": True, "deduplicated": True}

        guard_error = resolve_guard_error(reply_evidence=reply_evidence)
        if guard_error:
            self._record_attempt(
                session_id=session_id,
                item_id=item_id,
                lease_id=lease_id,
                agent_id=agent_id,
                idempotency_key=idempotency_key,
                status="blocked",
                retry_count=0,
                last_error=guard_error,
                timestamp=timestamp,
            )
            return {"status": "blocked", "error": guard_error}

        resolved = bool(self._resolve_thread(thread_id))
        status = "succeeded" if resolved else "failed"
        self._record_attempt(
            session_id=session_id,
            item_id=item_id,
            lease_id=lease_id,
            agent_id=agent_id,
            idempotency_key=idempotency_key,
            status=status,
            retry_count=0,
            external_url=thread_id if resolved else None,
            timestamp=timestamp,
        )
        if resolved:
            self.ledger.append_event(
                session_id=session_id,
                item_id=item_id,
                lease_id=lease_id,
                agent_id=agent_id,
                role="publisher",
                event_type="thread_resolved",
                payload={
                    "thread_id": thread_id,
                    "idempotency_key": idempotency_key,
                    "reply_evidence": reply_evidence,
                },
                timestamp=timestamp,
            )
        return {"status": status, "resolved": resolved, "deduplicated": False}

    def _record_attempt(
        self,
        *,
        session_id: str,
        item_id: str,
        lease_id: str | None,
        agent_id: str,
        idempotency_key: str,
        status: str,
        retry_count: int,
        timestamp: str,
        last_error: str | None = None,
        external_url: str | None = None,
    ) -> None:
        attempt = SideEffectAttempt.new(
            session_id=session_id,
            item_id=item_id,
            side_effect_type="github_resolve",
            idempotency_key=idempotency_key,
            status=status,
            retry_count=retry_count,
            last_error=last_error,
            external_url=external_url,
            timestamp=timestamp,
        )
        self.ledger.record_side_effect_attempt(
            attempt=attempt,
            lease_id=lease_id,
            agent_id=agent_id,
            timestamp=timestamp,
        )
