"""Typed runtime fact inputs for the review-resolution kernel."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


JsonDict = dict[str, Any]

RUNTIME_FACT_SCHEMA_VERSION = "1.0"
REVIEW_THREAD_OBSERVED = "review_thread_observed"
COMMAND_EXECUTED = "command_executed"
REPORTING_OBSERVED = "reporting_observed"
SUPPORTED_FACT_KINDS = (REVIEW_THREAD_OBSERVED, COMMAND_EXECUTED, REPORTING_OBSERVED)


def _require_string(payload: JsonDict, field_name: str) -> str:
    value = payload.get(field_name)
    if value is None or str(value).strip() == "":
        raise ValueError(f"{field_name} is required")
    return str(value)


def _require_payload(payload: JsonDict) -> JsonDict:
    value = payload.get("payload", {})
    if not isinstance(value, dict):
        raise ValueError("payload must be a JSON object")
    return dict(value)


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
            return payload
        schema_version = _require_string(payload, "schema_version")
        if schema_version != RUNTIME_FACT_SCHEMA_VERSION:
            raise ValueError(f"unsupported runtime fact schema_version: {schema_version}")
        fact_kind = _require_string(payload, "fact_kind")
        if fact_kind not in SUPPORTED_FACT_KINDS:
            raise ValueError(f"unsupported runtime fact kind: {fact_kind}")
        fact_id = _require_string(payload, "fact_id")
        observed_at = _require_string(payload, "observed_at")
        return cls(
            schema_version=schema_version,
            fact_kind=fact_kind,
            fact_id=fact_id,
            observed_at=observed_at,
            sequence=int(payload.get("sequence", 0)),
            payload=_require_payload(payload),
        )

    def sort_key(self) -> tuple[str, int, str]:
        return (self.observed_at, self.sequence, self.fact_id)

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
    return tuple(sorted((RuntimeFact.from_dict(fact) for fact in facts), key=lambda fact: fact.sort_key()))


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
        item_id = str(fact.payload.get("item_id") or canonical_item_id)
        if item_id != canonical_item_id:
            raise ValueError(f"ambiguous item_id for thread_id {thread_id}: {item_id}")
        return cls(fact=fact, thread_id=thread_id, item_id=item_id, payload=dict(fact.payload))

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
        status = _require_string(fact.payload, "status")
        return cls(
            fact=fact,
            command_id=command_id,
            command_kind=command_kind,
            item_id=fact.payload.get("item_id"),
            status=status,
            result_url=fact.payload.get("result_url"),
            payload=dict(fact.payload),
        )

    @property
    def succeeded(self) -> bool:
        return self.status == "succeeded"
