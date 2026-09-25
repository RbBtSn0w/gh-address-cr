from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, TypeVar

from gh_address_cr.core.github_thread_state import returned_claimable_state
from gh_address_cr.core.io import json_ready, write_json_atomic
from gh_address_cr.evidence.ledger import EvidenceRecord, payload_hash

SCHEMA_VERSION = 1
_LEASE_DATETIME_FIELDS = {"created_at", "expires_at", "submitted_at", "completed_at"}
_SAFE_OPERATIONS = {
    "bootstrap",
    "legacy_import",
    "lease_claim",
    "lease_release",
    "session_update",
    "status_update",
}
T = TypeVar("T")


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

    def bootstrap(self, payload: dict[str, Any], *, evidence: list[dict[str, Any]] | None = None) -> StoreSnapshot:
        return self._bootstrap_new(payload, evidence=evidence or [])

    def _bootstrap_new(
        self,
        payload: dict[str, Any],
        *,
        evidence: list[dict[str, Any]],
        legacy_hashes: tuple[str, str | None] | None = None,
    ) -> StoreSnapshot:
        self.workspace.mkdir(parents=True, exist_ok=True)
        if self.database_path.exists():
            return self.load()
        descriptor, temporary_name = tempfile.mkstemp(
            prefix="runtime.", suffix=".sqlite3.tmp", dir=self.workspace
        )
        os.close(descriptor)
        temporary_path = Path(temporary_name)
        connection = self._connect(temporary_path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._create_schema(connection)
            imported = legacy_hashes is not None
            self._insert_metadata(connection, payload, revision=1, imported=imported)
            self._write_session(connection, payload, revision=1)
            self._write_evidence(connection, evidence, revision=1)
            if legacy_hashes is not None:
                now = _utc_now()
                connection.execute(
                    "INSERT INTO migration_history "
                    "(migration_id, from_version, to_version, started_at, committed_at, outcome, "
                    "legacy_session_hash, legacy_ledger_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        "legacy-v1-to-sqlite-v1",
                        0,
                        SCHEMA_VERSION,
                        now,
                        now,
                        "committed",
                        legacy_hashes[0],
                        legacy_hashes[1],
                    ),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            temporary_path.unlink(missing_ok=True)
            raise
        finally:
            connection.close()
        try:
            if self.database_path.exists():
                return self.load()
            os.replace(temporary_path, self.database_path)
        finally:
            temporary_path.unlink(missing_ok=True)
        return self.load()

    def open_or_migrate(self, *, session_path: Path, ledger_path: Path) -> StoreSnapshot:
        if self.database_path.exists():
            return self.load()
        if not session_path.is_file():
            raise PersistenceInvalidError("PERSISTENCE_INVALID", "No runtime store or legacy session exists.")
        payload = self._read_legacy_session(session_path)
        evidence = self._read_legacy_evidence(ledger_path)
        self._create_recovery_bundle(session_path, ledger_path)
        snapshot = self._bootstrap_new(
            payload,
            evidence=evidence,
            legacy_hashes=(
                _sha256(session_path),
                _sha256(ledger_path) if ledger_path.is_file() else None,
            ),
        )
        _emit_persistence_event(
            "persistence.migration",
            operation="legacy_import",
            outcome="committed",
            contention="none",
        )
        return snapshot

    def load(self) -> StoreSnapshot:
        if not self.database_path.is_file():
            raise PersistenceInvalidError("PERSISTENCE_INVALID", "The runtime store does not exist.")
        self._verify_recovery_bundle()
        connection = self._connect()
        try:
            self._validate_schema(connection)
            return self._load_snapshot(connection)
        finally:
            connection.close()

    def replace(
        self,
        payload: dict[str, Any],
        *,
        expected_revision: int | None,
        operation: str,
    ) -> StoreSnapshot:
        def replace_payload(current: dict[str, Any]) -> None:
            current.clear()
            current.update(payload)

        result = self.transact(
            replace_payload,
            expected_revision=expected_revision,
            operation=operation,
        )
        return StoreSnapshot(payload=result.payload, revision=result.revision)

    def transact(
        self,
        mutation: Callable[[dict[str, Any]], T],
        *,
        expected_revision: int | None = None,
        operation: str,
        evidence: list[dict[str, Any]] | None = None,
    ) -> TransactionResult:
        started_at = time.monotonic()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._validate_schema(connection)
            current = self._load_snapshot(connection)
            if expected_revision is not None and expected_revision != current.revision:
                raise StaleRevisionError(expected=expected_revision, actual=current.revision)
            value = mutation(current.payload)
            next_revision = current.revision + 1
            normalized = json_ready(current.payload)
            self._write_session(connection, normalized, revision=next_revision)
            self._write_evidence(connection, evidence or [], revision=next_revision)
            connection.execute(
                "UPDATE store_metadata SET latest_revision = ?, updated_at = ? WHERE singleton = 1",
                (next_revision, _utc_now()),
            )
            connection.commit()
            result = TransactionResult(
                payload=self._load_snapshot_from_new_connection(),
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
                _emit_persistence_event(
                    "persistence.transaction",
                    operation=operation,
                    outcome="busy",
                    contention=_contention_bucket(started_at),
                )
                raise PersistenceBusyError() from exc
            _emit_persistence_event(
                "persistence.transaction",
                operation=operation,
                outcome="failed",
                contention=_contention_bucket(started_at),
            )
            raise
        except Exception as exc:
            connection.rollback()
            _emit_persistence_event(
                "persistence.transaction",
                operation=operation,
                outcome=_exception_outcome(exc),
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

    def materialize_compatibility_artifacts(self, *, session_path: Path, ledger_path: Path) -> None:
        self.materialize_session_projection(session_path=session_path)
        snapshot = self.load()
        ledger_metadata_path = ledger_path.with_name(f"{ledger_path.name}.meta.json")

        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(prefix=f"{ledger_path.name}.", suffix=".tmp", dir=ledger_path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                for record in self.load_evidence():
                    handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
                    handle.write("\n")
            os.replace(temporary_name, ledger_path)
        except Exception:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)
            raise

        write_json_atomic(
            ledger_metadata_path,
            {
                "format_version": 1,
                "schema_version": SCHEMA_VERSION,
                "revision": snapshot.revision,
            },
        )

        self._record_materializations(
            snapshot.revision,
            (
                ("session_json", session_path),
                ("evidence_jsonl", ledger_path),
                ("evidence_jsonl_metadata", ledger_metadata_path),
            ),
        )

    def materialize_session_projection(self, *, session_path: Path) -> None:
        snapshot = self.load()
        projection = json_ready(snapshot.payload)
        projection["persistence"] = {"schema_version": SCHEMA_VERSION, "revision": snapshot.revision}
        write_json_atomic(session_path, projection)
        self._record_materializations(snapshot.revision, (("session_json", session_path),))

    def _record_materializations(self, revision: int, artifacts: tuple[tuple[str, Path], ...]) -> None:
        connection = self._connect()
        try:
            for kind, path in artifacts:
                connection.execute(
                    "INSERT INTO artifact_materializations "
                    "(artifact_kind, source_revision, format_version, status, content_hash, last_attempt_at, error_type) "
                    "VALUES (?, ?, ?, ?, ?, ?, NULL) "
                    "ON CONFLICT(artifact_kind) DO UPDATE SET source_revision=excluded.source_revision, "
                    "format_version=excluded.format_version, status=excluded.status, content_hash=excluded.content_hash, "
                    "last_attempt_at=excluded.last_attempt_at, error_type=NULL",
                    (kind, revision, 1, "current", _sha256(path), _utc_now()),
                )
            connection.commit()
        finally:
            connection.close()

    def _connect(self, database_path: Path | None = None) -> sqlite3.Connection:
        self.workspace.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            database_path or self.database_path,
            timeout=self.busy_timeout_ms / 1_000,
            isolation_level=None,
        )
        connection.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _load_snapshot_from_new_connection(self) -> dict[str, Any]:
        connection = self._connect()
        try:
            return self._load_snapshot(connection).payload
        finally:
            connection.close()

    @staticmethod
    def _create_schema(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE store_metadata (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                schema_version INTEGER NOT NULL,
                store_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                legacy_import_completed_at TEXT,
                import_format_version TEXT,
                latest_revision INTEGER NOT NULL
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
                UNIQUE (session_id, effect_type, idempotency_key)
            );
            CREATE TABLE artifact_materializations (
                artifact_kind TEXT PRIMARY KEY,
                source_revision INTEGER NOT NULL,
                format_version INTEGER NOT NULL,
                status TEXT NOT NULL,
                content_hash TEXT,
                last_attempt_at TEXT,
                error_type TEXT
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
            """
        )

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
            "INSERT INTO store_metadata VALUES (1, ?, ?, ?, ?, ?, ?, ?)",
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
    def _write_session(connection: sqlite3.Connection, payload: dict[str, Any], *, revision: int) -> None:
        normalized = json_ready(payload)
        session_id = str(normalized.get("session_id") or "")
        if not session_id:
            raise PersistenceInvalidError("PERSISTENCE_INVALID", "Session ID is required.")
        items = normalized.pop("items", {})
        leases = normalized.pop("leases", {})
        normalized.pop("persistence", None)
        now = _utc_now()
        created_row = connection.execute(
            "SELECT created_at FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        first_observed_revisions = dict(
            connection.execute(
                "SELECT item_id, first_observed_revision FROM items WHERE session_id = ?",
                (session_id,),
            )
        )
        connection.execute("DELETE FROM sessions")
        connection.execute(
            "INSERT INTO sessions (session_id, repo, pr_number, status, payload_json, revision, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                session_id,
                str(normalized.get("repo") or ""),
                str(normalized.get("pr_number") or ""),
                str(normalized.get("status") or ""),
                _json(normalized),
                revision,
                str(created_row[0]) if created_row else now,
                now,
            ),
        )
        if not isinstance(items, dict) or not isinstance(leases, dict):
            raise PersistenceInvalidError("PERSISTENCE_INVALID", "Session items and leases must be objects.")
        for item_id, item in items.items():
            if not isinstance(item, dict):
                raise PersistenceInvalidError("PERSISTENCE_INVALID", f"Item {item_id} must be an object.")
            evidence = item.get("classification_evidence")
            classification = evidence.get("classification") if isinstance(evidence, dict) else item.get("decision")
            connection.execute(
                "INSERT INTO items VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    session_id,
                    str(item_id),
                    str(item.get("item_kind") or "unknown"),
                    str(item.get("state") or "open"),
                    str(classification) if classification else None,
                    _json(item),
                    int(first_observed_revisions.get(str(item_id), revision)),
                    revision,
                ),
            )
        for lease_id, lease in leases.items():
            if not isinstance(lease, dict):
                raise PersistenceInvalidError("PERSISTENCE_INVALID", f"Lease {lease_id} must be an object.")
            connection.execute(
                "INSERT INTO leases VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(lease_id),
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
                    _json(lease),
                ),
            )
            for key in lease.get("conflict_keys") or ():
                connection.execute("INSERT INTO lease_conflict_keys VALUES (?, ?)", (str(lease_id), str(key)))

    @staticmethod
    def _write_evidence(connection: sqlite3.Connection, records: list[dict[str, Any]], *, revision: int) -> None:
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
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)",
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
                    revision,
                    encoded,
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

    def _create_recovery_bundle(self, session_path: Path, ledger_path: Path) -> None:
        bundle = self.workspace / "legacy-v1-recovery"
        if bundle.exists():
            self._verify_recovery_bundle()
            manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
            expected = {"session.json": _sha256(session_path)}
            if ledger_path.is_file():
                expected["evidence.jsonl"] = _sha256(ledger_path)
            if manifest.get("files") != expected:
                raise PersistenceInvalidError(
                    "PERSISTENCE_INVALID",
                    "Legacy inputs diverge from the verified recovery bundle.",
                )
            return
        bundle.mkdir(parents=False)
        shutil.copy2(session_path, bundle / "session.json")
        files = {"session.json": _sha256(bundle / "session.json")}
        if ledger_path.is_file():
            shutil.copy2(ledger_path, bundle / "evidence.jsonl")
            files["evidence.jsonl"] = _sha256(bundle / "evidence.jsonl")
        write_json_atomic(bundle / "manifest.json", {"format_version": "legacy-v1", "files": files})

    def _verify_recovery_bundle(self) -> None:
        bundle = self.workspace / "legacy-v1-recovery"
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
