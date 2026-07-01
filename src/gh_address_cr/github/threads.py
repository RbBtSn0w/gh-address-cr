from __future__ import annotations

from typing import Any, Callable


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
    first_body = first_comment.get("body") or ""
    latest_body = latest_comment.get("body") or ""
    first_url = first_comment.get("url")
    latest_url = latest_comment.get("url")
    row = {
        "item_id": f"github-thread:{thread_id}",
        "item_kind": "github_thread",
        "source": "github",
        "thread_id": thread_id,
        "title": f"GitHub review thread {thread_id}",
        "body": str(body),
        "path": node.get("path"),
        "line": node.get("line"),
        "url": url,
        "first_body": str(first_body),
        "first_url": first_url,
        "latest_body": str(latest_body),
        "latest_url": latest_url,
        "comment_source": "latest" if len(comments) > 1 else "first",
        "is_resolved": bool(node.get("isResolved", node.get("is_resolved", False))),
        "is_outdated": bool(node.get("isOutdated", node.get("is_outdated", False))),
        "reply_evidence": _viewer_reply_evidence(comments, viewer_login),
    }
    first_author_login = _author_login(first_comment)
    latest_author_login = _author_login(latest_comment)
    if first_author_login:
        row["first_author_login"] = first_author_login
    if latest_author_login:
        row["latest_author_login"] = latest_author_login
    return row


def normalize_threads(
    payload: dict[str, Any] | list[dict[str, Any]], *, viewer_login: str | None = None
) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [normalize_thread(node, viewer_login=viewer_login) for node in payload]

    selected_viewer = viewer_login or payload.get("viewer_login")
    if isinstance(payload.get("threads"), list):
        return [normalize_thread(node, viewer_login=selected_viewer) for node in payload["threads"]]

    review_threads = (
        ((payload.get("data") or {}).get("repository") or {}).get("pullRequest", {}).get("reviewThreads", {})
    )
    nodes = review_threads.get("nodes") if isinstance(review_threads, dict) else None
    if isinstance(nodes, list):
        return [normalize_thread(node, viewer_login=selected_viewer) for node in nodes]
    raise ValueError("GitHub thread payload must include threads or reviewThreads.nodes.")


class ThreadStateProvider:
    def __init__(
        self, load_threads: Callable[[], dict[str, Any] | list[dict[str, Any]]], *, viewer_login: str | None = None
    ):
        self._load_threads = load_threads
        self.viewer_login = viewer_login

    def normalized_threads(self) -> list[dict[str, Any]]:
        return normalize_threads(self._load_threads(), viewer_login=self.viewer_login)
