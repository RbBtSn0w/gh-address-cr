"""Typed runtime fact inputs for the review-resolution kernel."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

JsonDict = dict[str, Any]

RUNTIME_FACT_SCHEMA_VERSION = "1.0"
REVIEW_THREAD_OBSERVED = "review_thread_observed"
LOCAL_ITEM_OBSERVED = "local_item_observed"
PENDING_REVIEW_OBSERVED = "pending_review_observed"
CHECK_RUN_OBSERVED = "check_run_observed"
LOGIC_VALIDATION_OBSERVED = "logic_validation_observed"
COMMAND_EXECUTED = "command_executed"
REPORTING_OBSERVED = "reporting_observed"
SUPPORTED_FACT_KINDS = (
    REVIEW_THREAD_OBSERVED,
    LOCAL_ITEM_OBSERVED,
    PENDING_REVIEW_OBSERVED,
    CHECK_RUN_OBSERVED,
    LOGIC_VALIDATION_OBSERVED,
    COMMAND_EXECUTED,
    REPORTING_OBSERVED,
)
SUPPORTED_COMMAND_KINDS = frozenset({"reply_thread", "resolve_thread", "retry_command", "run_final_gate"})
SUPPORTED_COMMAND_EXECUTION_STATUSES = frozenset({"succeeded", "failed"})


def _require_string(payload: JsonDict, field_name: str) -> str:
    value = payload.get(field_name)
    if value is None:
        raise ValueError(f"{field_name} is required")
    if not isinstance(value, str) or value.strip() == "":
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _optional_string(payload: JsonDict, field_name: str) -> str | None:
    if field_name not in payload or payload[field_name] is None:
        return None
    value = payload[field_name]
    if not isinstance(value, str) or value.strip() == "":
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _require_payload(payload: JsonDict) -> JsonDict:
    value = payload.get("payload", {})
    if not isinstance(value, dict):
        raise ValueError("payload must be a JSON object")
    return dict(value)


def _optional_int(payload: JsonDict, field_name: str, default: int = 0) -> int:
    value = payload.get(field_name, default)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer")
    return value


def _parse_observed_at(value: str) -> datetime:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        raise ValueError(f"observed_at must be an RFC3339 timestamp with timezone: {value}") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"observed_at must include a timezone offset: {value}")
    return parsed.astimezone(timezone.utc)


def _optional_bool(payload: JsonDict, field_name: str) -> bool | None:
    if field_name not in payload or payload[field_name] is None:
        return None
    value = payload[field_name]
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be a boolean")
    return value


def _optional_bool_alias(payload: JsonDict, snake_name: str, camel_name: str) -> bool | None:
    snake_value = _optional_bool(payload, snake_name)
    camel_value = _optional_bool(payload, camel_name)
    if snake_value is not None and camel_value is not None and snake_value != camel_value:
        raise ValueError(f"{snake_name}/{camel_name} boolean fields conflict")
    return snake_value if snake_value is not None else camel_value


@dataclass(frozen=True)
class RuntimeFact:
    schema_version: str
    fact_kind: str
    fact_id: str
    observed_at: str
    sequence: int = 0
    payload: JsonDict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: JsonDict | "RuntimeFact") -> "RuntimeFact":
        if isinstance(payload, RuntimeFact):
            payload = payload.to_dict()
        schema_version = _require_string(payload, "schema_version")
        if schema_version != RUNTIME_FACT_SCHEMA_VERSION:
            raise ValueError(f"unsupported runtime fact schema_version: {schema_version}")
        fact_kind = _require_string(payload, "fact_kind")
        if fact_kind not in SUPPORTED_FACT_KINDS:
            raise ValueError(f"unsupported runtime fact kind: {fact_kind}")
        fact_id = _require_string(payload, "fact_id")
        observed_at = _require_string(payload, "observed_at")
        _parse_observed_at(observed_at)
        return cls(
            schema_version=schema_version,
            fact_kind=fact_kind,
            fact_id=fact_id,
            observed_at=observed_at,
            sequence=_optional_int(payload, "sequence"),
            payload=_require_payload(payload),
        )

    def sort_key(self) -> tuple[datetime, int, str]:
        return (_parse_observed_at(self.observed_at), self.sequence, self.fact_id)

    def to_dict(self) -> JsonDict:
        return {
            "schema_version": self.schema_version,
            "fact_kind": self.fact_kind,
            "fact_id": self.fact_id,
            "observed_at": self.observed_at,
            "sequence": self.sequence,
            "payload": dict(self.payload),
        }


def sort_runtime_facts(facts: list[JsonDict | RuntimeFact] | tuple[JsonDict | RuntimeFact, ...]) -> tuple[RuntimeFact, ...]:
    parsed_facts = tuple(RuntimeFact.from_dict(fact) for fact in facts)
    seen_keys = set()
    for fact in parsed_facts:
        sort_key = fact.sort_key()
        if sort_key in seen_keys:
            raise ValueError(f"duplicate runtime fact ordering key: {fact.fact_id}")
        seen_keys.add(sort_key)
    return tuple(sorted(parsed_facts, key=lambda fact: fact.sort_key()))


@dataclass(frozen=True)
class ReviewThreadFact:
    fact: RuntimeFact
    thread_id: str
    item_id: str
    payload: JsonDict

    @classmethod
    def from_runtime_fact(cls, fact: RuntimeFact) -> "ReviewThreadFact":
        if fact.fact_kind != REVIEW_THREAD_OBSERVED:
            raise ValueError(f"expected {REVIEW_THREAD_OBSERVED}, got {fact.fact_kind}")
        thread_id = _require_string(fact.payload, "thread_id")
        canonical_item_id = f"github-thread:{thread_id}"
        item_id = _optional_string(fact.payload, "item_id") or canonical_item_id
        if item_id != canonical_item_id:
            raise ValueError(f"ambiguous item_id for thread_id {thread_id}: {item_id}")
        payload = dict(fact.payload)
        resolved = _optional_bool_alias(payload, "is_resolved", "isResolved")
        outdated = _optional_bool_alias(payload, "is_outdated", "isOutdated")
        reply_evidence = _optional_bool(payload, "reply_evidence_present")
        external_wait = _optional_bool(payload, "external_wait")
        if resolved is not None:
            payload["is_resolved"] = resolved
            payload["isResolved"] = resolved
        if outdated is not None:
            payload["is_outdated"] = outdated
            payload["isOutdated"] = outdated
        if reply_evidence is not None:
            payload["reply_evidence_present"] = reply_evidence
        if external_wait is not None:
            payload["external_wait"] = external_wait
        return cls(fact=fact, thread_id=thread_id, item_id=item_id, payload=payload)

    def row(self) -> JsonDict:
        row = {
            "item_id": self.item_id,
            "item_kind": "github_thread",
            "thread_id": self.thread_id,
            "state": self.payload.get("state"),
            "status": self.payload.get("status"),
            "is_resolved": self.payload.get("is_resolved"),
            "isResolved": self.payload.get("isResolved"),
            "is_outdated": self.payload.get("is_outdated"),
            "isOutdated": self.payload.get("isOutdated"),
        }
        return {key: value for key, value in row.items() if value is not None}


@dataclass(frozen=True)
class CommandExecutionFact:
    fact: RuntimeFact
    command_id: str
    command_kind: str
    item_id: str | None
    status: str
    result_url: str | None = None
    payload: JsonDict = field(default_factory=dict)

    @classmethod
    def from_runtime_fact(cls, fact: RuntimeFact) -> "CommandExecutionFact":
        if fact.fact_kind != COMMAND_EXECUTED:
            raise ValueError(f"expected {COMMAND_EXECUTED}, got {fact.fact_kind}")
        command_id = _require_string(fact.payload, "command_id")
        command_kind = _require_string(fact.payload, "command_kind")
        if command_kind not in SUPPORTED_COMMAND_KINDS:
            raise ValueError(f"unsupported command execution kind: {command_kind}")
        status = _require_string(fact.payload, "status")
        if status not in SUPPORTED_COMMAND_EXECUTION_STATUSES:
            raise ValueError(f"unsupported command execution status: {status}")
        result_url = fact.payload.get("result_url")
        if result_url is not None and not isinstance(result_url, str):
            raise ValueError("result_url must be a string")
        return cls(
            fact=fact,
            command_id=command_id,
            command_kind=command_kind,
            item_id=_optional_string(fact.payload, "item_id"),
            status=status,
            result_url=result_url,
            payload=dict(fact.payload),
        )

    @property
    def succeeded(self) -> bool:
        return self.status == "succeeded"
