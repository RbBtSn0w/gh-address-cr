from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, TypeVar

from gh_address_cr.core import paths
from gh_address_cr.core.io import JsonIOError, read_json_object
from gh_address_cr.core.runtime_store import (
    PersistenceBusyError,
    PersistenceInvalidError,
    RuntimeStore,
    StaleRevisionError,
    TransactionResult,
    WorkingSetRequest,
)
from gh_address_cr.evidence.ledger import take_pending_evidence

DATETIME_FIELDS = {"created_at", "expires_at", "submitted_at", "completed_at"}
_WRITABLE_STATE_DIRECTORIES: set[Path] = set()
T = TypeVar("T")


class SessionError(RuntimeError):
    def __init__(self, reason_code: str, detail: str):
        self.reason_code = reason_code
        super().__init__(detail)


# Persistence outcomes an agent may retry by rerunning the same command.
RETRYABLE_SESSION_REASONS = frozenset({"STALE_REVISION", "PERSISTENCE_BUSY"})
PR_TARGET_REASONS = frozenset({"INVALID_REPO", "INVALID_PR_NUMBER"})
STALE_REVISION_ATTEMPTS = 3

_PERSISTENCE_NEXT_ACTIONS = {
    "STALE_REVISION": (
        "Another gh-address-cr command changed this session after it was loaded. Rerun the same command; "
        "it reloads the current state."
    ),
    "PERSISTENCE_BUSY": (
        "The runtime store stayed locked past its bounded wait. Let the other gh-address-cr command finish, "
        "then rerun the same command."
    ),
    "PERSISTENCE_INVALID": (
        "The runtime store failed an integrity check. Stop: do not edit session.json, evidence.jsonl, or "
        "runtime.sqlite3, and keep legacy-v1-recovery intact. Report it with `gh-address-cr submit-feedback`."
    ),
}


def session_error_guidance(exc: SessionError) -> dict[str, Any]:
    """The machine-facing recovery fields for a session or persistence failure."""
    reason_code = str(exc.reason_code)
    if reason_code in _PERSISTENCE_NEXT_ACTIONS:
        waiting_on = "runtime_store"
        next_action = f"{_PERSISTENCE_NEXT_ACTIONS[reason_code]} ({exc})"
    else:
        if reason_code == "STATE_DIR_NOT_WRITABLE":
            waiting_on = "state_directory"
        elif reason_code in PR_TARGET_REASONS:
            waiting_on = "pr_scope"
        else:
            waiting_on = "session"
        next_action = str(exc)
    return {
        "reason_code": reason_code,
        "waiting_on": waiting_on,
        "next_action": next_action,
        "retryable": reason_code in RETRYABLE_SESSION_REASONS,
    }


def retry_on_stale_revision(operation: Callable[[], T], *, attempts: int = STALE_REVISION_ATTEMPTS) -> T:
    """Rerun a load-validate-save operation when a concurrent writer committed first.

    Only for operations whose work before the save is pure (no external side
    effects), or whose external side effects all run through the canonical
    outbox, which a rerun reuses instead of repeating. Either way a rerun from
    freshly loaded state is equivalent to the first try. The bounded attempts keep a hot session from spinning; the final
    conflict surfaces as ``STALE_REVISION``.
    """
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except SessionError as exc:
            if exc.reason_code != "STALE_REVISION" or attempt == attempts:
                raise
            _emit_stale_retry(attempt)
    raise AssertionError("unreachable")


def _emit_stale_retry(attempt: int) -> None:
    try:
        from gh_address_cr.otel_tracing import add_current_span_event

        add_current_span_event("persistence.stale_retry", {"persistence.retry_attempt": attempt})
    except Exception:
        return


def state_dir() -> Path:
    try:
        path = paths.state_dir()
    except paths.PathResolutionError as exc:
        raise SessionError(exc.reason_code, str(exc)) from exc
    _ensure_writable_state_directory(path)
    return path


def validate_pr_target(repo: str, pr_number: str) -> None:
    """Reject a malformed target before any command reads or creates its workspace."""
    try:
        paths.validate_pr_target(repo, pr_number)
    except paths.PathResolutionError as exc:
        raise SessionError(exc.reason_code, str(exc)) from exc


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

    def transact(
        self,
        mutation: Callable[[dict[str, Any]], T],
        *,
        operation: str,
        expected_revision: int | None = None,
        evidence: list[dict[str, Any]] | None = None,
        outbox: list[dict[str, Any]] | None = None,
    ) -> TransactionResult:
        return transact_session(
            self.repo,
            self.pr_number,
            mutation,
            operation=operation,
            expected_revision=expected_revision,
            evidence=evidence,
            outbox=outbox,
        )


def load_session(repo: str, pr_number: str) -> dict[str, Any]:
    path = session_file(repo, pr_number)
    store = RuntimeStore(workspace_dir(repo, pr_number))
    try:
        if not store.is_initialized():
            if not path.exists():
                raise SessionError(
                    "SESSION_NOT_FOUND", f"No session exists for {repo} PR {pr_number}. Run review first."
                )
            try:
                read_json_object(path)
            except JsonIOError as exc:
                reason_code = "INVALID_SESSION_JSON" if exc.reason_code == "INVALID_JSON" else exc.reason_code
                raise SessionError(reason_code, str(exc)) from exc
            store.open_or_migrate(
                session_path=path,
                ledger_path=default_ledger_path(repo, pr_number),
            )
        store.recover()
        store.recover_artifacts(
            session_path=path,
            ledger_path=default_ledger_path(repo, pr_number),
            wait=False,
        )
        snapshot = store.load()
    except (PersistenceBusyError, PersistenceInvalidError) as exc:
        raise SessionError(exc.reason_code, str(exc)) from exc
    payload = snapshot.payload
    payload["persistence"] = {"schema_version": snapshot.schema_version, "revision": snapshot.revision}
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


def load_working_set(repo: str, pr_number: str, request: WorkingSetRequest) -> dict[str, Any]:
    """Load a declared runtime subset while preserving recovery and revision semantics."""
    store = RuntimeStore(workspace_dir(repo, pr_number))
    try:
        if not store.is_initialized():
            load_session(repo, pr_number)
        else:
            from gh_address_cr.core.telemetry import configure_context_safely

            configure_context_safely(repo, pr_number)
        store.recover()
        snapshot = store.load_working_set(request)
    except (PersistenceBusyError, PersistenceInvalidError) as exc:
        raise SessionError(exc.reason_code, str(exc)) from exc
    payload = snapshot.payload
    payload["persistence"] = {"schema_version": snapshot.schema_version, "revision": snapshot.revision}
    payload.setdefault("session_id", f"{repo}#{pr_number}")
    payload.setdefault("repo", repo)
    payload.setdefault("pr_number", str(pr_number))
    payload.setdefault("items", {})
    payload.setdefault("leases", {})
    payload.setdefault("ledger_path", str(default_ledger_path(repo, pr_number)))
    _coerce_lease_datetimes(payload)
    return payload


def load_canonical_evidence(repo: str, pr_number: str) -> list[dict[str, Any]]:
    """Committed evidence rows from the runtime store; never the ``evidence.jsonl`` projection."""
    store = RuntimeStore(workspace_dir(repo, pr_number))
    try:
        if not store.is_initialized():
            return []
        return store.load_evidence()
    except (PersistenceBusyError, PersistenceInvalidError) as exc:
        raise SessionError(exc.reason_code, str(exc)) from exc


def save_session(repo: str, pr_number: str, payload: dict[str, Any]) -> None:
    path = session_file(repo, pr_number)
    store = RuntimeStore(workspace_dir(repo, pr_number))
    evidence = take_pending_evidence(payload)
    try:
        if store.is_initialized():
            persistence = payload.get("persistence")
            if not isinstance(persistence, dict) or not isinstance(persistence.get("revision"), int):
                raise SessionError(
                    "UNVERSIONED_SESSION_WRITE",
                    "Existing runtime state must be loaded before it can be saved.",
                )
            snapshot = store.replace(
                payload,
                expected_revision=int(persistence["revision"]),
                operation="session_update",
                evidence=evidence,
            )
        elif path.exists():
            raise SessionError(
                "PERSISTENCE_INVALID",
                "A legacy session exists but has not been migrated. Load the session to import it before saving.",
            )
        else:
            snapshot = store.bootstrap(payload, evidence=evidence, require_new=True)
        payload["persistence"] = {"schema_version": snapshot.schema_version, "revision": snapshot.revision}
        store.materialize_compatibility_artifacts(
            session_path=path,
            ledger_path=default_ledger_path(repo, pr_number),
        )
    except (PersistenceBusyError, PersistenceInvalidError, StaleRevisionError) as exc:
        raise SessionError(exc.reason_code, str(exc)) from exc


def transact_session(
    repo: str,
    pr_number: str,
    mutation: Callable[[dict[str, Any]], T],
    *,
    operation: str,
    expected_revision: int | None = None,
    evidence: list[dict[str, Any]] | None = None,
    outbox: list[dict[str, Any]] | None = None,
) -> TransactionResult:
    store = RuntimeStore(workspace_dir(repo, pr_number))
    try:
        if not store.is_initialized():
            load_session(repo, pr_number)
        else:
            # load_session binds local telemetry to this PR; a transaction-only command must too,
            # or its subprocess and command metrics are dropped.
            from gh_address_cr.core.telemetry import configure_context_safely

            configure_context_safely(repo, pr_number)
        result = store.transact(
            mutation,
            expected_revision=expected_revision,
            operation=operation,
            evidence=evidence,
            outbox=outbox,
        )
        payload = result.payload
        payload["persistence"] = {"schema_version": result.schema_version, "revision": result.revision}
        store.materialize_evidence_artifacts(
            ledger_path=default_ledger_path(repo, pr_number),
        )
        return TransactionResult(
            payload=payload,
            revision=result.revision,
            schema_version=result.schema_version,
            value=result.value,
            operation=result.operation,
        )
    except (PersistenceBusyError, PersistenceInvalidError, StaleRevisionError) as exc:
        raise SessionError(exc.reason_code, str(exc)) from exc


def transact_working_set(
    repo: str,
    pr_number: str,
    request: WorkingSetRequest,
    mutation: Callable[[dict[str, Any]], T],
    *,
    operation: str,
    expected_revision: int | None = None,
    evidence: list[dict[str, Any]] | None = None,
    outbox: list[dict[str, Any]] | None = None,
) -> TransactionResult:
    store = RuntimeStore(workspace_dir(repo, pr_number))
    try:
        if not store.is_initialized():
            load_session(repo, pr_number)
        else:
            from gh_address_cr.core.telemetry import configure_context_safely

            configure_context_safely(repo, pr_number)
        result = store.transact_working_set(
            request,
            mutation,
            expected_revision=expected_revision,
            operation=operation,
            evidence=evidence,
            outbox=outbox,
        )
        store.materialize_evidence_artifacts(
            ledger_path=default_ledger_path(repo, pr_number),
        )
        return result
    except (PersistenceBusyError, PersistenceInvalidError, StaleRevisionError) as exc:
        raise SessionError(exc.reason_code, str(exc)) from exc


def metadata_delta(base: Any, local: Any) -> dict[str, Any]:
    """The metadata keys a command changed relative to the copy it loaded.

    Commands that decide under the write lock apply only this delta to the
    committed metadata, so keys another writer committed in between survive.
    """
    base_map = base if isinstance(base, dict) else {}
    local_map = local if isinstance(local, dict) else {}
    updates = {key: value for key, value in local_map.items() if base_map.get(key, _MISSING) != value}
    removed = [key for key in base_map if key not in local_map]
    return {"updates": updates, "removed": removed}


def apply_metadata_delta(current: dict[str, Any], delta: dict[str, Any]) -> None:
    metadata = current.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
        current["metadata"] = metadata
    metadata.update(delta["updates"])
    for key in delta["removed"]:
        metadata.pop(key, None)


_MISSING = object()


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
