from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from gh_address_cr.agent.roles import AgentRole, parse_role


JsonDict = dict[str, Any]


def stable_payload_hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _string_tuple(values: Any) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, str):
        return (values,)
    return tuple(str(value) for value in values)


def _dict_copy(value: Any) -> JsonDict:
    if value is None:
        return {}
    return dict(value)


@dataclass(frozen=True)
class WorkItem:
    item_id: str
    item_kind: str
    source: str
    title: str
    body: str
    path: str | None = None
    line: int | None = None
    state: str = "open"
    allowed_actions: tuple[str, ...] = ()
    classification_evidence: JsonDict | None = None
    conflict_keys: tuple[str, ...] = ()
    reply_evidence: JsonDict | None = None
    validation_evidence: tuple[JsonDict, ...] = ()

    @classmethod
    def from_dict(cls, payload: JsonDict) -> "WorkItem":
        return cls(
            item_id=str(payload["item_id"]),
            item_kind=str(payload["item_kind"]),
            source=str(payload.get("source", "")),
            title=str(payload.get("title", "")),
            body=str(payload.get("body", "")),
            path=payload.get("path"),
            line=payload.get("line"),
            state=str(payload.get("state", "open")),
            allowed_actions=_string_tuple(payload.get("allowed_actions")),
            classification_evidence=payload.get("classification_evidence"),
            conflict_keys=_string_tuple(payload.get("conflict_keys")),
            reply_evidence=payload.get("reply_evidence"),
            validation_evidence=tuple(dict(record) for record in payload.get("validation_evidence", ())),
        )

    def to_dict(self) -> JsonDict:
        payload: JsonDict = {
            "item_id": self.item_id,
            "item_kind": self.item_kind,
            "source": self.source,
            "title": self.title,
            "body": self.body,
            "state": self.state,
            "allowed_actions": list(self.allowed_actions),
        }
        if self.path is not None:
            payload["path"] = self.path
        if self.line is not None:
            payload["line"] = self.line
        if self.classification_evidence is not None:
            payload["classification_evidence"] = dict(self.classification_evidence)
        if self.conflict_keys:
            payload["conflict_keys"] = list(self.conflict_keys)
        if self.reply_evidence is not None:
            payload["reply_evidence"] = dict(self.reply_evidence)
        if self.validation_evidence:
            payload["validation_evidence"] = [dict(record) for record in self.validation_evidence]
        return payload


@dataclass(frozen=True)
class ActionRequest:
    schema_version: str
    request_id: str
    session_id: str
    lease_id: str
    agent_role: AgentRole
    item: WorkItem
    allowed_actions: tuple[str, ...]
    required_evidence: tuple[str, ...]
    repository_context: JsonDict = field(default_factory=dict)
    resume_command: str | None = None
    forbidden_actions: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, payload: JsonDict) -> "ActionRequest":
        return cls(
            schema_version=str(payload.get("schema_version", "1.0")),
            request_id=str(payload["request_id"]),
            session_id=str(payload["session_id"]),
            lease_id=str(payload["lease_id"]),
            agent_role=parse_role(payload["agent_role"]),
            item=WorkItem.from_dict(payload["item"]),
            allowed_actions=_string_tuple(payload["allowed_actions"]),
            required_evidence=_string_tuple(payload["required_evidence"]),
            repository_context=_dict_copy(payload.get("repository_context")),
            resume_command=payload.get("resume_command"),
            forbidden_actions=_string_tuple(payload.get("forbidden_actions")),
        )

    def to_dict(self) -> JsonDict:
        payload: JsonDict = {
            "schema_version": self.schema_version,
            "request_id": self.request_id,
            "session_id": self.session_id,
            "lease_id": self.lease_id,
            "agent_role": self.agent_role.value,
            "item": self.item.to_dict(),
            "allowed_actions": list(self.allowed_actions),
            "required_evidence": list(self.required_evidence),
            "repository_context": dict(self.repository_context),
            "forbidden_actions": list(self.forbidden_actions),
        }
        if self.resume_command is not None:
            payload["resume_command"] = self.resume_command
        return payload

    def stable_hash(self) -> str:
        return stable_payload_hash(self.to_dict())


@dataclass(frozen=True)
class ActionResponse:
    schema_version: str
    request_id: str
    lease_id: str
    agent_id: str
    resolution: str
    note: str
    files: tuple[str, ...] = ()
    validation_commands: tuple[JsonDict, ...] = ()
    reply_markdown: str | None = None
    fix_reply: JsonDict | None = None
    confidence: float | None = None

    @classmethod
    def from_dict(cls, payload: JsonDict) -> "ActionResponse":
        return cls(
            schema_version=str(payload.get("schema_version", "1.0")),
            request_id=str(payload["request_id"]),
            lease_id=str(payload["lease_id"]),
            agent_id=str(payload["agent_id"]),
            resolution=str(payload["resolution"]),
            note=str(payload["note"]),
            files=_string_tuple(payload.get("files")),
            validation_commands=tuple(dict(record) for record in payload.get("validation_commands", ())),
            reply_markdown=payload.get("reply_markdown"),
            fix_reply=payload.get("fix_reply"),
            confidence=payload.get("confidence"),
        )

    def to_dict(self) -> JsonDict:
        payload: JsonDict = {
            "schema_version": self.schema_version,
            "request_id": self.request_id,
            "lease_id": self.lease_id,
            "agent_id": self.agent_id,
            "resolution": self.resolution,
            "note": self.note,
            "validation_commands": [dict(record) for record in self.validation_commands],
        }
        if self.files:
            payload["files"] = list(self.files)
        if self.reply_markdown is not None:
            payload["reply_markdown"] = self.reply_markdown
        if self.fix_reply is not None:
            payload["fix_reply"] = dict(self.fix_reply)
        if self.confidence is not None:
            payload["confidence"] = self.confidence
        return payload


@dataclass(frozen=True)
class CapabilityManifest:
    schema_version: str
    agent_id: str
    roles: tuple[AgentRole, ...]
    actions: tuple[str, ...]
    input_formats: tuple[str, ...]
    output_formats: tuple[str, ...]
    protocol_versions: tuple[str, ...]
    constraints: JsonDict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: JsonDict) -> "CapabilityManifest":
        return cls(
            schema_version=str(payload.get("schema_version", "1.0")),
            agent_id=str(payload["agent_id"]),
            roles=tuple(parse_role(role) for role in payload["roles"]),
            actions=_string_tuple(payload["actions"]),
            input_formats=_string_tuple(payload["input_formats"]),
            output_formats=_string_tuple(payload["output_formats"]),
            protocol_versions=_string_tuple(payload["protocol_versions"]),
            constraints=_dict_copy(payload.get("constraints")),
        )

    def to_dict(self) -> JsonDict:
        return {
            "schema_version": self.schema_version,
            "agent_id": self.agent_id,
            "roles": [role.value for role in self.roles],
            "actions": list(self.actions),
            "input_formats": list(self.input_formats),
            "output_formats": list(self.output_formats),
            "protocol_versions": list(self.protocol_versions),
            "constraints": dict(self.constraints),
        }


@dataclass
class ClaimLease:
    lease_id: str
    item_id: str
    agent_id: str
    role: AgentRole | str
    status: str = "active"
    created_at: str | None = None
    expires_at: str | None = None
    resume_token: str | None = None
    request_hash: str | None = None
    request_id: str | None = None
    request_path: str | None = None
    conflict_keys: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        self.role = parse_role(self.role)
        self.conflict_keys = _string_tuple(self.conflict_keys)

    def to_dict(self) -> JsonDict:
        payload: JsonDict = {
            "lease_id": self.lease_id,
            "item_id": self.item_id,
            "agent_id": self.agent_id,
            "role": self.role.value,
            "status": self.status,
            "conflict_keys": list(self.conflict_keys),
        }
        if self.created_at is not None:
            payload["created_at"] = self.created_at
        if self.expires_at is not None:
            payload["expires_at"] = self.expires_at
        if self.resume_token is not None:
            payload["resume_token"] = self.resume_token
        if self.request_hash is not None:
            payload["request_hash"] = self.request_hash
        if self.request_id is not None:
            payload["request_id"] = self.request_id
        if self.request_path is not None:
            payload["request_path"] = self.request_path
        return payload


@dataclass(frozen=True)
class EvidenceRecord:
    record_id: str
    timestamp: str
    session_id: str
    item_id: str | None
    lease_id: str | None
    agent_id: str | None
    role: AgentRole | str | None
    event_type: str
    payload: JsonDict
    payload_hash: str

    @classmethod
    def create(
        cls,
        *,
        session_id: str,
        event_type: str,
        payload: JsonDict,
        item_id: str | None = None,
        lease_id: str | None = None,
        agent_id: str | None = None,
        role: AgentRole | str | None = None,
    ) -> "EvidenceRecord":
        timestamp = datetime.now(timezone.utc).isoformat()
        role_value = parse_role(role).value if role is not None else None
        body = {
            "session_id": session_id,
            "item_id": item_id,
            "lease_id": lease_id,
            "agent_id": agent_id,
            "role": role_value,
            "event_type": event_type,
            "payload": payload,
            "timestamp": timestamp,
        }
        payload_hash = stable_payload_hash(body)
        return cls(
            record_id=f"ev_{payload_hash[:16]}",
            timestamp=timestamp,
            session_id=session_id,
            item_id=item_id,
            lease_id=lease_id,
            agent_id=agent_id,
            role=role_value,
            event_type=event_type,
            payload=dict(payload),
            payload_hash=payload_hash,
        )

    def to_dict(self) -> JsonDict:
        return {
            "record_id": self.record_id,
            "timestamp": self.timestamp,
            "session_id": self.session_id,
            "item_id": self.item_id,
            "lease_id": self.lease_id,
            "agent_id": self.agent_id,
            "role": self.role.value if isinstance(self.role, AgentRole) else self.role,
            "event_type": self.event_type,
            "payload": dict(self.payload),
            "payload_hash": self.payload_hash,
        }


@dataclass
class ReviewSession:
    session_id: str
    repo: str
    pr_number: str
    status: str = "IDLE"
    items: dict[str, WorkItem] = field(default_factory=dict)
    leases: dict[str, ClaimLease] = field(default_factory=dict)
    ledger_path: Path | None = None
    resume_token: str | None = None
    metrics: JsonDict = field(default_factory=dict)
    evidence: list[EvidenceRecord] = field(default_factory=list)

    def append_evidence(self, record: EvidenceRecord) -> EvidenceRecord:
        self.evidence.append(record)
        return record


@dataclass(frozen=True)
class SideEffectAttempt:
    attempt_id: str
    session_id: str
    item_id: str
    side_effect_type: str
    idempotency_key: str
    status: str
    retry_count: int = 0
    backoff_until: str | None = None
    last_error: str | None = None
    external_url: str | None = None
