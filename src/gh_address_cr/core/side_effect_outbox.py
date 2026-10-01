from __future__ import annotations

import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from gh_address_cr.core import protocol_codes
from gh_address_cr.core import session as session_store
from gh_address_cr.core.errors import WorkflowError
from gh_address_cr.core.process_lock import ExecutionLock, is_execution_lock_held, try_acquire_execution_lock
from gh_address_cr.core.runtime_store import (
    OutboxCommit,
    RuntimeStore,
    RuntimeStoreError,
    outbox_command_id,
    retry_boundary_for,
)
from gh_address_cr.evidence.ledger import SideEffectAttempt

# Execution locks this process holds, keyed by (workspace, command_id), with the
# owner token recorded on the outbox row while the command is in flight.
_HELD: dict[tuple[str, str], tuple[ExecutionLock, str]] = {}


@contextmanager
def execution_guard(session: dict[str, Any], *, effect_type: str, idempotency_key: str) -> Iterator[None]:
    """Hold the command's execution lock for the whole in_flight → external call → result span.

    The lock is what lets any other process tell a running command from one
    whose executor died, so it is taken before the attempt is marked
    ``in_flight`` and released only after the result commits or the call
    unwinds. A command already held by a live executor is not re-executed.
    """
    workspace = _workspace(session)
    command_id = outbox_command_id(effect_type, idempotency_key)
    key = (str(workspace), command_id)
    if key in _HELD:
        raise RuntimeError("An execution guard for this side effect is already active in this process.")
    lock = try_acquire_execution_lock(workspace, command_id)
    if lock is None:
        raise side_effect_in_progress(session, effect_type=effect_type)
    _HELD[key] = (lock, uuid.uuid4().hex)
    try:
        yield
    finally:
        _HELD.pop(key, None)
        lock.release()


def side_effect_state(session: dict[str, Any], *, effect_type: str, idempotency_key: str) -> dict[str, Any] | None:
    """Canonical outbox state for one side effect, with ``owner_alive`` for in-flight rows.

    An ``in_flight`` row whose executor is gone is demoted to ``unknown`` here,
    so callers only ever see ``in_flight`` for a command that is still running.
    """
    store = RuntimeStore(_workspace(session))
    try:
        command = store.outbox_command(effect_type=effect_type, idempotency_key=idempotency_key)
        if command is not None and command["status"] == "in_flight" and not _owner_alive(store, command):
            _advance_token(session, store.recover_outbox())
            command = store.outbox_command(effect_type=effect_type, idempotency_key=idempotency_key)
    except RuntimeStoreError as exc:
        raise session_store.SessionError(exc.reason_code, str(exc)) from exc
    if command is None:
        return None
    command["owner_alive"] = command["status"] == "in_flight" and _owner_alive(store, command)
    return command


def persist_side_effect_attempt(session: dict[str, Any], records: list[dict[str, Any]]) -> None:
    if len(records) != 1:
        raise ValueError("Side-effect persistence requires exactly one evidence record.")
    record = records[0]
    attempt = SideEffectAttempt.from_json(dict(record.get("payload") or {}))
    workspace = _workspace(session)
    store = RuntimeStore(workspace)
    command_id = outbox_command_id(attempt.side_effect_type, attempt.idempotency_key)
    held = _HELD.get((str(workspace), command_id))
    try:
        if attempt.status == "in_flight":
            if held is None:
                raise RuntimeError("Marking a side effect in flight requires its execution guard.")
            _begin_attempt(session, store, attempt, records, command_id=command_id, owner_token=held[1])
        elif attempt.status in {"succeeded", "failed"}:
            _finish_attempt(session, store, attempt, records, command_id=command_id, owner_token=held and held[1])
        else:
            raise ValueError(f"Unsupported side-effect attempt status: {attempt.status}")
    except RuntimeStoreError as exc:
        raise session_store.SessionError(exc.reason_code, str(exc)) from exc
    _materialize(store, session)


def reconcile_side_effect_no_effect(
    session: dict[str, Any],
    *,
    effect_type: str,
    idempotency_key: str,
) -> None:
    store = RuntimeStore(_workspace(session))
    try:
        result = store.record_outbox_result(
            outbox_command_id(effect_type, idempotency_key),
            status="failed",
            evidence=[],
            error_type="reconciled_no_effect",
        )
    except RuntimeStoreError as exc:
        raise session_store.SessionError(exc.reason_code, str(exc)) from exc
    _advance_token(session, result)


def side_effect_in_progress(session: dict[str, Any], *, effect_type: str) -> WorkflowError:
    return WorkflowError(
        status=protocol_codes.PUBLISH_BLOCKED,
        reason_code=protocol_codes.SIDE_EFFECT_IN_PROGRESS,
        waiting_on="side_effect_execution",
        exit_code=5,
        message=(
            f"Another process is executing this {effect_type} side effect right now. Wait for it to finish, "
            f"then rerun the same command; it will reuse the recorded result instead of repeating the effect."
        ),
        payload={"effect_type": effect_type},
    )


def _begin_attempt(
    session: dict[str, Any],
    store: RuntimeStore,
    attempt: SideEffectAttempt,
    records: list[dict[str, Any]],
    *,
    command_id: str,
    owner_token: str,
) -> None:
    existing = store.outbox_command(effect_type=attempt.side_effect_type, idempotency_key=attempt.idempotency_key)
    if existing is None:
        # Before the external call a stale caller still fails fast, so nothing is
        # posted from a payload another writer has already superseded.
        _plan(session, store, attempt, command_id, guard_revision=True)
    elif not (
        existing["status"] in {"planned", "failed"}
        or (existing["status"] == "unknown" and existing["retry_boundary"] == "idempotent")
    ):
        raise WorkflowError(
            status=protocol_codes.PUBLISH_BLOCKED,
            reason_code=protocol_codes.PUBLISH_RECONCILE_REQUIRED,
            waiting_on="reply_reconciliation",
            exit_code=5,
            message=(
                f"The {attempt.side_effect_type} side effect is {existing['status']} in the canonical outbox and "
                "cannot be retried blindly; reconcile it before publishing again."
            ),
            payload={"item_id": attempt.item_id, "effect_type": attempt.side_effect_type},
        )
    # The attempt evidence commits with the in_flight transition, so a concurrent
    # writer can never leave a command in flight without its attempt record.
    _advance_token(session, store.mark_outbox_in_flight(command_id, owner_token=owner_token, evidence=records))


def _finish_attempt(
    session: dict[str, Any],
    store: RuntimeStore,
    attempt: SideEffectAttempt,
    records: list[dict[str, Any]],
    *,
    command_id: str,
    owner_token: str | None,
) -> None:
    existing = store.outbox_command(effect_type=attempt.side_effect_type, idempotency_key=attempt.idempotency_key)
    if existing is None:
        _plan(session, store, attempt, command_id)
        existing = {"status": "planned"}
    if existing["status"] == "planned":
        _advance_token(session, store.mark_outbox_in_flight(command_id, owner_token=owner_token))
    result = store.record_outbox_result(
        command_id,
        status=attempt.status,
        evidence=records,
        external_result_reference=attempt.external_url,
        error_type="external_error" if attempt.status == "failed" else None,
        owner_token=owner_token,
    )
    _advance_token(session, result)


def _plan(
    session: dict[str, Any],
    store: RuntimeStore,
    attempt: SideEffectAttempt,
    command_id: str,
    *,
    guard_revision: bool = False,
) -> None:
    # Planning after the external call records a fact, so it never waits on the
    # caller's revision: a concurrent unrelated commit must not leave a real
    # GitHub mutation unrecorded.
    persistence = session.get("persistence")
    token = persistence.get("revision") if isinstance(persistence, dict) else None
    planned = store.transact(
        lambda current: None,
        operation="outbox_plan",
        expected_revision=token if guard_revision and isinstance(token, int) else None,
        outbox=[_command(attempt, command_id)],
    )
    _advance_token(session, OutboxCommit(base_revision=planned.revision - 1, revision=planned.revision))


def _owner_alive(store: RuntimeStore, command: dict[str, Any]) -> bool:
    command_id = str(command["command_id"])
    if (str(store.workspace), command_id) in _HELD:
        return True
    return is_execution_lock_held(store.workspace, command_id)


def _workspace(session: dict[str, Any]) -> Path:
    return session_store.workspace_dir(str(session["repo"]), str(session["pr_number"]))


def _command(attempt: SideEffectAttempt, command_id: str) -> dict[str, Any]:
    return {
        "command_id": command_id,
        "effect_type": attempt.side_effect_type,
        "idempotency_key": attempt.idempotency_key,
        "operation_category": attempt.side_effect_type,
        "retry_boundary": retry_boundary_for(attempt.side_effect_type),
    }


def _advance_token(session: dict[str, Any], commit: OutboxCommit | None) -> None:
    """Adopt an outbox commit's revision only when nothing else committed in between.

    The session payload describes its token's revision. Moving the token past a
    foreign commit would let the caller's next whole-session save overwrite that
    commit, so a non-contiguous commit leaves the token stale and the save fails
    with the documented, retryable STALE_REVISION.
    """
    if commit is None:
        return
    persistence = session.get("persistence")
    if isinstance(persistence, dict) and persistence.get("revision") == commit.base_revision:
        persistence["revision"] = commit.revision


def _materialize(store: RuntimeStore, session: dict[str, Any]) -> None:
    repo = str(session["repo"])
    pr_number = str(session["pr_number"])
    store.materialize_compatibility_artifacts(
        session_path=session_store.session_file(repo, pr_number),
        ledger_path=session_store.default_ledger_path(repo, pr_number),
    )
