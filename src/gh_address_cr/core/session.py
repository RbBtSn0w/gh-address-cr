from __future__ import annotations

import json
import os
import platform
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DATETIME_FIELDS = {"created_at", "expires_at", "submitted_at", "completed_at"}


class SessionError(RuntimeError):
    def __init__(self, reason_code: str, detail: str):
        self.reason_code = reason_code
        super().__init__(detail)


def state_dir() -> Path:
    override = os.environ.get("GH_ADDRESS_CR_STATE_DIR")
    if override:
        path = Path(override)
        path.mkdir(parents=True, exist_ok=True)
        return path

    home = os.environ.get("HOME")
    if platform.system() == "Darwin":
        base = os.environ.get("XDG_CACHE_HOME") or (f"{home}/Library/Caches" if home else None)
    else:
        base = os.environ.get("XDG_CACHE_HOME") or (f"{home}/.cache" if home else None)
    if not base:
        raise SessionError("STATE_DIR_UNAVAILABLE", "Unable to determine a user cache directory. Set GH_ADDRESS_CR_STATE_DIR.")
    path = Path(base) / "gh-address-cr"
    path.mkdir(parents=True, exist_ok=True)
    return path


def normalize_repo(repo: str) -> str:
    return repo.replace("/", "__")


def workspace_dir(repo: str, pr_number: str) -> Path:
    path = state_dir() / normalize_repo(repo) / f"pr-{pr_number}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def session_file(repo: str, pr_number: str) -> Path:
    return workspace_dir(repo, pr_number) / "session.json"


def default_ledger_path(repo: str, pr_number: str) -> Path:
    return workspace_dir(repo, pr_number) / "evidence.jsonl"


def load_session(repo: str, pr_number: str) -> dict[str, Any]:
    path = session_file(repo, pr_number)
    if not path.exists():
        raise SessionError("SESSION_NOT_FOUND", f"No session exists for {repo} PR {pr_number}. Run review first.")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SessionError("INVALID_SESSION_JSON", f"Invalid session JSON at {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SessionError("INVALID_SESSION_SHAPE", f"Session at {path} must be a JSON object.")
    payload.setdefault("session_id", f"{repo}#{pr_number}")
    payload.setdefault("repo", repo)
    payload.setdefault("pr_number", str(pr_number))
    payload.setdefault("items", {})
    payload.setdefault("leases", {})
    payload.setdefault("ledger_path", str(default_ledger_path(repo, pr_number)))
    _coerce_lease_datetimes(payload)
    return payload


def save_session(repo: str, pr_number: str, payload: dict[str, Any]) -> None:
    path = session_file(repo, pr_number)
    path.write_text(json.dumps(_json_ready(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _coerce_lease_datetimes(payload: dict[str, Any]) -> None:
    leases = payload.get("leases")
    if not isinstance(leases, dict):
        payload["leases"] = {}
        return
    for lease in leases.values():
        if not isinstance(lease, dict):
            continue
        for field in DATETIME_FIELDS:
            value = lease.get(field)
            if isinstance(value, str) and value:
                lease[field] = _parse_datetime(value)


def _parse_datetime(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _json_ready(value: Any) -> Any:
    if is_dataclass(value):
        return _json_ready(asdict(value))
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_ready(inner) for key, inner in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_ready(inner) for inner in value]
    return value
