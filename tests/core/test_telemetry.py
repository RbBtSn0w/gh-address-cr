import subprocess
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from gh_address_cr.core.telemetry import SessionTelemetry, command_label, is_inline_env_assignment


class TestTelemetry(unittest.TestCase):
    def setUp(self):
        SessionTelemetry.reset()

    def test_record_metric(self):
        tracker = SessionTelemetry.get_instance()
        tracker.record("ls -l", 100.0, 101.5, 0)
        
        self.assertEqual(len(tracker.metrics), 1)
        metric = tracker.metrics[0]
        self.assertEqual(metric.command, "ls -l")
        self.assertEqual(metric.duration, 1.5)
        self.assertTrue(metric.is_success)
        self.assertFalse(metric.is_retry)
        self.assertGreater(metric.pid, 0)
        self.assertNotEqual(metric.execution_id, "")

    def test_retry_detection(self):
        tracker = SessionTelemetry.get_instance()
        tracker.record("npm install", 100.0, 105.0, 1) # Failed
        tracker.record("npm install", 106.0, 110.0, 0) # Retry succeeded
        
        self.assertEqual(len(tracker.metrics), 2)
        self.assertFalse(tracker.metrics[0].is_retry)
        self.assertTrue(tracker.metrics[1].is_retry)

    def test_aggregation(self):
        tracker = SessionTelemetry.get_instance()
        tracker.record("cmd1", 100.0, 101.0, 0)
        tracker.record("cmd2", 102.0, 104.0, 1)
        
        report = tracker.get_report()
        self.assertEqual(report.total_invocations, 2)
        self.assertEqual(report.total_duration, 3.0)
        self.assertEqual(report.success_rate, 50.0)

    def test_threshold_flagging(self):
        tracker = SessionTelemetry.get_instance()
        # Duration threshold (>60s)
        tracker.record("long cmd", 0, 61, 0)
        # Error rate (1 failure out of 1 is 100% > 20%)
        tracker.record("fail cmd", 100, 101, 1)
        # Explicit Timeout (124)
        tracker.record("hang cmd", 200, 320, 124)
        
        report = tracker.get_report()
        # Flags: 
        # - long cmd > 60s
        # - hang cmd > 60s
        # - hang cmd Timeout
        # - Global error rate
        self.assertGreaterEqual(len(report.flagged_inefficiencies), 4)
        
        flags_lower = [f.lower() for f in report.flagged_inefficiencies]
        self.assertTrue(any("exceeds 60s" in f for f in flags_lower))
        self.assertTrue(any("error rate" in f for f in flags_lower))
        self.assertTrue(any("critical" in f and "timeout" in f and "hang cmd" in f for f in flags_lower))

    def test_consecutive_retry_flagging(self):
        tracker = SessionTelemetry.get_instance()
        tracker.record("pytest", 0, 1, 1)
        tracker.record("pytest", 2, 3, 1)
        tracker.record("pytest", 4, 5, 0)
        
        report = tracker.get_report()
        # Should flag "pytest" for high retry count
        self.assertTrue(any("retries" in f.lower() and "pytest" in f for f in report.flagged_inefficiencies))

    def test_retry_flagging_uses_max_consecutive_chain(self):
        tracker = SessionTelemetry.get_instance()
        tracker.record("pytest", 0, 1, 1)
        tracker.record("pytest", 2, 3, 0)
        tracker.record("other", 4, 5, 0)
        tracker.record("pytest", 6, 7, 1)
        tracker.record("pytest", 8, 9, 0)

        report = tracker.get_report()

        retry_flags = [f for f in report.flagged_inefficiencies if "pytest" in f and "High Retry Rate" in f]
        self.assertEqual(len(retry_flags), 1)
        self.assertIn("ran 2 times consecutively with 1 retry", retry_flags[0])
        self.assertNotIn("ran 3 times consecutively", retry_flags[0])

    def test_timeout_wording_uses_hung(self):
        tracker = SessionTelemetry.get_instance()
        tracker.record("hang cmd", 200, 320, 124)

        report = tracker.get_report()

        timeout_flags = [f for f in report.flagged_inefficiencies if "execution timeout" in f]
        self.assertTrue(timeout_flags)
        self.assertIn("hung", timeout_flags[0])
        self.assertNotIn("Hanged", timeout_flags[0])

    def test_command_label_sanitizes_sensitive_arguments(self):
        label = command_label(
            [
                "/Users/snow/.pyenv/versions/3.10.19/bin/python",
                "-m",
                "gh_address_cr",
                "address",
                "owner/repo",
                "67",
                "--token",
                "ghp_secret",
                "/Users/snow/private workspace/file.txt",
            ]
        )

        self.assertEqual(label, "python -m gh_address_cr address")
        self.assertNotIn("ghp_secret", label)
        self.assertNotIn("/Users/snow", label)
        self.assertNotIn("owner/repo", label)

    def test_command_label_uses_shell_escaping_for_label_tokens(self):
        label = command_label(["/tmp/custom tool", "sub command", "--secret", "value"])

        self.assertEqual(label, "'custom tool' 'sub command'")
        self.assertNotIn("value", label)

    def test_command_label_skips_flag_values_and_sensitive_tokens(self):
        label = command_label([
            "curl",
            "-H",
            "Authorization: Bearer ghp_secret",
            "https://api.github.com/user",
        ])
        self.assertEqual(label, "curl")
        self.assertNotIn("Bearer", label)
        self.assertNotIn("ghp_secret", label)
        self.assertNotIn("https://", label)

    def test_command_label_strips_leading_inline_env_assignments(self):
        label = command_label(["GH_TOKEN=ghp_secret", "PYTHONPATH=src", "python", "-m", "adapter"])

        self.assertEqual(label, "python -m adapter")
        self.assertNotIn("GH_TOKEN", label)
        self.assertNotIn("ghp_secret", label)

    def test_command_label_strips_empty_inline_env_assignments(self):
        label = command_label(["GH_TOKEN=", "python", "-m", "adapter"])

        self.assertEqual(label, "python -m adapter")
        self.assertNotIn("GH_TOKEN", label)

    def test_is_inline_env_assignment_accepts_empty_values(self):
        self.assertTrue(is_inline_env_assignment("GH_TOKEN="))
        self.assertTrue(is_inline_env_assignment("PYTHONPATH=src"))
        self.assertFalse(is_inline_env_assignment("1BAD=value"))
        self.assertFalse(is_inline_env_assignment("A-B=value"))

    def test_json_serialization(self):
        tracker = SessionTelemetry.get_instance()
        tracker.record("cmd", 0, 1, 0)
        report = tracker.get_report()
        
        data = report.to_dict()
        self.assertEqual(data["total_invocations"], 1)
        self.assertEqual(len(data["metrics"]), 1)
        self.assertEqual(data["metrics"][0]["command"], "cmd")
        
        import json
        json_str = json.dumps(data)
        self.assertIsInstance(json_str, str)

    def test_empty_report(self):
        tracker = SessionTelemetry.get_instance()
        report = tracker.get_report()
        self.assertEqual(report.total_invocations, 0)
        self.assertEqual(report.total_duration, 0.0)
        self.assertEqual(report.success_rate, 0.0)
        self.assertEqual(report.flagged_inefficiencies, [])
        self.assertEqual(report.metrics, [])

    @patch("gh_address_cr.core.telemetry.core_paths.workspace_dir")
    def test_configure_context_resets_metrics(self, workspace_dir):
        first_payload = {
            "command": "pytest",
            "start_time": 0.0,
            "end_time": 1.0,
            "duration": 1.0,
            "exit_code": 0,
            "is_success": True,
            "is_retry": False,
            "pid": 1234,
            "execution_id": "first-run",
        }

        with tempfile.TemporaryDirectory() as tmp:
            telemetry_dir = Path(tmp) / "owner__repo" / "pr-77"
            telemetry_file = telemetry_dir / "telemetry.jsonl"
            telemetry_file.parent.mkdir(parents=True, exist_ok=True)
            telemetry_file.write_text(json.dumps(first_payload) + "\n", encoding="utf-8")

            workspace_dir.return_value = telemetry_dir
            tracker = SessionTelemetry.get_instance()
            tracker.record("leftover", 10.0, 11.0, 0)
            tracker.configure_context("owner/repo", "77")

            self.assertEqual(len(tracker.metrics), 1)
            self.assertEqual(tracker.metrics[0].command, "pytest")

            second_dir = Path(tmp) / "owner__repo" / "pr-78"
            second_file = second_dir / "telemetry.jsonl"
            second_file.parent.mkdir(parents=True, exist_ok=True)
            second_file.write_text(
                json.dumps({**first_payload, "command": "ruff", "execution_id": "second-run"}) + "\n",
                encoding="utf-8",
            )

            workspace_dir.return_value = second_dir
            tracker.configure_context("owner/repo", "78")
            self.assertEqual(len(tracker.metrics), 1)
            self.assertEqual(tracker.metrics[0].command, "ruff")

    def test_display_command_only_uses_ellipsis_if_needed(self):
        tracker = SessionTelemetry.get_instance()
        tracker.record("short cmd", 0, 1, 124)
        short_flags = tracker.get_report().flagged_inefficiencies
        self.assertTrue(any("`short cmd` hit execution timeout (hung)." in flag for flag in short_flags))
        self.assertFalse(any("`" + "short cmd" + "..." in flag for flag in short_flags))

        SessionTelemetry.reset()
        tracker = SessionTelemetry.get_instance()
        tracker.record("x" * 55, 0, 1, 124)
        long_flags = tracker.get_report().flagged_inefficiencies
        self.assertTrue(any("`" + "x" * 50 + "...` hit execution timeout (hung)." in flag for flag in long_flags))

    def test_metrics_persist_across_process_instances(self):
        with tempfile.TemporaryDirectory() as tmp:
            telemetry_file = Path(tmp) / "telemetry.jsonl"
            tracker = SessionTelemetry.get_instance()
            tracker.configure_file(telemetry_file)
            tracker.record("pytest", 0, 2, 0)

            SessionTelemetry.reset()
            restored = SessionTelemetry.get_instance()
            restored.configure_file(telemetry_file)
            report = restored.get_report()

        self.assertEqual(report.total_invocations, 1)
        self.assertEqual(report.total_duration, 2.0)
        self.assertEqual(report.metrics[0].command, "pytest")

    def test_configure_file_is_fail_open_when_persisted_metrics_are_unreadable(self):
        with tempfile.TemporaryDirectory() as tmp:
            telemetry_file = Path(tmp) / "telemetry.jsonl"
            telemetry_file.write_text("{}", encoding="utf-8")
            tracker = SessionTelemetry.get_instance()

            with patch.object(Path, "read_text", side_effect=OSError("denied")):
                tracker.configure_file(telemetry_file)

            self.assertEqual(tracker.metrics, [])

    def test_record_is_fail_open_when_metric_persistence_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            telemetry_file = Path(tmp) / "telemetry.jsonl"
            tracker = SessionTelemetry.get_instance()
            tracker.configure_file(telemetry_file)

            with patch.object(Path, "open", side_effect=OSError("denied")):
                tracker.record("pytest", 0, 1, 0)

            self.assertEqual(len(tracker.metrics), 1)
            self.assertEqual(tracker.metrics[0].command, "pytest")

    def test_metric_pid_and_execution_id(self):
        tracker = SessionTelemetry.get_instance()
        tracker.record("some cmd", 0, 1, 0, pid=12345, execution_id="exec-id-abc")
        metric = tracker.metrics[0]
        self.assertEqual(metric.pid, 12345)
        self.assertEqual(metric.execution_id, "exec-id-abc")
        
        # Test serialization
        data = metric.to_dict()
        self.assertEqual(data["pid"], 12345)
        self.assertEqual(data["execution_id"], "exec-id-abc")

    @patch("subprocess.run")
    def test_run_cmd_timeout(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd=["sleep", "10"], timeout=120.0, output=b"out", stderr=b"err")

        from gh_address_cr.core.cr_loop import run_cmd
        res = run_cmd(["sleep", "10"], timeout=120.0)

        self.assertEqual(res.returncode, 124)
        self.assertEqual(res.stdout, "out")
        self.assertIn("err", res.stderr)
        self.assertIn("Command timed out after 120.0 seconds.", res.stderr)
        
        tracker = SessionTelemetry.get_instance()
        self.assertEqual(len(tracker.metrics), 1)
        self.assertEqual(tracker.metrics[0].exit_code, 124)

    @patch("subprocess.run")
    def test_run_cmd_does_not_apply_default_timeout(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(args=["ls"], returncode=0, stdout="ok", stderr="")

        from gh_address_cr.core.cr_loop import run_cmd
        run_cmd(["ls"])

        self.assertIsNone(mock_run.call_args.kwargs["timeout"])

    @patch("sys.stderr")
    @patch("gh_address_cr.core.telemetry.SessionTelemetry.record")
    @patch("subprocess.run")
    def test_run_cmd_fail_open(self, mock_run, mock_record, mock_stderr):
        mock_run.return_value = subprocess.CompletedProcess(args=["ls"], returncode=0, stdout="ok", stderr="")
        mock_record.side_effect = Exception("Telemetry DB error")
        
        from gh_address_cr.core.cr_loop import run_cmd
        res = run_cmd(["ls"])
        self.assertEqual(res.returncode, 0)
        self.assertEqual(res.stdout, "ok")
        self.assertEqual(res.stderr, "")
        mock_stderr.write.assert_not_called()

    @patch("gh_address_cr.core.workflow.submit_lease")
    @patch("gh_address_cr.core.workflow.accept_lease")
    @patch("gh_address_cr.core.workflow._apply_response_to_item")
    def test_accept_action_response_submission_records_validation_telemetry(self, mock_apply, mock_accept, mock_submit):
        from gh_address_cr.core.workflow import _accept_action_response_submission
        from unittest.mock import MagicMock
        import tempfile
        from pathlib import Path

        session = {
            "session_id": "owner/repo#123",
            "repo": "owner/repo",
            "pr_number": "123",
            "items": {},
            "leases": {}
        }
        ledger = MagicMock()
        response = {
            "agent_id": "test-agent",
            "resolution": "fix",
            "note": "my fix note",
            "validation_commands": [
                {
                    "command": "GH_TOKEN=ghp_secret pytest tests/core --token ghp_secret",
                    "result": "Passed (528 tests)",
                    "duration": 5.5
                },
                {
                    "command": "GH_TOKEN=ghp_secret pytest tests/core --token ghp_secret",
                    "result": "Passed (528 tests)",
                    "duration": 5.5
                },
                {
                    "command": "pytest 'unterminated --token ghp_secret",
                    "result": "passed",
                    "duration": 1.0
                },
                {
                    "command": "ruff check src",
                    "result": "failed",
                    "start_time": 1000.0,
                    "end_time": 1002.5
                },
                {
                    "command": "ruff check src",
                    "result": "failed",
                    "duration": 0.0
                },
                {
                    "command": "pytest tests/unit",
                    "result": "passed"
                },
                {
                    "command": "pytest tests/integration",
                    "result": "passed"
                }
            ]
        }
        prepared = {
            "lease_id": "lease-123",
            "lease": {"role": "fixer"},
            "item_id": "finding-1",
            "item": {"item_kind": "local_finding"},
            "expected_request_hash": "hash-123"
        }

        with tempfile.TemporaryDirectory() as tmp:
            telemetry_file = Path(tmp) / "telemetry.jsonl"
            tracker = SessionTelemetry.get_instance()
            tracker.configure_file(telemetry_file)

            _accept_action_response_submission(session, ledger, response, prepared, now=datetime.now(timezone.utc))

            # We should have 5 metrics recorded; only the exact duplicate and malformed command are skipped.
            self.assertEqual(len(tracker.metrics), 5)

            # First one: inline env + path + token should be sanitized to pytest.
            self.assertEqual(tracker.metrics[0].command, "pytest")
            self.assertEqual(tracker.metrics[0].exit_code, 0)
            self.assertAlmostEqual(tracker.metrics[0].duration, 5.5)
            self.assertNotIn("ghp_secret", tracker.metrics[0].command)
            self.assertNotIn("GH_TOKEN", tracker.metrics[0].command)

            # Second one: ruff check src, exit_code 1, duration 2.5
            self.assertEqual(tracker.metrics[1].command, "ruff check")
            self.assertEqual(tracker.metrics[1].exit_code, 1)
            self.assertAlmostEqual(tracker.metrics[1].duration, 2.5)
            self.assertAlmostEqual(tracker.metrics[1].start_time, 1000.0)
            self.assertAlmostEqual(tracker.metrics[1].end_time, 1002.5)
            self.assertEqual(tracker.metrics[2].command, "ruff check")
            self.assertEqual(tracker.metrics[2].exit_code, 1)
            self.assertAlmostEqual(tracker.metrics[2].duration, 0.0)
            self.assertEqual(tracker.metrics[3].command, "pytest")
            self.assertEqual(tracker.metrics[4].command, "pytest")
            self.assertNotIn("_telemetry_validation_seen", session)

            _accept_action_response_submission(session, ledger, response, prepared, now=datetime.now(timezone.utc))
            self.assertEqual(len(tracker.metrics), 10)

    @patch("gh_address_cr.core.workflow.submit_lease")
    @patch("gh_address_cr.core.workflow.accept_lease")
    @patch("gh_address_cr.core.workflow._apply_response_to_item")
    def test_shared_batch_seen_deduplicates_validation_telemetry(self, mock_apply, mock_accept, mock_submit):
        from gh_address_cr.core.workflow import _accept_action_response_submission
        from unittest.mock import MagicMock
        import tempfile
        from pathlib import Path

        session = {
            "session_id": "owner/repo#123",
            "repo": "owner/repo",
            "pr_number": "123",
            "items": {},
            "leases": {}
        }
        ledger = MagicMock()
        response = {
            "agent_id": "test-agent",
            "resolution": "fix",
            "note": "my fix note",
            "validation_commands": [
                {
                    "command": "ruff check src",
                    "result": "passed",
                    "duration": 1.0
                }
            ]
        }
        prepared = {
            "lease_id": "lease-123",
            "lease": {"role": "fixer"},
            "item_id": "github-thread:one",
            "item": {"item_kind": "github_thread"},
            "expected_request_hash": "hash-123"
        }

        with tempfile.TemporaryDirectory() as tmp:
            telemetry_file = Path(tmp) / "telemetry.jsonl"
            tracker = SessionTelemetry.get_instance()
            tracker.configure_file(telemetry_file)
            telemetry_seen = set()

            _accept_action_response_submission(
                session, ledger, response, prepared, now=datetime.now(timezone.utc), telemetry_seen=telemetry_seen
            )
            _accept_action_response_submission(
                session, ledger, response, prepared, now=datetime.now(timezone.utc), telemetry_seen=telemetry_seen
            )

            self.assertEqual(len(tracker.metrics), 1)
            self.assertNotIn("_telemetry_validation_seen", session)

    @patch("gh_address_cr.core.workflow.submit_lease")
    @patch("gh_address_cr.core.workflow.accept_lease")
    def test_verifier_rejection_records_validation_telemetry(self, mock_accept, mock_submit):
        from gh_address_cr.core.workflow import WorkflowError, _accept_action_response_submission
        from unittest.mock import MagicMock
        import tempfile
        from pathlib import Path

        session = {
            "session_id": "owner/repo#123",
            "repo": "owner/repo",
            "pr_number": "123",
            "items": {},
            "leases": {}
        }
        ledger = MagicMock()
        ledger.append_event.return_value.record_id = "ev-reject"
        response = {
            "agent_id": "test-verifier",
            "resolution": "reject",
            "note": "validation failed",
            "validation_commands": [
                {
                    "command": "pytest tests/core",
                    "result": "failed (1 failed)",
                    "duration": 2.0
                }
            ]
        }
        prepared = {
            "lease_id": "lease-123",
            "lease": {"role": "verifier"},
            "item_id": "finding-1",
            "item": {"item_kind": "local_finding"},
            "expected_request_hash": "hash-123"
        }

        with tempfile.TemporaryDirectory() as tmp:
            telemetry_file = Path(tmp) / "telemetry.jsonl"
            tracker = SessionTelemetry.get_instance()
            tracker.configure_file(telemetry_file)

            with self.assertRaises(WorkflowError):
                _accept_action_response_submission(session, ledger, response, prepared, now=datetime.now(timezone.utc))

            self.assertEqual(len(tracker.metrics), 1)
            self.assertEqual(tracker.metrics[0].command, "pytest")
            self.assertEqual(tracker.metrics[0].exit_code, 1)
            self.assertAlmostEqual(tracker.metrics[0].duration, 2.0)

    @patch("subprocess.run")
    def test_run_adapter_command_records_telemetry(self, mock_run):
        from gh_address_cr.cli import _run_adapter_command
        import tempfile
        from pathlib import Path

        mock_run.return_value = subprocess.CompletedProcess(args=["my-adapter"], returncode=0, stdout="findings JSON", stderr="")

        with tempfile.TemporaryDirectory() as tmp:
            telemetry_file = Path(tmp) / "telemetry.jsonl"
            tracker = SessionTelemetry.get_instance()
            tracker.configure_file(telemetry_file)

            stdout, error = _run_adapter_command(["GH_TOKEN=ghp_secret", "my-adapter", "--fast"])

            self.assertEqual(stdout, "findings JSON")
            self.assertIsNone(error)
            mock_run.assert_called_once()
            self.assertEqual(mock_run.call_args.args[0], ["my-adapter", "--fast"])
            self.assertEqual(mock_run.call_args.kwargs["env"]["GH_TOKEN"], "ghp_secret")
            
            self.assertEqual(len(tracker.metrics), 1)
            self.assertEqual(tracker.metrics[0].command, "my-adapter")
            self.assertEqual(tracker.metrics[0].exit_code, 0)
            self.assertNotIn("ghp_secret", tracker.metrics[0].command)

if __name__ == "__main__":
    unittest.main()
