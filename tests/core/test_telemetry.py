import subprocess
import unittest
from unittest.mock import patch

from gh_address_cr.core.telemetry import SessionTelemetry, command_label


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
        mock_run.side_effect = subprocess.TimeoutExpired(cmd=["sleep", "10"], timeout=120.0, output="out", stderr="err")
        
        from gh_address_cr.core.cr_loop import run_cmd
        res = run_cmd(["sleep", "10"], timeout=120.0)
        
        self.assertEqual(res.returncode, 124)
        self.assertIn("Command timed out after 120.0 seconds.", res.stderr)
        
        tracker = SessionTelemetry.get_instance()
        self.assertEqual(len(tracker.metrics), 1)
        self.assertEqual(tracker.metrics[0].exit_code, 124)

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

if __name__ == "__main__":
    unittest.main()
