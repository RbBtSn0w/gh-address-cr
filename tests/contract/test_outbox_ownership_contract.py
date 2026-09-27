"""Spec 035 F3/F4/F6 and P2/P3: outbox ownership, publish authority, schema v2, projections.

Regression coverage for the Spec 034 audit reproductions R4 (loading a session
demoted a live ``in_flight`` command to ``unknown``) and R5 (publish
idempotency was decided from the rebuildable ``evidence.jsonl`` projection).
"""

from __future__ import annotations

import json
import multiprocessing
import os
import sqlite3
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from gh_address_cr.core import protocol_codes
from gh_address_cr.core import session as session_store
from gh_address_cr.core.errors import WorkflowError
from gh_address_cr.core.process_lock import try_acquire_execution_lock
from gh_address_cr.core.runtime_kernel.stack import project_stack_context
from gh_address_cr.core.runtime_store import (
    SCHEMA_VERSION,
    PersistenceInvalidError,
    RuntimeStore,
    outbox_command_id,
)
from gh_address_cr.evidence.ledger import EvidenceRecord, SideEffectAttempt

REPO = "owner/repo"
PR_NUMBER = "123"
SESSION_ID = f"{REPO}#{PR_NUMBER}"
ITEM_ID = "github-thread:THREAD_1"
REPLY_KEY = f"{SESSION_ID}:{ITEM_ID}:github_reply"
COMMAND = {
    "command_id": "command-owner",
    "effect_type": "github_resolve",
    "idempotency_key": "resolve-owner",
    "operation_category": "github_resolve",
    "retry_boundary": "idempotent",
}


def _session() -> dict:
    return {
        "session_id": SESSION_ID,
        "repo": REPO,
        "pr_number": PR_NUMBER,
        "status": "WAITING_FOR_FIX",
        "items": {
            "finding-1": {"item_id": "finding-1", "item_kind": "local_finding", "state": "open", "status": "OPEN"},
            "finding-2": {"item_id": "finding-2", "item_kind": "local_finding", "state": "open", "status": "OPEN"},
        },
        "leases": {},
        "metadata": {},
    }


def _publish_ready_item() -> dict:
    return {
        "item_id": ITEM_ID,
        "item_kind": "github_thread",
        "source": "github",
        "thread_id": "THREAD_1",
        "state": "publish_ready",
        "status": "OPEN",
        "blocking": True,
        "accepted_response": {
            "resolution": "clarify",
            "note": "Need maintainer input.",
            "reply_markdown": "Can you confirm the intended behavior?",
            "validation_commands": [{"command": "python3 -m unittest tests.test_example", "result": "passed"}],
        },
    }


class _CountingClient:
    def __init__(self):
        self.post_reply_calls = 0
        self.resolved: list[str] = []

    def get_stack_context(self, repo, pr_number):
        return project_stack_context(
            {
                "schema_version": "stack_observation.v1",
                "availability": "absent",
                "repo": repo,
                "selected_pr_number": str(pr_number),
                "observed_at": "2026-09-27T00:00:00Z",
                "selected_pr": {
                    "position": 1,
                    "pr_number": str(pr_number),
                    "state": "OPEN",
                    "is_draft": False,
                    "base_ref_name": "main",
                    "head_ref_name": "feature",
                    "head_oid": "a" * 40,
                    "merge_queue_state": None,
                },
                "members": [],
            }
        )

    def viewer_login(self):
        return "agent-login"

    def post_reply(self, repo, pr_number, thread_id, body):
        self.post_reply_calls += 1
        return "https://github.test/reply-new"

    def resolve_thread(self, repo, pr_number, thread_id):
        self.resolved.append(thread_id)
        return True

    def list_threads(self, repo, pr_number):
        return [{"id": "THREAD_1", "isResolved": bool(self.resolved)}]


def _write_publish_session() -> session_store.SessionManager:
    manager = session_store.SessionManager(REPO, PR_NUMBER)
    session = manager.create(status="WAITING_FOR_PUBLISH")
    session["items"] = {ITEM_ID: _publish_ready_item()}
    manager.save(session)
    return manager


def _reply_attempt(status: str, *, external_url: str | None = None) -> SideEffectAttempt:
    return SideEffectAttempt.new(
        session_id=SESSION_ID,
        item_id=ITEM_ID,
        side_effect_type="github_reply",
        idempotency_key=REPLY_KEY,
        status=status,
        external_url=external_url,
        timestamp="2026-09-27T00:00:00Z",
    )


def _record(ledger, attempt: SideEffectAttempt) -> None:
    ledger.record_side_effect_attempt(
        attempt=attempt, lease_id=None, agent_id="gh-address-cr-publisher", timestamp="2026-09-27T00:00:00Z"
    )


def _hold_in_flight(workspace: str, started, resume) -> None:
    store = RuntimeStore(Path(workspace))
    lock = try_acquire_execution_lock(Path(workspace), COMMAND["command_id"])
    assert lock is not None
    store.mark_outbox_in_flight(COMMAND["command_id"], owner_token="owner-a")
    started.set()
    resume.wait(timeout=30)
    lock.release()


def _die_in_flight(workspace: str) -> None:
    store = RuntimeStore(Path(workspace))
    try_acquire_execution_lock(Path(workspace), COMMAND["command_id"])
    store.mark_outbox_in_flight(COMMAND["command_id"], owner_token="owner-dead")
    os._exit(0)


def _publisher_mid_reply(state_dir: str, started, resume) -> None:
    from gh_address_cr.core import side_effect_outbox
    from gh_address_cr.core.utils import get_session_ledger

    with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": state_dir}, clear=False):
        session = session_store.load_session(REPO, PR_NUMBER)
        ledger = get_session_ledger(session)
        with side_effect_outbox.execution_guard(session, effect_type="github_reply", idempotency_key=REPLY_KEY):
            _record(ledger, _reply_attempt("in_flight"))
            started.set()
            resume.wait(timeout=30)
            _record(ledger, _reply_attempt("succeeded", external_url="https://github.test/reply-first"))


def _open_v1_store(workspace: str, barrier, queue) -> None:
    barrier.wait()
    try:
        RuntimeStore(Path(workspace), busy_timeout_ms=30_000).load()
    except Exception as exc:
        queue.put(f"{type(exc).__name__}: {exc}")
    else:
        queue.put("ok")


def _write_and_materialize(workspace: str, barrier, index: int) -> None:
    store = RuntimeStore(Path(workspace), busy_timeout_ms=30_000)
    barrier.wait()
    for step in range(5):
        record = EvidenceRecord.new(
            session_id=SESSION_ID,
            item_id="finding-1",
            lease_id=None,
            agent_id=f"agent-{index}",
            role="fixer",
            event_type="note",
            payload={"writer": index, "step": step},
        )
        store.transact(lambda payload: None, operation="session_update", evidence=[record.to_json()])
        store.materialize_compatibility_artifacts(
            session_path=Path(workspace) / "session.json", ledger_path=Path(workspace) / "evidence.jsonl"
        )


def _downgrade_to_v1(store: RuntimeStore) -> None:
    """Rewrite a fresh store into the Spec 034 (schema v1) layout."""
    with closing(sqlite3.connect(store.database_path)) as connection:
        connection.execute("DROP INDEX leases_one_active_per_item")
        for table, column in (
            ("outbox_commands", "owner_token"),
            ("outbox_commands", "in_flight_since"),
            ("outbox_commands", "transaction_id"),
            ("artifact_materializations", "size"),
            ("artifact_materializations", "mtime_ns"),
            ("artifact_materializations", "last_sequence"),
            ("store_metadata", "legacy_bundle_signature"),
        ):
            connection.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
        connection.execute("UPDATE store_metadata SET schema_version = 1")
        connection.commit()


def _side_effect_record(effect_type: str, key: str, status: str, url: str | None = None) -> dict:
    attempt = SideEffectAttempt.new(
        session_id=SESSION_ID,
        item_id="finding-1",
        side_effect_type=effect_type,
        idempotency_key=key,
        status=status,
        external_url=url,
        timestamp=f"2026-09-27T00:00:0{len(status)}Z",
    )
    return EvidenceRecord.new(
        session_id=SESSION_ID,
        item_id="finding-1",
        lease_id=None,
        agent_id="publisher",
        role="publisher",
        event_type="side_effect_attempt",
        payload=attempt.to_json(),
    ).to_json()


LEGACY_SIDE_EFFECTS = [
    ("github_reply", "reply-ok", "in_flight", None),
    ("github_reply", "reply-ok", "succeeded", "https://github.test/reply-ok"),
    ("github_reply", "reply-interrupted", "in_flight", None),
    ("github_resolve", "resolve-failed", "in_flight", None),
    ("github_resolve", "resolve-failed", "failed", None),
    ("github_reply", "reply-no-url", "succeeded", None),
]
EXPECTED_BACKFILL = {
    "reply-ok": ("succeeded", "https://github.test/reply-ok", "reconcile_only"),
    "reply-interrupted": ("unknown", None, "reconcile_only"),
    "resolve-failed": ("failed", None, "idempotent"),
    "reply-no-url": ("unknown", None, "reconcile_only"),
}


@unittest.skipIf(os.name == "nt", "ownership contracts use fork")
class OutboxOwnershipContractTest(unittest.TestCase):
    def _store_with_planned_command(self, tmp: str) -> RuntimeStore:
        store = RuntimeStore(Path(tmp))
        store.bootstrap(_session())
        store.transact(lambda payload: None, operation="outbox_plan", outbox=[dict(COMMAND)])
        return store

    def test_load_does_not_demote_live_in_flight_command(self):
        context = multiprocessing.get_context("fork")
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store_with_planned_command(tmp)
            started, resume = context.Event(), context.Event()
            owner = context.Process(target=_hold_in_flight, args=(tmp, started, resume))
            owner.start()
            self.assertTrue(started.wait(timeout=30))

            recovered = [RuntimeStore(Path(tmp)).recover() for _ in range(3)]
            status_while_alive = store.load_outbox()[0]["status"]
            resume.set()
            owner.join(timeout=30)

        self.assertEqual(recovered, [0, 0, 0])
        self.assertEqual(status_while_alive, "in_flight")

    def test_owner_death_demotes_to_unknown(self):
        context = multiprocessing.get_context("fork")
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store_with_planned_command(tmp)
            owner = context.Process(target=_die_in_flight, args=(tmp,))
            owner.start()
            owner.join(timeout=30)
            self.assertEqual(owner.exitcode, 0)

            recovered = RuntimeStore(Path(tmp)).recover()
            command = store.load_outbox()[0]

        self.assertEqual(recovered, 1)
        self.assertEqual(command["status"], "unknown")
        self.assertIsNone(command["owner_token"])

    def test_in_flight_result_is_accepted_only_from_its_owner(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store_with_planned_command(tmp)
            store.mark_outbox_in_flight(COMMAND["command_id"], owner_token="owner-a")
            evidence = EvidenceRecord.new(
                session_id=SESSION_ID,
                item_id="finding-1",
                lease_id=None,
                agent_id="agent",
                role="publisher",
                event_type="thread_resolved",
                payload={"result": "recorded"},
            ).to_json()

            with self.assertRaises(PersistenceInvalidError):
                store.record_outbox_result(
                    COMMAND["command_id"], status="succeeded", evidence=[evidence],
                    external_result_reference="thread", owner_token="owner-b",
                )
            store.record_outbox_result(
                COMMAND["command_id"], status="succeeded", evidence=[evidence],
                external_result_reference="thread", owner_token="owner-a",
            )
            status = store.load_outbox()[0]["status"]

        self.assertEqual(status, "succeeded")

    def test_concurrent_publish_same_item_posts_once(self):
        from gh_address_cr.core import publisher

        context = multiprocessing.get_context("fork")
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                manager = _write_publish_session()
                started, resume = context.Event(), context.Event()
                first = context.Process(target=_publisher_mid_reply, args=(tmp, started, resume))
                first.start()
                self.assertTrue(started.wait(timeout=30))
                client = _CountingClient()

                with self.assertRaises(WorkflowError) as blocked:
                    publisher.publish_github_thread_responses(REPO, PR_NUMBER, github_client=client)
                resume.set()
                first.join(timeout=30)
                self.assertEqual(first.exitcode, 0)
                result = publisher.publish_github_thread_responses(REPO, PR_NUMBER, github_client=client)
                item = manager.load()["items"][ITEM_ID]

        self.assertEqual(blocked.exception.reason_code, protocol_codes.SIDE_EFFECT_IN_PROGRESS)
        self.assertEqual(result["status"], "PUBLISH_COMPLETE")
        self.assertEqual(client.post_reply_calls, 0)
        self.assertEqual(item["reply_url"], "https://github.test/reply-first")

    def test_publish_decisions_ignore_projection_tampering(self):
        from gh_address_cr.core import publisher, side_effect_outbox
        from gh_address_cr.core.utils import get_session_ledger

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                manager = _write_publish_session()
                session = manager.load()
                ledger = get_session_ledger(session)
                with side_effect_outbox.execution_guard(
                    session, effect_type="github_reply", idempotency_key=REPLY_KEY
                ):
                    _record(ledger, _reply_attempt("in_flight"))
                    _record(ledger, _reply_attempt("succeeded", external_url="https://github.test/reply-first"))
                manager.ledger_path.write_text("", encoding="utf-8")
                client = _CountingClient()

                with patch(
                    "gh_address_cr.evidence.ledger.EvidenceLedger._iter_records",
                    side_effect=AssertionError("publish must not read the evidence.jsonl projection"),
                ):
                    result = publisher.publish_github_thread_responses(REPO, PR_NUMBER, github_client=client)
                item = manager.load()["items"][ITEM_ID]

        self.assertEqual(result["status"], "PUBLISH_COMPLETE")
        self.assertEqual(client.post_reply_calls, 0)
        self.assertEqual(item["reply_url"], "https://github.test/reply-first")

    def test_read_only_load_takes_no_write_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                manager = _write_publish_session()
                manager.load()
                blocker = sqlite3.connect(RuntimeStore(manager.workspace_path).database_path, isolation_level=None)
                try:
                    blocker.execute("BEGIN IMMEDIATE")
                    started = time.monotonic()
                    loaded = manager.load()
                    elapsed = time.monotonic() - started
                finally:
                    blocker.rollback()
                    blocker.close()

        self.assertEqual(loaded["items"][ITEM_ID]["state"], "publish_ready")
        self.assertLess(elapsed, 2.0)


@unittest.skipIf(os.name == "nt", "schema contracts use fork")
class SchemaV2ContractTest(unittest.TestCase):
    def test_legacy_import_backfills_outbox_from_side_effect_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / "session.json").write_text(json.dumps(_session()), encoding="utf-8")
            with (workspace / "evidence.jsonl").open("w", encoding="utf-8") as handle:
                for effect_type, key, status, url in LEGACY_SIDE_EFFECTS:
                    handle.write(json.dumps(_side_effect_record(effect_type, key, status, url)) + "\n")
            store = RuntimeStore(workspace)

            store.open_or_migrate(session_path=workspace / "session.json", ledger_path=workspace / "evidence.jsonl")
            rows = {row["idempotency_key"]: row for row in store.load_outbox()}

        self.assertEqual(
            {key: (row["status"], row["external_result_reference"], row["retry_boundary"]) for key, row in rows.items()},
            EXPECTED_BACKFILL,
        )
        self.assertEqual(rows["reply-ok"]["command_id"], outbox_command_id("github_reply", "reply-ok"))

    @unittest.skipIf(sqlite3.sqlite_version_info < (3, 35, 0), "fixture needs ALTER TABLE DROP COLUMN")
    def test_v1_store_upgrade_backfills_outbox_and_keeps_existing_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RuntimeStore(Path(tmp))
            store.bootstrap(_session())
            existing = {
                "command_id": outbox_command_id("github_reply", "reply-ok"),
                "effect_type": "github_reply",
                "idempotency_key": "reply-ok",
                "operation_category": "github_reply",
                "retry_boundary": "reconcile_only",
            }
            store.transact(
                lambda payload: None,
                operation="outbox_plan",
                evidence=[_side_effect_record(*row) for row in LEGACY_SIDE_EFFECTS],
                outbox=[existing],
            )
            _downgrade_to_v1(store)

            upgraded = RuntimeStore(Path(tmp))
            snapshot = upgraded.load()
            rows = {row["idempotency_key"]: row for row in upgraded.load_outbox()}
            with closing(sqlite3.connect(upgraded.database_path)) as connection:
                version = connection.execute("SELECT schema_version FROM store_metadata").fetchone()[0]
                migrations = [row[0] for row in connection.execute("SELECT migration_id FROM migration_history")]

        self.assertEqual(snapshot.revision, 2)
        self.assertEqual(version, SCHEMA_VERSION)
        self.assertEqual(migrations, ["sqlite-v1-to-v2"])
        self.assertEqual(rows["reply-ok"]["status"], "planned", "an existing canonical row is never overwritten")
        self.assertEqual(
            {key: (row["status"], row["external_result_reference"]) for key, row in rows.items() if key != "reply-ok"},
            {key: value[:2] for key, value in EXPECTED_BACKFILL.items() if key != "reply-ok"},
        )

    @unittest.skipIf(sqlite3.sqlite_version_info < (3, 35, 0), "fixture needs ALTER TABLE DROP COLUMN")
    def test_v1_store_upgrades_to_v2_exactly_once_under_concurrency(self):
        context = multiprocessing.get_context("fork")
        worker_count = 8
        for _round in range(5):
            with self.subTest(round=_round), tempfile.TemporaryDirectory() as tmp:
                store = RuntimeStore(Path(tmp))
                store.bootstrap(_session())
                _downgrade_to_v1(store)
                barrier, queue = context.Barrier(worker_count), context.Queue()
                workers = [context.Process(target=_open_v1_store, args=(tmp, barrier, queue)) for _ in range(worker_count)]
                for worker in workers:
                    worker.start()
                for worker in workers:
                    worker.join(timeout=60)
                outcomes = [queue.get(timeout=5) for _ in workers]
                with closing(sqlite3.connect(store.database_path)) as connection:
                    upgrades = connection.execute(
                        "SELECT COUNT(*) FROM migration_history WHERE migration_id = 'sqlite-v1-to-v2'"
                    ).fetchone()[0]

                self.assertEqual(outcomes, ["ok"] * worker_count)
                self.assertEqual(upgrades, 1)

    @unittest.skipIf(sqlite3.sqlite_version_info < (3, 35, 0), "fixture needs ALTER TABLE DROP COLUMN")
    def test_v1_upgrade_rejects_duplicate_active_leases(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RuntimeStore(Path(tmp))
            store.bootstrap(_session())
            _downgrade_to_v1(store)
            with closing(sqlite3.connect(store.database_path)) as connection:
                for lease_id in ("lease-a", "lease-b"):
                    connection.execute(
                        "INSERT INTO leases (lease_id, session_id, item_id, agent_id, role, status, "
                        "transition_revision, payload_json) VALUES (?, ?, 'finding-1', 'agent', 'fixer', 'active', 1, ?)",
                        (lease_id, SESSION_ID, json.dumps({"lease_id": lease_id, "item_id": "finding-1"})),
                    )
                connection.commit()

            with self.assertRaises(PersistenceInvalidError):
                RuntimeStore(Path(tmp)).load()
            with closing(sqlite3.connect(store.database_path)) as connection:
                version = connection.execute("SELECT schema_version FROM store_metadata").fetchone()[0]

        self.assertEqual(version, 1, "a rejected upgrade leaves the v1 store untouched")

    def test_db_rejects_second_active_lease_for_item_without_bricking_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RuntimeStore(Path(tmp))
            store.bootstrap(_session())

            def two_active_leases(payload: dict) -> None:
                for lease_id in ("lease-a", "lease-b"):
                    payload["leases"][lease_id] = {
                        "lease_id": lease_id,
                        "item_id": "finding-1",
                        "agent_id": lease_id,
                        "role": "fixer",
                        "status": "active",
                    }

            with self.assertRaises(PersistenceInvalidError):
                store.transact(two_active_leases, operation="lease_claim")
            snapshot = store.load()

        self.assertEqual(snapshot.revision, 1)
        self.assertEqual(snapshot.payload["leases"], {})

    def test_committed_view_matches_a_fresh_reload(self):
        from datetime import datetime, timezone

        with tempfile.TemporaryDirectory() as tmp:
            store = RuntimeStore(Path(tmp))
            store.bootstrap(_session())

            def mutate(payload: dict) -> None:
                payload["items"] = {
                    "z-item": {"item_id": "z-item", "item_kind": "local_finding", "state": "open", "status": "OPEN"},
                    **payload["items"],
                }
                payload["leases"]["lease-b"] = {
                    "item_id": "finding-1",
                    "agent_id": "agent-b",
                    "role": "fixer",
                    "status": "active",
                    "created_at": datetime(2026, 9, 27, 1, 0, tzinfo=timezone.utc),
                    "expires_at": "2026-09-27T02:00:00Z",
                }
                payload["leases"]["lease-a"] = {
                    "item_id": "finding-2", "agent_id": "agent-a", "role": "fixer", "status": "released",
                }
                payload["persistence"] = {"schema_version": SCHEMA_VERSION, "revision": 99}

            committed = store.transact(mutate, operation="lease_claim")
            reloaded = store.load()

        self.assertEqual(committed.payload, reloaded.payload)
        self.assertEqual(list(committed.payload["items"]), list(reloaded.payload["items"]))
        self.assertEqual(list(committed.payload["leases"]), list(reloaded.payload["leases"]))
        self.assertEqual(committed.payload["items"]["finding-1"]["state"], "claimed")

    def test_transaction_id_is_shared_by_events_and_outbox_of_one_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RuntimeStore(Path(tmp))
            store.bootstrap(_session())
            record = EvidenceRecord.new(
                session_id=SESSION_ID, item_id="finding-1", lease_id=None, agent_id="agent",
                role="fixer", event_type="note", payload={"n": 1},
            )
            store.transact(
                lambda payload: None, operation="outbox_plan", evidence=[record.to_json()], outbox=[dict(COMMAND)]
            )
            with closing(sqlite3.connect(store.database_path)) as connection:
                event_ids = {row[0] for row in connection.execute("SELECT transaction_id FROM evidence_events")}
                outbox_ids = {row[0] for row in connection.execute("SELECT transaction_id FROM outbox_commands")}

        self.assertEqual(len(event_ids), 1)
        self.assertEqual(event_ids, outbox_ids)
        self.assertIsNotNone(next(iter(event_ids)))

    def test_last_observed_revision_changes_only_with_item_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RuntimeStore(Path(tmp))
            store.bootstrap(_session())
            # The first rewrite stores the derived claim fields every loaded item carries; after that an
            # item's revision moves only when its own payload changes.
            store.transact(lambda payload: None, operation="session_update")
            store.transact(
                lambda payload: payload["items"]["finding-1"].update(status="FIXED"), operation="session_update"
            )
            with closing(sqlite3.connect(store.database_path)) as connection:
                observed = dict(
                    connection.execute("SELECT item_id, last_observed_revision FROM items").fetchall()
                )

        self.assertEqual(observed, {"finding-1": 3, "finding-2": 2})


@unittest.skipIf(os.name == "nt", "projection contracts use fork")
class ProjectionContractTest(unittest.TestCase):
    def _evidence(self, index: int) -> dict:
        return EvidenceRecord.new(
            session_id=SESSION_ID, item_id="finding-1", lease_id=None, agent_id="agent",
            role="fixer", event_type="note", payload={"index": index, "text": "ünïcode"},
        ).to_json()

    def test_incremental_projection_is_byte_identical_to_full_rebuild(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            session_path, ledger_path = workspace / "session.json", workspace / "evidence.jsonl"
            store = RuntimeStore(workspace)
            store.bootstrap(_session(), evidence=[self._evidence(0)])
            for index in range(1, 25):
                store.transact(lambda payload: None, operation="session_update", evidence=[self._evidence(index)])
                store.materialize_compatibility_artifacts(session_path=session_path, ledger_path=ledger_path)
            incremental = ledger_path.read_bytes()
            ledger_path.unlink()
            store.recover_artifacts(session_path=session_path, ledger_path=ledger_path)
            rebuilt = ledger_path.read_bytes()
            canonical = store.load_evidence()

        self.assertEqual(incremental, rebuilt)
        self.assertEqual([json.loads(line) for line in rebuilt.decode("utf-8").splitlines()], canonical)

    def test_projection_drift_is_repaired_from_canonical_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            session_path, ledger_path = workspace / "session.json", workspace / "evidence.jsonl"
            store = RuntimeStore(workspace)
            store.bootstrap(_session(), evidence=[self._evidence(0)])
            store.materialize_compatibility_artifacts(session_path=session_path, ledger_path=ledger_path)
            with ledger_path.open("a", encoding="utf-8") as handle:
                handle.write('{"forged":true}\n')

            with patch("gh_address_cr.otel_tracing.add_current_span_event") as emit:
                repairs = store.recover_artifacts(session_path=session_path, ledger_path=ledger_path)
            lines = [json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines()]
            canonical = store.load_evidence()
            clean = store.recover_artifacts(session_path=session_path, ledger_path=ledger_path)

        outcomes = [(call.args[0], call.args[1]["persistence.outcome"]) for call in emit.call_args_list]
        self.assertEqual(repairs, 1)
        self.assertEqual(lines, canonical)
        self.assertIn(("artifact.materialization", "drift_repaired"), outcomes)
        self.assertEqual(clean, 0)

    def test_materialized_meta_revision_matches_content_under_concurrent_writes(self):
        context = multiprocessing.get_context("fork")
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            store = RuntimeStore(workspace, busy_timeout_ms=30_000)
            store.bootstrap(_session())
            barrier = context.Barrier(4)
            workers = [context.Process(target=_write_and_materialize, args=(tmp, barrier, index)) for index in range(4)]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(timeout=60)
                self.assertEqual(worker.exitcode, 0)
            snapshot = store.load()
            repairs = store.recover_artifacts(
                session_path=workspace / "session.json", ledger_path=workspace / "evidence.jsonl"
            )
            lines = (workspace / "evidence.jsonl").read_text(encoding="utf-8").splitlines()
            meta = json.loads((workspace / "evidence.jsonl.meta.json").read_text(encoding="utf-8"))
            canonical = store.load_evidence()

        self.assertEqual(repairs, 0)
        self.assertEqual(meta["revision"], snapshot.revision)
        self.assertEqual([json.loads(line) for line in lines], canonical)
        self.assertEqual(len(canonical), 20)


class PersistenceSpanContractTest(unittest.TestCase):
    def test_persistence_spans_are_bounded_and_private(self):
        from gh_address_cr import otel_tracing

        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        tracer = provider.get_tracer("persistence-span-contract")
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            store = RuntimeStore(workspace)
            store.bootstrap(_session())

            def operation() -> int:
                store.transact(
                    lambda payload: payload.update(status="ACTIVE"), operation="status_update", outbox=[dict(COMMAND)]
                )
                store.materialize_compatibility_artifacts(
                    session_path=workspace / "session.json", ledger_path=workspace / "evidence.jsonl"
                )
                return 0

            otel_tracing.run_traced(tracer, "gh-address-cr.cli", operation)

        spans = {span.name: span for span in exporter.get_finished_spans()}
        transaction = spans["gh_address_cr.persistence.transaction"]
        self.assertIn("gh_address_cr.persistence.materialize", spans)
        self.assertEqual(transaction.attributes["gh_address_cr.persistence.operation"], "status_update")
        self.assertEqual(transaction.attributes["gh_address_cr.persistence.outcome"], "committed")
        self.assertEqual(transaction.attributes["gh_address_cr.persistence.items_bucket"], "1-10")
        self.assertIn("gh_address_cr.persistence.lock_wait_ms", transaction.attributes)
        self.assertIn("gh_address_cr.persistence.execute_ms", transaction.attributes)
        serialized = json.dumps(
            [dict(span.attributes or {}) for span in spans.values()] + [span.name for span in spans.values()],
            sort_keys=True,
        )
        for forbidden in (REPO, "finding-1", "command-owner", "resolve-owner", "runtime.sqlite3", str(workspace)):
            self.assertNotIn(forbidden, serialized)


if __name__ == "__main__":
    unittest.main()
