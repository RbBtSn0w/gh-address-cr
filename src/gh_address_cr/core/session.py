from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from gh_address_cr.core import paths
from gh_address_cr.core.io import JsonIOError, read_json_object, write_json_atomic


DATETIME_FIELDS = {"created_at", "expires_at", "submitted_at", "completed_at"}


class SessionError(RuntimeError):
    def __init__(self, reason_code: str, detail: str):
        self.reason_code = reason_code
        super().__init__(detail)


def state_dir() -> Path:
    try:
        path = paths.state_dir()
    except paths.PathResolutionError as exc:
        raise SessionError(exc.reason_code, str(exc)) from exc
    path.mkdir(parents=True, exist_ok=True)
    return path


def normalize_repo(repo: str) -> str:
    try:
        return paths.normalize_repo(repo)
    except paths.PathResolutionError as exc:
        raise SessionError(exc.reason_code, str(exc)) from exc


def workspace_dir(repo: str, pr_number: str) -> Path:
    try:
        path = paths.workspace_dir(repo, pr_number)
    except paths.PathResolutionError as exc:
        raise SessionError(exc.reason_code, str(exc)) from exc
    path.mkdir(parents=True, exist_ok=True)
    return path


def session_file(repo: str, pr_number: str) -> Path:
    return workspace_dir(repo, pr_number) / paths.session_file(repo, pr_number).name


def default_ledger_path(repo: str, pr_number: str) -> Path:
    return workspace_dir(repo, pr_number) / paths.evidence_ledger_file(repo, pr_number).name


class SessionManager:
    def __init__(self, repo: str, pr_number: str):
        self.repo = repo
        self.pr_number = str(pr_number)

    @property
    def workspace_path(self) -> Path:
        return workspace_dir(self.repo, self.pr_number)

    @property
    def session_path(self) -> Path:
        return session_file(self.repo, self.pr_number)

    @property
    def ledger_path(self) -> Path:
        return default_ledger_path(self.repo, self.pr_number)

    def create(self, *, status: str = "ACTIVE") -> dict[str, Any]:
        return {
            "session_id": f"{self.repo}#{self.pr_number}",
            "repo": self.repo,
            "pr_number": self.pr_number,
            "status": status,
            "items": {},
            "leases": {},
            "ledger_path": str(self.ledger_path),
            "metadata": {},
        }

    def load(self) -> dict[str, Any]:
        return load_session(self.repo, self.pr_number)

    def save(self, payload: dict[str, Any]) -> None:
        save_session(self.repo, self.pr_number, payload)


def load_session(repo: str, pr_number: str) -> dict[str, Any]:
    path = session_file(repo, pr_number)
    if not path.exists():
        raise SessionError("SESSION_NOT_FOUND", f"No session exists for {repo} PR {pr_number}. Run review first.")
    try:
        payload = read_json_object(path)
    except JsonIOError as exc:
        reason_code = "INVALID_SESSION_JSON" if exc.reason_code == "INVALID_JSON" else exc.reason_code
        raise SessionError(reason_code, str(exc)) from exc
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
    write_json_atomic(path, payload)


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
