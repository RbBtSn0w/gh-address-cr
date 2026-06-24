from __future__ import annotations

import subprocess
from datetime import datetime
from typing import Any

from gh_address_cr.core import protocol_codes
from gh_address_cr.core import session as session_store
from gh_address_cr.core.errors import WorkflowError
from gh_address_cr.core.reply_templates import (
    clarify_reply as render_clarify_reply,
)
from gh_address_cr.core.reply_templates import (
    defer_reply as render_defer_reply,
)
from gh_address_cr.core.reply_templates import (
    fix_reply as render_fix_reply,
)
from gh_address_cr.core.severity import (
    review_priority_for_publish,
)
from gh_address_cr.core.utils import (
    coerce_now as _coerce_now,
)
from gh_address_cr.core.utils import (
    fix_reply_severity_for_publish as _fix_reply_severity_for_publish,
)
from gh_address_cr.core.utils import (
    format_timestamp as _format_timestamp,
)
from gh_address_cr.core.utils import (
    get_session_items as _items,
)
from gh_address_cr.core.utils import (
    get_session_ledger as _ledger,
)
from gh_address_cr.core.utils import (
    normalize_string_list as _normalize_string_list,
)
from gh_address_cr.core.utils import (
    normalize_validation_commands as _normalize_validation_commands,
)
from gh_address_cr.evidence.ledger import EvidenceLedger, SideEffectAttempt
from gh_address_cr.github.client import GitHubClient
from gh_address_cr.github.diagnostics import github_waiting_on
from gh_address_cr.github.errors import GitHubError


def _build_publish_plans(
    session: dict[str, Any],
    ledger: Any,
    publish_items: list[tuple[str, dict[str, Any]]],
    repo: str,
    pr_number: str,
    agent_id: str,
) -> list[dict[str, Any]]:
    default_commit_hash = None
    plans: list[dict[str, Any]] = []
    for item_id, item in publish_items:
        response = item.get("accepted_response")
        if not isinstance(response, dict):
            _record_publish_blocked(session, ledger, item_id, agent_id, "MISSING_ACCEPTED_RESPONSE")
            session_store.save_session(repo, pr_number, session)
            raise WorkflowError(
                status=protocol_codes.PUBLISH_BLOCKED,
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
                status=protocol_codes.PUBLISH_BLOCKED,
                reason_code="MISSING_THREAD_ID",
                waiting_on="github_thread",
                exit_code=5,
                message=f"Publish-ready item has no GitHub thread id: {item_id}",
                payload={"item_id": item_id},
            )
        resolved_commit_hash = ""
        need_default = False
        if isinstance(response, dict):
            fix_reply = response.get("fix_reply")
            if isinstance(fix_reply, dict):
                if not str(fix_reply.get("commit_hash") or "").strip():
                    if not _item_commit_hash(item):
                        need_default = True

        if need_default:
            if default_commit_hash is None:
                default_commit_hash = _default_commit_hash_for_publish(session)
            resolved_commit_hash = default_commit_hash

        hydrated_response = _hydrate_publish_response(session, item, response, default_commit_hash=resolved_commit_hash)
        reply_body, error = publish_reply_body(item, hydrated_response)
        if not reply_body:
            _record_publish_blocked(session, ledger, item_id, agent_id, error or protocol_codes.MISSING_PUBLISH_REPLY)
            session_store.save_session(repo, pr_number, session)
            raise WorkflowError(
                status=protocol_codes.PUBLISH_BLOCKED,
                reason_code=error or protocol_codes.MISSING_PUBLISH_REPLY,
                waiting_on="reply_evidence",
                exit_code=5,
                message=f"Publish-ready item has no valid GitHub reply body: {item_id}",
                payload={"item_id": item_id},
            )
        plans.append(
            {
                "item_id": item_id,
                "item": item,
                "response": hydrated_response,
                "thread_id": thread_id,
                "reply_body": reply_body,
            }
        )
    return plans


def _execute_single_publish_plan(
    plan: dict[str, Any],
    repo: str,
    pr_number: str,
    session: dict[str, Any],
    ledger: Any,
    client: Any,
    publisher_login: str,
    agent_id: str,
    timestamp: str,
) -> str:
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
    return item_id


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

    plans = _build_publish_plans(session, ledger, publish_items, repo, pr_number, agent_id)

    published: list[str] = []
    for plan in plans:
        item_id = _execute_single_publish_plan(
            plan,
            repo,
            pr_number,
            session,
            ledger,
            client,
            publisher_login,
            agent_id,
            timestamp,
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
    from gh_address_cr.core.telemetry import configure_context_safely

    configure_context_safely(repo, pr_number)


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


def validate_fix_reply_for_submit(item: dict[str, Any], response: dict[str, Any]) -> str | None:
    fix_reply = response.get("fix_reply")
    if not isinstance(fix_reply, dict):
        return protocol_codes.MISSING_PUBLISH_REPLY
    files = _normalize_string_list(fix_reply.get("files") or response.get("files"))
    if not files:
        return "MISSING_FIX_REPLY_FILES"
    validation_commands = _normalize_validation_commands(response.get("validation_commands"))
    test_command = str(fix_reply.get("test_command") or " && ".join(validation_commands)).strip()
    test_result = str(fix_reply.get("test_result") or ("passed" if validation_commands else "")).strip()
    if not test_command:
        return "MISSING_FIX_REPLY_TEST_COMMAND"
    if not test_result:
        return "MISSING_FIX_REPLY_TEST_RESULT"
    _, severity_error = _fix_reply_severity_for_publish(fix_reply, item)
    if severity_error:
        return severity_error
    return None


def _hydrate_publish_response(
    session: dict[str, Any],
    item: dict[str, Any],
    response: dict[str, Any],
    *,
    default_commit_hash: str,
) -> dict[str, Any]:
    hydrated = dict(response)
    fix_reply = hydrated.get("fix_reply")
    if not isinstance(fix_reply, dict):
        return hydrated
    hydrated_fix_reply = dict(fix_reply)
    if not str(hydrated_fix_reply.get("commit_hash") or "").strip():
        commit_hash = _item_commit_hash(item) or default_commit_hash
        if commit_hash:
            hydrated_fix_reply["commit_hash"] = commit_hash
    hydrated["fix_reply"] = hydrated_fix_reply
    return hydrated


def _default_commit_hash_for_publish(session: dict[str, Any]) -> str:
    return _commit_hash_from_evidence(session.get("commit_evidence")) or _git_head_commit()


def _item_commit_hash(item: dict[str, Any]) -> str:
    return _commit_hash_from_evidence(item.get("commit_evidence"))


def _commit_hash_from_evidence(source: Any) -> str:
    if not isinstance(source, dict):
        return ""
    for key in ("commit_hash", "head_sha", "sha"):
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _git_head_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def publish_reply_body(item: dict[str, Any], response: dict[str, Any]) -> tuple[str | None, str | None]:
    resolution = str(response.get("resolution") or item.get("publish_resolution") or "")
    reply_markdown = response.get("reply_markdown")

    if resolution != "fix":
        if not isinstance(reply_markdown, str) or not reply_markdown.strip():
            return None, protocol_codes.MISSING_PUBLISH_REPLY
        if resolution == "clarify":
            return render_clarify_reply([reply_markdown.strip()]), None
        if resolution == "defer":
            return render_defer_reply([reply_markdown.strip()]), None
        return reply_markdown, None
    fix_reply = response.get("fix_reply")
    if not isinstance(fix_reply, dict):
        return None, protocol_codes.MISSING_PUBLISH_REPLY
    submit_error = validate_fix_reply_for_submit(item, response)
    if submit_error:
        return None, submit_error
    commit_hash = str(fix_reply.get("commit_hash") or "").strip()
    if not commit_hash:
        return None, protocol_codes.MISSING_FIX_REPLY_COMMIT_HASH
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
        return None, str(exc) or protocol_codes.MISSING_PUBLISH_REPLY


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
        status=protocol_codes.PUBLISH_BLOCKED,
        reason_code=exc.reason_code,
        waiting_on=github_waiting_on(exc.diagnostics),
        exit_code=5,
        message=f"GitHub publish failed for {item_id}: {exc}",
        payload=payload,
    )
