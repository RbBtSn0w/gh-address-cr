from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from gh_address_cr.core import paths
from gh_address_cr.core.io import JsonIOError, read_json_object, write_json_atomic

DATETIME_FIELDS = {"created_at", "expires_at", "submitted_at", "completed_at"}
_WRITABLE_STATE_DIRECTORIES: set[Path] = set()


class SessionError(RuntimeError):
    def __init__(self, reason_code: str, detail: str):
        self.reason_code = reason_code
        super().__init__(detail)


def state_dir() -> Path:
    try:
        path = paths.state_dir()
    except paths.PathResolutionError as exc:
        raise SessionError(exc.reason_code, str(exc)) from exc
    _ensure_writable_state_directory(path)
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
    _ensure_writable_state_directory(path)
    return path


def _ensure_writable_state_directory(path: Path) -> None:
    if path in _WRITABLE_STATE_DIRECTORIES:
        return
    try:
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix=".gh-address-cr-", dir=path):
            pass
        _WRITABLE_STATE_DIRECTORIES.add(path)
    except OSError as exc:
        raise SessionError(
            "STATE_DIR_NOT_WRITABLE",
            "The gh-address-cr state directory is not writable. "
            "Set GH_ADDRESS_CR_STATE_DIR to one writable directory and reuse it for the full PR session.",
        ) from exc


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
    from gh_address_cr.core.telemetry import configure_context_safely

    configure_context_safely(repo, pr_number)
    return payload


def save_session(repo: str, pr_number: str, payload: dict[str, Any]) -> None:
    path = session_file(repo, pr_number)
    write_json_atomic(path, payload)


def cache_pull_request_context(session: dict[str, Any], stack_context: dict[str, Any]) -> None:
    """Cache a labelled GitHub observation without making it session truth."""
    metadata = session.setdefault("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
        session["metadata"] = metadata
    previous = metadata.get("pull_request_context")
    previous_context = previous.get("stack_context") if isinstance(previous, dict) else None
    availability = stack_context.get("availability")
    if availability in {"present", "absent"}:
        stack_membership_observed = availability == "present"
    else:
        stack_membership_observed = bool(
            (isinstance(previous, dict) and previous.get("stack_membership_observed") is True)
            or (isinstance(previous_context, dict) and previous_context.get("availability") == "present")
        )
    metadata["pull_request_context"] = {
        "authority": "github_observation",
        "authoritative": False,
        "stack_context": dict(stack_context),
        "stack_membership_observed": stack_membership_observed,
        "refreshed_at": str(stack_context.get("observed_at") or ""),
    }


def cached_stack_context(session: dict[str, Any]) -> dict[str, Any] | None:
    metadata = session.get("metadata")
    if not isinstance(metadata, dict):
        return None
    observed = metadata.get("pull_request_context")
    if not isinstance(observed, dict) or observed.get("authoritative") is not False:
        return None
    context = observed.get("stack_context")
    return dict(context) if isinstance(context, dict) else None


def has_observed_stack_membership(session: dict[str, Any]) -> bool:
    """Return a conservative safety hint, never a current topology assertion."""
    metadata = session.get("metadata")
    observed = metadata.get("pull_request_context") if isinstance(metadata, dict) else None
    if not isinstance(observed, dict):
        return False
    if observed.get("stack_membership_observed") is True:
        return True
    context = observed.get("stack_context")
    return isinstance(context, dict) and context.get("availability") == "present"


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
