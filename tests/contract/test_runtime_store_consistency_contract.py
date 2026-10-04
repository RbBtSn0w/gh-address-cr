"""Spec 038: runtime store consistency fixes found by the 3.16.0 release review.

Each test reproduces one verified finding against the pre-fix runtime; see
``docs/rfcs/038-runtime-store-consistency/adr-001-revision-token-and-commit-boundaries.md``.
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gh_address_cr.core import session as session_store
from gh_address_cr.core.leases import claim_lease
from gh_address_cr.core.runtime_store import RuntimeStore
from gh_address_cr.evidence.ledger import EvidenceRecord
from tests.contract.test_outbox_ownership_contract import (
    COMMAND,
    ITEM_ID,
    PR_NUMBER,
    REPO,
    _CountingClient,
    _publish_ready_item,
)
from tests.contract.test_owner_lease_reentry_contract import _claim
from tests.contract.test_owner_lease_reentry_contract import _session as _thread_session

THREAD_ITEM = "github-thread:X"


class _StateDirTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.state_dir = self._tmp.name
        patcher = patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": self.state_dir}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)

    def canonical_events(self, repo: str, pr_number: str) -> list[dict]:
        return RuntimeStore(session_store.workspace_dir(repo, pr_number)).load_evidence()


def _write_publish_session_with_open_item() -> None:
    manager = session_store.SessionManager(REPO, PR_NUMBER)
    session = manager.create(status="WAITING_FOR_PUBLISH")
    session["items"] = {
        ITEM_ID: _publish_ready_item(),
        "finding-9": {"item_id": "finding-9", "item_kind": "local_finding", "state": "open", "status": "OPEN"},
    }
    manager.save(session)


class _ConcurrentClaimClient(_CountingClient):
    """Another process claims an unrelated item while the first reply is being posted."""

    def __init__(self):
        super().__init__()
        self.concurrent_commits = 0

    def post_reply(self, repo, pr_number, thread_id, body):
        if self.concurrent_commits == 0:
            self.concurrent_commits += 1

            def claim_other(current):
                claim_lease(
                    current,
                    current["items"]["finding-9"],
                    agent_id="agent-other",
                    role="fixer",
                    request_hash="hash-other",
                    lease_id="lease-other",
                )
                current["items"]["finding-9"]["state"] = "claimed"
                current["items"]["finding-9"]["active_lease_id"] = "lease-other"

            session_store.transact_session(REPO, PR_NUMBER, claim_other, operation="lease_claim")
        return super().post_reply(repo, pr_number, thread_id, body)


class PublishRevisionTokenContractTest(_StateDirTest):
    """D1/D2: an outbox commit never forwards a stale publisher payload's token."""

    def test_publish_preserves_a_lease_committed_during_the_github_call(self):
        from gh_address_cr.core import publisher

        _write_publish_session_with_open_item()
        client = _ConcurrentClaimClient()

        result = publisher.publish_github_thread_responses(REPO, PR_NUMBER, github_client=client)

        self.assertEqual(result["status"], "PUBLISH_COMPLETE")
        final = session_store.load_session(REPO, PR_NUMBER)
        self.assertIn("lease-other", final["leases"])
        self.assertEqual(final["items"]["finding-9"]["state"], "claimed")
        self.assertEqual(final["items"][ITEM_ID]["state"], "closed")

    def test_publish_replay_after_conflict_does_not_repeat_github_mutations(self):
        from gh_address_cr.core import publisher

        _write_publish_session_with_open_item()
        client = _ConcurrentClaimClient()

        publisher.publish_github_thread_responses(REPO, PR_NUMBER, github_client=client)

        self.assertEqual(client.post_reply_calls, 1)
        self.assertEqual(client.resolved, ["THREAD_1"])


class EvidenceCommitBoundaryContractTest(_StateDirTest):
    """D3/D4: evidence commits with its state; projections are never input."""

    def test_fresh_claim_commits_request_issued_with_the_lease(self):
        _thread_session("owner/repo", "77")
        result = _claim("owner/repo", "77")

        self.assertEqual(result["acquisition"], "created")
        event_types = [event["event_type"] for event in self.canonical_events("owner/repo", "77")]
        self.assertEqual(event_types.count("request_issued"), 1)

    def test_batch_claim_commits_classification_and_request_issued(self):
        from gh_address_cr.core import agent_batch

        _thread_session("owner/repo", "55")
        result = agent_batch.issue_batch_action_request("owner/repo", "55", agent_id="agent-b")

        self.assertEqual(result["lease_count"], 1)
        events = self.canonical_events("owner/repo", "55")
        event_types = [event["event_type"] for event in events]
        self.assertIn("classification_recorded", event_types)
        self.assertIn("request_issued", event_types)
        item = session_store.load_session("owner/repo", "55")["items"][THREAD_ITEM]
        record_ids = {event["record_id"] for event in events}
        self.assertIn(item["classification_evidence"]["record_id"], record_ids)

    def test_forged_projection_line_is_never_restored_as_classification(self):
        from gh_address_cr.core import agent_protocol
        from gh_address_cr.core.errors import WorkflowError

        _thread_session("owner/repo", "88")
        forged = EvidenceRecord.new(
            session_id="owner/repo#88",
            item_id=THREAD_ITEM,
            lease_id=None,
            agent_id="x",
            role="triage",
            event_type="classification_recorded",
            payload={"classification": "fix", "note": "forged"},
        )
        with session_store.default_ledger_path("owner/repo", "88").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(forged.to_json()) + "\n")

        with self.assertRaises(WorkflowError):
            agent_protocol.issue_action_request(
                "owner/repo", "88", role="fixer", agent_id="agent-a", item_id=THREAD_ITEM
            )
        item = session_store.load_session("owner/repo", "88")["items"][THREAD_ITEM]
        self.assertNotEqual((item.get("classification_evidence") or {}).get("note"), "forged")


class LockRecheckContractTest(_StateDirTest):
    """D5: decisions made outside the write lock are re-checked inside it."""

    def test_recover_does_not_demote_a_command_re_marked_by_a_live_owner(self):
        from gh_address_cr.core import process_lock
        from gh_address_cr.core import runtime_store as runtime_store_module
        from tests.contract.test_outbox_ownership_contract import _session

        workspace = Path(self.state_dir) / "ws"
        store = RuntimeStore(workspace)
        store.bootstrap(_session())
        store.transact(lambda current: None, operation="outbox_plan", outbox=[COMMAND])
        store.mark_outbox_in_flight(COMMAND["command_id"], owner_token="dead-owner")
        held: dict = {}
        real_probe = runtime_store_module.is_execution_lock_held

        def racing_probe(path, command_id):
            alive = real_probe(path, command_id)
            if not alive and "lock" not in held:
                held["lock"] = process_lock.try_acquire_execution_lock(path, command_id)
                with sqlite3.connect(workspace / "runtime.sqlite3") as connection:
                    connection.execute(
                        "UPDATE outbox_commands SET owner_token = 'live-owner' WHERE command_id = ?",
                        (command_id,),
                    )
            return alive

        try:
            with patch.object(runtime_store_module, "is_execution_lock_held", racing_probe):
                store.recover()
            row = store.outbox_command(effect_type=COMMAND["effect_type"], idempotency_key=COMMAND["idempotency_key"])
            self.assertEqual(row["status"], "in_flight")
            self.assertEqual(row["owner_token"], "live-owner")
        finally:
            held["lock"].release()

    def test_claim_preserves_metadata_written_concurrently(self):
        from gh_address_cr.core import agent_protocol

        _thread_session("owner/repo", "99")
        agent_protocol.record_classification(
            "owner/repo", "99", item_id=THREAD_ITEM, classification="fix", agent_id="agent-a", note="n"
        )
        original_refresh = agent_protocol.refresh_stack_context_for_request

        def racing_refresh(*args, **kwargs):
            result = original_refresh(*args, **kwargs)

            def concurrent_review(current):
                current.setdefault("metadata", {})["check_summary"] = {"status": "concurrent"}

            session_store.transact_session("owner/repo", "99", concurrent_review, operation="session_update")
            return result

        with patch.object(agent_protocol, "refresh_stack_context_for_request", racing_refresh):
            agent_protocol.issue_action_request(
                "owner/repo", "99", role="fixer", agent_id="agent-a", item_id=THREAD_ITEM
            )

        metadata = session_store.load_session("owner/repo", "99")["metadata"]
        self.assertEqual(metadata.get("check_summary"), {"status": "concurrent"})



def _hold_write_lock(database: Path, statement: str = "BEGIN EXCLUSIVE") -> sqlite3.Connection:
    connection = sqlite3.connect(database, isolation_level=None)
    connection.execute(statement)
    return connection


class PersistenceErrorMappingContractTest(_StateDirTest):
    """D6/D9: persistence failures keep their documented reason codes."""

    def _workspace(self) -> Path:
        _thread_session("owner/repo", "81")
        return session_store.workspace_dir("owner/repo", "81")

    def test_locked_store_reads_raise_persistence_busy(self):
        from gh_address_cr.core.runtime_store import PersistenceBusyError

        workspace = self._workspace()
        holder = _hold_write_lock(workspace / "runtime.sqlite3")
        try:
            for operation in (
                lambda store: store.is_initialized(),
                lambda store: store.load(),
                lambda store: store.load_evidence(),
                lambda store: store.recover(),
            ):
                with self.assertRaises(PersistenceBusyError):
                    operation(RuntimeStore(workspace, busy_timeout_ms=20))
        finally:
            holder.rollback()
            holder.close()

    def test_locked_store_outbox_result_raises_persistence_busy(self):
        from gh_address_cr.core.runtime_store import PersistenceBusyError

        workspace = self._workspace()
        store = RuntimeStore(workspace, busy_timeout_ms=20)
        store.transact(lambda current: None, operation="outbox_plan", outbox=[COMMAND])
        holder = _hold_write_lock(workspace / "runtime.sqlite3", "BEGIN IMMEDIATE")
        try:
            with self.assertRaises(PersistenceBusyError):
                store.mark_outbox_in_flight(COMMAND["command_id"], owner_token="owner")
        finally:
            holder.rollback()
            holder.close()

    def test_gate_does_not_replace_an_unreadable_session(self):
        from gh_address_cr.core import gate

        with patch.object(
            gate.SessionManager,
            "load",
            side_effect=session_store.SessionError("PERSISTENCE_BUSY", "busy"),
        ):
            with self.assertRaises(session_store.SessionError) as raised:
                gate.Gatekeeper(github_client=object()).run("owner/repo", "82")
        self.assertEqual(raised.exception.reason_code, "PERSISTENCE_BUSY")

    def test_final_gate_keeps_persistence_reason_and_retryability(self):
        import contextlib
        import io

        from gh_address_cr.commands.final_gate import handle_final_gate

        stdout = io.StringIO()
        with (
            patch(
                "gh_address_cr.commands.final_gate.core_gate.Gatekeeper.run",
                side_effect=session_store.SessionError("PERSISTENCE_BUSY", "busy"),
            ),
            contextlib.redirect_stdout(stdout),
        ):
            exit_code = handle_final_gate("owner/repo", "83", ["--machine", "--no-auto-clean"])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 5)
        self.assertEqual(payload["reason_code"], "PERSISTENCE_BUSY")
        self.assertTrue(payload["retryable"])

    def test_final_gate_reruns_evaluation_after_a_stale_revision(self):
        import contextlib
        import io

        from gh_address_cr.commands.final_gate import handle_final_gate

        outcomes = [
            session_store.SessionError("STALE_REVISION", "stale"),
            session_store.SessionError("PERSISTENCE_BUSY", "busy"),
        ]
        stdout = io.StringIO()
        with (
            patch(
                "gh_address_cr.commands.final_gate.core_gate.Gatekeeper.run",
                side_effect=outcomes,
            ) as run,
            contextlib.redirect_stdout(stdout),
        ):
            handle_final_gate("owner/repo", "84", ["--machine", "--no-auto-clean"])

        self.assertEqual(run.call_count, 2)
        self.assertEqual(json.loads(stdout.getvalue())["reason_code"], "PERSISTENCE_BUSY")

    def test_load_session_does_not_wait_behind_a_writer_to_repair_projections(self):
        import time

        workspace = self._workspace()

        def touch(current):
            current.setdefault("metadata", {})["note"] = "dirty projection"

        session_store.transact_session("owner/repo", "81", touch, operation="session_update")
        holder = _hold_write_lock(workspace / "runtime.sqlite3", "BEGIN IMMEDIATE")
        try:
            started = time.monotonic()
            payload = session_store.load_session("owner/repo", "81")
            elapsed = time.monotonic() - started
        finally:
            holder.rollback()
            holder.close()
        self.assertEqual(payload["metadata"]["note"], "dirty projection")
        self.assertLess(elapsed, 2.0)


class MigrationAuthorityContractTest(_StateDirTest):
    """D7: an uncommitted migration grants its recovery bundle no authority."""

    def _legacy_paths(self) -> tuple[Path, Path, Path]:
        root = Path(self.state_dir) / "legacy"
        root.mkdir()
        return root / "session.json", root / "evidence.jsonl", root / "ws"

    def test_malformed_legacy_item_fails_with_persistence_invalid(self):
        from gh_address_cr.core.runtime_store import PersistenceInvalidError

        session_path, ledger_path, workspace = self._legacy_paths()
        session_path.write_text(
            json.dumps({"session_id": "o/r#1", "repo": "o/r", "pr_number": "1", "items": {"t1": "bad"}}),
            encoding="utf-8",
        )
        with self.assertRaises(PersistenceInvalidError):
            RuntimeStore(workspace).open_or_migrate(session_path=session_path, ledger_path=ledger_path)

    def test_changed_legacy_input_migrates_after_an_uncommitted_attempt(self):
        session_path, ledger_path, workspace = self._legacy_paths()
        session_path.write_text(
            json.dumps({"session_id": "o/r#1", "repo": "o/r", "pr_number": "1", "items": {}}),
            encoding="utf-8",
        )
        with patch.object(RuntimeStore, "_create_schema", side_effect=RuntimeError("injected import crash")):
            with self.assertRaisesRegex(RuntimeError, "injected import crash"):
                RuntimeStore(workspace).open_or_migrate(session_path=session_path, ledger_path=ledger_path)

        session_path.write_text(
            json.dumps({"session_id": "o/r#1", "repo": "o/r", "pr_number": "1", "items": {"t1": {"item_id": "t1"}}}),
            encoding="utf-8",
        )
        snapshot = RuntimeStore(workspace).open_or_migrate(session_path=session_path, ledger_path=ledger_path)

        self.assertIn("t1", snapshot.payload["items"])
        self.assertEqual(len(list(workspace.glob("legacy-v1-recovery.superseded-*"))), 1)


class BoundaryContractTest(_StateDirTest):
    """D8: version, shape, and ordering contracts at runtime boundaries."""

    def test_dev_preview_runtime_satisfies_its_release_minimum(self):
        from gh_address_cr.core import workflow

        with patch.object(workflow, "__version__", "3.16.0.dev303+abc1234"):
            self.assertEqual(workflow.runtime_compatibility()["status"], "compatible")
        with patch.object(workflow, "__version__", "3.15.9"):
            self.assertEqual(workflow.runtime_compatibility()["reason_code"], "RUNTIME_VERSION_INCOMPATIBLE")

    def test_naive_lease_timestamps_expire_as_utc(self):
        from gh_address_cr.core.leases import expire_leases

        store = RuntimeStore(Path(self.state_dir) / "naive")
        store.bootstrap(
            {
                "session_id": "o/r#1",
                "repo": "o/r",
                "pr_number": "1",
                "items": {"t1": {"item_id": "t1", "item_kind": "github_thread", "state": "claimed"}},
                "leases": {
                    "l1": {
                        "lease_id": "l1",
                        "item_id": "t1",
                        "agent_id": "a",
                        "role": "fixer",
                        "status": "active",
                        "created_at": "2020-01-01T00:00:00",
                        "expires_at": "2020-01-01T01:00:00",
                    }
                },
            }
        )
        result = store.transact(lambda current: expire_leases(current), operation="lease_release")
        self.assertEqual(len(result.value), 1)

    def test_item_verified_before_addressed_is_excluded_not_fatal(self):
        from gh_address_cr.core.cr_metrics import project_cr_lifecycle

        def event(record_id, timestamp, event_type, role, payload=None):
            return {
                "record_id": record_id,
                "timestamp": timestamp,
                "session_id": "s",
                "item_id": "t1",
                "event_type": event_type,
                "role": role,
                "payload": payload or {},
            }

        report = project_cr_lifecycle(
            [
                event("a", "2026-01-01T00:00:00Z", "finding_observed", "intake", {"item_kind": "github_thread"}),
                event("b", "2026-01-01T00:01:00Z", "response_published", "publisher"),
                event("c", "2026-01-01T00:02:00Z", "response_accepted", "fixer"),
            ],
            repo="o/r",
            pr_number="1",
        )
        item = report["items"][0]
        self.assertFalse(item["eligible"])
        self.assertIn("verified_before_addressed", item["exclusion_reasons"])

    def test_submit_against_a_superseded_protocol_request_fails_fast(self):
        from gh_address_cr.core import agent_protocol
        from gh_address_cr.core.errors import WorkflowError

        _thread_session("owner/repo", "60")
        claimed = _claim("owner/repo", "60")
        request_path = Path(claimed["request_path"])
        request = json.loads(request_path.read_text(encoding="utf-8"))
        request["schema_version"] = "1.0"
        request_path.write_text(json.dumps(request), encoding="utf-8")
        response = json.loads(Path(claimed["response_skeleton_path"]).read_text(encoding="utf-8"))
        response.update({"resolution": "clarify", "note": "n", "reply_markdown": "Please confirm."})
        response.pop("validation_commands", None)
        response_path = Path(self.state_dir) / "response.json"
        response_path.write_text(json.dumps(response), encoding="utf-8")

        with self.assertRaises(WorkflowError) as raised:
            agent_protocol.submit_action_response("owner/repo", "60", response_path=response_path)
        self.assertEqual(raised.exception.reason_code, "REQUEST_PROTOCOL_SUPERSEDED")

    def test_superseded_protocol_request_upgrade_path_end_to_end(self):
        from gh_address_cr.core import agent_protocol
        from gh_address_cr.core.errors import WorkflowError

        _thread_session("owner/repo", "63")
        claimed = _claim("owner/repo", "63")
        request_path = Path(claimed["request_path"])
        request = json.loads(request_path.read_text(encoding="utf-8"))
        request["schema_version"] = "1.0"
        request_path.write_text(json.dumps(request), encoding="utf-8")

        def response_file() -> Path:
            response = json.loads(Path(claimed["response_skeleton_path"]).read_text(encoding="utf-8"))
            response.update({"resolution": "clarify", "note": "n", "reply_markdown": "Please confirm."})
            response.pop("validation_commands", None)
            path = Path(self.state_dir) / "response-63.json"
            path.write_text(json.dumps(response), encoding="utf-8")
            return path

        with self.assertRaises(WorkflowError) as raised:
            agent_protocol.submit_action_response("owner/repo", "63", response_path=response_file())
        self.assertEqual(raised.exception.reason_code, "REQUEST_PROTOCOL_SUPERSEDED")
        self.assertIn("agent next", json.dumps(raised.exception.to_summary(repo="owner/repo", pr_number="63")))

        again = agent_protocol.issue_action_request(
            "owner/repo", "63", role="fixer", agent_id="agent-a", item_id=THREAD_ITEM
        )
        self.assertEqual(again["acquisition"], "reentered")
        self.assertEqual(again["lease_id"], claimed["lease_id"])

        accepted = agent_protocol.submit_action_response("owner/repo", "63", response_path=response_file())
        self.assertEqual(accepted["status"], "ACTION_ACCEPTED")

    def test_reentry_reissues_a_superseded_protocol_request(self):
        from gh_address_cr import PROTOCOL_VERSION
        from gh_address_cr.core.models import ActionRequest

        _thread_session("owner/repo", "61")
        claimed = _claim("owner/repo", "61")
        request_path = Path(claimed["request_path"])
        request = json.loads(request_path.read_text(encoding="utf-8"))
        request["schema_version"] = "1.0"
        request_path.write_text(json.dumps(request), encoding="utf-8")

        again = _claim("owner/repo", "61")

        self.assertEqual(again["acquisition"], "reentered")
        rebuilt = json.loads(request_path.read_text(encoding="utf-8"))
        lease = session_store.load_session("owner/repo", "61")["leases"][claimed["lease_id"]]
        self.assertEqual(rebuilt["schema_version"], PROTOCOL_VERSION)
        self.assertEqual(ActionRequest.from_dict(rebuilt).stable_hash(), lease["request_hash"])

    def test_batch_reentry_rebuild_updates_the_lease_request_hash(self):
        from gh_address_cr.core import agent_batch
        from gh_address_cr.core.models import ActionRequest

        _thread_session("owner/repo", "62")
        claimed = _claim("owner/repo", "62")

        def stale_hash(current):
            current["leases"][claimed["lease_id"]]["request_hash"] = "hash-from-3.15"

        session_store.transact_session("owner/repo", "62", stale_hash, operation="session_update")
        Path(claimed["request_path"]).unlink()

        agent_batch.issue_batch_action_request("owner/repo", "62", agent_id="agent-a")

        lease = session_store.load_session("owner/repo", "62")["leases"][claimed["lease_id"]]
        rebuilt = json.loads(Path(lease["request_path"]).read_text(encoding="utf-8"))
        self.assertEqual(ActionRequest.from_dict(rebuilt).stable_hash(), lease["request_hash"])

    def test_archive_does_not_remove_a_store_with_an_active_writer(self):
        from gh_address_cr.commands import final_gate

        workspace = PersistenceErrorMappingContractTest._workspace(self)
        holder = _hold_write_lock(workspace / "runtime.sqlite3", "BEGIN IMMEDIATE")
        try:
            with patch.object(final_gate, "ARCHIVE_BUSY_TIMEOUT_MS", 20):
                archived = final_gate.archive_and_clean_workspace("owner/repo", "81", "audit")
            self.assertIsNone(archived)
            self.assertTrue((workspace / "runtime.sqlite3").is_file())
        finally:
            holder.rollback()
            holder.close()

    def test_archive_copies_a_committed_store_snapshot(self):
        from gh_address_cr.commands import final_gate

        workspace = PersistenceErrorMappingContractTest._workspace(self)
        revision = RuntimeStore(workspace).load().revision

        archived = final_gate.archive_and_clean_workspace("owner/repo", "81", "audit")

        self.assertFalse(workspace.exists())
        self.assertEqual(RuntimeStore(archived).load().revision, revision)


if __name__ == "__main__":
    unittest.main()
