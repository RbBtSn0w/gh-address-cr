from __future__ import annotations

from datetime import datetime
from typing import Any

from gh_address_cr.core import session as session_store
from gh_address_cr.core.reply_templates import (
    clarify_reply as render_clarify_reply,
    defer_reply as render_defer_reply,
    fix_reply as render_fix_reply,
)
from gh_address_cr.core.severity import (
    review_priority_for_publish,
)
from gh_address_cr.core.errors import WorkflowError
from gh_address_cr.evidence.ledger import EvidenceLedger, SideEffectAttempt
from gh_address_cr.github.client import GitHubClient
from gh_address_cr.github.diagnostics import github_waiting_on
from gh_address_cr.github.errors import GitHubError
from gh_address_cr.core.utils import (
    coerce_now as _coerce_now,
    format_timestamp as _format_timestamp,
    get_session_items as _items,
    get_session_ledger as _ledger,
    normalize_string_list as _normalize_string_list,
    normalize_validation_commands as _normalize_validation_commands,
    fix_reply_severity_for_publish as _fix_reply_severity_for_publish,
)


def publish_github_thread_responses(
    repo: str,
    pr_number: str,
    *,
    github_client: Any | None = None,
    agent_id: str = "gh-address-cr-publisher",
    now: datetime | None = None,
) -> dict[str, Any]:
    current_time = _coerce_now(now)
    timestamp = _format_timestamp(current_time)
    _configure_publish_telemetry(repo, pr_number)
    session = session_store.load_session(repo, pr_number)
    ledger = _ledger(session)
    client = github_client or GitHubClient()
    publish_items = _publish_ready_items(session)
    if not publish_items:
        return {
            "status": "NO_PUBLISH_READY_ITEMS",
            "repo": repo,
            "pr_number": str(pr_number),
            "published_count": 0,
        }
    publisher_login = _publisher_login(client, fallback=agent_id)

    plans: list[dict[str, Any]] = []
    for item_id, item in publish_items:
        response = item.get("accepted_response")
        if not isinstance(response, dict):
            _record_publish_blocked(session, ledger, item_id, agent_id, "MISSING_ACCEPTED_RESPONSE")
            session_store.save_session(repo, pr_number, session)
            raise WorkflowError(
                status="PUBLISH_BLOCKED",
                reason_code="MISSING_ACCEPTED_RESPONSE",
                waiting_on="action_response",
                exit_code=5,
                message=f"Publish-ready item has no accepted response: {item_id}",
                payload={"item_id": item_id},
            )
        thread_id = _github_thread_id(item_id, item)
        if not thread_id:
            _record_publish_blocked(session, ledger, item_id, agent_id, "MISSING_THREAD_ID")
            session_store.save_session(repo, pr_number, session)
            raise WorkflowError(
                status="PUBLISH_BLOCKED",
                reason_code="MISSING_THREAD_ID",
                waiting_on="github_thread",
                exit_code=5,
                message=f"Publish-ready item has no GitHub thread id: {item_id}",
                payload={"item_id": item_id},
            )
        reply_body, error = publish_reply_body(item, response)
        if not reply_body:
            _record_publish_blocked(session, ledger, item_id, agent_id, error or "MISSING_PUBLISH_REPLY")
            session_store.save_session(repo, pr_number, session)
            raise WorkflowError(
                status="PUBLISH_BLOCKED",
                reason_code=error or "MISSING_PUBLISH_REPLY",
                waiting_on="reply_evidence",
                exit_code=5,
                message=f"Publish-ready item has no valid GitHub reply body: {item_id}",
                payload={"item_id": item_id},
            )
        plans.append(
            {"item_id": item_id, "item": item, "response": response, "thread_id": thread_id, "reply_body": reply_body}
        )

    published: list[str] = []
    for plan in plans:
        item_id = str(plan["item_id"])
        item = plan["item"]
        thread_id = str(plan["thread_id"])
        lease_id = item.get("active_lease_id")
        reply_url = item.get("reply_url") if item.get("reply_posted") else None
        reply_key = _side_effect_key(session, item_id, "github_reply")
        resolve_key = _side_effect_key(session, item_id, "github_resolve")
        existing_reply_url = ledger.successful_side_effect_url(reply_key, "github_reply")
        if existing_reply_url:
            reply_url = existing_reply_url
        if not reply_url:
            try:
                reply_url = client.post_reply(repo, str(pr_number), thread_id, str(plan["reply_body"]))
            except GitHubError as exc:
                _record_side_effect_attempt(
                    ledger,
                    session=session,
                    item_id=item_id,
                    lease_id=lease_id,
                    agent_id=agent_id,
                    side_effect_type="github_reply",
                    idempotency_key=reply_key,
                    status="failed",
                    timestamp=timestamp,
                    last_error=str(exc),
                )
                session_store.save_session(repo, pr_number, session)
                raise _publish_error(repo, pr_number, item_id, exc) from exc
            _record_side_effect_attempt(
                ledger,
                session=session,
                item_id=item_id,
                lease_id=lease_id,
                agent_id=agent_id,
                side_effect_type="github_reply",
                idempotency_key=reply_key,
                status="succeeded",
                timestamp=timestamp,
                external_url=reply_url,
            )
            ledger.append_event(
                session_id=str(session["session_id"]),
                item_id=item_id,
                lease_id=lease_id,
                agent_id=agent_id,
                role="publisher",
                event_type="reply_posted",
                payload={"thread_id": thread_id, "reply_url": reply_url, "idempotency_key": reply_key},
                timestamp=timestamp,
            )
        item["reply_posted"] = True
        item["reply_url"] = reply_url
        item["reply_evidence"] = {"reply_url": reply_url, "author_login": publisher_login}

        existing_resolve = ledger.successful_side_effect_url(resolve_key, "github_resolve")
        if not existing_resolve and not item.get("thread_resolved"):
            try:
                client.resolve_thread(repo, str(pr_number), thread_id)
            except GitHubError as exc:
                _record_side_effect_attempt(
                    ledger,
                    session=session,
                    item_id=item_id,
                    lease_id=lease_id,
                    agent_id=agent_id,
                    side_effect_type="github_resolve",
                    idempotency_key=resolve_key,
                    status="failed",
                    timestamp=timestamp,
                    last_error=str(exc),
                )
                session_store.save_session(repo, pr_number, session)
                raise _publish_error(repo, pr_number, item_id, exc) from exc
            _record_side_effect_attempt(
                ledger,
                session=session,
                item_id=item_id,
                lease_id=lease_id,
                agent_id=agent_id,
                side_effect_type="github_resolve",
                idempotency_key=resolve_key,
                status="succeeded",
                timestamp=timestamp,
                external_url=thread_id,
            )
            ledger.append_event(
                session_id=str(session["session_id"]),
                item_id=item_id,
                lease_id=lease_id,
                agent_id=agent_id,
                role="publisher",
                event_type="thread_resolved",
                payload={"thread_id": thread_id, "idempotency_key": resolve_key},
                timestamp=timestamp,
            )

        item["state"] = "closed"
        item["status"] = "CLOSED"
        item["blocking"] = False
        item["handled"] = True
        item["thread_resolved"] = True
        item["handled_at"] = timestamp
        item["claimed_by"] = None
        item["claimed_at"] = None
        item["lease_expires_at"] = None
        item.pop("active_lease_id", None)
        ledger.append_event(
            session_id=str(session["session_id"]),
            item_id=item_id,
            lease_id=lease_id,
            agent_id=agent_id,
            role="publisher",
            event_type="response_published",
            payload={"thread_id": thread_id, "reply_url": reply_url},
            timestamp=timestamp,
        )
        published.append(item_id)

    session_store.save_session(repo, pr_number, session)
    return {
        "status": "PUBLISH_COMPLETE",
        "repo": repo,
        "pr_number": str(pr_number),
        "published_count": len(published),
        "published_items": published,
    }


def _configure_publish_telemetry(repo: str, pr_number: str) -> None:
    try:
        from gh_address_cr.core.telemetry import SessionTelemetry

        SessionTelemetry.get_instance().configure_context(repo, pr_number)
    except Exception:
        return

def _publish_ready_items(session: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    ready: list[tuple[str, dict[str, Any]]] = []
    for item_id, item in _items(session).items():
        if item.get("item_kind") != "github_thread":
            continue
        if str(item.get("state") or "").lower() == "publish_ready":
            ready.append((item_id, item))
    return ready


def _publisher_login(client: Any, *, fallback: str) -> str:
    viewer_login = getattr(client, "viewer_login", None)
    if callable(viewer_login):
        try:
            login = str(viewer_login() or "").strip()
        except GitHubError:
            login = ""
        if login:
            return login
    return fallback


def _github_thread_id(item_id: str, item: dict[str, Any]) -> str:
    for key in ("thread_id", "origin_ref"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    if item_id.startswith("github-thread:"):
        return item_id.removeprefix("github-thread:").strip()
    return ""


def publish_reply_body(item: dict[str, Any], response: dict[str, Any]) -> tuple[str | None, str | None]:
    resolution = str(response.get("resolution") or item.get("publish_resolution") or "")
    reply_markdown = response.get("reply_markdown")

    if resolution != "fix":
        if not isinstance(reply_markdown, str) or not reply_markdown.strip():
            return None, "MISSING_PUBLISH_REPLY"
        if resolution == "clarify":
            return render_clarify_reply([reply_markdown.strip()]), None
        if resolution == "defer":
            return render_defer_reply([reply_markdown.strip()]), None
        return reply_markdown, None
    fix_reply = response.get("fix_reply")
    if not isinstance(fix_reply, dict):
        return None, "MISSING_PUBLISH_REPLY"
    commit_hash = str(fix_reply.get("commit_hash") or "").strip()
    if not commit_hash:
        return None, "MISSING_FIX_REPLY_COMMIT_HASH"
    files = _normalize_string_list(fix_reply.get("files") or response.get("files"))
    if not files:
        return None, "MISSING_FIX_REPLY_FILES"
    validation_commands = _normalize_validation_commands(response.get("validation_commands"))
    test_command = str(fix_reply.get("test_command") or " && ".join(validation_commands)).strip()
    test_result = str(fix_reply.get("test_result") or ("passed" if validation_commands else "")).strip()
    if not test_command:
        return None, "MISSING_FIX_REPLY_TEST_COMMAND"
    if not test_result:
        return None, "MISSING_FIX_REPLY_TEST_RESULT"
    severity, severity_error = _fix_reply_severity_for_publish(fix_reply, item)
    if severity_error:
        return None, severity_error
    why = str(fix_reply.get("why") or "Addressed the CR with targeted changes and validation evidence.").strip()
    summary = str(fix_reply.get("summary") or "").strip() or None
    review_priority, review_priority_note = review_priority_for_publish(item)
    try:
        return render_fix_reply(
            severity,
            [commit_hash, ",".join(files), test_command, test_result, why],
            summary=summary,
            review_priority=review_priority,
            review_priority_note=review_priority_note,
        ), None
    except SystemExit as exc:
        return None, str(exc) or "MISSING_PUBLISH_REPLY"




def _side_effect_key(session: dict[str, Any], item_id: str, side_effect_type: str) -> str:
    return f"{session['session_id']}:{item_id}:{side_effect_type}"


def _record_side_effect_attempt(
    ledger: EvidenceLedger,
    *,
    session: dict[str, Any],
    item_id: str,
    lease_id: str | None,
    agent_id: str,
    side_effect_type: str,
    idempotency_key: str,
    status: str,
    timestamp: str,
    external_url: str | None = None,
    last_error: str | None = None,
) -> None:
    attempt = SideEffectAttempt.new(
        session_id=str(session["session_id"]),
        item_id=item_id,
        side_effect_type=side_effect_type,
        idempotency_key=idempotency_key,
        status=status,
        retry_count=0,
        last_error=last_error,
        external_url=external_url,
        timestamp=timestamp,
    )
    ledger.record_side_effect_attempt(
        attempt=attempt,
        lease_id=lease_id,
        agent_id=agent_id,
        timestamp=timestamp,
    )


def _record_publish_blocked(
    session: dict[str, Any],
    ledger: EvidenceLedger,
    item_id: str,
    agent_id: str,
    reason_code: str,
) -> None:
    ledger.append_event(
        session_id=str(session["session_id"]),
        item_id=item_id,
        lease_id=None,
        agent_id=agent_id,
        role="publisher",
        event_type="publish_blocked",
        payload={"reason_code": reason_code},
    )


def _publish_error(repo: str, pr_number: str, item_id: str, exc: GitHubError) -> WorkflowError:
    payload = {"item_id": item_id, "retryable": exc.retryable, "repo": repo, "pr_number": str(pr_number)}
    if exc.diagnostics:
        payload["diagnostics"] = exc.diagnostics
    return WorkflowError(
        status="PUBLISH_BLOCKED",
        reason_code=exc.reason_code,
        waiting_on=github_waiting_on(exc.diagnostics),
        exit_code=5,
        message=f"GitHub publish failed for {item_id}: {exc}",
        payload=payload,
    )
