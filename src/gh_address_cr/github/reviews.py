from __future__ import annotations

from typing import Any, Callable


def normalize_pending_reviews(payload: dict[str, Any] | list[dict[str, Any]], *, viewer_login: str | None = None) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        reviews = payload
    else:
        reviews = payload.get("reviews") or payload.get("nodes") or []
    normalized = []
    for review in reviews:
        if not isinstance(review, dict):
            continue
        author = review.get("author")
        author_login = author.get("login") if isinstance(author, dict) else review.get("author_login")
        state = str(review.get("state") or review.get("status") or "").upper()
        if viewer_login and author_login != viewer_login:
            continue
        if state == "PENDING":
            normalized.append(
                {
                    "review_id": review.get("id"),
                    "author_login": author_login,
                    "state": "PENDING",
                }
            )
    return normalized


class ReviewStateProvider:
    def __init__(self, load_reviews: Callable[[], dict[str, Any] | list[dict[str, Any]]], *, viewer_login: str | None = None):
        self._load_reviews = load_reviews
        self.viewer_login = viewer_login

    def pending_reviews(self) -> list[dict[str, Any]]:
        return normalize_pending_reviews(self._load_reviews(), viewer_login=self.viewer_login)
