import io
import json
import os
import time
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gh_address_cr.core.session import SessionManager, load_session
from gh_address_cr.core.workflow import WorkflowError
from gh_address_cr.orchestrator.harness import handle_agent_orchestrate
from gh_address_cr.orchestrator.session import load_orchestration_session


class TestOrchestratorHarness(unittest.TestCase):
    def setUp(self):
        self.repo = "owner/repo"
        self.pr = "123"
        self.temp_dir = tempfile.TemporaryDirectory()
        self.env_patch = patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": self.temp_dir.name}, clear=False)
        self.env_patch.start()

    def tearDown(self):
        self.env_patch.stop()
        self.temp_dir.cleanup()

    def _core_manager(self) -> SessionManager:
        return SessionManager(self.repo, self.pr)

    def _open_item(self, item_id: str, *, classified: bool = True, path: str = "src/a.py") -> dict:
        item = {
            "item_id": item_id,
            "item_kind": "local_finding",
            "source": "local",
            "title": "Example finding",
            "body": "Fix me",
            "path": path,
            "line": 1,
            "state": "open",
            "status": "OPEN",
            "blocking": True,
            "handled": False,
            "allowed_actions": ["fix", "clarify", "defer", "reject"],
        }
        if classified:
            item["classification_evidence"] = {
                "event_type": "classification_recorded",
                "classification": "fix",
                "note": "verified",
                "record_id": "rec-1",
            }
        return item

    def _write_core_session(self, items: dict[str, dict]) -> None:
        manager = self._core_manager()
        payload = manager.create(status="ACTIVE")
        payload["items"] = items
        manager.save(payload)

    def _write_response(self, file_path: Path, payload: dict) -> None:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    @patch("gh_address_cr.orchestrator.harness.sys.stdout", new_callable=io.StringIO)
    def test_runtime_version_incompatibility_fails_loudly(self, mock_stdout):
        with patch("gh_address_cr.orchestrator.harness.__version__", "0.0.0"):
            exit_code = handle_agent_orchestrate("start", [self.repo, self.pr])
        self.assertEqual(exit_code, 2)
        payload = json.loads(mock_stdout.getvalue().strip().split("\n")[-1])
        self.assertEqual(payload["status"], "FAILED")
        self.assertEqual(payload["reason_code"], "INCOMPATIBLE_RUNTIME")
        self.assertEqual(payload["next_action"], "HALT")

    @patch("gh_address_cr.orchestrator.harness.sys.stdout", new_callable=io.StringIO)
    def test_start_syncs_queue_from_authoritative_runtime(self, mock_stdout):
        self._write_core_session(
            {
                "finding-1": self._open_item("finding-1", classified=True),
                "finding-2": {**self._open_item("finding-2", classified=True), "blocking": False},
                "finding-3": {**self._open_item("finding-3", classified=True), "handled": True},
            }
        )

        exit_code = handle_agent_orchestrate("start", [self.repo, self.pr])
        self.assertEqual(exit_code, 0)
        session = load_orchestration_session(self.repo, self.pr)
        self.assertEqual(session.queued_items, ["finding-1"])
        self.assertIn("INITIALIZED", mock_stdout.getvalue())

    @patch("gh_address_cr.orchestrator.harness.sys.stdout", new_callable=io.StringIO)
    def test_status_reports_authoritative_queue_count_after_start(self, mock_stdout):
        self._write_core_session({"finding-1": self._open_item("finding-1", classified=True)})
        self.assertEqual(handle_agent_orchestrate("start", [self.repo, self.pr]), 0)

        mock_stdout.truncate(0)
        mock_stdout.seek(0)
        self.assertEqual(handle_agent_orchestrate("status", [self.repo, self.pr]), 0)
        payload = json.loads(mock_stdout.getvalue())
        self.assertEqual(payload["queued_items"], 1)

    @patch("gh_address_cr.orchestrator.harness.sys.stdout", new_callable=io.StringIO)
    def test_step_dispatches_worker_packet_from_real_action_request(self, mock_stdout):
        self._write_core_session({"finding-1": self._open_item("finding-1", classified=True)})
        self.assertEqual(handle_agent_orchestrate("start", [self.repo, self.pr]), 0)

        mock_stdout.truncate(0)
        mock_stdout.seek(0)
        exit_code = handle_agent_orchestrate("step", [self.repo, self.pr, "--role", "fixer"])
        self.assertEqual(exit_code, 0)

        payload = json.loads(mock_stdout.getvalue())
        packet = payload["packet"]
        self.assertEqual(payload["status"], "DISPATCHED")
        self.assertEqual(packet["role_requested"], "fixer")
        self.assertEqual(packet["action_request"]["item"]["item_id"], "finding-1")
        self.assertTrue(packet["response_path"].endswith("response-finding-1.json"))

        core_state = load_session(self.repo, self.pr)
        self.assertEqual(len(core_state.get("leases", {})), 1)

    @patch("gh_address_cr.orchestrator.harness.sys.stdout", new_callable=io.StringIO)
    def test_step_resyncs_and_skips_stale_queued_items(self, mock_stdout):
        self._write_core_session(
            {
                "finding-stale": self._open_item("finding-stale", classified=True),
                "finding-live": self._open_item("finding-live", classified=True),
            }
        )
        self.assertEqual(handle_agent_orchestrate("start", [self.repo, self.pr]), 0)

        manager = self._core_manager()
        core_state = manager.load()
        core_state["items"]["finding-stale"]["blocking"] = False
        manager.save(core_state)

        mock_stdout.truncate(0)
        mock_stdout.seek(0)
        self.assertEqual(handle_agent_orchestrate("step", [self.repo, self.pr, "--role", "fixer"]), 0)
        payload = json.loads(mock_stdout.getvalue())
        self.assertEqual(payload["packet"]["action_request"]["item"]["item_id"], "finding-live")

    @patch("gh_address_cr.orchestrator.harness.sys.stdout", new_callable=io.StringIO)
    def test_resume_then_status_converges_to_runtime_queue(self, mock_stdout):
        self._write_core_session({"finding-1": self._open_item("finding-1", classified=True)})
        self.assertEqual(handle_agent_orchestrate("start", [self.repo, self.pr]), 0)

        manager = self._core_manager()
        core_state = manager.load()
        core_state["items"]["finding-2"] = self._open_item("finding-2", classified=True)
        manager.save(core_state)

        orchestration = load_orchestration_session(self.repo, self.pr)
        orchestration.queued_items = ["stale-item"]
        from gh_address_cr.orchestrator.session import save_orchestration_session

        save_orchestration_session(orchestration)

        self.assertEqual(handle_agent_orchestrate("resume", [self.repo, self.pr]), 0)
        mock_stdout.truncate(0)
        mock_stdout.seek(0)
        self.assertEqual(handle_agent_orchestrate("status", [self.repo, self.pr]), 0)
        payload = json.loads(mock_stdout.getvalue())
        self.assertEqual(payload["queued_items"], 2)

    @patch("gh_address_cr.orchestrator.harness.sys.stdout", new_callable=io.StringIO)
    def test_step_missing_workflow_context_returns_waiting_without_core_lease(self, mock_stdout):
        self._write_core_session({"finding-1": self._open_item("finding-1", classified=False)})
        self.assertEqual(handle_agent_orchestrate("start", [self.repo, self.pr]), 0)

        mock_stdout.truncate(0)
        mock_stdout.seek(0)
        exit_code = handle_agent_orchestrate("step", [self.repo, self.pr, "--role", "fixer"])
        self.assertEqual(exit_code, 0)
        payload = json.loads(mock_stdout.getvalue())
        self.assertEqual(payload["status"], "WAITING")

        core_state = load_session(self.repo, self.pr)
        self.assertEqual(core_state.get("leases", {}), {})

    @patch("gh_address_cr.orchestrator.harness.parse_and_validate_response")
    @patch("gh_address_cr.orchestrator.harness.workflow.submit_action_response")
    def test_submit_calls_runtime_and_releases_lease_only_after_success(self, mock_submit, mock_parse):
        self._write_core_session({"finding-1": self._open_item("finding-1", classified=True)})
        self.assertEqual(handle_agent_orchestrate("start", [self.repo, self.pr]), 0)
        self.assertEqual(handle_agent_orchestrate("step", [self.repo, self.pr, "--role", "fixer"]), 0)

        session = load_orchestration_session(self.repo, self.pr)
        lease = session.active_leases["finding-1"]
        response_path = Path(self.temp_dir.name) / "response.json"
        self._write_response(response_path, {"evidence": {"files": [], "validation_commands": [], "note": "n", "fix_reply": {}}})

        mock_parse.return_value = {}
        mock_submit.return_value = {"status": "ACTION_ACCEPTED"}
        exit_code = handle_agent_orchestrate(
            "submit",
            [
                self.repo,
                self.pr,
                "--item-id",
                "finding-1",
                "--token",
                lease.lease_token,
                "--input",
                str(response_path),
            ],
        )
        self.assertEqual(exit_code, 0)
        mock_submit.assert_called_once_with(self.repo, self.pr, response_path=str(response_path))
        post = load_orchestration_session(self.repo, self.pr)
        self.assertNotIn("finding-1", post.active_leases)

    @patch("gh_address_cr.orchestrator.harness.parse_and_validate_response")
    @patch("gh_address_cr.orchestrator.harness.workflow.submit_action_response")
    def test_submit_race_fast_fails_and_preserves_lease(self, mock_submit, mock_parse):
        self._write_core_session({"finding-1": self._open_item("finding-1", classified=True)})
        self.assertEqual(handle_agent_orchestrate("start", [self.repo, self.pr]), 0)
        self.assertEqual(handle_agent_orchestrate("step", [self.repo, self.pr, "--role", "fixer"]), 0)

        session = load_orchestration_session(self.repo, self.pr)
        lease = session.active_leases["finding-1"]
        response_path = Path(self.temp_dir.name) / "response-race.json"
        self._write_response(response_path, {"evidence": {"files": [], "validation_commands": [], "note": "n", "fix_reply": {}}})

        mock_parse.return_value = {}
        mock_submit.side_effect = WorkflowError(
            status="ACTION_REJECTED",
            reason_code="STALE_REQUEST_CONTEXT",
            exit_code=5,
            waiting_on="action_response",
            message="stale",
        )

        exit_code = handle_agent_orchestrate(
            "submit",
            [
                self.repo,
                self.pr,
                "--item-id",
                "finding-1",
                "--token",
                lease.lease_token,
                "--input",
                str(response_path),
            ],
        )
        self.assertEqual(exit_code, 2)
        post = load_orchestration_session(self.repo, self.pr)
        self.assertIn("finding-1", post.active_leases)

    @patch("gh_address_cr.orchestrator.harness.sys.stdout", new_callable=io.StringIO)
    def test_stop_enforces_authoritative_final_gate(self, mock_stdout):
        self._write_core_session({"finding-1": self._open_item("finding-1", classified=True)})
        self.assertEqual(handle_agent_orchestrate("start", [self.repo, self.pr]), 0)
        with patch("gh_address_cr.orchestrator.harness.session_engine.cmd_gate", return_value=1):
            exit_code = handle_agent_orchestrate("stop", [self.repo, self.pr])
        self.assertEqual(exit_code, 2)
        self.assertIn("final-gate", mock_stdout.getvalue().lower())

    @patch("gh_address_cr.orchestrator.harness.sys.stdout", new_callable=io.StringIO)
    def test_submit_retry_count_persisted_and_handoff_at_three_failures(self, mock_stdout):
        self._write_core_session({"finding-1": self._open_item("finding-1", classified=True)})
        self.assertEqual(handle_agent_orchestrate("start", [self.repo, self.pr]), 0)
        self.assertEqual(handle_agent_orchestrate("step", [self.repo, self.pr, "--role", "fixer"]), 0)

        session = load_orchestration_session(self.repo, self.pr)
        lease = session.active_leases["finding-1"]
        bad_response = Path(self.temp_dir.name) / "bad-response.json"
        bad_response.write_text("{ invalid", encoding="utf-8")

        for attempt in (1, 2, 3):
            exit_code = handle_agent_orchestrate(
                "submit",
                [
                    self.repo,
                    self.pr,
                    "--item-id",
                    "finding-1",
                    "--token",
                    lease.lease_token,
                    "--input",
                    str(bad_response),
                ],
            )
            self.assertEqual(exit_code, 2)
            current = load_orchestration_session(self.repo, self.pr)
            self.assertEqual(current.retry_counts.get("finding-1"), attempt)

        self.assertIn("human handoff", mock_stdout.getvalue().lower())

    @patch("gh_address_cr.orchestrator.harness.sys.stdout", new_callable=io.StringIO)
    def test_status_reconciliation_budget_guard_fails_loud_when_exceeded(self, mock_stdout):
        self._write_core_session({"finding-1": self._open_item("finding-1", classified=True)})
        self.assertEqual(handle_agent_orchestrate("start", [self.repo, self.pr]), 0)

        with patch("gh_address_cr.orchestrator.harness.time.perf_counter", side_effect=[1.0, 2.2]):
            exit_code = handle_agent_orchestrate("status", [self.repo, self.pr])
        self.assertEqual(exit_code, 2)
        self.assertIn("reconciliation", mock_stdout.getvalue().lower())

    @patch("gh_address_cr.orchestrator.harness.sys.stdout", new_callable=io.StringIO)
    def test_status_and_lock_reconciliation_target_is_under_100ms(self, mock_stdout):
        self._write_core_session({"finding-1": self._open_item("finding-1", classified=True)})
        self.assertEqual(handle_agent_orchestrate("start", [self.repo, self.pr]), 0)

        mock_stdout.truncate(0)
        mock_stdout.seek(0)
        status_start = time.perf_counter()
        exit_code = handle_agent_orchestrate("status", [self.repo, self.pr])
        status_elapsed = time.perf_counter() - status_start
        self.assertEqual(exit_code, 0)
        payload = json.loads(mock_stdout.getvalue().strip().split("\n")[-1])
        self.assertEqual(payload["status"], "READY")
        self.assertLess(payload["reconciliation_seconds"], 0.1)
        self.assertLess(status_elapsed, 0.1)

        session = load_orchestration_session(self.repo, self.pr)
        session.completed = True
        session.queued_items = []
        session.active_leases = {}
        from gh_address_cr.orchestrator.session import save_orchestration_session

        save_orchestration_session(session)
        with patch("gh_address_cr.orchestrator.harness._eligible_runtime_items", return_value=[]):
            mock_stdout.truncate(0)
            mock_stdout.seek(0)
            lock_start = time.perf_counter()
            exit_code = handle_agent_orchestrate("start", [self.repo, self.pr])
            lock_elapsed = time.perf_counter() - lock_start
            self.assertEqual(exit_code, 0)
            lock_payload = json.loads(mock_stdout.getvalue().strip().split("\n")[-1])
            self.assertEqual(lock_payload["status"], "LOCKED")
            self.assertLess(lock_elapsed, 0.1)

    @patch("gh_address_cr.orchestrator.harness.sys.stdout", new_callable=io.StringIO)
    def test_step_enforces_max_concurrency(self, mock_stdout):
        self._write_core_session({
            "finding-1": self._open_item("finding-1", classified=True, path="src/a.py"),
            "finding-2": self._open_item("finding-2", classified=True, path="src/b.py"),
            "finding-3": self._open_item("finding-3", classified=True, path="src/c.py")
        })
        self.assertEqual(handle_agent_orchestrate("start", [self.repo, self.pr, "--max-concurrency", "2"]), 0)
        self.assertEqual(handle_agent_orchestrate("step", [self.repo, self.pr, "--role", "fixer"]), 0)
        self.assertEqual(handle_agent_orchestrate("step", [self.repo, self.pr, "--role", "fixer"]), 0)
        
        mock_stdout.truncate(0)
        mock_stdout.seek(0)
        
        self.assertEqual(handle_agent_orchestrate("step", [self.repo, self.pr, "--role", "fixer"]), 0)
        payload = json.loads(mock_stdout.getvalue().strip().split("\n")[-1])
        
        self.assertEqual(payload["status"], "WAITING")
        self.assertEqual(payload["reason_code"], "MAX_CONCURRENCY_REACHED")
        self.assertEqual(payload["next_action"], "RETRY")

    @patch("gh_address_cr.orchestrator.harness.sys.stdout", new_callable=io.StringIO)
    def test_start_and_step_respect_completion_lock(self, mock_stdout):
        self._write_core_session({"finding-1": self._open_item("finding-1", classified=True)})
        self.assertEqual(handle_agent_orchestrate("start", [self.repo, self.pr]), 0)
        
        session = load_orchestration_session(self.repo, self.pr)
        session.completed = True
        from gh_address_cr.orchestrator.session import save_orchestration_session
        save_orchestration_session(session)

        mock_stdout.truncate(0)
        mock_stdout.seek(0)
        
        # If there are no eligible items, it's locked
        with patch("gh_address_cr.orchestrator.harness._eligible_runtime_items", return_value=[]):
            self.assertEqual(handle_agent_orchestrate("start", [self.repo, self.pr]), 0)
            payload = json.loads(mock_stdout.getvalue().strip().split("\n")[-1])
            self.assertEqual(payload["status"], "LOCKED")
            self.assertEqual(payload["reason_code"], "SESSION_LOCKED")
            self.assertEqual(payload["next_action"], "HALT")
        
        mock_stdout.truncate(0)
        mock_stdout.seek(0)
        session.queued_items = []
        session.active_leases = {}
        save_orchestration_session(session)
        with patch("gh_address_cr.orchestrator.harness._eligible_runtime_items", return_value=[]):
            self.assertEqual(handle_agent_orchestrate("step", [self.repo, self.pr]), 0)
            payload = json.loads(mock_stdout.getvalue().strip().split("\n")[-1])
            self.assertEqual(payload["status"], "LOCKED")
            self.assertEqual(payload["reason_code"], "SESSION_LOCKED")
            self.assertEqual(payload["next_action"], "HALT")


    @patch("gh_address_cr.orchestrator.harness.sys.stdout", new_callable=io.StringIO)
    def test_missing_arguments_emit_structured_failure_signal(self, mock_stdout):
        # Missing 'repo' and 'pr'
        exit_code = handle_agent_orchestrate("status", [])
        self.assertEqual(exit_code, 2)
        payload = json.loads(mock_stdout.getvalue().strip().split("\n")[-1])
        self.assertEqual(payload["status"], "FAILED")
        self.assertEqual(payload["reason_code"], "INVALID_ARGUMENTS")
        self.assertEqual(payload["next_action"], "HALT")


    @patch("gh_address_cr.orchestrator.harness.sys.stdout", new_callable=io.StringIO)
    def test_status_and_resume_emit_structured_failure_signals(self, mock_stdout):
        # Case 1: Status failure (Session missing)
        exit_code = handle_agent_orchestrate("status", [self.repo, self.pr])
        self.assertEqual(exit_code, 2)
        payload = json.loads(mock_stdout.getvalue().strip().split("\n")[-1])
        self.assertEqual(payload["status"], "FAILED")
        self.assertEqual(payload["reason_code"], "SESSION_ERROR")
        self.assertEqual(payload["next_action"], "HALT")

        mock_stdout.truncate(0)
        mock_stdout.seek(0)

        # Case 2: Resume failure (Session missing)
        exit_code = handle_agent_orchestrate("resume", [self.repo, self.pr])
        self.assertEqual(exit_code, 2)
        payload = json.loads(mock_stdout.getvalue().strip().split("\n")[-1])
        self.assertEqual(payload["status"], "FAILED")
        self.assertEqual(payload["reason_code"], "SESSION_ERROR")
        self.assertEqual(payload["next_action"], "HALT")


if __name__ == "__main__":
    unittest.main()
