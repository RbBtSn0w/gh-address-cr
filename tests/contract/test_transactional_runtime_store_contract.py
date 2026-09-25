from __future__ import annotations

import json
import multiprocessing
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from gh_address_cr.core.leases import LeaseConflictError, claim_lease
from gh_address_cr.core.runtime_store import (
    PersistenceBusyError,
    PersistenceInvalidError,
    RuntimeStore,
    StaleRevisionError,
)
from gh_address_cr.evidence.ledger import EvidenceLedger, EvidenceRecord

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)


def _session() -> dict:
    return {
        "session_id": "owner/repo#123",
        "repo": "owner/repo",
        "pr_number": "123",
        "status": "WAITING_FOR_FIX",
        "items": {
            "finding-1": {
                "item_id": "finding-1",
                "item_kind": "local_finding",
                "state": "open",
                "status": "OPEN",
                "path": "src/example.py",
                "line": 7,
            }
        },
        "leases": {},
        "metadata": {"source": "contract-test"},
    }


def _race_claim(workspace: str, barrier: multiprocessing.Barrier, queue: multiprocessing.Queue, agent: str) -> None:
    store = RuntimeStore(Path(workspace), busy_timeout_ms=5_000)
    barrier.wait()
    try:
        result = store.transact(
            lambda payload: claim_lease(
                payload,
                payload["items"]["finding-1"],
                agent_id=agent,
                role="fixer",
                request_hash=f"hash-{agent}",
                lease_id=f"lease-{agent}",
                now=NOW,
            ),
            operation="claim",
        )
    except LeaseConflictError as exc:
        queue.put(("conflict", exc.reason_code))
    else:
        queue.put(("committed", result.revision))


class _OfflineGitHub:
    def get_stack_context(self, repo: str, pr_number: str):
        raise RuntimeError("offline contract test")


def _race_action_request(
    state_dir: str,
    barrier: multiprocessing.Barrier,
    queue: multiprocessing.Queue,
    agent: str,
) -> None:
    os.environ["GH_ADDRESS_CR_STATE_DIR"] = state_dir
    from gh_address_cr.core.agent_protocol import issue_action_request

    barrier.wait()
    try:
        result = issue_action_request(
            "owner/repo",
            "123",
            role="fixer",
            agent_id=agent,
            item_id="finding-1",
            now=NOW,
            github_client=_OfflineGitHub(),
        )
    except Exception as exc:
        queue.put(("rejected", getattr(exc, "reason_code", type(exc).__name__)))
    else:
        queue.put(("requested", result["lease_id"]))


def _race_batch_action_request(
    state_dir: str,
    barrier: multiprocessing.Barrier,
    queue: multiprocessing.Queue,
    agent: str,
) -> None:
    os.environ["GH_ADDRESS_CR_STATE_DIR"] = state_dir
    from gh_address_cr.core.agent_batch import issue_batch_action_request

    barrier.wait()
    try:
        result = issue_batch_action_request("owner/repo", "124", agent_id=agent, now=NOW)
    except Exception as exc:
        queue.put(("rejected", getattr(exc, "reason_code", type(exc).__name__)))
    else:
        queue.put(("requested", result["leased_items"][0]["acquisition"]))


def _crash_transaction(workspace: str, stage: str) -> None:
    store = RuntimeStore(Path(workspace))
    evidence = EvidenceRecord.new(
        session_id="owner/repo#123",
        item_id="finding-1",
        lease_id=None,
        agent_id="agent-a",
        role="fixer",
        event_type="status_changed",
        payload={"status": "COMMITTED_AFTER_CRASH"},
        timestamp="2026-09-24T12:30:00Z",
    )
    outbox = {
        "command_id": "command-crash-contract",
        "effect_type": "github_reply",
        "idempotency_key": "reply-crash-contract",
        "operation_category": "reply",
        "retry_boundary": "idempotent",
    }

    def mutation(payload: dict) -> None:
        payload["status"] = "COMMITTED_AFTER_CRASH"
        if stage == "before_commit":
            os._exit(17)

    store.transact(
        mutation,
        operation="crash_contract",
        evidence=[evidence.to_json()],
        outbox=[outbox],
    )
    os._exit(23)


class TransactionalRuntimeStoreContractTests(unittest.TestCase):
    def test_schema_contains_every_phase_a_canonical_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RuntimeStore(Path(tmp))
            store.bootstrap(_session())

            with closing(sqlite3.connect(store.database_path)) as connection:
                tables = {
                    row[0]
                    for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
                }

        self.assertTrue(
            {
                "store_metadata",
                "sessions",
                "items",
                "leases",
                "lease_conflict_keys",
                "evidence_events",
                "outbox_commands",
                "artifact_materializations",
                "migration_history",
            }.issubset(tables)
        )

    def test_legacy_import_is_once_only_and_artifacts_are_not_authoritative(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            session_path = workspace / "session.json"
            ledger_path = workspace / "evidence.jsonl"
            session_path.write_text(json.dumps(_session()), encoding="utf-8")
            record = EvidenceRecord.new(
                session_id="owner/repo#123",
                item_id="finding-1",
                lease_id=None,
                agent_id="agent",
                role="triage",
                event_type="classification_recorded",
                payload={"classification": "fix"},
                timestamp="2026-09-24T12:00:00Z",
            )
            ledger_path.write_text(json.dumps(record.to_json()) + "\n", encoding="utf-8")

            store = RuntimeStore(workspace)
            imported = store.open_or_migrate(session_path=session_path, ledger_path=ledger_path)
            self.assertEqual(imported.revision, 1)
            self.assertEqual(store.load_evidence(), [record.to_json()])
            self.assertTrue((workspace / "legacy-v1-recovery" / "manifest.json").is_file())

            edited = _session()
            edited["status"] = "EXTERNALLY_EDITED"
            session_path.write_text(json.dumps(edited), encoding="utf-8")

            reopened = store.open_or_migrate(session_path=session_path, ledger_path=ledger_path)
            self.assertEqual(reopened.payload["status"], "WAITING_FOR_FIX")
            ledger_path.write_text('{"forged":true}\n', encoding="utf-8")
            store.materialize_compatibility_artifacts(session_path=session_path, ledger_path=ledger_path)
            projection = json.loads(session_path.read_text(encoding="utf-8"))
            self.assertEqual(projection["status"], "WAITING_FOR_FIX")
            self.assertEqual(projection["persistence"]["revision"], 1)
            self.assertEqual(
                [json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines()],
                [record.to_json()],
            )
            ledger_metadata = json.loads(
                ledger_path.with_name("evidence.jsonl.meta.json").read_text(encoding="utf-8")
            )
            self.assertEqual(ledger_metadata, {"format_version": 1, "schema_version": 1, "revision": 1})

    def test_tampered_legacy_recovery_bundle_fails_integrity_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            session_path = workspace / "session.json"
            ledger_path = workspace / "evidence.jsonl"
            session_path.write_text(json.dumps(_session()), encoding="utf-8")
            store = RuntimeStore(workspace)
            store.open_or_migrate(session_path=session_path, ledger_path=ledger_path)
            (workspace / "legacy-v1-recovery" / "session.json").write_text("{}", encoding="utf-8")

            with self.assertRaises(PersistenceInvalidError):
                store.load()

    def test_interrupted_legacy_import_reuses_verified_recovery_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            session_path = workspace / "session.json"
            ledger_path = workspace / "evidence.jsonl"
            session_path.write_text(json.dumps(_session()), encoding="utf-8")
            store = RuntimeStore(workspace)

            with patch.object(store, "_create_schema", side_effect=RuntimeError("injected import crash")):
                with self.assertRaisesRegex(RuntimeError, "injected import crash"):
                    store.open_or_migrate(session_path=session_path, ledger_path=ledger_path)

            self.assertFalse(store.database_path.exists())
            self.assertTrue((workspace / "legacy-v1-recovery" / "manifest.json").is_file())
            self.assertEqual(list(workspace.glob("runtime.*.sqlite3.tmp")), [])

            recovered = store.open_or_migrate(session_path=session_path, ledger_path=ledger_path)

        self.assertEqual(recovered.revision, 1)
        self.assertEqual(recovered.payload["status"], "WAITING_FOR_FIX")

    def test_compare_and_swap_rejects_a_stale_revision_without_partial_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RuntimeStore(Path(tmp))
            first = store.bootstrap(_session())
            changed = dict(first.payload)
            changed["status"] = "ACTIVE"
            committed = store.replace(changed, expected_revision=first.revision, operation="status_update")

            stale = dict(first.payload)
            stale["status"] = "STALE_WRITE"
            with self.assertRaises(StaleRevisionError):
                store.replace(stale, expected_revision=first.revision, operation="status_update")

            current = store.load()
            self.assertEqual(current.revision, committed.revision)
            self.assertEqual(current.payload["status"], "ACTIVE")

    def test_item_claim_projection_is_derived_from_canonical_active_lease(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RuntimeStore(Path(tmp))
            payload = _session()
            payload["items"]["finding-1"]["state"] = "claimed"
            payload["items"]["finding-1"]["active_lease_id"] = "forged-lease"
            store.bootstrap(payload)

            without_lease = store.load().payload["items"]["finding-1"]
            self.assertEqual(without_lease["state"], "open")
            self.assertNotIn("active_lease_id", without_lease)

            committed = store.transact(
                lambda current: claim_lease(
                    current,
                    current["items"]["finding-1"],
                    agent_id="agent-a",
                    role="fixer",
                    request_hash="hash-a",
                    lease_id="lease-a",
                    now=NOW,
                ),
                operation="lease_claim",
            )
            with closing(sqlite3.connect(store.database_path)) as connection:
                observed_revisions = connection.execute(
                    "SELECT first_observed_revision, last_observed_revision FROM items WHERE item_id = ?",
                    ("finding-1",),
                ).fetchone()

        item = committed.payload["items"]["finding-1"]
        self.assertEqual(item["state"], "claimed")
        self.assertEqual(item["active_lease_id"], "lease-a")
        self.assertEqual(item["claimed_by"], "agent-a")
        self.assertEqual(observed_revisions, (1, 2))

    def test_writer_timeout_is_bounded_and_retryable(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RuntimeStore(Path(tmp), busy_timeout_ms=20)
            store.bootstrap(_session())
            blocker = sqlite3.connect(store.database_path, isolation_level=None)
            blocker.execute("BEGIN IMMEDIATE")
            try:
                with self.assertRaises(PersistenceBusyError) as context:
                    store.transact(lambda payload: payload.update(status="BLOCKED"), operation="status_update")
            finally:
                blocker.rollback()
                blocker.close()

            self.assertTrue(context.exception.retryable)
            self.assertEqual(store.load().payload["status"], "WAITING_FOR_FIX")

    @unittest.skipIf(os.name == "nt", "multiprocessing barrier contract uses fork semantics")
    def test_two_processes_claiming_one_item_have_exactly_one_winner(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RuntimeStore(Path(tmp))
            store.bootstrap(_session())
            context = multiprocessing.get_context("fork")
            barrier = context.Barrier(2)
            queue = context.Queue()
            workers = [
                context.Process(target=_race_claim, args=(tmp, barrier, queue, agent))
                for agent in ("agent-a", "agent-b")
            ]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(timeout=10)
                self.assertEqual(worker.exitcode, 0)

            outcomes = sorted(queue.get(timeout=1) for _ in workers)
            snapshot = store.load()

        self.assertEqual([outcome[0] for outcome in outcomes], ["committed", "conflict"])
        self.assertEqual(len(snapshot.payload["leases"]), 1)
        self.assertEqual(snapshot.revision, 2)

    @unittest.skipIf(os.name == "nt", "multiprocessing barrier contract uses fork semantics")
    def test_one_hundred_process_claim_race_has_one_winner(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RuntimeStore(Path(tmp), busy_timeout_ms=10_000)
            store.bootstrap(_session())
            context = multiprocessing.get_context("fork")
            worker_count = 100
            barrier = context.Barrier(worker_count)
            queue = context.Queue()
            workers = [
                context.Process(target=_race_claim, args=(tmp, barrier, queue, f"agent-{index}"))
                for index in range(worker_count)
            ]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(timeout=20)
                self.assertEqual(worker.exitcode, 0)
            outcomes = [queue.get(timeout=2)[0] for _ in workers]
            snapshot = store.load()

        self.assertEqual(outcomes.count("committed"), 1)
        self.assertEqual(outcomes.count("conflict"), worker_count - 1)
        self.assertEqual(snapshot.revision, 2)

    @unittest.skipIf(os.name == "nt", "crash contract uses fork and os._exit")
    def test_process_exit_reopens_to_old_or_complete_committed_revision(self):
        context = multiprocessing.get_context("fork")
        for stage, expected_exit, expected_revision, expected_status in (
            ("before_commit", 17, 1, "WAITING_FOR_FIX"),
            ("after_commit", 23, 2, "COMMITTED_AFTER_CRASH"),
        ):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as tmp:
                store = RuntimeStore(Path(tmp))
                store.bootstrap(_session())
                worker = context.Process(target=_crash_transaction, args=(tmp, stage))
                worker.start()
                worker.join(timeout=10)
                self.assertEqual(worker.exitcode, expected_exit)

                reopened = store.load()

                self.assertEqual(reopened.revision, expected_revision)
                self.assertEqual(reopened.payload["status"], expected_status)
                self.assertEqual(len(store.load_evidence()), 0 if stage == "before_commit" else 1)
                self.assertEqual(len(store.load_outbox()), 0 if stage == "before_commit" else 1)

    def test_outbox_plan_commits_with_state_and_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RuntimeStore(Path(tmp))
            store.bootstrap(_session())
            evidence = EvidenceRecord.new(
                session_id="owner/repo#123",
                item_id="finding-1",
                lease_id=None,
                agent_id="agent-a",
                role="fixer",
                event_type="status_changed",
                payload={"status": "ACTIVE"},
                timestamp="2026-09-24T12:30:00Z",
            )

            committed = store.transact(
                lambda payload: payload.update(status="ACTIVE"),
                operation="status_update",
                evidence=[evidence.to_json()],
                outbox=[
                    {
                        "command_id": "command-1",
                        "effect_type": "github_reply",
                        "idempotency_key": "reply-1",
                        "operation_category": "reply",
                        "retry_boundary": "idempotent",
                    }
                ],
            )

            records = store.load_evidence()
            commands = store.load_outbox()

        self.assertEqual(committed.revision, 2)
        self.assertEqual([record["record_id"] for record in records], [evidence.record_id])
        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0]["status"], "planned")
        self.assertEqual(commands[0]["planned_revision"], 2)

    def test_restart_classifies_in_flight_outbox_as_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RuntimeStore(Path(tmp))
            store.bootstrap(_session())
            store.transact(
                lambda payload: payload.update(status="ACTIVE"),
                operation="status_update",
                outbox=[
                    {
                        "command_id": "command-1",
                        "effect_type": "github_reply",
                        "idempotency_key": "reply-1",
                        "operation_category": "reply",
                        "retry_boundary": "idempotent",
                    }
                ],
            )
            store.mark_outbox_in_flight("command-1")

            recovered = RuntimeStore(Path(tmp)).recover()

            commands = store.load_outbox()

        self.assertEqual(recovered, 1)
        self.assertEqual(commands[0]["status"], "unknown")
        self.assertEqual(commands[0]["attempt_count"], 1)

    def test_outbox_success_requires_a_later_transaction_with_result_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RuntimeStore(Path(tmp))
            store.bootstrap(_session())
            store.transact(
                lambda payload: payload.update(status="ACTIVE"),
                operation="status_update",
                outbox=[
                    {
                        "command_id": "command-1",
                        "effect_type": "github_reply",
                        "idempotency_key": "reply-1",
                        "operation_category": "reply",
                        "retry_boundary": "idempotent",
                    }
                ],
            )
            store.mark_outbox_in_flight("command-1")
            result = EvidenceRecord.new(
                session_id="owner/repo#123",
                item_id="finding-1",
                lease_id=None,
                agent_id="agent-a",
                role="publisher",
                event_type="reply_posted",
                payload={"result": "recorded"},
                timestamp="2026-09-24T12:31:00Z",
            )

            committed = store.record_outbox_result(
                "command-1",
                status="succeeded",
                evidence=[result.to_json()],
                external_result_reference="comment-1",
            )

            command = store.load_outbox()[0]
            records = store.load_evidence()

        self.assertEqual(committed.revision, 4)
        self.assertEqual(command["status"], "succeeded")
        self.assertEqual(command["external_result_reference"], "comment-1")
        self.assertEqual([record["record_id"] for record in records], [result.record_id])

    def test_unknown_outbox_retries_only_when_effect_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RuntimeStore(Path(tmp))
            store.bootstrap(_session())
            store.transact(
                lambda payload: None,
                operation="status_update",
                outbox=[
                    {
                        "command_id": "command-1",
                        "effect_type": "github_reply",
                        "idempotency_key": "reply-1",
                        "operation_category": "reply",
                        "retry_boundary": "reconcile_only",
                    }
                ],
            )
            store.mark_outbox_in_flight("command-1")
            store.recover()

            with self.assertRaises(PersistenceInvalidError):
                store.mark_outbox_in_flight("command-1")

            command = store.load_outbox()[0]

        self.assertEqual(command["status"], "unknown")

    def test_dirty_or_missing_artifacts_rebuild_from_canonical_revision(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            session_path = workspace / "session.json"
            ledger_path = workspace / "evidence.jsonl"
            store = RuntimeStore(workspace)
            store.bootstrap(_session())
            store.materialize_compatibility_artifacts(session_path=session_path, ledger_path=ledger_path)
            session_path.write_text('{"status":"FORGED"}', encoding="utf-8")
            ledger_path.unlink()
            store.transact(
                lambda payload: payload.update(status="ACTIVE"),
                operation="status_update",
            )

            rebuilt = store.recover_artifacts(session_path=session_path, ledger_path=ledger_path)

            projection = json.loads(session_path.read_text(encoding="utf-8"))
            materializations = store.load_materializations()
            ledger_exists = ledger_path.is_file()

        self.assertEqual(rebuilt, 3)
        self.assertEqual(projection["status"], "ACTIVE")
        self.assertEqual(projection["persistence"]["revision"], 2)
        self.assertTrue(ledger_exists)
        self.assertTrue(all(row["status"] == "current" for row in materializations))
        self.assertTrue(all(row["source_revision"] == 2 for row in materializations))

    def test_stale_session_write_leaves_no_orphan_evidence_projection(self):
        from gh_address_cr.core.session import SessionError, SessionManager
        from gh_address_cr.core.utils import get_session_ledger

        with tempfile.TemporaryDirectory() as tmp:
            previous = os.environ.get("GH_ADDRESS_CR_STATE_DIR")
            os.environ["GH_ADDRESS_CR_STATE_DIR"] = tmp
            try:
                manager = SessionManager("owner/repo", "125")
                initial = manager.create(status="WAITING_FOR_FIX")
                manager.save(initial)
                stale = manager.load()
                current = manager.load()
                current["status"] = "ACTIVE"
                manager.save(current)

                get_session_ledger(stale).append_event(
                    session_id=str(stale["session_id"]),
                    item_id="finding-1",
                    lease_id=None,
                    agent_id="agent-a",
                    role="fixer",
                    event_type="status_changed",
                    payload={"status": "STALE"},
                    timestamp="2026-09-24T12:32:00Z",
                )
                stale["status"] = "STALE"
                with self.assertRaises(SessionError) as context:
                    manager.save(stale)

                store = RuntimeStore(manager.workspace_path)
                records = store.load_evidence()
                projected_records = EvidenceLedger(manager.ledger_path).load()
            finally:
                if previous is None:
                    os.environ.pop("GH_ADDRESS_CR_STATE_DIR", None)
                else:
                    os.environ["GH_ADDRESS_CR_STATE_DIR"] = previous

        self.assertEqual(context.exception.reason_code, "STALE_REVISION")
        self.assertEqual(records, [])
        self.assertEqual(projected_records, [])

    def test_post_commit_reload_failure_cannot_change_commit_truth(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            store = RuntimeStore(workspace)
            store.bootstrap(_session())
            original_connect = store._connect
            connect_count = 0

            def connect_once(database_path=None):
                nonlocal connect_count
                connect_count += 1
                if connect_count > 1:
                    raise sqlite3.OperationalError("post-commit reload unavailable")
                return original_connect(database_path)

            with patch.object(store, "_connect", side_effect=connect_once):
                committed = store.transact(
                    lambda payload: payload.update(status="ACTIVE"),
                    operation="status_update",
                )

            reopened = RuntimeStore(workspace).load()

        self.assertEqual(connect_count, 1)
        self.assertEqual(committed.revision, 2)
        self.assertEqual(committed.payload["status"], "ACTIVE")
        self.assertEqual(reopened.payload["status"], "ACTIVE")

    def test_session_load_recovers_in_flight_outbox_and_dirty_artifacts(self):
        from gh_address_cr.core.session import SessionManager

        with tempfile.TemporaryDirectory() as tmp:
            previous = os.environ.get("GH_ADDRESS_CR_STATE_DIR")
            os.environ["GH_ADDRESS_CR_STATE_DIR"] = tmp
            try:
                manager = SessionManager("owner/repo", "126")
                session = manager.create(status="ACTIVE")
                manager.save(session)
                store = RuntimeStore(manager.workspace_path)
                planned = store.transact(
                    lambda payload: None,
                    operation="outbox_plan",
                    outbox=[
                        {
                            "command_id": "command-recover-on-load",
                            "effect_type": "github_reply",
                            "idempotency_key": "reply-recover-on-load",
                            "operation_category": "github_reply",
                            "retry_boundary": "reconcile_only",
                        }
                    ],
                )
                store.mark_outbox_in_flight("command-recover-on-load")
                manager.session_path.unlink(missing_ok=True)
                manager.ledger_path.unlink(missing_ok=True)

                loaded = manager.load()

                command = store.load_outbox()[0]
                materializations = store.load_materializations()
                session_exists = manager.session_path.is_file()
                ledger_exists = manager.ledger_path.is_file()
            finally:
                if previous is None:
                    os.environ.pop("GH_ADDRESS_CR_STATE_DIR", None)
                else:
                    os.environ["GH_ADDRESS_CR_STATE_DIR"] = previous

        self.assertEqual(planned.revision, 2)
        self.assertEqual(command["status"], "unknown")
        self.assertEqual(loaded["persistence"]["revision"], 4)
        self.assertTrue(session_exists)
        self.assertTrue(ledger_exists)
        self.assertTrue(all(row["status"] == "current" for row in materializations))

    def test_transaction_and_migration_telemetry_is_bounded_and_private(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            session_path = workspace / "session.json"
            ledger_path = workspace / "evidence.jsonl"
            session_path.write_text(json.dumps(_session()), encoding="utf-8")
            store = RuntimeStore(workspace)

            with patch("gh_address_cr.otel_tracing.add_current_span_event") as emit:
                store.open_or_migrate(session_path=session_path, ledger_path=ledger_path)
                store.transact(lambda payload: payload.update(status="ACTIVE"), operation="status_update")

        events = [(call.args[0], call.args[1]) for call in emit.call_args_list]
        self.assertIn("persistence.migration", [name for name, _ in events])
        transaction = next(attributes for name, attributes in events if name == "persistence.transaction")
        self.assertEqual(transaction["persistence.operation"], "status_update")
        self.assertEqual(transaction["persistence.outcome"], "committed")
        self.assertEqual(transaction["persistence.schema_version"], 1)
        serialized = json.dumps(events, sort_keys=True)
        for forbidden in ("owner/repo", "finding-1", "runtime.sqlite3", str(workspace), "SELECT", "INSERT"):
            self.assertNotIn(forbidden, serialized)

    def test_telemetry_failure_does_not_change_commit_truth(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RuntimeStore(Path(tmp))
            store.bootstrap(_session())

            with patch(
                "gh_address_cr.otel_tracing.add_current_span_event",
                side_effect=RuntimeError("telemetry unavailable"),
            ):
                committed = store.transact(
                    lambda payload: payload.update(status="ACTIVE"),
                    operation="status_update",
                )

        self.assertEqual(committed.revision, 2)
        self.assertEqual(committed.payload["status"], "ACTIVE")

    @unittest.skipIf(os.name == "nt", "multiprocessing barrier contract uses fork semantics")
    def test_action_request_race_commits_one_lease_without_orphan_request_files(self):
        from gh_address_cr.core.session import SessionManager

        with tempfile.TemporaryDirectory() as tmp:
            previous = os.environ.get("GH_ADDRESS_CR_STATE_DIR")
            os.environ["GH_ADDRESS_CR_STATE_DIR"] = tmp
            try:
                manager = SessionManager("owner/repo", "123")
                session = manager.create(status="WAITING_FOR_FIX")
                item = _session()["items"]["finding-1"]
                item["allowed_actions"] = ["fix", "clarify", "defer", "reject"]
                item["classification_evidence"] = {
                    "event_type": "classification_recorded",
                    "classification": "fix",
                    "note": "confirmed",
                    "record_id": "ev-classification",
                }
                item["decision"] = "fix"
                session["items"] = {"finding-1": item}
                manager.save(session)

                context = multiprocessing.get_context("fork")
                barrier = context.Barrier(2)
                queue = context.Queue()
                workers = [
                    context.Process(target=_race_action_request, args=(tmp, barrier, queue, agent))
                    for agent in ("agent-a", "agent-b")
                ]
                for worker in workers:
                    worker.start()
                for worker in workers:
                    worker.join(timeout=10)
                    self.assertEqual(worker.exitcode, 0)

                outcomes = sorted(queue.get(timeout=1) for _ in workers)
                request_files = list(manager.workspace_path.glob("action-request-*.json"))
                snapshot = manager.load()
            finally:
                if previous is None:
                    os.environ.pop("GH_ADDRESS_CR_STATE_DIR", None)
                else:
                    os.environ["GH_ADDRESS_CR_STATE_DIR"] = previous

        self.assertEqual([outcome[0] for outcome in outcomes], ["rejected", "requested"])
        self.assertNotEqual(outcomes[0][1], "STALE_REVISION")
        self.assertEqual(len(request_files), 1)
        self.assertEqual(len(snapshot["leases"]), 1)

    @unittest.skipIf(os.name == "nt", "multiprocessing barrier contract uses fork semantics")
    def test_batch_action_request_race_commits_one_lease_without_orphan_request_files(self):
        from gh_address_cr.core.session import SessionManager
        from tests.test_control_plane_workflow import github_thread

        with tempfile.TemporaryDirectory() as tmp:
            previous = os.environ.get("GH_ADDRESS_CR_STATE_DIR")
            os.environ["GH_ADDRESS_CR_STATE_DIR"] = tmp
            try:
                manager = SessionManager("owner/repo", "124")
                session = manager.create(status="WAITING_FOR_FIX")
                session["items"] = {"github-thread:T1": github_thread("github-thread:T1")}
                manager.save(session)

                context = multiprocessing.get_context("fork")
                barrier = context.Barrier(2)
                queue = context.Queue()
                workers = [
                    context.Process(target=_race_batch_action_request, args=(tmp, barrier, queue, agent))
                    for agent in ("agent-a", "agent-b")
                ]
                for worker in workers:
                    worker.start()
                for worker in workers:
                    worker.join(timeout=10)
                    self.assertEqual(worker.exitcode, 0)

                outcomes = sorted(queue.get(timeout=1) for _ in workers)
                request_files = list(manager.workspace_path.glob("action-request-*.json"))
                snapshot = manager.load()
            finally:
                if previous is None:
                    os.environ.pop("GH_ADDRESS_CR_STATE_DIR", None)
                else:
                    os.environ["GH_ADDRESS_CR_STATE_DIR"] = previous

        self.assertEqual([outcome[0] for outcome in outcomes], ["rejected", "requested"])
        self.assertNotEqual(outcomes[0][1], "STALE_REVISION")
        self.assertEqual(outcomes[1][1], "created")
        self.assertEqual(len(request_files), 1)
        self.assertEqual(len(snapshot["leases"]), 1)


if __name__ == "__main__":
    unittest.main()
