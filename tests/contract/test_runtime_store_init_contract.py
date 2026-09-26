"""Spec 035 F1/F2: store initialization and legacy migration are exactly-once.

Regression coverage for the Spec 034 audit reproductions R1 (a crash while the
recovery bundle is half-written stranded the session), R2 (a late bootstrap
replaced a store that had already committed revisions), and R3 (concurrent
first-open migration raised bare ``FileExistsError`` or transient
``PERSISTENCE_INVALID``).
"""

from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
import shutil
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from gh_address_cr.core import session as session_store
from gh_address_cr.core.runtime_store import PersistenceInvalidError, RuntimeStore
from gh_address_cr.evidence.ledger import EvidenceRecord

SESSION_ID = "owner/repo#123"


def _session() -> dict:
    return {
        "session_id": SESSION_ID,
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
        "metadata": {"writers": []},
    }


def _write_legacy(workspace: Path) -> tuple[Path, Path]:
    session_path = workspace / "session.json"
    ledger_path = workspace / "evidence.jsonl"
    session_path.write_text(json.dumps(_session()), encoding="utf-8")
    record = EvidenceRecord.new(
        session_id=SESSION_ID,
        item_id="finding-1",
        lease_id=None,
        agent_id="agent",
        role="triage",
        event_type="classification_recorded",
        payload={"classification": "fix"},
        timestamp="2026-09-24T12:00:00Z",
    )
    ledger_path.write_text(json.dumps(record.to_json()) + "\n", encoding="utf-8")
    return session_path, ledger_path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _migration_rows(store: RuntimeStore) -> int:
    with closing(sqlite3.connect(store.database_path)) as connection:
        return int(connection.execute("SELECT COUNT(*) FROM migration_history").fetchone()[0])


def _bootstrap_then_write(workspace: str, barrier, queue, name: str) -> None:
    store = RuntimeStore(Path(workspace), busy_timeout_ms=30_000)
    barrier.wait()
    try:
        store.bootstrap(_session())
        store.transact(lambda payload: payload["metadata"]["writers"].append(name), operation="session_update")
    except Exception as exc:
        queue.put(f"{type(exc).__name__}: {exc}")
    else:
        queue.put("ok")


def _late_initializer(workspace: str, publishing, resume) -> None:
    """Hold an initializer at the moment it would publish a database file.

    Pre-035 initialization built a temporary database and then ``os.replace``d
    it over ``runtime.sqlite3``; pausing here lets another writer commit first,
    which is the R2 clobber window. An in-place initializer never publishes a
    file this way, so the hook never fires.
    """
    original_replace = os.replace

    def paused_replace(source, destination, *args, **kwargs):
        if str(destination).endswith("runtime.sqlite3"):
            publishing.set()
            resume.wait(timeout=30)
        return original_replace(source, destination, *args, **kwargs)

    with patch("os.replace", side_effect=paused_replace):
        RuntimeStore(Path(workspace), busy_timeout_ms=30_000).bootstrap(_session())


def _migrate(workspace: str, barrier, queue) -> None:
    store = RuntimeStore(Path(workspace), busy_timeout_ms=30_000)
    barrier.wait()
    try:
        snapshot = store.open_or_migrate(
            session_path=Path(workspace) / "session.json",
            ledger_path=Path(workspace) / "evidence.jsonl",
        )
    except Exception as exc:
        queue.put(f"{type(exc).__name__}: {exc}")
    else:
        queue.put(("ok", snapshot.revision))


def _crash_during_initialize(workspace: str) -> None:
    def exit_before_commit(*args, **kwargs):
        os._exit(31)

    with patch.object(RuntimeStore, "_insert_metadata", side_effect=exit_before_commit):
        RuntimeStore(Path(workspace)).bootstrap(_session())


def _crash_during_bundle(workspace: str, checkpoint: str) -> None:
    from gh_address_cr.core import runtime_store

    original_copy = shutil.copy2
    copies = {"count": 0}

    def copy_then_maybe_exit(source, destination, *args, **kwargs):
        copies["count"] += 1
        if checkpoint == "before_session_copy":
            os._exit(41)
        result = original_copy(source, destination, *args, **kwargs)
        if checkpoint == "after_session_copy" and copies["count"] == 1:
            os._exit(42)
        if checkpoint == "after_ledger_copy" and copies["count"] == 2:
            os._exit(43)
        return result

    def exit_instead(*args, **kwargs):
        os._exit(44 if checkpoint == "before_manifest" else 45)

    patches = [patch.object(runtime_store.shutil, "copy2", side_effect=copy_then_maybe_exit)]
    if checkpoint == "before_manifest":
        patches.append(patch.object(runtime_store, "write_json_durable", side_effect=exit_instead))
    if checkpoint == "before_publish":
        patches.append(patch.object(runtime_store.os, "rename", side_effect=exit_instead))
    for active in patches:
        active.start()
    RuntimeStore(Path(workspace)).open_or_migrate(
        session_path=Path(workspace) / "session.json",
        ledger_path=Path(workspace) / "evidence.jsonl",
    )


@unittest.skipIf(os.name == "nt", "initialization contracts use fork and os._exit")
class RuntimeStoreInitializationContractTest(unittest.TestCase):
    def test_concurrent_bootstrap_never_clobbers_committed_revision(self):
        context = multiprocessing.get_context("fork")
        worker_count = 32
        for _round in range(3):
            with self.subTest(round=_round), tempfile.TemporaryDirectory() as tmp:
                barrier = context.Barrier(worker_count)
                queue = context.Queue()
                workers = [
                    context.Process(target=_bootstrap_then_write, args=(tmp, barrier, queue, f"writer-{index}"))
                    for index in range(worker_count)
                ]
                for worker in workers:
                    worker.start()
                for worker in workers:
                    worker.join(timeout=60)
                    self.assertEqual(worker.exitcode, 0)
                outcomes = [queue.get(timeout=5) for _ in workers]
                snapshot = RuntimeStore(Path(tmp)).load()

                self.assertEqual(outcomes, ["ok"] * worker_count)
                self.assertEqual(len(snapshot.payload["metadata"]["writers"]), worker_count)
                self.assertEqual(snapshot.revision, worker_count + 1)

    def test_late_initializer_cannot_replace_committed_store(self):
        context = multiprocessing.get_context("fork")
        with tempfile.TemporaryDirectory() as tmp:
            publishing = context.Event()
            resume = context.Event()
            late = context.Process(target=_late_initializer, args=(tmp, publishing, resume))
            late.start()
            publishing.wait(timeout=2)
            store = RuntimeStore(Path(tmp), busy_timeout_ms=30_000)
            store.bootstrap(_session())
            store.transact(lambda payload: payload["metadata"]["writers"].append("early"), operation="session_update")
            resume.set()
            late.join(timeout=30)
            self.assertEqual(late.exitcode, 0)

            snapshot = RuntimeStore(Path(tmp)).load()

        self.assertEqual(snapshot.revision, 2)
        self.assertEqual(snapshot.payload["metadata"]["writers"], ["early"])

    def test_concurrent_legacy_migration_is_exactly_once(self):
        context = multiprocessing.get_context("fork")
        worker_count = 8
        for _round in range(20):
            with self.subTest(round=_round), tempfile.TemporaryDirectory() as tmp:
                _write_legacy(Path(tmp))
                barrier = context.Barrier(worker_count)
                queue = context.Queue()
                workers = [context.Process(target=_migrate, args=(tmp, barrier, queue)) for _ in range(worker_count)]
                for worker in workers:
                    worker.start()
                for worker in workers:
                    worker.join(timeout=60)
                    self.assertEqual(worker.exitcode, 0)
                outcomes = [queue.get(timeout=5) for _ in workers]
                store = RuntimeStore(Path(tmp))

                self.assertEqual(outcomes, [("ok", 1)] * worker_count)
                self.assertEqual(_migration_rows(store), 1)
                self.assertEqual(len(store.load_evidence()), 1)

    def test_crash_inside_initialize_leaves_uninitialized_store_that_retries_cleanly(self):
        context = multiprocessing.get_context("fork")
        with tempfile.TemporaryDirectory() as tmp:
            worker = context.Process(target=_crash_during_initialize, args=(tmp,))
            worker.start()
            worker.join(timeout=30)
            self.assertEqual(worker.exitcode, 31)
            store = RuntimeStore(Path(tmp))

            self.assertFalse(store.is_initialized())
            snapshot = store.bootstrap(_session())

            self.assertTrue(store.is_initialized())
            self.assertEqual(snapshot.revision, 1)
            self.assertEqual(snapshot.payload["status"], "WAITING_FOR_FIX")

    def test_save_session_refuses_to_bootstrap_over_legacy_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                session_path = session_store.session_file("owner/repo", "123")
                session_path.write_text(json.dumps(_session()), encoding="utf-8")
                original = session_path.read_bytes()
                replacement = _session()
                replacement["status"] = "OVERWRITTEN_WITHOUT_MIGRATION"

                with self.assertRaises(session_store.SessionError) as raised:
                    session_store.save_session("owner/repo", "123", replacement)

                store = RuntimeStore(session_store.workspace_dir("owner/repo", "123"))
                self.assertEqual(raised.exception.reason_code, "PERSISTENCE_INVALID")
                self.assertEqual(session_path.read_bytes(), original)
                self.assertFalse(store.is_initialized())

    def test_crash_at_every_bundle_checkpoint_recovers(self):
        context = multiprocessing.get_context("fork")
        for checkpoint, expected_exit in (
            ("before_session_copy", 41),
            ("after_session_copy", 42),
            ("after_ledger_copy", 43),
            ("before_manifest", 44),
            ("before_publish", 45),
        ):
            with self.subTest(checkpoint=checkpoint), tempfile.TemporaryDirectory() as tmp:
                workspace = Path(tmp)
                session_path, ledger_path = _write_legacy(workspace)
                worker = context.Process(target=_crash_during_bundle, args=(tmp, checkpoint))
                worker.start()
                worker.join(timeout=30)
                self.assertEqual(worker.exitcode, expected_exit)
                store = RuntimeStore(workspace)
                self.assertFalse(store.is_initialized())

                snapshot = store.open_or_migrate(session_path=session_path, ledger_path=ledger_path)

                bundle = workspace / "legacy-v1-recovery"
                manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
                self.assertEqual(snapshot.revision, 1)
                self.assertEqual(
                    manifest["files"],
                    {"session.json": _sha256(session_path), "evidence.jsonl": _sha256(ledger_path)},
                )
                self.assertEqual(list(workspace.glob("legacy-v1-recovery.tmp-*")), [])
                self.assertEqual(store.load().revision, 1)

    def test_tampered_complete_bundle_still_fails_fast(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            session_path, ledger_path = _write_legacy(workspace)
            store = RuntimeStore(workspace)
            with patch.object(RuntimeStore, "_create_schema", side_effect=RuntimeError("injected import crash")):
                with self.assertRaisesRegex(RuntimeError, "injected import crash"):
                    store.open_or_migrate(session_path=session_path, ledger_path=ledger_path)
            (workspace / "legacy-v1-recovery" / "session.json").write_text("{}", encoding="utf-8")

            with self.assertRaises(PersistenceInvalidError):
                store.open_or_migrate(session_path=session_path, ledger_path=ledger_path)
            self.assertFalse(store.is_initialized())

    def test_incomplete_bundle_quarantine_emits_bounded_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            session_path, ledger_path = _write_legacy(workspace)
            incomplete = workspace / "legacy-v1-recovery"
            incomplete.mkdir()
            shutil.copy2(session_path, incomplete / "session.json")
            store = RuntimeStore(workspace)

            with patch("gh_address_cr.otel_tracing.add_current_span_event") as emit:
                snapshot = store.open_or_migrate(session_path=session_path, ledger_path=ledger_path)

            quarantined = list(workspace.glob("legacy-v1-recovery.incomplete-*"))
            self.assertEqual(snapshot.revision, 1)
            self.assertEqual(len(quarantined), 1)
            self.assertTrue((quarantined[0] / "session.json").is_file())
            self.assertTrue((incomplete / "manifest.json").is_file())
            events = [(call.args[0], call.args[1]) for call in emit.call_args_list]
            quarantine = [
                attributes
                for name, attributes in events
                if name == "persistence.migration" and attributes["persistence.outcome"] == "bundle_quarantined"
            ]
            self.assertEqual(len(quarantine), 1)
            self.assertEqual(quarantine[0]["persistence.operation"], "bundle_quarantine")
            serialized = json.dumps(events, sort_keys=True)
            for forbidden in ("owner/repo", "finding-1", "legacy-v1-recovery", str(workspace)):
                self.assertNotIn(forbidden, serialized)


if __name__ == "__main__":
    unittest.main()
