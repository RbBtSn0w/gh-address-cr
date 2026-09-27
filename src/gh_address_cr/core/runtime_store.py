from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, TypeVar

from gh_address_cr.core.github_thread_state import returned_claimable_state
from gh_address_cr.core.io import fsync_directory, fsync_file, json_ready, write_json_atomic, write_json_durable
from gh_address_cr.core.process_lock import is_execution_lock_held
from gh_address_cr.evidence.ledger import EvidenceRecord, SideEffectAttempt, payload_hash

SCHEMA_VERSION = 2
RECOVERY_BUNDLE_NAME = "legacy-v1-recovery"
_LEASE_DATETIME_FIELDS = {"created_at", "expires_at", "submitted_at", "completed_at"}
_SAFE_OPERATIONS = {
    "artifact_drift",
    "artifact_recovery",
    "artifact_write",
    "bootstrap",
    "bundle_quarantine",
    "legacy_import",
    "lease_claim",
    "lease_release",
    "outbox_attempt",
    "outbox_execute",
    "outbox_plan",
    "outbox_recovery",
    "outbox_result",
    "schema_upgrade",
    "session_update",
    "status_update",
}
T = TypeVar("T")

_SCHEMA_SQL = """
CREATE TABLE store_metadata (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    schema_version INTEGER NOT NULL,
    store_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    legacy_import_completed_at TEXT,
    import_format_version TEXT,
    latest_revision INTEGER NOT NULL,
    legacy_bundle_signature TEXT
);
CREATE TABLE sessions (
    session_id TEXT PRIMARY KEY,
    repo TEXT NOT NULL,
    pr_number TEXT NOT NULL,
    status TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    revision INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE items (
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    item_id TEXT NOT NULL,
    item_kind TEXT NOT NULL,
    state TEXT NOT NULL,
    classification TEXT,
    payload_json TEXT NOT NULL,
    first_observed_revision INTEGER NOT NULL,
    last_observed_revision INTEGER NOT NULL,
    PRIMARY KEY (session_id, item_id)
);
CREATE TABLE leases (
    lease_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    item_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    role TEXT NOT NULL,
    status TEXT NOT NULL,
    request_id TEXT,
    request_hash TEXT,
    request_path TEXT,
    resume_token TEXT,
    created_at TEXT,
    expires_at TEXT,
    submitted_at TEXT,
    completed_at TEXT,
    transition_revision INTEGER NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE TABLE lease_conflict_keys (
    lease_id TEXT NOT NULL REFERENCES leases(lease_id) ON DELETE CASCADE,
    conflict_key TEXT NOT NULL,
    PRIMARY KEY (lease_id, conflict_key)
);
CREATE TABLE evidence_events (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id TEXT NOT NULL UNIQUE,
    session_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    lease_id TEXT,
    actor_role TEXT NOT NULL,
    event_type TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    transaction_id TEXT,
    committed_revision INTEGER NOT NULL,
    record_json TEXT NOT NULL
);
CREATE TABLE outbox_commands (
    command_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    effect_type TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    planned_revision INTEGER NOT NULL,
    operation_category TEXT NOT NULL,
    status TEXT NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    retry_boundary TEXT,
    error_type TEXT,
    external_result_reference TEXT,
    owner_token TEXT,
    in_flight_since TEXT,
    transaction_id TEXT,
    UNIQUE (session_id, effect_type, idempotency_key)
);
CREATE TABLE artifact_materializations (
    artifact_kind TEXT PRIMARY KEY,
    source_revision INTEGER NOT NULL,
    format_version INTEGER NOT NULL,
    status TEXT NOT NULL,
    content_hash TEXT,
    last_attempt_at TEXT,
    error_type TEXT,
    size INTEGER,
    mtime_ns INTEGER,
    last_sequence INTEGER
);
CREATE TABLE migration_history (
    migration_id TEXT PRIMARY KEY,
    from_version INTEGER NOT NULL,
    to_version INTEGER NOT NULL,
    started_at TEXT NOT NULL,
    committed_at TEXT,
    outcome TEXT NOT NULL,
    legacy_session_hash TEXT,
    legacy_ledger_hash TEXT
);
CREATE UNIQUE INDEX leases_one_active_per_item ON leases (session_id, item_id)
    WHERE status IN ('active', 'submitted');
"""


class RuntimeStoreError(RuntimeError):
    def __init__(self, reason_code: str, detail: str):
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {detail}")


class PersistenceBusyError(RuntimeStoreError):
    retryable = True

    def __init__(self, detail: str = "The runtime store is busy."):
        super().__init__("PERSISTENCE_BUSY", detail)


class StaleRevisionError(RuntimeStoreError):
    retryable = True

    def __init__(self, *, expected: int, actual: int):
        super().__init__("STALE_REVISION", f"Expected revision {expected}, found {actual}.")
        self.expected = expected
        self.actual = actual


class PersistenceInvalidError(RuntimeStoreError):
    retryable = False


@dataclass(frozen=True)
class StoreSnapshot:
    payload: dict[str, Any]
    revision: int
    schema_version: int = SCHEMA_VERSION


@dataclass(frozen=True)
class TransactionResult(StoreSnapshot):
    value: Any = None
    operation: str = "update"


class RuntimeStore:
    def __init__(self, workspace: Path, *, busy_timeout_ms: int = 5_000):
        self.workspace = Path(workspace)
        self.database_path = self.workspace / "runtime.sqlite3"
        self.busy_timeout_ms = max(1, int(busy_timeout_ms))
        self._schema_current = False

    def is_initialized(self) -> bool:
        """True once a committed store metadata row exists.

        File existence is not initialization: the database file appears as soon
        as an initializer opens it, and a crashed initializer leaves it empty.
        """
        if not self.database_path.is_file():
            return False
        connection = self._connect()
        try:
            return self._is_initialized(connection)
        except sqlite3.OperationalError as exc:
            if _is_busy(exc):
                raise PersistenceBusyError() from exc
            raise
        finally:
            connection.close()

    def bootstrap(
        self,
        payload: dict[str, Any],
        *,
        evidence: list[dict[str, Any]] | None = None,
        require_new: bool = False,
    ) -> StoreSnapshot:
        """Create the store from ``payload``, or load it if another writer already did.

        With ``require_new`` the caller's payload must become revision 1; losing
        the initialization race raises ``StaleRevisionError`` instead of
        silently discarding that payload.
        """
        snapshot, created = self._initialize(payload=payload, evidence=evidence or [])
        if require_new and not created:
            raise StaleRevisionError(expected=0, actual=snapshot.revision)
        return snapshot

    def open_or_migrate(self, *, session_path: Path, ledger_path: Path) -> StoreSnapshot:
        if self.is_initialized():
            return self.load()
        snapshot, _created = self._initialize(legacy=(session_path, ledger_path))
        return snapshot

    def _initialize(
        self,
        *,
        payload: dict[str, Any] | None = None,
        evidence: list[dict[str, Any]] | None = None,
        legacy: tuple[Path, Path] | None = None,
    ) -> tuple[StoreSnapshot, bool]:
        """Initialize the store in place under one exclusive SQLite transaction.

        Every initializer queues on the target database's own lock, so exactly
        one creates the schema and every other one loads its committed result. A
        crash rolls the transaction back and leaves an uninitialized database
        that the next initializer completes. Legacy import builds the recovery
        bundle while holding this lock; that bundle is the only file IO allowed
        inside a runtime write transaction.
        """
        started_at = time.monotonic()
        connection = self._connect()
        created = False
        quarantined = False
        try:
            try:
                connection.execute("BEGIN EXCLUSIVE")
            except sqlite3.OperationalError as exc:
                if _is_busy(exc):
                    raise PersistenceBusyError() from exc
                raise
            if not self._is_initialized(connection):
                legacy_hashes: tuple[str, str | None] | None = None
                if legacy is not None:
                    session_path, ledger_path = legacy
                    if not session_path.is_file():
                        raise PersistenceInvalidError(
                            "PERSISTENCE_INVALID", "No runtime store or legacy session exists."
                        )
                    payload = self._read_legacy_session(session_path)
                    evidence = self._read_legacy_evidence(ledger_path)
                    quarantined = self._create_recovery_bundle(session_path, ledger_path)
                    legacy_hashes = (
                        _sha256(session_path),
                        _sha256(ledger_path) if ledger_path.is_file() else None,
                    )
                if payload is None:
                    raise PersistenceInvalidError("PERSISTENCE_INVALID", "Initialization requires a session payload.")
                self._create_schema(connection)
                self._insert_metadata(connection, payload, revision=1, imported=legacy_hashes is not None)
                self._write_session(connection, payload, revision=1)
                self._write_evidence(connection, evidence or [], revision=1)
                if legacy_hashes is not None:
                    _backfill_outbox_from_evidence(connection, revision=1)
                    self._insert_legacy_migration(connection, legacy_hashes)
                    self._record_bundle_signature(connection)
                connection.commit()
                created = True
            else:
                connection.rollback()
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()
        if quarantined:
            _emit_persistence_event(
                "persistence.migration",
                operation="bundle_quarantine",
                outcome="bundle_quarantined",
                contention="none",
            )
        if created and legacy is not None:
            _emit_persistence_event(
                "persistence.migration",
                operation="legacy_import",
                outcome="committed",
                contention=_contention_bucket(started_at),
            )
        return self.load(), created

    @staticmethod
    def _is_initialized(connection: sqlite3.Connection) -> bool:
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'store_metadata'"
        ).fetchone()
        if table is None:
            return False
        if connection.execute("SELECT 1 FROM store_metadata WHERE singleton = 1").fetchone() is None:
            raise PersistenceInvalidError("PERSISTENCE_INVALID", "Runtime store metadata is incomplete.")
        return True

    @staticmethod
    def _insert_legacy_migration(connection: sqlite3.Connection, legacy_hashes: tuple[str, str | None]) -> None:
        now = _utc_now()
        connection.execute(
            "INSERT INTO migration_history "
            "(migration_id, from_version, to_version, started_at, committed_at, outcome, "
            "legacy_session_hash, legacy_ledger_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("legacy-v1-to-sqlite-v1", 0, SCHEMA_VERSION, now, now, "committed", *legacy_hashes),
        )

    def load(self) -> StoreSnapshot:
        if not self.database_path.is_file():
            raise PersistenceInvalidError("PERSISTENCE_INVALID", "The runtime store does not exist.")
        connection = self._connect()
        try:
            self._validate_schema(connection)
            self._check_recovery_bundle(connection)
            return self._load_snapshot(connection)
        finally:
            connection.close()

    def replace(
        self,
        payload: dict[str, Any],
        *,
        expected_revision: int | None,
        operation: str,
        evidence: list[dict[str, Any]] | None = None,
        outbox: list[dict[str, Any]] | None = None,
    ) -> StoreSnapshot:
        """Commit ``payload`` as the whole session at ``expected_revision``'s successor.

        The caller already holds the full payload, so no snapshot is loaded
        before the write or reloaded after it; the returned snapshot carries the
        caller's payload and the committed revision.
        """
        result = self._transact(
            lambda current: current.update(payload),
            expected_revision=expected_revision,
            operation=operation,
            evidence=evidence,
            outbox=outbox,
            load_current=False,
            reload_committed=False,
        )
        return StoreSnapshot(payload=result.payload, revision=result.revision)

    def transact(
        self,
        mutation: Callable[[dict[str, Any]], T],
        *,
        expected_revision: int | None = None,
        operation: str,
        evidence: list[dict[str, Any]] | None = None,
        outbox: list[dict[str, Any]] | None = None,
    ) -> TransactionResult:
        return self._transact(
            mutation,
            expected_revision=expected_revision,
            operation=operation,
            evidence=evidence,
            outbox=outbox,
        )

    def _transact(
        self,
        mutation: Callable[[dict[str, Any]], T],
        *,
        expected_revision: int | None,
        operation: str,
        evidence: list[dict[str, Any]] | None,
        outbox: list[dict[str, Any]] | None,
        load_current: bool = True,
        reload_committed: bool = True,
    ) -> TransactionResult:
        started_at = time.monotonic()
        transaction_id = uuid.uuid4().hex
        with _persistence_span("gh_address_cr.persistence.transaction", operation) as span:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                locked_at = time.monotonic()
                self._validate_schema(connection)
                if load_current:
                    current = self._load_snapshot(connection)
                    current_revision, working = current.revision, current.payload
                else:
                    current_revision, working = self._latest_revision(connection), {}
                if expected_revision is not None and expected_revision != current_revision:
                    raise StaleRevisionError(expected=expected_revision, actual=current_revision)
                value = mutation(working)
                next_revision = current_revision + 1
                normalized = json_ready(working)
                self._write_session(connection, normalized, revision=next_revision, already_normalized=True)
                self._write_evidence(
                    connection, evidence or [], revision=next_revision, transaction_id=transaction_id
                )
                self._write_outbox(connection, outbox or [], revision=next_revision, transaction_id=transaction_id)
                self._advance_revision(connection, next_revision)
                committed_payload = _committed_view(normalized) if reload_committed else working
                _record_size_buckets(span, connection, committed_payload)
                connection.commit()
                _record_timing(span, started_at=started_at, locked_at=locked_at, outcome="committed")
                result = TransactionResult(
                    payload=committed_payload,
                    revision=next_revision,
                    value=value,
                    operation=operation,
                )
                _emit_persistence_event(
                    "persistence.transaction",
                    operation=operation,
                    outcome="committed",
                    contention=_contention_bucket(started_at),
                )
                return result
            except sqlite3.OperationalError as exc:
                connection.rollback()
                if _is_busy(exc):
                    _record_timing(span, started_at=started_at, locked_at=None, outcome="busy")
                    _emit_persistence_event(
                        "persistence.transaction",
                        operation=operation,
                        outcome="busy",
                        contention=_contention_bucket(started_at),
                    )
                    raise PersistenceBusyError() from exc
                _record_timing(span, started_at=started_at, locked_at=None, outcome="failed")
                _emit_persistence_event(
                    "persistence.transaction",
                    operation=operation,
                    outcome="failed",
                    contention=_contention_bucket(started_at),
                )
                raise
            except sqlite3.IntegrityError as exc:
                connection.rollback()
                _record_timing(span, started_at=started_at, locked_at=None, outcome="invariant_violation")
                _emit_persistence_event(
                    "persistence.transaction",
                    operation=operation,
                    outcome="invariant_violation",
                    contention=_contention_bucket(started_at),
                )
                raise PersistenceInvalidError(
                    "PERSISTENCE_INVALID",
                    "The transition violates a runtime store invariant, such as one active lease per item.",
                ) from exc
            except Exception as exc:
                connection.rollback()
                outcome = _exception_outcome(exc)
                _record_timing(span, started_at=started_at, locked_at=None, outcome=outcome)
                _emit_persistence_event(
                    "persistence.transaction",
                    operation=operation,
                    outcome=outcome,
                    contention=_contention_bucket(started_at),
                )
                raise
            finally:
                connection.close()

    def load_evidence(self) -> list[dict[str, Any]]:
        connection = self._connect()
        try:
            self._validate_schema(connection)
            rows = connection.execute("SELECT record_json FROM evidence_events ORDER BY sequence").fetchall()
        finally:
            connection.close()
        return [json.loads(row[0]) for row in rows]

    def load_outbox(self) -> list[dict[str, Any]]:
        connection = self._connect()
        try:
            self._validate_schema(connection)
            rows = connection.execute(
                f"SELECT {', '.join(_OUTBOX_COLUMNS)} FROM outbox_commands ORDER BY rowid"
            ).fetchall()
        finally:
            connection.close()
        return [dict(zip(_OUTBOX_COLUMNS, row, strict=True)) for row in rows]

    def outbox_command(self, *, effect_type: str, idempotency_key: str) -> dict[str, Any] | None:
        """Return the canonical outbox row for one side effect, or None if it was never planned."""
        connection = self._connect()
        try:
            self._validate_schema(connection)
            row = connection.execute(
                f"SELECT {', '.join(_OUTBOX_COLUMNS)} FROM outbox_commands "
                "WHERE effect_type = ? AND idempotency_key = ?",
                (effect_type, idempotency_key),
            ).fetchone()
        finally:
            connection.close()
        return dict(zip(_OUTBOX_COLUMNS, row, strict=True)) if row is not None else None

    def mark_outbox_in_flight(self, command_id: str, *, owner_token: str | None = None) -> StoreSnapshot:
        return self._transition_outbox(
            "status = 'in_flight', attempt_count = attempt_count + 1, "
            "error_type = NULL, external_result_reference = NULL, owner_token = ?, in_flight_since = ?",
            (owner_token, _utc_now()),
            command_id=command_id,
            allowed_statuses=("planned", "failed", "unknown"),
            operation="outbox_execute",
            unknown_requires_idempotency=True,
        )

    def record_outbox_result(
        self,
        command_id: str,
        *,
        status: str,
        evidence: list[dict[str, Any]],
        external_result_reference: str | None = None,
        error_type: str | None = None,
        owner_token: str | None = None,
    ) -> StoreSnapshot:
        """Record an external result; an ``in_flight`` row accepts it only from its owner.

        ``unknown`` rows (owner gone) accept a reconciled result from anyone.
        """
        if status not in {"succeeded", "failed"}:
            raise PersistenceInvalidError("PERSISTENCE_INVALID", "Outbox result must be succeeded or failed.")
        if status == "succeeded" and (not evidence or not external_result_reference):
            raise PersistenceInvalidError(
                "PERSISTENCE_INVALID",
                "A successful outbox result requires evidence and an external result reference.",
            )
        connection = self._connect()
        started_at = time.monotonic()
        transaction_id = uuid.uuid4().hex
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._validate_schema(connection)
            next_revision = self._latest_revision(connection) + 1
            cursor = connection.execute(
                "UPDATE outbox_commands SET status = ?, error_type = ?, external_result_reference = ?, "
                "owner_token = NULL, in_flight_since = NULL "
                "WHERE command_id = ? AND (status = 'unknown' OR "
                "(status = 'in_flight' AND (owner_token IS NULL OR owner_token = ?)))",
                (status, error_type, external_result_reference, command_id, owner_token),
            )
            if cursor.rowcount != 1:
                raise PersistenceInvalidError(
                    "PERSISTENCE_INVALID",
                    "Outbox command is missing, not owned by this executor, or cannot record the requested result.",
                )
            self._write_evidence(connection, evidence, revision=next_revision, transaction_id=transaction_id)
            connection.execute("UPDATE sessions SET revision = ?, updated_at = ?", (next_revision, _utc_now()))
            self._advance_revision(connection, next_revision)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        _emit_persistence_event(
            "outbox.execution",
            operation="outbox_result",
            outcome=status,
            contention=_contention_bucket(started_at),
        )
        return self.load()

    def recover(self) -> int:
        """Demote ``in_flight`` commands whose executor is gone to ``unknown``.

        Reads first and opens a write transaction only when a dead-owner row
        exists, so ordinary loads never contend for the write lock. An executor
        holds its execution lock for the whole external call, so a held lock
        means the command is still running and must stay ``in_flight``.
        """
        started_at = time.monotonic()
        connection = self._connect()
        try:
            self._validate_schema(connection)
            in_flight = [
                str(row[0])
                for row in connection.execute("SELECT command_id FROM outbox_commands WHERE status = 'in_flight'")
            ]
        finally:
            connection.close()
        if not in_flight:
            return 0
        dead = [command_id for command_id in in_flight if not is_execution_lock_held(self.workspace, command_id)]
        recovered = 0
        if dead:
            with _persistence_span("gh_address_cr.persistence.recover", "outbox_recovery") as span:
                connection = self._connect()
                try:
                    connection.execute("BEGIN IMMEDIATE")
                    locked_at = time.monotonic()
                    self._validate_schema(connection)
                    current_revision = self._latest_revision(connection)
                    placeholders = ", ".join("?" for _ in dead)
                    cursor = connection.execute(
                        "UPDATE outbox_commands SET status = 'unknown', owner_token = NULL "
                        f"WHERE status = 'in_flight' AND command_id IN ({placeholders})",
                        dead,
                    )
                    recovered = int(cursor.rowcount)
                    if recovered:
                        next_revision = current_revision + 1
                        connection.execute(
                            "UPDATE sessions SET revision = ?, updated_at = ?", (next_revision, _utc_now())
                        )
                        self._advance_revision(connection, next_revision)
                    connection.commit()
                    _record_timing(span, started_at=started_at, locked_at=locked_at, outcome="recovered")
                except Exception:
                    connection.rollback()
                    raise
                finally:
                    connection.close()
        _emit_persistence_event(
            "persistence.recovery",
            operation="outbox_recovery",
            outcome="recovered" if recovered else "owner_alive",
            contention=_contention_bucket(started_at),
        )
        return recovered

    def _transition_outbox(
        self,
        assignment: str,
        assignment_params: tuple[Any, ...],
        *,
        command_id: str,
        allowed_statuses: tuple[str, ...],
        operation: str,
        unknown_requires_idempotency: bool = False,
    ) -> StoreSnapshot:
        started_at = time.monotonic()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._validate_schema(connection)
            current_revision = self._latest_revision(connection)
            placeholders = ", ".join("?" for _ in allowed_statuses)
            retry_clause = (
                " AND (status != 'unknown' OR retry_boundary = 'idempotent')"
                if unknown_requires_idempotency
                else ""
            )
            cursor = connection.execute(
                f"UPDATE outbox_commands SET {assignment} "
                f"WHERE command_id = ? AND status IN ({placeholders}){retry_clause}",
                (*assignment_params, command_id, *allowed_statuses),
            )
            if cursor.rowcount != 1:
                raise PersistenceInvalidError(
                    "PERSISTENCE_INVALID",
                    "Outbox command is missing or cannot enter the requested state.",
                )
            next_revision = current_revision + 1
            connection.execute("UPDATE sessions SET revision = ?, updated_at = ?", (next_revision, _utc_now()))
            self._advance_revision(connection, next_revision)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        _emit_persistence_event(
            "outbox.execution",
            operation=operation,
            outcome="in_flight",
            contention=_contention_bucket(started_at),
        )
        return self.load()

    def load_materializations(self) -> list[dict[str, Any]]:
        connection = self._connect()
        try:
            self._validate_schema(connection)
            return list(self._materialization_rows(connection).values())
        finally:
            connection.close()

    def recover_artifacts(self, *, session_path: Path, ledger_path: Path) -> int:
        """Rebuild stale, missing, failed, or externally edited projections.

        Drift is detected from the size and mtime recorded when each projection
        was last written, so the common path costs three ``stat`` calls rather
        than hashing files that grow with the session.
        """
        connection = self._connect()
        try:
            self._validate_schema(connection)
            revision = self._latest_revision(connection)
            rows = self._materialization_rows(connection)
        finally:
            connection.close()
        repairs = 0
        drift = 0
        for kind, path in self._artifact_paths(session_path, ledger_path):
            row = rows.get(kind)
            if row is not None and int(row["source_revision"]) > revision:
                raise PersistenceInvalidError(
                    "PERSISTENCE_INVALID",
                    "Artifact revision is newer than canonical runtime state.",
                )
            if row is None or int(row["source_revision"]) < revision or row["status"] != "current":
                repairs += 1
            elif not _artifact_matches(row, path):
                repairs += 1
                drift += 1
        if repairs:
            self._materialize(session_path=session_path, ledger_path=ledger_path, full_rebuild=bool(drift))
        if drift:
            _emit_persistence_event(
                "artifact.materialization",
                operation="artifact_drift",
                outcome="drift_repaired",
                contention="none",
            )
        _emit_persistence_event(
            "artifact.materialization",
            operation="artifact_recovery",
            outcome="rebuilt" if repairs else "current",
            contention="none",
        )
        return repairs

    def materialize_compatibility_artifacts(
        self, *, session_path: Path, ledger_path: Path, committed: StoreSnapshot | None = None
    ) -> None:
        """Materialize projections; ``committed`` skips a reload when it is still the latest revision."""
        self._materialize(session_path=session_path, ledger_path=ledger_path, committed=committed)

    def _materialize(
        self,
        *,
        session_path: Path,
        ledger_path: Path,
        full_rebuild: bool = False,
        committed: StoreSnapshot | None = None,
    ) -> None:
        """Write projections for one committed revision under the store's write lock.

        Holding the lock makes the projection bytes and the recorded revision
        agree even when writers race, and lets ``evidence.jsonl`` grow by
        appending only rows committed since the last write: evidence rows are
        append-only, so the appended file is byte-identical to a full rewrite.
        A full rebuild runs only when the file is missing, failed, or edited.
        """
        kinds = tuple(kind for kind, _ in self._artifact_paths(session_path, ledger_path))
        started_at = time.monotonic()
        with _persistence_span("gh_address_cr.persistence.materialize", "artifact_write") as span:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                locked_at = time.monotonic()
                self._validate_schema(connection)
                if committed is not None and committed.revision == self._latest_revision(connection):
                    snapshot = committed
                else:
                    snapshot = self._load_snapshot(connection)
                rows = self._materialization_rows(connection)
                written: list[tuple[str, Path, int | None]] = []
                self._write_session_projection(snapshot, session_path=session_path)
                written.append(("session_json", session_path, None))
                last_sequence = self._materialize_evidence(
                    connection, None if full_rebuild else rows.get("evidence_jsonl"), ledger_path
                )
                written.append(("evidence_jsonl", ledger_path, last_sequence))
                metadata_path = ledger_path.with_name(f"{ledger_path.name}.meta.json")
                write_json_atomic(
                    metadata_path,
                    {"format_version": 1, "schema_version": SCHEMA_VERSION, "revision": snapshot.revision},
                )
                written.append(("evidence_jsonl_metadata", metadata_path, None))
                for kind, path, last_sequence in written:
                    self._upsert_materialization(
                        connection, kind, revision=snapshot.revision, status="current", path=path,
                        last_sequence=last_sequence,
                    )
                connection.commit()
                _record_timing(span, started_at=started_at, locked_at=locked_at, outcome="current")
            except Exception as exc:
                if connection.in_transaction:
                    try:
                        revision = self._latest_revision(connection)
                        for kind in kinds:
                            self._upsert_materialization(
                                connection, kind, revision=revision, status="failed", error_type=type(exc).__name__
                            )
                        connection.commit()
                    except Exception:
                        connection.rollback()
                _record_timing(span, started_at=started_at, locked_at=None, outcome="failed")
                _emit_persistence_event(
                    "artifact.materialization",
                    operation="artifact_write",
                    outcome="failed",
                    contention="none",
                )
                if isinstance(exc, sqlite3.OperationalError) and _is_busy(exc):
                    raise PersistenceBusyError() from exc
                raise
            finally:
                connection.close()
        _emit_persistence_event(
            "artifact.materialization",
            operation="artifact_write",
            outcome="current",
            contention="none",
        )

    @staticmethod
    def _materialize_evidence(connection: sqlite3.Connection, row: dict[str, Any] | None, ledger_path: Path) -> int:
        last_sequence = int(connection.execute("SELECT COALESCE(MAX(sequence), 0) FROM evidence_events").fetchone()[0])
        appendable = (
            row is not None
            and row["status"] in {"current", "dirty"}
            and row["last_sequence"] is not None
            and int(row["last_sequence"]) <= last_sequence
            and _artifact_matches(row, ledger_path)
        )
        if appendable:
            rows = connection.execute(
                "SELECT record_json FROM evidence_events WHERE sequence > ? ORDER BY sequence",
                (int(row["last_sequence"]),),
            )
            with ledger_path.open("a", encoding="utf-8") as handle:
                for (encoded,) in rows:
                    handle.write(encoded)
                    handle.write("\n")
            return last_sequence
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(prefix=f"{ledger_path.name}.", suffix=".tmp", dir=ledger_path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                for (encoded,) in connection.execute("SELECT record_json FROM evidence_events ORDER BY sequence"):
                    handle.write(encoded)
                    handle.write("\n")
            os.replace(temporary_name, ledger_path)
        except BaseException:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)
            raise
        return last_sequence

    @staticmethod
    def _write_session_projection(snapshot: StoreSnapshot, *, session_path: Path) -> None:
        projection = dict(snapshot.payload)
        projection["persistence"] = {"schema_version": SCHEMA_VERSION, "revision": snapshot.revision}
        write_json_atomic(session_path, projection)

    @staticmethod
    def _artifact_paths(session_path: Path, ledger_path: Path) -> tuple[tuple[str, Path], ...]:
        return (
            ("session_json", session_path),
            ("evidence_jsonl", ledger_path),
            ("evidence_jsonl_metadata", ledger_path.with_name(f"{ledger_path.name}.meta.json")),
        )

    @staticmethod
    def _materialization_rows(connection: sqlite3.Connection) -> dict[str, dict[str, Any]]:
        rows = connection.execute(
            f"SELECT {', '.join(_MATERIALIZATION_COLUMNS)} FROM artifact_materializations ORDER BY artifact_kind"
        ).fetchall()
        return {row[0]: dict(zip(_MATERIALIZATION_COLUMNS, row, strict=True)) for row in rows}

    @staticmethod
    def _upsert_materialization(
        connection: sqlite3.Connection,
        kind: str,
        *,
        revision: int,
        status: str,
        path: Path | None = None,
        last_sequence: int | None = None,
        error_type: str | None = None,
    ) -> None:
        stat = path.stat() if path is not None else None
        connection.execute(
            "INSERT INTO artifact_materializations "
            "(artifact_kind, source_revision, format_version, status, content_hash, last_attempt_at, error_type, "
            "size, mtime_ns, last_sequence) VALUES (?, ?, 1, ?, NULL, ?, ?, ?, ?, ?) "
            "ON CONFLICT(artifact_kind) DO UPDATE SET source_revision = excluded.source_revision, "
            "format_version = excluded.format_version, status = excluded.status, content_hash = NULL, "
            "last_attempt_at = excluded.last_attempt_at, error_type = excluded.error_type, "
            "size = excluded.size, mtime_ns = excluded.mtime_ns, last_sequence = excluded.last_sequence",
            (
                kind,
                revision,
                status,
                _utc_now(),
                error_type,
                stat.st_size if stat is not None else None,
                stat.st_mtime_ns if stat is not None else None,
                last_sequence,
            ),
        )

    @staticmethod
    def _latest_revision(connection: sqlite3.Connection) -> int:
        return int(connection.execute("SELECT latest_revision FROM store_metadata WHERE singleton = 1").fetchone()[0])

    @staticmethod
    def _advance_revision(connection: sqlite3.Connection, revision: int) -> None:
        connection.execute("UPDATE artifact_materializations SET status = 'dirty' WHERE status = 'current'")
        connection.execute(
            "UPDATE store_metadata SET latest_revision = ?, updated_at = ? WHERE singleton = 1",
            (revision, _utc_now()),
        )

    def _upgrade_schema(self, connection: sqlite3.Connection) -> None:
        """Bring an initialized older store to ``SCHEMA_VERSION`` exactly once.

        Every opener checks the version; only a store that is behind takes the
        exclusive lock, re-checks under it, and applies each step in one
        transaction recorded in ``migration_history``.
        """
        version = _stored_schema_version(connection)
        if version is None or version > SCHEMA_VERSION:
            return
        if version == SCHEMA_VERSION:
            self._schema_current = True
            return
        started_at = time.monotonic()
        with _persistence_span("gh_address_cr.persistence.migrate", "schema_upgrade") as span:
            try:
                connection.execute("BEGIN EXCLUSIVE")
            except sqlite3.OperationalError as exc:
                if _is_busy(exc):
                    raise PersistenceBusyError() from exc
                raise
            locked_at = time.monotonic()
            try:
                version = _stored_schema_version(connection) or SCHEMA_VERSION
                while version < SCHEMA_VERSION:
                    step = _MIGRATIONS.get(version)
                    if step is None:
                        raise PersistenceInvalidError(
                            "PERSISTENCE_INVALID", f"No migration exists from runtime schema version {version}."
                        )
                    step(connection)
                    now = _utc_now()
                    connection.execute(
                        "INSERT INTO migration_history (migration_id, from_version, to_version, started_at, "
                        "committed_at, outcome) VALUES (?, ?, ?, ?, ?, 'committed')",
                        (f"sqlite-v{version}-to-v{version + 1}", version, version + 1, now, now),
                    )
                    version += 1
                    connection.execute(
                        "UPDATE store_metadata SET schema_version = ?, updated_at = ? WHERE singleton = 1",
                        (version, now),
                    )
                self._record_bundle_signature(connection)
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
            _record_timing(span, started_at=started_at, locked_at=locked_at, outcome="committed")
        self._schema_current = True
        _emit_persistence_event(
            "persistence.migration",
            operation="schema_upgrade",
            outcome="committed",
            contention=_contention_bucket(started_at),
        )

    def _connect(self, database_path: Path | None = None) -> sqlite3.Connection:
        self.workspace.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            database_path or self.database_path,
            timeout=self.busy_timeout_ms / 1_000,
            isolation_level=None,
        )
        connection.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")
        connection.execute("PRAGMA foreign_keys = ON")
        if database_path is None and not self._schema_current:
            try:
                self._upgrade_schema(connection)
            except BaseException:
                connection.close()
                raise
        return connection

    @staticmethod
    def _create_schema(connection: sqlite3.Connection) -> None:
        # One statement at a time: ``executescript`` commits any open transaction
        # first, which would publish a half-initialized schema outside the
        # exclusive initialization transaction.
        for statement in _SCHEMA_SQL.split(";"):
            if statement.strip():
                connection.execute(statement)

    @staticmethod
    def _insert_metadata(
        connection: sqlite3.Connection,
        payload: dict[str, Any],
        *,
        revision: int,
        imported: bool,
    ) -> None:
        now = _utc_now()
        store_seed = f"{payload.get('session_id', '')}:{now}".encode()
        connection.execute(
            "INSERT INTO store_metadata VALUES (1, ?, ?, ?, ?, ?, ?, ?, NULL)",
            (
                SCHEMA_VERSION,
                hashlib.sha256(store_seed).hexdigest()[:32],
                now,
                now,
                now if imported else None,
                "legacy-v1" if imported else None,
                revision,
            ),
        )

    @staticmethod
    def _validate_schema(connection: sqlite3.Connection) -> None:
        try:
            row = connection.execute(
                "SELECT schema_version FROM store_metadata WHERE singleton = 1"
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            raise PersistenceInvalidError("PERSISTENCE_INVALID", "Runtime schema metadata is unavailable.") from exc
        if row is None or int(row[0]) != SCHEMA_VERSION:
            found = "missing" if row is None else str(row[0])
            raise PersistenceInvalidError(
                "PERSISTENCE_INVALID",
                f"Unsupported runtime schema version {found}; expected {SCHEMA_VERSION}.",
            )

    @staticmethod
    def _write_session(
        connection: sqlite3.Connection, payload: dict[str, Any], *, revision: int, already_normalized: bool = False
    ) -> None:
        """Write the session, touching only item and lease rows whose payload changed.

        Unchanged rows keep their revisions, so ``last_observed_revision`` and
        ``transition_revision`` record when each row last changed. Changed and
        removed leases are deleted before any lease is inserted, so a
        transaction that releases one lease and grants another on the same
        item never trips the one-active-lease index mid-write.
        """
        normalized = dict(payload if already_normalized else json_ready(payload))
        session_id = str(normalized.get("session_id") or "")
        if not session_id:
            raise PersistenceInvalidError("PERSISTENCE_INVALID", "Session ID is required.")
        items = normalized.pop("items", {})
        leases = normalized.pop("leases", {})
        normalized.pop("persistence", None)
        if not isinstance(items, dict) or not isinstance(leases, dict):
            raise PersistenceInvalidError("PERSISTENCE_INVALID", "Session items and leases must be objects.")
        now = _utc_now()
        connection.execute("DELETE FROM sessions WHERE session_id != ?", (session_id,))
        connection.execute(
            "INSERT INTO sessions (session_id, repo, pr_number, status, payload_json, revision, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(session_id) DO UPDATE SET repo = excluded.repo, "
            "pr_number = excluded.pr_number, status = excluded.status, payload_json = excluded.payload_json, "
            "revision = excluded.revision, updated_at = excluded.updated_at",
            (
                session_id,
                str(normalized.get("repo") or ""),
                str(normalized.get("pr_number") or ""),
                str(normalized.get("status") or ""),
                _dumps(normalized),
                revision,
                now,
                now,
            ),
        )
        _write_items(connection, session_id, items, revision=revision)
        _write_leases(connection, session_id, leases, revision=revision)

    @staticmethod
    def _write_evidence(
        connection: sqlite3.Connection,
        records: list[dict[str, Any]],
        *,
        revision: int,
        transaction_id: str | None = None,
    ) -> None:
        for raw in records:
            record = EvidenceRecord.from_json(raw)
            if payload_hash(record.payload) != record.payload_hash:
                raise PersistenceInvalidError(
                    "PERSISTENCE_INVALID", f"Evidence record {record.record_id} has a payload hash mismatch."
                )
            existing = connection.execute(
                "SELECT record_json FROM evidence_events WHERE record_id = ?", (record.record_id,)
            ).fetchone()
            encoded = _json(record.to_json())
            if existing is not None:
                if existing[0] != encoded:
                    raise PersistenceInvalidError(
                        "PERSISTENCE_INVALID", f"Evidence record {record.record_id} diverges from canonical content."
                    )
                continue
            connection.execute(
                "INSERT INTO evidence_events "
                "(record_id, session_id, item_id, lease_id, actor_role, event_type, timestamp, payload_json, "
                "payload_hash, transaction_id, committed_revision, record_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record.record_id,
                    record.session_id,
                    record.item_id,
                    record.lease_id,
                    record.role,
                    record.event_type,
                    record.timestamp,
                    _json(record.payload),
                    record.payload_hash,
                    transaction_id,
                    revision,
                    encoded,
                ),
            )

    @staticmethod
    def _write_outbox(
        connection: sqlite3.Connection,
        commands: list[dict[str, Any]],
        *,
        revision: int,
        transaction_id: str | None = None,
    ) -> None:
        session_row = connection.execute("SELECT session_id FROM sessions ORDER BY rowid LIMIT 1").fetchone()
        if session_row is None:
            raise PersistenceInvalidError("PERSISTENCE_INVALID", "Runtime store has no session row.")
        session_id = str(session_row[0])
        required = {"command_id", "effect_type", "idempotency_key", "operation_category"}
        for command in commands:
            missing = sorted(required.difference(command))
            if missing:
                raise PersistenceInvalidError(
                    "PERSISTENCE_INVALID",
                    f"Outbox command is missing required fields: {', '.join(missing)}.",
                )
            connection.execute(
                "INSERT INTO outbox_commands "
                "(command_id, session_id, effect_type, idempotency_key, planned_revision, "
                "operation_category, status, attempt_count, retry_boundary, error_type, "
                "external_result_reference, transaction_id) VALUES (?, ?, ?, ?, ?, ?, 'planned', 0, ?, NULL, NULL, ?)",
                (
                    str(command["command_id"]),
                    session_id,
                    str(command["effect_type"]),
                    str(command["idempotency_key"]),
                    revision,
                    str(command["operation_category"]),
                    command.get("retry_boundary"),
                    transaction_id,
                ),
            )

    @staticmethod
    def _load_snapshot(connection: sqlite3.Connection) -> StoreSnapshot:
        row = connection.execute(
            "SELECT payload_json, revision FROM sessions ORDER BY rowid LIMIT 1"
        ).fetchone()
        if row is None:
            raise PersistenceInvalidError("PERSISTENCE_INVALID", "Runtime store has no session row.")
        payload = json.loads(row[0])
        session_id = str(payload["session_id"])
        payload["items"] = {
            item_id: json.loads(encoded)
            for item_id, encoded in connection.execute(
                "SELECT item_id, payload_json FROM items WHERE session_id = ? ORDER BY item_id", (session_id,)
            )
        }
        leases: dict[str, dict[str, Any]] = {}
        for lease_id, encoded in connection.execute(
            "SELECT lease_id, payload_json FROM leases WHERE session_id = ? ORDER BY lease_id", (session_id,)
        ):
            lease = json.loads(encoded)
            lease.setdefault("lease_id", lease_id)
            _coerce_lease_datetimes(lease)
            leases[lease_id] = lease
        payload["leases"] = leases
        _derive_item_claim_projection(payload["items"], leases)
        return StoreSnapshot(payload=payload, revision=int(row[1]))

    @staticmethod
    def _read_legacy_session(path: Path) -> dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PersistenceInvalidError("PERSISTENCE_INVALID", "Legacy session JSON is malformed.") from exc
        if not isinstance(payload, dict):
            raise PersistenceInvalidError("PERSISTENCE_INVALID", "Legacy session must be a JSON object.")
        repo = str(payload.get("repo") or "")
        pr_number = str(payload.get("pr_number") or "")
        if not payload.get("session_id") and repo and pr_number:
            payload["session_id"] = f"{repo}#{pr_number}"
        payload.setdefault("items", {})
        payload.setdefault("leases", {})
        payload.setdefault("metadata", {})
        return payload

    @staticmethod
    def _read_legacy_evidence(path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        records: list[dict[str, Any]] = []
        try:
            for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if not line.strip():
                    continue
                raw = json.loads(line)
                if not isinstance(raw, dict):
                    raise ValueError(f"row {line_number} is not an object")
                record = EvidenceRecord.from_json(raw)
                if payload_hash(record.payload) != record.payload_hash:
                    raise ValueError(f"row {line_number} payload hash mismatch")
                records.append(record.to_json())
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise PersistenceInvalidError("PERSISTENCE_INVALID", f"Legacy evidence ledger is malformed: {exc}") from exc
        return records

    def _create_recovery_bundle(self, session_path: Path, ledger_path: Path) -> bool:
        """Publish the verified legacy-v1 bundle; return True if an incomplete one was quarantined.

        Callers hold the exclusive initialization lock, so no other process is
        writing bundle state. The bundle is built in a staging directory and
        published by one atomic rename, and ``manifest.json`` is written last,
        so a published bundle without a manifest can only come from a pre-035
        build that crashed mid-copy. That bundle is renamed aside, never
        trusted and never deleted. A complete bundle whose hashes diverge is
        tampering and still fails fast.
        """
        bundle = self.workspace / RECOVERY_BUNDLE_NAME
        for staging_leftover in self.workspace.glob(f"{RECOVERY_BUNDLE_NAME}.tmp-*"):
            shutil.rmtree(staging_leftover)
        quarantined = False
        if bundle.exists():
            if (bundle / "manifest.json").is_file():
                self._verify_recovery_bundle()
                manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
                if manifest.get("files") != self._legacy_input_hashes(session_path, ledger_path):
                    raise PersistenceInvalidError(
                        "PERSISTENCE_INVALID",
                        "Legacy inputs diverge from the verified recovery bundle.",
                    )
                return False
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            bundle.rename(self.workspace / f"{RECOVERY_BUNDLE_NAME}.incomplete-{stamp}-{uuid.uuid4().hex[:8]}")
            quarantined = True
        staging = self.workspace / f"{RECOVERY_BUNDLE_NAME}.tmp-{uuid.uuid4().hex}"
        staging.mkdir()
        files: dict[str, str] = {}
        for name, source in (("session.json", session_path), ("evidence.jsonl", ledger_path)):
            if name == "evidence.jsonl" and not source.is_file():
                continue
            shutil.copy2(source, staging / name)
            fsync_file(staging / name)
            files[name] = _sha256(staging / name)
        write_json_durable(staging / "manifest.json", {"format_version": "legacy-v1", "files": files})
        os.rename(staging, bundle)
        fsync_directory(self.workspace)
        return quarantined

    @staticmethod
    def _legacy_input_hashes(session_path: Path, ledger_path: Path) -> dict[str, str]:
        expected = {"session.json": _sha256(session_path)}
        if ledger_path.is_file():
            expected["evidence.jsonl"] = _sha256(ledger_path)
        return expected

    def _bundle_signature(self) -> str | None:
        bundle = self.workspace / RECOVERY_BUNDLE_NAME
        if not bundle.is_dir():
            return None
        parts = []
        for entry in sorted(bundle.iterdir()):
            stat = entry.stat()
            parts.append(f"{entry.name}:{stat.st_size}:{stat.st_mtime_ns}")
        return "|".join(parts)

    def _record_bundle_signature(self, connection: sqlite3.Connection) -> None:
        """Remember the verified bundle's stat signature so later loads skip re-hashing it."""
        signature = self._bundle_signature()
        if signature is not None:
            self._verify_recovery_bundle()
        connection.execute("UPDATE store_metadata SET legacy_bundle_signature = ? WHERE singleton = 1", (signature,))

    def _check_recovery_bundle(self, connection: sqlite3.Connection) -> None:
        """Fail fast on a changed bundle; hash it only when its stat signature moved."""
        signature = self._bundle_signature()
        if signature is None:
            return
        stored = connection.execute("SELECT legacy_bundle_signature FROM store_metadata WHERE singleton = 1").fetchone()
        if stored is None or stored[0] != signature:
            self._verify_recovery_bundle()

    def _verify_recovery_bundle(self) -> None:
        bundle = self.workspace / RECOVERY_BUNDLE_NAME
        if not bundle.exists():
            return
        manifest_path = bundle / "manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            files = manifest["files"]
            if manifest.get("format_version") != "legacy-v1" or not isinstance(files, dict):
                raise ValueError("unsupported manifest shape")
            for name, expected_hash in files.items():
                if name not in {"session.json", "evidence.jsonl"}:
                    raise ValueError(f"unsupported recovery file {name}")
                artifact = bundle / name
                if not artifact.is_file() or _sha256(artifact) != expected_hash:
                    raise ValueError(f"recovery file {name} failed hash verification")
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise PersistenceInvalidError(
                "PERSISTENCE_INVALID", f"Legacy recovery bundle integrity check failed: {exc}"
            ) from exc


_OUTBOX_COLUMNS = (
    "command_id",
    "session_id",
    "effect_type",
    "idempotency_key",
    "planned_revision",
    "operation_category",
    "status",
    "attempt_count",
    "retry_boundary",
    "error_type",
    "external_result_reference",
    "owner_token",
    "in_flight_since",
    "transaction_id",
)
_MATERIALIZATION_COLUMNS = (
    "artifact_kind",
    "source_revision",
    "format_version",
    "status",
    "content_hash",
    "last_attempt_at",
    "error_type",
    "size",
    "mtime_ns",
    "last_sequence",
)
_BACKFILL_STATUS = {"succeeded": "succeeded", "failed": "failed", "in_flight": "unknown"}


def outbox_command_id(effect_type: str, idempotency_key: str) -> str:
    digest = hashlib.sha256(f"{effect_type}\0{idempotency_key}".encode()).hexdigest()[:24]
    return f"outbox_{digest}"


def retry_boundary_for(effect_type: str) -> str:
    """A reply may already be visible after an interrupted call, so it is reconciled, never blindly retried."""
    return "reconcile_only" if effect_type == "github_reply" else "idempotent"


def _backfill_outbox_from_evidence(connection: sqlite3.Connection, *, revision: int) -> int:
    """Derive outbox rows for side effects recorded only as evidence.

    Stores created before schema v2 (and legacy JSON sessions) record side
    effects as ``side_effect_attempt`` evidence; the publisher now decides from
    the outbox, so each recorded key needs a row. Rows that already exist are
    canonical and are never overwritten. The latest attempt per key decides the
    status: an interrupted ``in_flight`` attempt, or a success without its
    external reference, becomes ``unknown`` and goes through reconciliation.
    """
    session_row = connection.execute("SELECT session_id FROM sessions ORDER BY rowid LIMIT 1").fetchone()
    if session_row is None:
        raise PersistenceInvalidError("PERSISTENCE_INVALID", "Runtime store has no session row.")
    existing = {
        (str(effect_type), str(key))
        for effect_type, key in connection.execute("SELECT effect_type, idempotency_key FROM outbox_commands")
    }
    latest: dict[tuple[str, str], SideEffectAttempt] = {}
    attempts: dict[tuple[str, str], int] = {}
    for (encoded,) in connection.execute(
        "SELECT payload_json FROM evidence_events WHERE event_type = 'side_effect_attempt' ORDER BY sequence"
    ):
        try:
            attempt = SideEffectAttempt.from_json(json.loads(encoded))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise PersistenceInvalidError(
                "PERSISTENCE_INVALID", "A recorded side-effect attempt is malformed and cannot be backfilled."
            ) from exc
        key = (attempt.side_effect_type, attempt.idempotency_key)
        latest[key] = attempt
        if attempt.status == "in_flight":
            attempts[key] = attempts.get(key, 0) + 1
    created = 0
    for (effect_type, idempotency_key), attempt in latest.items():
        if (effect_type, idempotency_key) in existing:
            continue
        status = _BACKFILL_STATUS.get(attempt.status)
        if status is None:
            raise PersistenceInvalidError(
                "PERSISTENCE_INVALID", f"Unsupported recorded side-effect status {attempt.status!r}."
            )
        reference = attempt.external_url if status == "succeeded" else None
        if status == "succeeded" and not reference:
            status = "unknown"
        connection.execute(
            "INSERT INTO outbox_commands (command_id, session_id, effect_type, idempotency_key, planned_revision, "
            "operation_category, status, attempt_count, retry_boundary, error_type, external_result_reference) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                outbox_command_id(effect_type, idempotency_key),
                str(session_row[0]),
                effect_type,
                idempotency_key,
                revision,
                effect_type,
                status,
                attempts.get((effect_type, idempotency_key), 0),
                retry_boundary_for(effect_type),
                "external_error" if status == "failed" else None,
                reference,
            ),
        )
        created += 1
    return created


def _migrate_v1_to_v2(connection: sqlite3.Connection) -> None:
    for statement in (
        "ALTER TABLE outbox_commands ADD COLUMN owner_token TEXT",
        "ALTER TABLE outbox_commands ADD COLUMN in_flight_since TEXT",
        "ALTER TABLE outbox_commands ADD COLUMN transaction_id TEXT",
        "ALTER TABLE artifact_materializations ADD COLUMN size INTEGER",
        "ALTER TABLE artifact_materializations ADD COLUMN mtime_ns INTEGER",
        "ALTER TABLE artifact_materializations ADD COLUMN last_sequence INTEGER",
        "ALTER TABLE store_metadata ADD COLUMN legacy_bundle_signature TEXT",
    ):
        connection.execute(statement)
    duplicate = connection.execute(
        "SELECT COUNT(*) FROM (SELECT 1 FROM leases WHERE status IN ('active', 'submitted') "
        "GROUP BY session_id, item_id HAVING COUNT(*) > 1)"
    ).fetchone()[0]
    if duplicate:
        raise PersistenceInvalidError(
            "PERSISTENCE_INVALID",
            f"{duplicate} item(s) hold more than one active lease; the store cannot be upgraded until repaired.",
        )
    connection.execute(
        "CREATE UNIQUE INDEX leases_one_active_per_item ON leases (session_id, item_id) "
        "WHERE status IN ('active', 'submitted')"
    )
    revision = int(connection.execute("SELECT latest_revision FROM store_metadata WHERE singleton = 1").fetchone()[0])
    _backfill_outbox_from_evidence(connection, revision=revision)
    connection.execute("UPDATE artifact_materializations SET status = 'dirty'")


_MIGRATIONS: dict[int, Callable[[sqlite3.Connection], None]] = {1: _migrate_v1_to_v2}


def _stored_schema_version(connection: sqlite3.Connection) -> int | None:
    table = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'store_metadata'"
    ).fetchone()
    if table is None:
        return None
    row = connection.execute("SELECT schema_version FROM store_metadata WHERE singleton = 1").fetchone()
    return int(row[0]) if row is not None else None


def _artifact_matches(row: dict[str, Any], path: Path) -> bool:
    if row.get("size") is None or row.get("mtime_ns") is None:
        return False
    try:
        stat = path.stat()
    except OSError:
        return False
    return stat.st_size == int(row["size"]) and stat.st_mtime_ns == int(row["mtime_ns"])


def _count_bucket(count: int) -> str:
    if count <= 0:
        return "0"
    if count <= 10:
        return "1-10"
    if count <= 100:
        return "11-100"
    if count <= 1000:
        return "101-1000"
    return "1000+"


class _UnrecordedSpan:
    def is_recording(self) -> bool:
        return False

    def set_attribute(self, key: str, value: Any) -> None:
        return None


@contextmanager
def _persistence_span(name: str, operation: str) -> Iterator[Any]:
    """Open a child span for one persistence operation without letting telemetry change the outcome."""
    attributes = {"gh_address_cr.persistence.operation": operation if operation in _SAFE_OPERATIONS else "other"}
    try:
        from gh_address_cr.otel_tracing import start_child_span

        manager = start_child_span(name, attributes=attributes)
        span = manager.__enter__()
    except Exception:
        yield _UnrecordedSpan()
        return
    try:
        yield span
    except BaseException as exc:
        try:
            manager.__exit__(type(exc), exc, exc.__traceback__)
        except Exception:
            pass
        raise
    else:
        try:
            manager.__exit__(None, None, None)
        except Exception:
            pass


def _set_span_attributes(span: Any, attributes: dict[str, Any]) -> None:
    try:
        if not span.is_recording():
            return
        for key, value in attributes.items():
            span.set_attribute(key, value)
    except Exception:
        return


def _record_timing(span: Any, *, started_at: float, locked_at: float | None, outcome: str) -> None:
    now = time.monotonic()
    attributes: dict[str, Any] = {"gh_address_cr.persistence.outcome": outcome}
    if locked_at is not None:
        attributes["gh_address_cr.persistence.lock_wait_ms"] = round((locked_at - started_at) * 1000, 3)
        attributes["gh_address_cr.persistence.execute_ms"] = round((now - locked_at) * 1000, 3)
    else:
        attributes["gh_address_cr.persistence.duration_ms"] = round((now - started_at) * 1000, 3)
    _set_span_attributes(span, attributes)


def _record_size_buckets(span: Any, connection: sqlite3.Connection, payload: dict[str, Any]) -> None:
    try:
        if not span.is_recording():
            return
        evidence_count = int(connection.execute("SELECT COALESCE(MAX(sequence), 0) FROM evidence_events").fetchone()[0])
    except Exception:
        return
    items = payload.get("items")
    _set_span_attributes(
        span,
        {
            "gh_address_cr.persistence.items_bucket": _count_bucket(len(items) if isinstance(items, dict) else 0),
            "gh_address_cr.persistence.evidence_bucket": _count_bucket(evidence_count),
        },
    )


def _write_items(connection: sqlite3.Connection, session_id: str, items: dict[str, Any], *, revision: int) -> None:
    stored = {
        str(item_id): (int(first), encoded)
        for item_id, first, encoded in connection.execute(
            "SELECT item_id, first_observed_revision, payload_json FROM items WHERE session_id = ?", (session_id,)
        )
    }
    for item_id in stored.keys() - {str(key) for key in items}:
        connection.execute("DELETE FROM items WHERE session_id = ? AND item_id = ?", (session_id, item_id))
    for item_id, item in items.items():
        if not isinstance(item, dict):
            raise PersistenceInvalidError("PERSISTENCE_INVALID", f"Item {item_id} must be an object.")
        encoded = _dumps(item)
        prior = stored.get(str(item_id))
        if prior is not None and prior[1] == encoded:
            continue
        evidence = item.get("classification_evidence")
        classification = evidence.get("classification") if isinstance(evidence, dict) else item.get("decision")
        connection.execute(
            "INSERT OR REPLACE INTO items VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                session_id,
                str(item_id),
                str(item.get("item_kind") or "unknown"),
                str(item.get("state") or "open"),
                str(classification) if classification else None,
                encoded,
                prior[0] if prior is not None else revision,
                revision,
            ),
        )


def _write_leases(connection: sqlite3.Connection, session_id: str, leases: dict[str, Any], *, revision: int) -> None:
    stored = {
        str(lease_id): encoded
        for lease_id, encoded in connection.execute(
            "SELECT lease_id, payload_json FROM leases WHERE session_id = ?", (session_id,)
        )
    }
    changed: list[tuple[str, dict[str, Any], str]] = []
    for lease_id, lease in leases.items():
        if not isinstance(lease, dict):
            raise PersistenceInvalidError("PERSISTENCE_INVALID", f"Lease {lease_id} must be an object.")
        encoded = _dumps(lease)
        if stored.get(str(lease_id)) != encoded:
            changed.append((str(lease_id), lease, encoded))
    for lease_id in (stored.keys() - {str(key) for key in leases}) | {lease_id for lease_id, _, _ in changed}:
        connection.execute("DELETE FROM leases WHERE lease_id = ?", (lease_id,))
    for lease_id, lease, encoded in changed:
        connection.execute(
            "INSERT INTO leases VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                lease_id,
                session_id,
                str(lease.get("item_id") or ""),
                str(lease.get("agent_id") or ""),
                str(lease.get("role") or ""),
                str(lease.get("status") or ""),
                lease.get("request_id"),
                lease.get("request_hash"),
                lease.get("request_path"),
                lease.get("resume_token"),
                lease.get("created_at"),
                lease.get("expires_at"),
                lease.get("submitted_at"),
                lease.get("completed_at"),
                revision,
                encoded,
            ),
        )
        for key in lease.get("conflict_keys") or ():
            connection.execute("INSERT INTO lease_conflict_keys VALUES (?, ?)", (lease_id, str(key)))


def _committed_view(normalized: dict[str, Any]) -> dict[str, Any]:
    """The payload ``_load_snapshot`` would return for rows just written from ``normalized``.

    Rows are written from this same JSON-ready payload, so rebuilding the view
    in memory (id-ordered items and leases, coerced lease datetimes, derived
    claim projection) matches a reload without decoding every row again.
    """
    payload = {key: value for key, value in normalized.items() if key not in {"items", "leases", "persistence"}}
    items = normalized.get("items") or {}
    payload["items"] = {str(item_id): items[item_id] for item_id in sorted(items, key=str)}
    source_leases = normalized.get("leases") or {}
    leases: dict[str, dict[str, Any]] = {}
    for lease_id in sorted(source_leases, key=str):
        lease = dict(source_leases[lease_id])
        lease.setdefault("lease_id", str(lease_id))
        _coerce_lease_datetimes(lease)
        leases[str(lease_id)] = lease
    payload["leases"] = leases
    _derive_item_claim_projection(payload["items"], leases)
    return payload


def _dumps(value: Any) -> str:
    """Canonical compact JSON for values that are already JSON-ready."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json(value: Any) -> str:
    return json.dumps(json_ready(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65_536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_busy(exc: sqlite3.OperationalError) -> bool:
    return getattr(exc, "sqlite_errorcode", None) in {5, 6} or "locked" in str(exc).lower()


def _coerce_lease_datetimes(lease: dict[str, Any]) -> None:
    for field in _LEASE_DATETIME_FIELDS:
        value = lease.get(field)
        if not isinstance(value, str) or not value:
            continue
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        lease[field] = parsed


def _derive_item_claim_projection(
    items: dict[str, dict[str, Any]], leases: dict[str, dict[str, Any]]
) -> None:
    active_by_item: dict[str, dict[str, Any]] = {}
    for lease in leases.values():
        if lease.get("status") not in {"active", "submitted"}:
            continue
        item_id = str(lease.get("item_id") or "")
        if item_id in active_by_item:
            raise PersistenceInvalidError(
                "PERSISTENCE_INVALID",
                "Multiple active leases reference one item.",
            )
        active_by_item[item_id] = lease

    for item_id, item in items.items():
        active_lease = active_by_item.get(item_id)
        if active_lease is None:
            if item.get("state") == "claimed":
                state, status = returned_claimable_state(item)
                item["state"] = state
                item["status"] = status
            item["claimed_by"] = None
            item["claimed_at"] = None
            item["lease_expires_at"] = None
            item.pop("active_lease_id", None)
            continue
        item["state"] = "claimed"
        item["active_lease_id"] = str(active_lease["lease_id"])
        item["claimed_by"] = active_lease.get("agent_id")
        item["claimed_at"] = active_lease.get("created_at")
        item["lease_expires_at"] = active_lease.get("expires_at")


def _contention_bucket(started_at: float) -> str:
    elapsed_ms = max(0.0, (time.monotonic() - started_at) * 1_000)
    if elapsed_ms < 5:
        return "none"
    if elapsed_ms < 50:
        return "low"
    if elapsed_ms < 500:
        return "medium"
    return "high"


def _exception_outcome(exc: Exception) -> str:
    reason_code = str(getattr(exc, "reason_code", "")).upper()
    if reason_code == "STALE_REVISION":
        return "stale_revision"
    if reason_code in {"ITEM_ALREADY_LEASED", "CONFLICT_KEYS_OVERLAP", "ITEM_NOT_CLAIMABLE"}:
        return "policy_rejected"
    return "failed"


def _emit_persistence_event(name: str, *, operation: str, outcome: str, contention: str) -> None:
    try:
        from gh_address_cr.otel_tracing import add_current_span_event

        add_current_span_event(
            name,
            {
                "persistence.operation": operation if operation in _SAFE_OPERATIONS else "other",
                "persistence.outcome": outcome,
                "persistence.schema_version": SCHEMA_VERSION,
                "persistence.contention": contention,
            },
        )
    except Exception:
        return
