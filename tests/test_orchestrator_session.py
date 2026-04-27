import unittest
from gh_address_cr.orchestrator.worker import build_worker_packet, validate_action_response, WorkerPacketValidationError


class TestOrchestratorSession(unittest.TestCase):
    def test_worker_packet_generation_schema(self):
        item = {
            "item_id": "finding-1",
            "item_kind": "local_finding",
            "status": "OPEN",
            "title": "Example finding",
            "body": "Fix the null pointer.",
        }
        packet = build_worker_packet(
            run_id="run-xyz",
            lease_token="lease-abc",
            role="fixer",
            session_id="owner__repo/pr-123",
            item=item,
            response_path="/tmp/workspace/response-finding-1.json",
        )

        self.assertEqual(packet["orchestration_run_id"], "run-xyz")
        self.assertEqual(packet["lease_token"], "lease-abc")
        self.assertEqual(packet["role_requested"], "fixer")
        self.assertEqual(packet["response_path"], "/tmp/workspace/response-finding-1.json")

        action_request = packet["action_request"]
        self.assertIn("request_id", action_request)
        self.assertEqual(action_request["session_id"], "owner__repo/pr-123")
        self.assertEqual(action_request["lease_id"], "lease-abc")
        self.assertEqual(action_request["agent_role"], "fixer")
        self.assertEqual(action_request["item"], item)
        self.assertIn("allowed_actions", action_request)
        self.assertIn("required_evidence", action_request)

    def test_evidence_omission_causes_submission_failure(self):
        # Missing 'files' which is required
        action_response = {
            "action": "fix",
            "evidence": {"validation_commands": [], "note": "Fixed it.", "fix_reply": "Done"},
        }
        required_evidence = ["files", "validation_commands", "note", "fix_reply"]

        with self.assertRaises(WorkerPacketValidationError):
            validate_action_response(action_response, required_evidence)

    def test_missing_or_corrupted_orchestration_json_fails_loud(self):
        # T021: Error handling test for missing/corrupted orchestration.json
        import tempfile
        from pathlib import Path
        from gh_address_cr.orchestrator.session import load_orchestration_session, OrchestrationSessionError

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            # Mock the workspace_dir to use our tmp dir
            with unittest.mock.patch("gh_address_cr.core.session.workspace_dir", return_value=tmp_path):
                # 1. Test Missing
                with self.assertRaises(OrchestrationSessionError) as cm:
                    load_orchestration_session("owner/repo", "123")
                self.assertIn("missing", str(cm.exception))

                # 2. Test Corrupted
                json_file = tmp_path / "orchestration.json"
                json_file.write_text("invalid { json", encoding="utf-8")
                with self.assertRaises(OrchestrationSessionError) as cm:
                    load_orchestration_session("owner/repo", "123")
                self.assertIn("corrupted", str(cm.exception))

    def test_initialization(self):
        pass


if __name__ == "__main__":
    unittest.main()
