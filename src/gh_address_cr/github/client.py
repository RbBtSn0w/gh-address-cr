from __future__ import annotations

import json
import subprocess
import time
from collections.abc import Callable
from typing import Any

from gh_address_cr.github.errors import (
    GitHubAuthError,
    GitHubError,
    GitHubNotFoundError,
    GitHubRateLimitError,
    GitHubTransientError,
)


Runner = Callable[[list[str]], subprocess.CompletedProcess]

TRANSIENT_MARKERS = (
    "502",
    "503",
    "temporary failure",
    "timeout",
    "timed out",
    "connection reset",
    "graphql error",
    "graphql failed",
)


class GitHubClient:
    def __init__(self, *, runner: Runner | None = None):
        self._runner = runner or self._default_runner

    def list_threads(self, repo: str, pr_number: str) -> list[dict[str, Any]]:
        owner, name = _split_repo(repo)
        try:
            viewer_login = self.viewer_login()
        except GitHubError:
            viewer_login = ""

        query = """query($owner:String!,$name:String!,$number:Int!,$after:String){
  repository(owner:$owner,name:$name){
    pullRequest(number:$number){
      reviewThreads(first:100, after:$after){
        pageInfo{ hasNextPage endCursor }
        nodes{
          id
          isResolved
          isOutdated
          path
          line
          comments(first:100){
            pageInfo{ hasNextPage endCursor }
            nodes{ url author{ login } }
          }
          firstComment: comments(first:1){ nodes{ url body } }
          latestComment: comments(last:1){ nodes{ url body } }
        }
      }
    }
  }
}"""

        threads: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            cmd = [
                "api",
                "graphql",
                "-f",
                f"query={query}",
                "-F",
                f"owner={owner}",
                "-F",
                f"name={name}",
                "-F",
                f"number={pr_number}",
            ]
            if cursor:
                cmd.extend(["-F", f"after={cursor}"])
            payload = self._read_json(cmd)
            review_threads = _review_threads(payload)
            for node in _connection_nodes(review_threads):
                comments_connection = node.get("comments") if isinstance(node.get("comments"), dict) else None
                comments = self._load_thread_comments(str(node["id"]), comments_connection) if comments_connection else []
                latest = _connection_nodes(node.get("latestComment"))
                first = _connection_nodes(node.get("firstComment"))
                latest_node = latest[0] if latest else {}
                first_node = first[0] if first else {}
                viewer_reply_checked = bool(viewer_login) and comments_connection is not None
                viewer_replied, viewer_reply_url = _viewer_reply_evidence(comments, viewer_login)
                threads.append(
                    {
                        "id": node["id"],
                        "isResolved": node.get("isResolved"),
                        "isOutdated": node.get("isOutdated"),
                        "path": node.get("path"),
                        "line": node.get("line"),
                        "url": latest_node.get("url") or first_node.get("url"),
                        "body": latest_node.get("body") or first_node.get("body"),
                        "comment_source": "latest" if latest else ("first" if first else "none"),
                        "first_url": first_node.get("url"),
                        "latest_url": latest_node.get("url"),
                        "first_body": first_node.get("body"),
                        "latest_body": latest_node.get("body"),
                        "viewer_reply_checked": viewer_reply_checked,
                        "viewer_replied": viewer_replied,
                        "viewer_reply_url": viewer_reply_url,
                    }
                )
            has_next_page, cursor = _comment_page_state(review_threads)
            if not has_next_page:
                return threads

    def post_reply(self, repo: str, pr_number: str, thread_id: str, body: str) -> str:
        _ = (repo, pr_number)
        query = (
            "mutation($threadId:ID!,$body:String!){ "
            "addPullRequestReviewThreadReply(input:{pullRequestReviewThreadId:$threadId,body:$body}){ "
            "comment{ url } } }"
        )
        payload = self._read_json(
            [
                "api",
                "graphql",
                "-f",
                f"query={query}",
                "-F",
                f"threadId={thread_id}",
                "-F",
                f"body={body}",
            ]
        )
        reply_url = (
            payload.get("data", {})
            .get("addPullRequestReviewThreadReply", {})
            .get("comment", {})
            .get("url")
        )
        if not isinstance(reply_url, str) or not reply_url.strip():
            raise GitHubError("GITHUB_INCOMPLETE_RESPONSE", "GitHub reply response did not include comment.url.")
        return reply_url

    def resolve_thread(self, repo: str, pr_number: str, thread_id: str) -> bool:
        _ = (repo, pr_number)
        query = "mutation($threadId:ID!){ resolveReviewThread(input:{threadId:$threadId}) { thread { id isResolved } } }"
        payload = self._read_json(
            [
                "api",
                "graphql",
                "-f",
                f"query={query}",
                "-F",
                f"threadId={thread_id}",
            ]
        )
        resolved = (
            payload.get("data", {})
            .get("resolveReviewThread", {})
            .get("thread", {})
            .get("isResolved")
        )
        if resolved is not True:
            raise GitHubError("GITHUB_INCOMPLETE_RESPONSE", "GitHub resolve response did not confirm isResolved=true.")
        return True

    def list_pending_reviews(self, repo: str, pr_number: str, login: str | None = None) -> list[dict[str, Any]]:
        page = 1
        pending: list[dict[str, Any]] = []
        while True:
            payload = self._read_json(["api", f"repos/{repo}/pulls/{pr_number}/reviews?per_page=100&page={page}"])
            if not isinstance(payload, list):
                raise GitHubError("GITHUB_INCOMPLETE_RESPONSE", "GitHub reviews response must be a JSON array.")
            if not payload:
                return pending
            for review in payload:
                if not isinstance(review, dict):
                    continue
                if str(review.get("state") or "").upper() != "PENDING":
                    continue
                review_login = _review_login(review)
                if login and review_login != login:
                    continue
                pending.append(review)
            page += 1

    def viewer_login(self) -> str:
        payload = self._read_json(["api", "user"])
        login = payload.get("login")
        if not isinstance(login, str) or not login.strip():
            raise GitHubError("GITHUB_INCOMPLETE_RESPONSE", "GitHub user response did not include login.")
        return login

    def _load_thread_comments(self, thread_id: str, initial_connection: dict[str, Any] | None) -> list[dict[str, Any]]:
        comments = _connection_nodes(initial_connection)
        has_next_page, cursor = _comment_page_state(initial_connection)
        if not has_next_page:
            return comments

        query = """query($threadId:ID!,$after:String){
  node(id:$threadId){
    ... on PullRequestReviewThread{
      comments(first:100, after:$after){
        pageInfo{ hasNextPage endCursor }
        nodes{ url author{ login } }
      }
    }
  }
}"""
        seen_cursors: set[str | None] = set()
        while has_next_page and cursor not in seen_cursors:
            seen_cursors.add(cursor)
            cmd = ["api", "graphql", "-f", f"query={query}", "-F", f"threadId={thread_id}"]
            if cursor:
                cmd.extend(["-F", f"after={cursor}"])
            payload = self._read_json(cmd)
            node = ((payload.get("data") or {}).get("node") or {})
            comment_connection = node.get("comments") if isinstance(node, dict) else {}
            comments.extend(_connection_nodes(comment_connection))
            has_next_page, cursor = _comment_page_state(comment_connection)
        return comments

    def _read_json(self, args: list[str], *, retries: int = 1) -> Any:
        result = self._run_gh(args, retries=retries)
        if result.returncode != 0:
            _raise_classified_error(result.stderr, result.stdout, result.returncode)
        try:
            payload = json.loads(result.stdout or "{}")
        except json.JSONDecodeError as exc:
            raise GitHubError("GITHUB_INVALID_JSON", f"GitHub response was not valid JSON: {exc}") from exc
        if isinstance(payload, dict):
            errors = payload.get("errors")
            if errors:
                _raise_classified_error(_format_graphql_errors(errors), result.stdout, result.returncode)
        return payload

    def _run_gh(self, args: list[str], *, retries: int) -> subprocess.CompletedProcess:
        cmd = ["gh", *args]
        attempts = max(1, retries)
        for attempt in range(attempts):
            try:
                result = self._runner(cmd)
            except FileNotFoundError as exc:
                raise GitHubError("GITHUB_CLI_MISSING", "Missing GitHub CLI `gh` on PATH.") from exc
            if result.returncode == 0 or not _is_transient(result.stderr, result.stdout):
                return result
            if attempt < attempts - 1:
                time.sleep(2**attempt)
        return result

    @staticmethod
    def _default_runner(cmd: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(cmd, text=True, capture_output=True, check=False)


def _split_repo(repo: str) -> tuple[str, str]:
    if "/" not in repo:
        raise GitHubError("INVALID_REPOSITORY", f"Repository must be owner/name: {repo}")
    owner, name = repo.split("/", 1)
    if not owner or not name:
        raise GitHubError("INVALID_REPOSITORY", f"Repository must be owner/name: {repo}")
    return owner, name


def _review_threads(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        review_threads = payload["data"]["repository"]["pullRequest"]["reviewThreads"]
    except KeyError as exc:
        raise GitHubError("GITHUB_INCOMPLETE_RESPONSE", "GitHub response did not include reviewThreads.") from exc
    if not isinstance(review_threads, dict):
        raise GitHubError("GITHUB_INCOMPLETE_RESPONSE", "GitHub reviewThreads response must be an object.")
    return review_threads


def _connection_nodes(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, dict):
        return []
    nodes = value.get("nodes")
    if not isinstance(nodes, list):
        return []
    return [node for node in nodes if isinstance(node, dict)]


def _comment_page_state(connection: dict[str, Any] | None) -> tuple[bool, str | None]:
    if not isinstance(connection, dict):
        return False, None
    page_info = connection.get("pageInfo")
    if not isinstance(page_info, dict):
        return False, None
    cursor = page_info.get("endCursor")
    return bool(page_info.get("hasNextPage")), cursor if isinstance(cursor, str) and cursor else None


def _viewer_reply_evidence(comments: list[dict[str, Any]], viewer_login: str) -> tuple[bool, str | None]:
    if not viewer_login:
        return False, None
    viewer_reply_url = None
    for comment in comments[1:]:
        author = comment.get("author")
        author_login = author.get("login") if isinstance(author, dict) else None
        comment_url = comment.get("url")
        if author_login == viewer_login and isinstance(comment_url, str) and comment_url.strip():
            viewer_reply_url = comment_url
    return bool(viewer_reply_url), viewer_reply_url


def _review_login(review: dict[str, Any]) -> str | None:
    for key in ("author_login", "login"):
        value = review.get(key)
        if isinstance(value, str) and value:
            return value
    user = review.get("user")
    if isinstance(user, dict) and isinstance(user.get("login"), str):
        return user["login"]
    author = review.get("author")
    if isinstance(author, dict) and isinstance(author.get("login"), str):
        return author["login"]
    return None


def _format_graphql_errors(errors: Any) -> str:
    if not isinstance(errors, list):
        return str(errors)
    messages = [str(error.get("message") or "").strip() for error in errors if isinstance(error, dict)]
    return "; ".join(message for message in messages if message) or "GraphQL request failed."


def _raise_classified_error(stderr: str | None, stdout: str | None, returncode: int | None) -> None:
    detail = (stderr or stdout or "GitHub command failed.").strip()
    text = detail.lower()
    if "authentication" in text or "gh auth login" in text or "bad credentials" in text or "401" in text:
        raise GitHubAuthError(detail)
    if "rate limit" in text or "secondary rate" in text:
        raise GitHubRateLimitError(detail)
    if "not found" in text or "could not resolve to a node" in text or "404" in text:
        raise GitHubNotFoundError(detail)
    if _is_transient(stderr, stdout):
        raise GitHubTransientError(detail)
    raise GitHubError("GITHUB_API_FAILED", detail, retryable=False)


def _is_transient(stderr: str | None, stdout: str | None) -> bool:
    text = f"{stderr or ''}\n{stdout or ''}".lower()
    return any(marker in text for marker in TRANSIENT_MARKERS)
