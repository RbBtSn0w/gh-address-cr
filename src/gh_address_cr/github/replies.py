from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from gh_address_cr.evidence.ledger import EvidenceLedger, SideEffectAttempt


class GitHubTransientError(RuntimeError):
    pass


class GitHubPermanentError(RuntimeError):
    pass


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    immediate_retries: int = 1
    backoff_seconds: int = 60


def _parse_timestamp(value: str) -> datetime:
    if value.endswith("Z"):
        value = f"{value[:-1]}+00:00"
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _resume_token(session_id: str, item_id: str, side_effect_type: str) -> str:
    return f"resume:{session_id}:{item_id}:{side_effect_type}"


class ReplyPublisher:
    def __init__(
        self,
        ledger: EvidenceLedger,
        *,
        post_reply: Callable[[str, str], str],
        retry_policy: RetryPolicy | None = None,
    ):
        self.ledger = ledger
        self._post_reply = post_reply
        self.retry_policy = retry_policy or RetryPolicy()

    def post_reply(
        self,
        *,
        session_id: str,
        item_id: str,
        lease_id: str | None,
        agent_id: str,
        thread_id: str,
        body: str,
        idempotency_key: str,
        timestamp: str,
    ) -> dict:
        existing_url = self.ledger.successful_side_effect_url(idempotency_key, "github_reply")
        if existing_url:
            return {
                "status": "succeeded",
                "reply_url": existing_url,
                "deduplicated": True,
                "idempotency_key": idempotency_key,
            }

        for attempt_number in range(1, self.retry_policy.max_attempts + 1):
            try:
                reply_url = self._post_reply(thread_id, body)
            except GitHubTransientError as exc:
                error = str(exc)
                if attempt_number <= self.retry_policy.immediate_retries and attempt_number < self.retry_policy.max_attempts:
                    self._record_attempt(
                        session_id=session_id,
                        item_id=item_id,
                        lease_id=lease_id,
                        agent_id=agent_id,
                        idempotency_key=idempotency_key,
                        status="retrying",
                        retry_count=attempt_number,
                        last_error=error,
                        timestamp=timestamp,
                    )
                    continue
                if attempt_number < self.retry_policy.max_attempts:
                    backoff_until = _format_timestamp(
                        _parse_timestamp(timestamp) + timedelta(seconds=self.retry_policy.backoff_seconds)
                    )
                    self._record_attempt(
                        session_id=session_id,
                        item_id=item_id,
                        lease_id=lease_id,
                        agent_id=agent_id,
                        idempotency_key=idempotency_key,
                        status="retrying",
                        retry_count=attempt_number,
                        backoff_until=backoff_until,
                        last_error=error,
                        timestamp=timestamp,
                    )
                    return {
                        "status": "retrying",
                        "backoff_until": backoff_until,
                        "resume_token": _resume_token(session_id, item_id, "github_reply"),
                        "error": error,
                    }

                self._record_attempt(
                    session_id=session_id,
                    item_id=item_id,
                    lease_id=lease_id,
                    agent_id=agent_id,
                    idempotency_key=idempotency_key,
                    status="blocked",
                    retry_count=attempt_number,
                    last_error=error,
                    timestamp=timestamp,
                )
                return {
                    "status": "blocked",
                    "resume_token": _resume_token(session_id, item_id, "github_reply"),
                    "error": error,
                }
            except GitHubPermanentError as exc:
                error = str(exc)
                self._record_attempt(
                    session_id=session_id,
                    item_id=item_id,
                    lease_id=lease_id,
                    agent_id=agent_id,
                    idempotency_key=idempotency_key,
                    status="failed",
                    retry_count=attempt_number,
                    last_error=error,
                    timestamp=timestamp,
                )
                return {"status": "failed", "error": error}

            if not isinstance(reply_url, str) or not reply_url.strip():
                error = "GitHub reply did not return a durable reply URL."
                self._record_attempt(
                    session_id=session_id,
                    item_id=item_id,
                    lease_id=lease_id,
                    agent_id=agent_id,
                    idempotency_key=idempotency_key,
                    status="failed",
                    retry_count=attempt_number - 1,
                    last_error=error,
                    timestamp=timestamp,
                )
                return {"status": "failed", "error": error}

            self._record_attempt(
                session_id=session_id,
                item_id=item_id,
                lease_id=lease_id,
                agent_id=agent_id,
                idempotency_key=idempotency_key,
                status="succeeded",
                retry_count=attempt_number - 1,
                external_url=reply_url,
                timestamp=timestamp,
            )
            self.ledger.append_event(
                session_id=session_id,
                item_id=item_id,
                lease_id=lease_id,
                agent_id=agent_id,
                role="publisher",
                event_type="reply_posted",
                payload={
                    "thread_id": thread_id,
                    "reply_url": reply_url,
                    "idempotency_key": idempotency_key,
                },
                timestamp=timestamp,
            )
            return {
                "status": "succeeded",
                "reply_url": reply_url,
                "deduplicated": False,
                "idempotency_key": idempotency_key,
            }

        return {"status": "blocked", "resume_token": _resume_token(session_id, item_id, "github_reply")}

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
        backoff_until: str | None = None,
        last_error: str | None = None,
        external_url: str | None = None,
    ) -> None:
        attempt = SideEffectAttempt.new(
            session_id=session_id,
            item_id=item_id,
            side_effect_type="github_reply",
            idempotency_key=idempotency_key,
            status=status,
            retry_count=retry_count,
            backoff_until=backoff_until,
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
