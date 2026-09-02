from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _stable_id(prefix: str, payload: dict[str, Any]) -> str:
    digest = hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()[:20]
    return f"{prefix}_{digest}"


def payload_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class EvidenceRecord:
    record_id: str
    timestamp: str
    session_id: str
    item_id: str
    lease_id: str | None
    agent_id: str
    role: str
    event_type: str
    payload: dict[str, Any]
    payload_hash: str

    @classmethod
    def new(
        cls,
        *,
        session_id: str,
        item_id: str,
        lease_id: str | None,
        agent_id: str,
        role: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
        timestamp: str | None = None,
    ) -> "EvidenceRecord":
        normalized_payload = dict(payload or {})
        created_at = timestamp or _utc_now()
        digest = payload_hash(normalized_payload)
        record_id = _stable_id(
            "ev",
            {
                "timestamp": created_at,
                "session_id": session_id,
                "item_id": item_id,
                "lease_id": lease_id,
                "agent_id": agent_id,
                "role": role,
                "event_type": event_type,
                "payload_hash": digest,
            },
        )
        return cls(
            record_id=record_id,
            timestamp=created_at,
            session_id=session_id,
            item_id=item_id,
            lease_id=lease_id,
            agent_id=agent_id,
            role=role,
            event_type=event_type,
            payload=normalized_payload,
            payload_hash=digest,
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "timestamp": self.timestamp,
            "session_id": self.session_id,
            "item_id": self.item_id,
            "lease_id": self.lease_id,
            "agent_id": self.agent_id,
            "role": self.role,
            "event_type": self.event_type,
            "payload": self.payload,
            "payload_hash": self.payload_hash,
        }

    @classmethod
    def from_json(cls, value: dict[str, Any]) -> "EvidenceRecord":
        return cls(
            record_id=str(value["record_id"]),
            timestamp=str(value["timestamp"]),
            session_id=str(value["session_id"]),
            item_id=str(value["item_id"]),
            lease_id=value.get("lease_id"),
            agent_id=str(value["agent_id"]),
            role=str(value["role"]),
            event_type=str(value["event_type"]),
            payload=dict(value.get("payload") or {}),
            payload_hash=str(value["payload_hash"]),
        )


@dataclass(frozen=True)
class SideEffectAttempt:
    attempt_id: str
    session_id: str
    item_id: str
    side_effect_type: str
    idempotency_key: str
    status: str
    retry_count: int
    backoff_until: str | None = None
    last_error: str | None = None
    external_url: str | None = None

    @classmethod
    def new(
        cls,
        *,
        session_id: str,
        item_id: str,
        side_effect_type: str,
        idempotency_key: str,
        status: str,
        retry_count: int = 0,
        backoff_until: str | None = None,
        last_error: str | None = None,
        external_url: str | None = None,
        timestamp: str | None = None,
    ) -> "SideEffectAttempt":
        attempt_id = _stable_id(
            "attempt",
            {
                "timestamp": timestamp or _utc_now(),
                "session_id": session_id,
                "item_id": item_id,
                "side_effect_type": side_effect_type,
                "idempotency_key": idempotency_key,
                "status": status,
                "retry_count": retry_count,
                "backoff_until": backoff_until,
                "last_error": last_error,
                "external_url": external_url,
            },
        )
        return cls(
            attempt_id=attempt_id,
            session_id=session_id,
            item_id=item_id,
            side_effect_type=side_effect_type,
            idempotency_key=idempotency_key,
            status=status,
            retry_count=retry_count,
            backoff_until=backoff_until,
            last_error=last_error,
            external_url=external_url,
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "attempt_id": self.attempt_id,
            "session_id": self.session_id,
            "item_id": self.item_id,
            "side_effect_type": self.side_effect_type,
            "idempotency_key": self.idempotency_key,
            "status": self.status,
            "retry_count": self.retry_count,
            "backoff_until": self.backoff_until,
            "last_error": self.last_error,
            "external_url": self.external_url,
        }

    @classmethod
    def from_json(cls, value: dict[str, Any]) -> "SideEffectAttempt":
        return cls(
            attempt_id=str(value["attempt_id"]),
            session_id=str(value["session_id"]),
            item_id=str(value["item_id"]),
            side_effect_type=str(value["side_effect_type"]),
            idempotency_key=str(value["idempotency_key"]),
            status=str(value["status"]),
            retry_count=int(value.get("retry_count", 0)),
            backoff_until=value.get("backoff_until"),
            last_error=value.get("last_error"),
            external_url=value.get("external_url"),
        )


class EvidenceLedger:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _iter_records(self) -> Iterator[tuple[int, str]]:
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                stripped = line.strip()
                if stripped:
                    yield line_number, stripped

    @staticmethod
    def _record_from_line(line_number: int, line: str) -> EvidenceRecord:
        try:
            return EvidenceRecord.from_json(json.loads(line))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Invalid evidence ledger row {line_number}: {exc}") from exc

    def append(self, record: EvidenceRecord) -> EvidenceRecord:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record.to_json(), ensure_ascii=False, sort_keys=True, separators=(",", ":")))
            handle.write("\n")
        return record

    def append_event(
        self,
        *,
        session_id: str,
        item_id: str,
        lease_id: str | None,
        agent_id: str,
        role: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
        timestamp: str | None = None,
    ) -> EvidenceRecord:
        return self.append(
            EvidenceRecord.new(
                session_id=session_id,
                item_id=item_id,
                lease_id=lease_id,
                agent_id=agent_id,
                role=role,
                event_type=event_type,
                payload=payload or {},
                timestamp=timestamp,
            )
        )

    def load(self, *, event_type: str | None = None) -> list[EvidenceRecord]:
        records: list[EvidenceRecord] = []
        for line_number, line in self._iter_records():
            record = self._record_from_line(line_number, line)
            if event_type is None or record.event_type == event_type:
                records.append(record)
        return records

    def record_lease_event(
        self,
        *,
        event_type: str,
        session_id: str,
        item_id: str,
        lease_id: str,
        agent_id: str,
        role: str,
        reason: str,
        timestamp: str | None = None,
    ) -> EvidenceRecord:
        return self.append_event(
            session_id=session_id,
            item_id=item_id,
            lease_id=lease_id,
            agent_id=agent_id,
            role=role,
            event_type=event_type,
            payload={"reason": reason},
            timestamp=timestamp,
        )

    def record_side_effect_attempt(
        self,
        *,
        attempt: SideEffectAttempt,
        lease_id: str | None,
        agent_id: str,
        role: str = "publisher",
        timestamp: str | None = None,
    ) -> EvidenceRecord:
        return self.append_event(
            session_id=attempt.session_id,
            item_id=attempt.item_id,
            lease_id=lease_id,
            agent_id=agent_id,
            role=role,
            event_type="side_effect_attempt",
            payload=attempt.to_json(),
            timestamp=timestamp,
        )

    def successful_side_effect_url(self, idempotency_key: str, side_effect_type: str | None = None) -> str | None:
        latest_successful_url: str | None = None
        for line_number, line in self._iter_records():
            record = self._record_from_line(line_number, line)
            if record.event_type != "side_effect_attempt":
                continue
            attempt = SideEffectAttempt.from_json(record.payload)
            if idempotency_key is not None and attempt.idempotency_key != idempotency_key:
                continue
            if side_effect_type is not None and attempt.side_effect_type != side_effect_type:
                continue
            if attempt.status == "succeeded" and attempt.external_url:
                latest_successful_url = attempt.external_url
        return latest_successful_url

    def latest_side_effect_status(self, idempotency_key: str, side_effect_type: str | None = None) -> str | None:
        """Status of the most recent attempt for a key, or None.

        Callers detect a dangling `in_flight` crash window by comparing the
        returned value to `"in_flight"`; this method only reports the status.
        """
        latest_status: str | None = None
        for line_number, line in self._iter_records():
            record = self._record_from_line(line_number, line)
            if record.event_type != "side_effect_attempt":
                continue
            attempt = SideEffectAttempt.from_json(record.payload)
            if idempotency_key is not None and attempt.idempotency_key != idempotency_key:
                continue
            if side_effect_type is not None and attempt.side_effect_type != side_effect_type:
                continue
            latest_status = attempt.status
        return latest_status
