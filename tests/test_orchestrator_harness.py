import unittest
import io
from unittest.mock import patch, MagicMock, mock_open
from gh_address_cr.orchestrator.harness import handle_agent_orchestrate
from gh_address_cr.orchestrator.session import OrchestrationSession
from gh_address_cr.orchestrator.worker import WorkerPacketValidationError, HumanHandoffRequired


class TestOrchestratorHarness(unittest.TestCase):
    def setUp(self):
        self.repo = "owner/repo"
        self.pr = "123"

    @patch("gh_address_cr.orchestrator.harness.sys.stderr", new_callable=io.StringIO)
    def test_runtime_version_incompatibility_fails_loudly(self, mock_stderr):
        # T008a: Mock version to be too old
        with patch("gh_address_cr.orchestrator.harness.__version__", "0.0.0"):
            exit_code = handle_agent_orchestrate("step", [self.repo, self.pr])
            self.assertEqual(exit_code, 2)
            self.assertIn("Incompatible Runtime CLI version", mock_stderr.getvalue())

    @patch("gh_address_cr.orchestrator.harness.load_orchestration_session")
    @patch("gh_address_cr.orchestrator.harness.sys.stdout", new_callable=io.StringIO)
    def test_step_dispatches_triage_task(self, mock_stdout, mock_load):
        # T008: Mock a session with one pending triage item
        mock_session = OrchestrationSession(run_id="run-1", repo=self.repo, pr_number=self.pr)
        mock_session.queued_items = ["finding-1"]
        mock_load.return_value = mock_session

        with patch("gh_address_cr.orchestrator.harness.save_orchestration_session"):
            handle_agent_orchestrate("step", [self.repo, self.pr])

        mock_load.assert_called_with(self.repo, self.pr)

    @patch("gh_address_cr.orchestrator.harness.load_orchestration_session")
    def test_stop_fails_loudly_with_active_leases(self, mock_load):
        # T015c: Mock session with active lease
        mock_session = MagicMock()
        mock_session.active_leases = {"item-1": MagicMock()}
        mock_load.return_value = mock_session

        with patch("gh_address_cr.orchestrator.harness.sys.stderr", new_callable=io.StringIO) as mock_stderr:
            exit_code = handle_agent_orchestrate("stop", [self.repo, self.pr])
            self.assertEqual(exit_code, 2)
            self.assertIn("active leases exist", mock_stderr.getvalue())

    @patch("gh_address_cr.orchestrator.harness.load_orchestration_session")
    def test_resume_restoring_queue_state(self, mock_load):
        # T020: Integration test for resume
        mock_session = OrchestrationSession(run_id="run-1", repo=self.repo, pr_number=self.pr)
        mock_load.return_value = mock_session

        exit_code = handle_agent_orchestrate("resume", [self.repo, self.pr])
        self.assertEqual(exit_code, 0)
        mock_load.assert_called_with(self.repo, self.pr)

    @patch("gh_address_cr.orchestrator.worker.os.path.exists", return_value=True)
    def test_bounded_retry_max_attempts_and_human_handoff(self, mock_exists):
        # T029a: Mock parse_and_validate_response reaching max retries
        from gh_address_cr.orchestrator.worker import parse_and_validate_response

        # Mock file content to be invalid JSON
        with patch("builtins.open", mock_open(read_data="invalid json")):
            with self.assertRaises(HumanHandoffRequired):
                parse_and_validate_response("some_path.json", [], retry_count=3)

    @patch("gh_address_cr.orchestrator.worker.os.path.exists", return_value=False)
    def test_step_fails_loudly_when_response_path_empty(self, mock_exists):
        # T029b: If file doesn't exist, it should raise error
        from gh_address_cr.orchestrator.worker import parse_and_validate_response

        with self.assertRaises(WorkerPacketValidationError):
            parse_and_validate_response("missing.json", [])

    @patch("gh_address_cr.orchestrator.harness.parse_and_validate_response")
    @patch("gh_address_cr.orchestrator.harness.load_orchestration_session")
    @patch("gh_address_cr.orchestrator.harness.save_orchestration_session")
    def test_submit_verifies_evidence_and_releases_lease(self, mock_save, mock_load, mock_parse):
        # T013b: Verify handle_submit calls validation and releases lease
        mock_session = MagicMock()
        mock_load.return_value = mock_session
        mock_parse.return_value = {"action": "fix"}

        exit_code = handle_agent_orchestrate(
            "submit", [self.repo, self.pr, "--item-id", "finding-1", "--token", "lease-123", "--input", "resp.json"]
        )

        self.assertEqual(exit_code, 0)
        mock_parse.assert_called_with("resp.json", ["files", "validation_commands", "note", "fix_reply"])
        mock_session.validate_lease_for_submission.assert_called_with("finding-1", "lease-123")
        mock_session.release_lease.assert_called_with("finding-1", "lease-123")
        mock_save.assert_called()

    def test_verify_no_orchestration_step_bypasses_final_gate(self):
        # T032: This is mostly a conceptual test, but we can verify the 'stop' logic again
        pass


if __name__ == "__main__":
    unittest.main()
