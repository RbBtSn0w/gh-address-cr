import subprocess
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from gh_address_cr.core import paths as core_paths
from gh_address_cr.core.telemetry import (
    SessionTelemetry,
    build_efficiency_report,
    command_label,
    import_external_telemetry,
    is_inline_env_assignment,
)


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

    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_runtime_only_efficiency_report_has_coverage_and_artifact(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            tracker = SessionTelemetry.get_instance()
            tracker.configure_context("octo/example", "77")
            tracker.record("python3 -m unittest discover -s tests", 0, 2, 0)

            report = build_efficiency_report("octo/example", "77")

            self.assertEqual(report["coverage_label"], "runtime-only")
            self.assertEqual(report["total_events"], 1)
            self.assertEqual(report["sources"][0]["source"], "runtime")
            self.assertTrue(Path(report["report_artifact"]).exists())

    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_no_telemetry_efficiency_report_is_unavailable(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)

            report = build_efficiency_report("octo/example", "77")

            self.assertEqual(report["coverage_label"], "unavailable")
            self.assertEqual(report["total_events"], 0)
            self.assertTrue(Path(report["report_artifact"]).exists())

    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_import_external_telemetry_deduplicates_and_combines_report(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            payload = "\n".join(
                [
                    json.dumps(
                        {
                            "schema_version": "1.0",
                            "source": "generic-agent",
                            "source_session_id": "run-1",
                            "event_id": "e1",
                            "kind": "tool_call",
                            "operation": "run unit tests",
                            "duration_ms": 89105,
                            "status": "success",
                            "metadata": {"command_label": "python3 -m unittest discover -s tests"},
                        }
                    ),
                    "",
                ]
            )

            first = import_external_telemetry(
                "octo/example", "77", source="generic-agent", fmt="agent-jsonl", raw=payload
            )
            second = import_external_telemetry(
                "octo/example", "77", source="generic-agent", fmt="agent-jsonl", raw=payload
            )
            report = build_efficiency_report("octo/example", "77")

            self.assertEqual(first["status"], "SUCCESS")
            self.assertEqual(first["accepted_count"], 1)
            self.assertEqual(len(first["accepted_fingerprints"]), 1)
            self.assertEqual(first["duplicate_fingerprints"], [])
            self.assertEqual(second["reason_code"], "DUPLICATE_TELEMETRY_IMPORT")
            self.assertEqual(second["duplicate_count"], 1)
            self.assertEqual(second["accepted_fingerprints"], [])
            self.assertEqual(second["duplicate_fingerprints"], first["accepted_fingerprints"])
            self.assertEqual(report["total_events"], 1)
            self.assertEqual(report["coverage_label"], "partial")
            self.assertEqual(report["diagnostics"], [])
            self.assertEqual(report["slowest_operations"][0]["operation"], "run unit tests")

    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_overlapping_external_imports_are_deduped_by_event_fingerprint(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            first = {
                "schema_version": "1.0",
                "source": "generic-agent",
                "source_session_id": "run-1",
                "event_id": "event-from-host-a",
                "kind": "tool_call",
                "operation": "run unit tests",
                "started_at": "2026-06-03T06:00:00Z",
                "ended_at": "2026-06-03T06:01:29Z",
                "status": "success",
                "correlation_id": "validation:unit-tests",
            }
            overlap = {**first, "event_id": "event-from-host-b"}

            accepted = import_external_telemetry(
                "octo/example", "77", source="generic-agent", fmt="agent-jsonl", raw=json.dumps(first)
            )
            duplicate = import_external_telemetry(
                "octo/example", "77", source="generic-agent", fmt="agent-jsonl", raw=json.dumps(overlap)
            )
            report = build_efficiency_report("octo/example", "77")

            self.assertEqual(accepted["accepted_count"], 1)
            self.assertEqual(duplicate["reason_code"], "DUPLICATE_TELEMETRY_IMPORT")
            self.assertEqual(duplicate["duplicate_fingerprints"], accepted["accepted_fingerprints"])
            self.assertEqual(report["total_events"], 1)
            self.assertEqual(report["total_observed_duration_ms"], 89000)

            stored_events = [
                json.loads(line)
                for line in core_paths.external_telemetry_file("octo/example", "77").read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(stored_events[0]["event_fingerprint"], accepted["accepted_fingerprints"][0])
            self.assertTrue(core_paths.telemetry_fingerprints_file("octo/example", "77").exists())

    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_same_correlation_duration_only_events_do_not_collide(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            first = {
                "schema_version": "1.0",
                "source": "generic-agent",
                "source_session_id": "run-1",
                "event_id": "e1",
                "kind": "tool_call",
                "operation": "exec_command",
                "duration_ms": 1000,
                "status": "success",
                "correlation_id": "shared-correlation",
            }
            second = {**first, "event_id": "e2"}

            result = import_external_telemetry(
                "octo/example",
                "77",
                source="generic-agent",
                fmt="agent-jsonl",
                raw="\n".join([json.dumps(first), json.dumps(second)]),
            )
            report = build_efficiency_report("octo/example", "77")

            self.assertEqual(result["accepted_count"], 2)
            self.assertEqual(result["duplicate_count"], 0)
            self.assertEqual(report["total_events"], 2)
            self.assertEqual(report["total_observed_duration_ms"], 2000)

    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_missing_event_id_fingerprint_uses_canonical_fields_only(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            base = {
                "schema_version": "1.0",
                "source": "generic-agent",
                "source_session_id": "run-1",
                "kind": "tool_call",
                "operation": "exec_command",
                "duration_ms": 1000,
                "status": "success",
                "correlation_id": "tool-call-1",
            }
            first = {**base, "metadata": {"exit_code": 0}}
            second = {**base, "metadata": {"exit_code": 0, "note": "safe extra context"}}

            accepted = import_external_telemetry(
                "octo/example", "77", source="generic-agent", fmt="agent-jsonl", raw=json.dumps(first)
            )
            duplicate = import_external_telemetry(
                "octo/example", "77", source="generic-agent", fmt="agent-jsonl", raw=json.dumps(second)
            )
            report = build_efficiency_report("octo/example", "77")

            self.assertEqual(accepted["accepted_count"], 1)
            self.assertEqual(duplicate["reason_code"], "DUPLICATE_TELEMETRY_IMPORT")
            self.assertEqual(duplicate["duplicate_fingerprints"], accepted["accepted_fingerprints"])
            self.assertEqual(report["total_events"], 1)

    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_import_external_telemetry_rejects_unsafe_source_labels(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            payloads = [
                {
                    "schema_version": "1.0",
                    "source": "ghp_secret_source",
                    "source_session_id": "run-1",
                    "event_id": "source-token",
                    "kind": "tool_call",
                    "operation": "exec_command",
                    "duration_ms": 1,
                    "status": "success",
                },
                {
                    "schema_version": "1.0",
                    "source_session_id": "run-1",
                    "event_id": "declared-source-path",
                    "kind": "tool_call",
                    "operation": "exec_command",
                    "duration_ms": 1,
                    "status": "success",
                },
            ]

            inline_source = import_external_telemetry(
                "octo/example", "77", source="generic-agent", fmt="agent-jsonl", raw=json.dumps(payloads[0])
            )
            declared_source = import_external_telemetry(
                "octo/example", "77", source="/home/alice/agent", fmt="agent-jsonl", raw=json.dumps(payloads[1])
            )

            self.assertEqual(inline_source["reason_code"], "UNSAFE_TELEMETRY_CONTENT")
            self.assertEqual(declared_source["reason_code"], "UNSAFE_TELEMETRY_CONTENT")
            self.assertTrue(any("source" in diagnostic for diagnostic in inline_source["diagnostics"]))
            self.assertTrue(any("source" in diagnostic for diagnostic in declared_source["diagnostics"]))

    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_import_external_telemetry_redacts_unsafe_declared_source_in_summary(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)

            result = import_external_telemetry(
                "octo/example", "77", source="/home/alice/agent", fmt="agent-jsonl", raw="{not-json}\n"
            )

            self.assertEqual(result["reason_code"], "MALFORMED_TELEMETRY")
            self.assertEqual(result["source"], "[redacted]")
            self.assertNotIn("/home/alice", json.dumps(result))

    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_import_external_telemetry_rejects_ambiguous_source_sessions(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            payloads = [
                {
                    "schema_version": "1.0",
                    "source": "generic-agent",
                    "source_session_id": "run-1",
                    "event_id": "e1",
                    "kind": "tool_call",
                    "operation": "exec_command",
                    "duration_ms": 1,
                    "status": "success",
                },
                {
                    "schema_version": "1.0",
                    "source": "generic-agent",
                    "source_session_id": "run-2",
                    "event_id": "e2",
                    "kind": "tool_call",
                    "operation": "exec_command",
                    "duration_ms": 1,
                    "status": "success",
                },
            ]

            result = import_external_telemetry(
                "octo/example",
                "77",
                source="generic-agent",
                fmt="agent-jsonl",
                raw="\n".join(json.dumps(payload) for payload in payloads),
            )

            self.assertEqual(result["status"], "FAILED")
            self.assertEqual(result["reason_code"], "AMBIGUOUS_TELEMETRY_SESSION")
            self.assertEqual(result["accepted_count"], 0)
            self.assertFalse(core_paths.external_telemetry_file("octo/example", "77").exists())

    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_import_external_telemetry_rejects_unsafe_source_session_id(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            payloads = [
                {
                    "schema_version": "1.0",
                    "source": "generic-agent",
                    "source_session_id": "/Users/alice/.codex/session",
                    "event_id": "path-session",
                    "kind": "tool_call",
                    "operation": "exec_command",
                    "duration_ms": 1,
                    "status": "success",
                },
                {
                    "schema_version": "1.0",
                    "source": "generic-agent",
                    "source_session_id": "machine-id-laptop",
                    "event_id": "machine-session",
                    "kind": "tool_call",
                    "operation": "exec_command",
                    "duration_ms": 1,
                    "status": "success",
                },
            ]

            result = import_external_telemetry(
                "octo/example",
                "77",
                source="generic-agent",
                fmt="agent-jsonl",
                raw="\n".join(json.dumps(payload) for payload in payloads),
            )

            self.assertEqual(result["reason_code"], "UNSAFE_TELEMETRY_CONTENT")
            self.assertEqual(result["rejected_count"], 2)
            self.assertTrue(any("source_session_id" in diagnostic for diagnostic in result["diagnostics"]))

    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_import_external_telemetry_treats_mixed_timezone_timestamps_as_malformed(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            payload = json.dumps(
                {
                    "schema_version": "1.0",
                    "source": "generic-agent",
                    "source_session_id": "run-1",
                    "event_id": "mixed-timezones",
                    "kind": "tool_call",
                    "operation": "exec_command",
                    "started_at": "2026-06-03T06:00:00",
                    "ended_at": "2026-06-03T06:00:01Z",
                    "status": "success",
                }
            )

            result = import_external_telemetry("octo/example", "77", source="generic-agent", fmt="agent-jsonl", raw=payload)

            self.assertEqual(result["status"], "FAILED")
            self.assertEqual(result["reason_code"], "MALFORMED_TELEMETRY")
            self.assertTrue(any("timestamp timezone" in diagnostic for diagnostic in result["diagnostics"]))

    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_report_deduplicates_runtime_and_external_events_by_correlation(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            tracker = SessionTelemetry.get_instance()
            tracker.configure_context("octo/example", "77")
            tracker.record("python3 -m unittest discover -s tests", 0, 2, 0, execution_id="exec-1")
            raw = json.dumps(
                {
                    "schema_version": "1.0",
                    "source": "codex",
                    "source_session_id": "run-1",
                    "event_id": "host-event-1",
                    "kind": "command",
                    "operation": "python3 -m unittest discover -s tests",
                    "duration_ms": 2000,
                    "status": "success",
                    "correlation_id": "exec-1",
                }
            )

            import_external_telemetry("octo/example", "77", source="codex", fmt="agent-jsonl", raw=raw)
            report = build_efficiency_report("octo/example", "77")

            self.assertEqual(report["coverage_label"], "complete")
            self.assertEqual(report["total_events"], 1)
            self.assertEqual(report["total_observed_duration_ms"], 2000)
            self.assertTrue(any("correlated telemetry event ignored" in diagnostic for diagnostic in report["diagnostics"]))

    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_report_deduplicates_stored_duplicate_fingerprints(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            event = {
                "schema_version": "1.0",
                "source": "codex",
                "source_session_id": "run-1",
                "event_id": "e1",
                "kind": "tool_call",
                "operation": "exec_command",
                "duration_ms": 1000,
                "status": "success",
                "correlation_id": "tool-call-1",
            }
            imported = import_external_telemetry("octo/example", "77", source="codex", fmt="agent-jsonl", raw=json.dumps(event))
            stored_path = core_paths.external_telemetry_file("octo/example", "77")
            stored_line = stored_path.read_text(encoding="utf-8")
            stored_path.write_text(stored_line + stored_line, encoding="utf-8")

            report = build_efficiency_report("octo/example", "77")

            self.assertEqual(report["total_events"], 1)
            self.assertEqual(report["total_observed_duration_ms"], 1000)
            self.assertIn(f"duplicate event fingerprint ignored: {imported['accepted_fingerprints'][0]}", report["diagnostics"])

    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_corrupted_external_telemetry_is_fail_open_with_diagnostics(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            path = core_paths.external_telemetry_file("octo/example", "77")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{not-json}\n", encoding="utf-8")

            report = build_efficiency_report("octo/example", "77")

            self.assertEqual(report["status"], "SUCCESS")
            self.assertEqual(report["coverage_label"], "unavailable")
            self.assertEqual(report["total_events"], 0)
            self.assertTrue(any("external telemetry line 1" in diagnostic for diagnostic in report["diagnostics"]))

    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_import_external_telemetry_rejects_unsafe_metadata(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            payload = json.dumps(
                {
                    "schema_version": "1.0",
                    "source": "generic-agent",
                    "source_session_id": "run-1",
                    "event_id": "e1",
                    "kind": "tool_call",
                    "operation": "unsafe",
                    "duration_ms": 1,
                    "status": "success",
                    "metadata": {"token": "ghp_secret", "raw_prompt": "private prompt"},
                }
            )

            result = import_external_telemetry(
                "octo/example", "77", source="generic-agent", fmt="agent-jsonl", raw=payload
            )

            self.assertEqual(result["status"], "FAILED")
            self.assertEqual(result["reason_code"], "UNSAFE_TELEMETRY_CONTENT")
            self.assertEqual(result["accepted_count"], 0)

    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_import_external_telemetry_rejects_nested_secrets_and_linux_paths(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            payloads = [
                {
                    "schema_version": "1.0",
                    "source": "generic-agent",
                    "source_session_id": "run-1",
                    "event_id": "secret-key",
                    "kind": "tool_call",
                    "operation": "safe operation",
                    "duration_ms": 1,
                    "status": "success",
                    "metadata": {"config": {"github_token": "plain-secret"}},
                },
                {
                    "schema_version": "1.0",
                    "source": "generic-agent",
                    "source_session_id": "run-1",
                    "event_id": "linux-path",
                    "kind": "tool_call",
                    "operation": "python /home/alice/work/repo/script.py",
                    "duration_ms": 1,
                    "status": "success",
                    "metadata": {"nested": [{"path": "/root/private/repo"}]},
                },
            ]

            result = import_external_telemetry(
                "octo/example",
                "77",
                source="generic-agent",
                fmt="agent-jsonl",
                raw="\n".join(json.dumps(payload) for payload in payloads),
            )

            self.assertEqual(result["status"], "FAILED")
            self.assertEqual(result["reason_code"], "UNSAFE_TELEMETRY_CONTENT")
            self.assertEqual(result["accepted_count"], 0)
            self.assertEqual(result["rejected_count"], 2)
            self.assertTrue(any("github_token" in diagnostic for diagnostic in result["diagnostics"]))
            self.assertTrue(any("absolute path" in diagnostic for diagnostic in result["diagnostics"]))

    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_host_source_and_error_prone_operations_are_reported(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            raw = "\n".join(
                [
                    json.dumps(
                        {
                            "schema_version": "1.0",
                            "source": "codex",
                            "source_session_id": "run-1",
                            "event_id": "e1",
                            "kind": "tool_call",
                            "operation": "exec_command",
                            "duration_ms": 65000,
                            "status": "timeout",
                            "metadata": {"exit_code": 124},
                        }
                    ),
                    json.dumps(
                        {
                            "schema_version": "1.0",
                            "source": "codex",
                            "source_session_id": "run-1",
                            "event_id": "e2",
                            "kind": "retry",
                            "operation": "exec_command",
                            "duration_ms": 1000,
                            "status": "failure",
                            "metadata": {"exit_code": 1},
                        }
                    ),
                ]
            )

            imported = import_external_telemetry("octo/example", "77", source="codex", fmt="agent-jsonl", raw=raw)
            report = build_efficiency_report("octo/example", "77")

            self.assertEqual(imported["accepted_count"], 2)
            self.assertEqual(report["sources"][0]["source"], "codex")
            self.assertEqual(report["sources"][0]["source_type"], "host-adapter")
            self.assertEqual(report["slowest_operations"][0]["operation"], "exec_command")
            self.assertEqual(report["error_prone_operations"][0]["timeouts"], 1)
            self.assertEqual(report["error_prone_operations"][0]["retries"], 1)
            self.assertTrue(report["inefficiency_flags"])

    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_partial_import_diagnostics_are_carried_into_reports(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            valid = {
                "schema_version": "1.0",
                "source": "generic-agent",
                "source_session_id": "run-1",
                "event_id": "e1",
                "kind": "tool_call",
                "operation": "exec_command",
                "duration_ms": 1,
                "status": "success",
            }
            malformed = {**valid, "event_id": "e2", "kind": "unsafe-kind"}

            imported = import_external_telemetry(
                "octo/example",
                "77",
                source="generic-agent",
                fmt="agent-jsonl",
                raw="\n".join([json.dumps(valid), json.dumps(malformed)]),
            )
            report = build_efficiency_report("octo/example", "77")

            self.assertEqual(imported["status"], "PARTIAL")
            self.assertTrue(any("unsupported kind" in diagnostic for diagnostic in imported["diagnostics"]))
            self.assertTrue(any("unsupported kind" in diagnostic for diagnostic in report["diagnostics"]))

    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_import_external_telemetry_rejects_unsupported_format(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)

            result = import_external_telemetry("octo/example", "77", source="generic-agent", fmt="xml", raw="")

            self.assertEqual(result["status"], "FAILED")
            self.assertEqual(result["reason_code"], "UNSUPPORTED_TELEMETRY_FORMAT")

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
