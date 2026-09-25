from __future__ import annotations

import hashlib
from typing import Any

from gh_address_cr.core import session as session_store
from gh_address_cr.core.runtime_store import RuntimeStore
from gh_address_cr.evidence.ledger import SideEffectAttempt


def persist_side_effect_attempt(session: dict[str, Any], records: list[dict[str, Any]]) -> None:
    if len(records) != 1:
        raise ValueError("Side-effect persistence requires exactly one evidence record.")
    record = records[0]
    attempt = SideEffectAttempt.from_json(dict(record.get("payload") or {}))
    repo = str(session["repo"])
    pr_number = str(session["pr_number"])
    persistence = session.get("persistence")
    expected_revision = persistence.get("revision") if isinstance(persistence, dict) else None
    store = RuntimeStore(session_store.workspace_dir(repo, pr_number))
    command_id = _command_id(attempt.side_effect_type, attempt.idempotency_key)
    existing = next(
        (
            command
            for command in store.load_outbox()
            if command["effect_type"] == attempt.side_effect_type
            and command["idempotency_key"] == attempt.idempotency_key
        ),
        None,
    )
    if attempt.status == "in_flight":
        if existing is not None and existing["status"] != "failed":
            raise ValueError("An existing side-effect command requires reconciliation before retry.")
        if existing is not None:
            in_flight = store.mark_outbox_in_flight(command_id)
            committed = store.transact(
                lambda current: None,
                operation="outbox_attempt",
                expected_revision=in_flight.revision,
                evidence=records,
            )
            _update_revision(session, committed)
            _materialize(store, repo, pr_number)
            return
        store.transact(
            lambda current: None,
            operation="outbox_plan",
            expected_revision=expected_revision if isinstance(expected_revision, int) else None,
            evidence=records,
            outbox=[_command(attempt, command_id)],
        )
        result = store.mark_outbox_in_flight(command_id)
        _update_revision(session, result)
        _materialize(store, repo, pr_number)
        return
    if attempt.status not in {"succeeded", "failed"}:
        raise ValueError(f"Unsupported side-effect attempt status: {attempt.status}")
    if existing is None:
        planned = store.transact(
            lambda current: None,
            operation="outbox_plan",
            expected_revision=expected_revision if isinstance(expected_revision, int) else None,
            outbox=[_command(attempt, command_id)],
        )
        _update_revision(session, planned)
        existing = next(command for command in store.load_outbox() if command["command_id"] == command_id)
    if existing["status"] == "planned":
        _update_revision(session, store.mark_outbox_in_flight(command_id))
    result = store.record_outbox_result(
        command_id,
        status=attempt.status,
        evidence=records,
        external_result_reference=attempt.external_url,
        error_type="external_error" if attempt.status == "failed" else None,
    )
    _update_revision(session, result)
    _materialize(store, repo, pr_number)


def reconcile_side_effect_no_effect(
    session: dict[str, Any],
    *,
    effect_type: str,
    idempotency_key: str,
) -> None:
    repo = str(session["repo"])
    pr_number = str(session["pr_number"])
    store = RuntimeStore(session_store.workspace_dir(repo, pr_number))
    result = store.record_outbox_result(
        _command_id(effect_type, idempotency_key),
        status="failed",
        evidence=[],
        error_type="reconciled_no_effect",
    )
    _update_revision(session, result)


def _command(attempt: SideEffectAttempt, command_id: str) -> dict[str, Any]:
    return {
        "command_id": command_id,
        "effect_type": attempt.side_effect_type,
        "idempotency_key": attempt.idempotency_key,
        "operation_category": attempt.side_effect_type,
        "retry_boundary": "reconcile_only" if attempt.side_effect_type == "github_reply" else "idempotent",
    }


def _command_id(effect_type: str, idempotency_key: str) -> str:
    digest = hashlib.sha256(f"{effect_type}\0{idempotency_key}".encode()).hexdigest()[:24]
    return f"outbox_{digest}"


def _update_revision(session: dict[str, Any], snapshot: Any) -> None:
    session["persistence"] = {
        "schema_version": snapshot.schema_version,
        "revision": snapshot.revision,
    }


def _materialize(store: RuntimeStore, repo: str, pr_number: str) -> None:
    store.materialize_compatibility_artifacts(
        session_path=session_store.session_file(repo, pr_number),
        ledger_path=session_store.default_ledger_path(repo, pr_number),
    )
