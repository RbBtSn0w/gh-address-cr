from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_REQUIRED_KEYS = ("source", "strategy", "discovery", "record", "fields", "safety_allowlist")


@dataclass(frozen=True)
class HostProfile:
    source: str
    strategy: str
    discovery: dict[str, Any]
    record: dict[str, Any]
    fields: dict[str, Any]
    safety_allowlist: tuple[str, ...]
    kind_classification: dict[str, Any] = field(default_factory=dict)
    scope_attribution: dict[str, Any] = field(default_factory=dict)
    profile_version: str = "1.0"

    def kind_for(self, operation: str) -> str:
        kc = self.kind_classification or {}
        if operation in (kc.get("wait") or []):
            return "wait"
        by_op = kc.get("by_operation") or {}
        if operation in by_op:
            return str(by_op[operation])
        return str(kc.get("default") or "tool_call")


def load_profile(path: Path) -> HostProfile:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid host profile: {exc}") from None
    if not isinstance(payload, dict):
        raise ValueError("host profile must be a JSON object")
    missing = [k for k in _REQUIRED_KEYS if k not in payload]
    if missing:
        raise ValueError(f"host profile missing required key(s): {', '.join(missing)}")
    return HostProfile(
        source=str(payload["source"]),
        strategy=str(payload["strategy"]),
        discovery=dict(payload["discovery"]),
        record=dict(payload["record"]),
        fields=dict(payload["fields"]),
        safety_allowlist=tuple(str(x) for x in payload["safety_allowlist"]),
        kind_classification=dict(payload.get("kind_classification") or {}),
        scope_attribution=dict(payload.get("scope_attribution") or {}),
        profile_version=str(payload.get("profile_version") or "1.0"),
    )
