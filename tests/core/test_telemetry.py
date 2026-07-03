import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from gh_address_cr.core import paths as core_paths
from gh_address_cr.core.agent_protocol import _record_validation_command_telemetry
from gh_address_cr.core.telemetry import (
    SessionTelemetry,
    _normalize_external_event,
    autodiscovery_miss_import_summary,
    build_efficiency_report,
    import_external_telemetry,
)
from gh_address_cr.core.telemetry_reporting import efficiency_report_markdown
from gh_address_cr.core.telemetry_safety import (
    command_label,
    is_inline_env_assignment,
)


class TestTelemetry(unittest.TestCase):
    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_runtime_events_preserve_measured_interval_timestamps(self, state_dir):
        from gh_address_cr.core.telemetry import _runtime_events

        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            paths = core_paths.SessionPaths("octo/example", "77")
            paths.workspace_dir.mkdir(parents=True)
            (paths.workspace_dir / "telemetry.jsonl").write_text(
                '{"command":"gh api","start_time":1.0,"end_time":2.5,"exit_code":0}\n',
                encoding="utf-8",
            )

            event = _runtime_events(paths)[0]

            self.assertEqual(event.started_at, "1970-01-01T00:00:01Z")
            self.assertEqual(event.ended_at, "1970-01-01T00:00:02.500000Z")

    def setUp(self):
        SessionTelemetry.reset()

    def test_telemetry_adapter_parse_documents_malformed_input_error_contract(self):
        from gh_address_cr.core.telemetry import TelemetryAdapter

        doc = TelemetryAdapter.parse.__doc__ or ""

        self.assertIn("TelemetryParseResult", doc)
        self.assertIn("ValueError", doc)
        self.assertIn("TypeError", doc)
        self.assertIn("KeyError", doc)
        self.assertIn("IndexError", doc)

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

    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_non_finite_persisted_runtime_metric_is_ignored_in_report(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            telemetry_path = core_paths.workspace_dir("octo/example", "77") / "telemetry.jsonl"
            telemetry_path.parent.mkdir(parents=True, exist_ok=True)
            telemetry_path.write_text(
                '{"command":"pytest","start_time":NaN,"end_time":1.0,"exit_code":0}\n',
                encoding="utf-8",
            )

            report = build_efficiency_report("octo/example", "77")

            self.assertEqual(report["status"], "SUCCESS")
            self.assertEqual(report["coverage_label"], "unavailable")
            self.assertEqual(report["total_events"], 0)

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

    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    @patch("gh_address_cr.core.telemetry._append_import_summary", side_effect=OSError("disk full"))
    def test_autodiscovery_miss_summary_is_fail_open_when_import_ledger_unwritable(self, _append, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)

            summary = autodiscovery_miss_import_summary(
                "octo/example",
                "77",
                diagnostics=["host telemetry autodiscovery codex: TELEMETRY_TRANSCRIPT_NOT_FOUND"],
            )

            self.assertEqual(summary["reason_code"], "TELEMETRY_AUTODISCOVERY_MISS")
            self.assertEqual(summary["diagnostics"][0], "host telemetry autodiscovery codex: TELEMETRY_TRANSCRIPT_NOT_FOUND")

    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_invalid_utf8_last_machine_summary_becomes_health_issue(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            path = core_paths.last_machine_summary_file("octo/example", "77")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"\xff\xfe\xfa")

            report = build_efficiency_report("octo/example", "77")

            reason_codes = {issue["reason_code"] for issue in report["cli_health_issues"]}
            self.assertIn("TELEMETRY_STORE_UNAVAILABLE", reason_codes)

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
    def test_efficiency_report_success_rate_ignores_unknown_status(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            payloads = [
                {
                    "schema_version": "1.0",
                    "source": "generic-agent",
                    "source_session_id": "run-1",
                    "event_id": "known-success",
                    "kind": "tool_call",
                    "operation": "run unit tests",
                    "duration_ms": 1000,
                    "status": "success",
                },
                {
                    "schema_version": "1.0",
                    "source": "generic-agent",
                    "source_session_id": "run-1",
                    "event_id": "unknown-status",
                    "kind": "tool_call",
                    "operation": "inspect local state",
                    "duration_ms": 1000,
                    "status": "unknown",
                },
            ]
            import_external_telemetry(
                "octo/example",
                "77",
                source="generic-agent",
                fmt="agent-jsonl",
                raw="\n".join(json.dumps(payload) for payload in payloads),
            )

            report = build_efficiency_report("octo/example", "77")

            self.assertEqual(report["total_events"], 2)
            self.assertEqual(report["success_rate"], 100.0)

    @patch("gh_address_cr.core.telemetry.write_json_atomic")
    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_efficiency_report_artifact_write_failure_is_fail_open(self, state_dir, write_json):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            write_json.side_effect = OSError("disk full")
            tracker = SessionTelemetry.get_instance()
            tracker.configure_context("octo/example", "77")
            tracker.record("python3 -m unittest discover -s tests", 0, 2, 0)

            report = build_efficiency_report("octo/example", "77")

            self.assertEqual(report["status"], "SUCCESS")
            self.assertEqual(report["reason_code"], "TELEMETRY_REPORT_READY")
            self.assertEqual(report["total_events"], 1)
            self.assertTrue(
                any("efficiency report artifact unavailable: OSError: disk full" in item for item in report["diagnostics"])
            )

    @patch("gh_address_cr.core.telemetry.write_json_atomic")
    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_efficiency_report_write_failure_diagnostic_omits_absolute_path(self, state_dir, write_json):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            write_json.side_effect = FileNotFoundError(
                2,
                "No such file or directory",
                "/private/tmp/secret/efficiency-report.json",
            )
            tracker = SessionTelemetry.get_instance()
            tracker.configure_context("octo/example", "77")
            tracker.record("python3 -m unittest discover -s tests", 0, 2, 0)

            report = build_efficiency_report("octo/example", "77")

            diagnostic = "\n".join(report["diagnostics"])
            self.assertIn("efficiency report artifact unavailable: FileNotFoundError: No such file or directory", diagnostic)
            self.assertNotIn("/private/tmp/secret", diagnostic)

    @patch("gh_address_cr.core.telemetry.time.perf_counter", side_effect=[10.0, 10.3, 10.3])
    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_efficiency_report_records_overhead_budget_diagnostics(self, state_dir, _perf_counter):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)

            report = build_efficiency_report("octo/example", "77")

            self.assertEqual(report["telemetry_overhead_budget_ms"], 250)
            self.assertEqual(report["telemetry_overhead_ms"], 300.0)
            self.assertIn("TELEMETRY_OVERHEAD_EXCEEDED", report["diagnostics"])

    @patch("gh_address_cr.core.telemetry.write_json_atomic")
    @patch("gh_address_cr.core.telemetry.time.perf_counter", side_effect=[10.0, 10.4])
    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_efficiency_report_overhead_includes_artifact_write_latency(self, state_dir, _perf_counter, write_json):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)

            report = build_efficiency_report("octo/example", "77")

            self.assertEqual(report["telemetry_overhead_ms"], 400.0)
            self.assertIn("TELEMETRY_OVERHEAD_EXCEEDED", report["diagnostics"])
            self.assertEqual(write_json.call_count, 1)

    @patch("gh_address_cr.core.telemetry.time.perf_counter", side_effect=[10.0, 10.4])
    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_efficiency_report_artifact_marks_final_overhead_unembedded(self, state_dir, _perf_counter):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)

            report = build_efficiency_report("octo/example", "77")

            artifact = json.loads(Path(report["report_artifact"]).read_text(encoding="utf-8"))
            self.assertEqual(report["telemetry_overhead_ms"], 400.0)
            self.assertIn("TELEMETRY_OVERHEAD_EXCEEDED", report["diagnostics"])
            self.assertIsNone(artifact["telemetry_overhead_ms"])
            self.assertNotIn("TELEMETRY_OVERHEAD_EXCEEDED", artifact["diagnostics"])

    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_efficiency_report_diagnostics_do_not_expose_absolute_paths(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            external_store = core_paths.workspace_dir("octo/example", "77") / "external-telemetry.jsonl"
            external_store.parent.mkdir(parents=True, exist_ok=True)
            external_store.mkdir()

            report = build_efficiency_report("octo/example", "77")

            self.assertTrue(report["diagnostics"])
            self.assertFalse(any(str(external_store.parent) in diagnostic for diagnostic in report["diagnostics"]))

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
    def test_generic_agent_import_does_not_renormalize_adapter_events(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            payload = json.dumps(
                {
                    "schema_version": "1.0",
                    "source": "generic-agent",
                    "source_session_id": "run-1",
                    "event_id": "e1",
                    "kind": "tool_call",
                    "operation": "run unit tests",
                    "duration_ms": 1000,
                    "status": "success",
                }
            )

            from gh_address_cr.core import telemetry as telemetry_module

            original = telemetry_module._normalize_external_event
            with patch("gh_address_cr.core.telemetry._normalize_external_event", wraps=original) as normalize_event:
                result = import_external_telemetry(
                    "octo/example", "77", source="generic-agent", fmt="agent-jsonl", raw=payload
                )

            self.assertEqual(result["status"], "SUCCESS")
            self.assertEqual(normalize_event.call_count, 1)

    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_efficiency_report_uses_canonical_fast_path_for_stored_external_events(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            imported = import_external_telemetry(
                "octo/example",
                "77",
                source="generic-agent",
                fmt="agent-jsonl",
                raw=json.dumps(
                    {
                        "schema_version": "1.0",
                        "source": "generic-agent",
                        "source_session_id": "run-1",
                        "event_id": "e1",
                        "kind": "tool_call",
                        "operation": "run unit tests",
                        "duration_ms": 1000,
                        "status": "success",
                    }
                ),
            )
            self.assertEqual(imported["status"], "SUCCESS")

            from gh_address_cr.core import telemetry as telemetry_module

            original = telemetry_module._normalize_external_event
            with patch("gh_address_cr.core.telemetry._normalize_external_event", wraps=original) as normalize_event:
                report = build_efficiency_report("octo/example", "77")

            self.assertEqual(report["status"], "SUCCESS")
            self.assertEqual(report["total_events"], 1)
            self.assertEqual(normalize_event.call_count, 0)

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
    def test_same_correlation_from_different_external_sources_is_not_report_deduped(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            base = {
                "schema_version": "1.0",
                "source_session_id": "run-1",
                "kind": "tool_call",
                "operation": "exec_command",
                "duration_ms": 1000,
                "status": "success",
                "correlation_id": "step-1",
            }
            first = {**base, "source": "generic-agent", "event_id": "agent-event"}
            second = {**base, "source": "codex", "event_id": "codex-event"}

            import_external_telemetry(
                "octo/example", "77", source="generic-agent", fmt="agent-jsonl", raw=json.dumps(first)
            )
            import_external_telemetry("octo/example", "77", source="codex", fmt="agent-jsonl", raw=json.dumps(second))
            report = build_efficiency_report("octo/example", "77")

            self.assertEqual(report["total_events"], 2)
            self.assertEqual(report["total_observed_duration_ms"], 2000)
            self.assertFalse(any("correlated telemetry event ignored" in item for item in report["diagnostics"]))

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

    def test_normalize_external_event_coalesces_blank_or_non_str_session_id(self):
        base = {
            "schema_version": "1.0",
            "source": "generic-agent",
            "kind": "tool_call",
            "operation": "exec_command",
            "duration_ms": 1000,
            "status": "success",
        }
        for label, raw_session_id in (
            ("empty string", ""),
            ("non-str int", 5),
            ("non-str bool", True),
        ):
            with self.subTest(case=label):
                event = _normalize_external_event(
                    {**base, "source_session_id": raw_session_id}, declared_source="generic-agent"
                )
                self.assertEqual(event.source_session_id, "unknown-session")

        missing = _normalize_external_event(dict(base), declared_source="generic-agent")
        self.assertEqual(missing.source_session_id, "unknown-session")

        # Boundary: a truthy non-empty string is preserved verbatim (including
        # whitespace-only), so coalescing applies only to blank/non-str input.
        for label, raw_session_id in (
            ("valid id", "run-1"),
            ("whitespace-only", "   "),
        ):
            with self.subTest(case=label):
                event = _normalize_external_event(
                    {**base, "source_session_id": raw_session_id}, declared_source="generic-agent"
                )
                self.assertEqual(event.source_session_id, raw_session_id)

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
                {
                    "schema_version": "1.0",
                    "source": "username-alice-laptop",
                    "source_session_id": "run-1",
                    "event_id": "source-private-id",
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
            private_source = import_external_telemetry(
                "octo/example", "77", source="generic-agent", fmt="agent-jsonl", raw=json.dumps(payloads[2])
            )

            self.assertEqual(inline_source["reason_code"], "UNSAFE_TELEMETRY_CONTENT")
            self.assertEqual(declared_source["reason_code"], "UNSAFE_TELEMETRY_CONTENT")
            self.assertEqual(private_source["reason_code"], "UNSAFE_TELEMETRY_CONTENT")
            self.assertTrue(any("source" in diagnostic for diagnostic in inline_source["diagnostics"]))
            self.assertTrue(any("source" in diagnostic for diagnostic in declared_source["diagnostics"]))
            self.assertTrue(any("source" in diagnostic for diagnostic in private_source["diagnostics"]))

    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_import_external_telemetry_rejects_source_control_characters(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            payload = {
                "schema_version": "1.0",
                "source": "generic-agent\n- injected",
                "source_session_id": "run-1",
                "event_id": "source-control",
                "kind": "tool_call",
                "operation": "exec_command",
                "duration_ms": 1,
                "status": "success",
            }

            result = import_external_telemetry(
                "octo/example", "77", source="generic-agent", fmt="agent-jsonl", raw=json.dumps(payload)
            )

            self.assertEqual(result["reason_code"], "UNSAFE_TELEMETRY_CONTENT")
            self.assertEqual(result["accepted_count"], 0)
            self.assertTrue(any("control character" in diagnostic for diagnostic in result["diagnostics"]))
            self.assertNotIn("- injected", json.dumps(result))
            self.assertFalse(core_paths.external_telemetry_file("octo/example", "77").exists())

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
    def test_import_external_telemetry_redacts_unsafe_unsupported_format_in_summary(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)

            result = import_external_telemetry(
                "octo/example", "77", source="generic-agent", fmt="/home/alice/telemetry.jsonl", raw=""
            )
            report = build_efficiency_report("octo/example", "77")

            self.assertEqual(result["reason_code"], "UNSUPPORTED_TELEMETRY_FORMAT")
            self.assertEqual(result["format"], "[redacted]")
            self.assertNotIn("/home/alice", json.dumps(result))
            self.assertNotIn("/home/alice", json.dumps(report))

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
    def test_import_external_telemetry_rejects_ambiguous_sessions_with_duplicates(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            first = {
                "schema_version": "1.0",
                "source": "generic-agent",
                "source_session_id": "run-1",
                "event_id": "e1",
                "kind": "tool_call",
                "operation": "exec_command",
                "duration_ms": 1,
                "status": "success",
            }
            second = {**first, "source_session_id": "run-2", "event_id": "e2"}

            import_external_telemetry("octo/example", "77", source="generic-agent", fmt="agent-jsonl", raw=json.dumps(first))
            result = import_external_telemetry(
                "octo/example",
                "77",
                source="generic-agent",
                fmt="agent-jsonl",
                raw="\n".join(json.dumps(payload) for payload in (first, second)),
            )
            report = build_efficiency_report("octo/example", "77")

            self.assertEqual(result["reason_code"], "AMBIGUOUS_TELEMETRY_SESSION")
            self.assertEqual(result["accepted_count"], 0)
            self.assertEqual(report["total_events"], 1)

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
    def test_import_external_telemetry_rejects_unsafe_event_id_and_timestamps(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            payloads = [
                {
                    "schema_version": "1.0",
                    "source": "generic-agent",
                    "source_session_id": "run-1",
                    "event_id": "ghp_secret_event",
                    "kind": "tool_call",
                    "operation": "exec_command",
                    "duration_ms": 1,
                    "status": "success",
                },
                {
                    "schema_version": "1.0",
                    "source": "generic-agent",
                    "source_session_id": "run-1",
                    "event_id": "unsafe-started-at",
                    "kind": "tool_call",
                    "operation": "exec_command",
                    "duration_ms": 1,
                    "started_at": "/home/alice/secret",
                    "status": "success",
                },
                {
                    "schema_version": "1.0",
                    "source": "generic-agent",
                    "source_session_id": "run-1",
                    "event_id": "unsafe-ended-at",
                    "kind": "tool_call",
                    "operation": "exec_command",
                    "duration_ms": 1,
                    "ended_at": "ghp_secret",
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
            self.assertEqual(result["rejected_count"], 3)
            self.assertTrue(any("event_id" in diagnostic for diagnostic in result["diagnostics"]))
            self.assertTrue(any("started_at" in diagnostic for diagnostic in result["diagnostics"]))
            self.assertTrue(any("ended_at" in diagnostic for diagnostic in result["diagnostics"]))

    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_import_external_telemetry_rejects_unsafe_schema_kind_and_status(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            payloads = [
                {
                    "schema_version": "ghp_secret_schema",
                    "source": "generic-agent",
                    "source_session_id": "run-1",
                    "event_id": "schema",
                    "kind": "tool_call",
                    "operation": "exec_command",
                    "duration_ms": 1,
                    "status": "success",
                },
                {
                    "schema_version": "1.0",
                    "source": "generic-agent",
                    "source_session_id": "run-1",
                    "event_id": "kind",
                    "kind": "ghp_secret_kind",
                    "operation": "exec_command",
                    "duration_ms": 1,
                    "status": "success",
                },
                {
                    "schema_version": "1.0",
                    "source": "generic-agent",
                    "source_session_id": "run-1",
                    "event_id": "status",
                    "kind": "tool_call",
                    "operation": "exec_command",
                    "duration_ms": 1,
                    "status": "ghp_secret_status",
                },
                {
                    "schema_version": "username-alice-laptop",
                    "source": "generic-agent",
                    "source_session_id": "run-1",
                    "event_id": "private-schema",
                    "kind": "tool_call",
                    "operation": "exec_command",
                    "duration_ms": 1,
                    "status": "success",
                },
                {
                    "schema_version": "1.0",
                    "source": "generic-agent",
                    "source_session_id": "run-1",
                    "event_id": "private-kind",
                    "kind": "machine-id-laptop",
                    "operation": "exec_command",
                    "duration_ms": 1,
                    "status": "success",
                },
                {
                    "schema_version": "1.0",
                    "source": "generic-agent",
                    "source_session_id": "run-1",
                    "event_id": "private-status",
                    "kind": "tool_call",
                    "operation": "exec_command",
                    "duration_ms": 1,
                    "status": "host-id-laptop",
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
            self.assertEqual(result["rejected_count"], 6)
            self.assertNotIn("ghp_secret", json.dumps(result))

    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_import_external_telemetry_rejects_identity_control_characters(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            payloads = [
                {
                    "schema_version": "1.0\n- injected",
                    "source": "generic-agent",
                    "source_session_id": "run-1",
                    "event_id": "schema-control",
                    "kind": "tool_call",
                    "operation": "exec_command",
                    "duration_ms": 1,
                    "status": "success",
                },
                {
                    "schema_version": "1.0",
                    "source": "generic-agent",
                    "source_session_id": "run-1",
                    "event_id": "kind-control",
                    "kind": "tool_call\n- injected",
                    "operation": "exec_command",
                    "duration_ms": 1,
                    "status": "success",
                },
                {
                    "schema_version": "1.0",
                    "source": "generic-agent",
                    "source_session_id": "run-1",
                    "event_id": "status-control",
                    "kind": "tool_call",
                    "operation": "exec_command",
                    "duration_ms": 1,
                    "status": "success\n- injected",
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
            self.assertEqual(result["rejected_count"], 3)
            self.assertTrue(any("control character" in diagnostic for diagnostic in result["diagnostics"]))
            self.assertNotIn("- injected", json.dumps(result))

    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_import_external_telemetry_fails_unsafe_partial_without_persisting(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            valid = {
                "schema_version": "1.0",
                "source": "generic-agent",
                "source_session_id": "run-1",
                "event_id": "valid",
                "kind": "tool_call",
                "operation": "exec_command",
                "duration_ms": 1,
                "status": "success",
            }
            unsafe = {**valid, "event_id": "unsafe", "metadata": {"token": "plain-secret"}}

            result = import_external_telemetry(
                "octo/example",
                "77",
                source="generic-agent",
                fmt="agent-jsonl",
                raw="\n".join(json.dumps(payload) for payload in (valid, unsafe)),
            )
            report = build_efficiency_report("octo/example", "77")

            self.assertEqual(result["status"], "FAILED")
            self.assertEqual(result["reason_code"], "UNSAFE_TELEMETRY_CONTENT")
            self.assertEqual(result["accepted_count"], 0)
            self.assertEqual(result["rejected_count"], 2)
            self.assertFalse(core_paths.external_telemetry_file("octo/example", "77").exists())
            self.assertEqual(report["total_events"], 0)

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
    def test_import_external_telemetry_rejects_nonstandard_json_constants(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            raw = (
                '{"schema_version":"1.0","source":"generic-agent","source_session_id":"run-1",'
                '"event_id":"nan-duration","kind":"tool_call","operation":"exec_command",'
                '"duration_ms":NaN,"status":"success"}'
            )

            result = import_external_telemetry("octo/example", "77", source="generic-agent", fmt="agent-jsonl", raw=raw)

            self.assertEqual(result["reason_code"], "MALFORMED_TELEMETRY")
            self.assertEqual(result["accepted_count"], 0)
            self.assertEqual(result["rejected_count"], 1)
            self.assertTrue(any("invalid JSON" in diagnostic for diagnostic in result["diagnostics"]))
            self.assertFalse(core_paths.external_telemetry_file("octo/example", "77").exists())

    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_import_external_telemetry_rejects_non_integer_duration_values(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            base = {
                "schema_version": "1.0",
                "source": "generic-agent",
                "source_session_id": "run-1",
                "kind": "tool_call",
                "operation": "exec_command",
                "status": "success",
            }
            payloads = [
                {**base, "event_id": "bool-duration", "duration_ms": True},
                {**base, "event_id": "float-duration", "duration_ms": 1.5},
            ]

            result = import_external_telemetry(
                "octo/example",
                "77",
                source="generic-agent",
                fmt="agent-jsonl",
                raw="\n".join(json.dumps(payload) for payload in payloads),
            )

            self.assertEqual(result["reason_code"], "MALFORMED_TELEMETRY")
            self.assertEqual(result["accepted_count"], 0)
            self.assertEqual(result["rejected_count"], 2)
            self.assertTrue(all("duration_ms must be an integer" in diagnostic for diagnostic in result["diagnostics"]))

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
    def test_report_deduplicates_correlated_runtime_and_external_events_with_duration_skew(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            tracker = SessionTelemetry.get_instance()
            tracker.configure_context("octo/example", "77")
            tracker.record("exec_command", 0, 2, 0, execution_id="exec-skew")
            raw = json.dumps(
                {
                    "schema_version": "1.0",
                    "source": "codex",
                    "source_session_id": "run-1",
                    "event_id": "host-event-skew",
                    "kind": "command",
                    "operation": "exec_command",
                    "duration_ms": 2100,
                    "status": "success",
                    "correlation_id": "exec-skew",
                }
            )

            import_external_telemetry("octo/example", "77", source="codex", fmt="agent-jsonl", raw=raw)
            report = build_efficiency_report("octo/example", "77")

            self.assertEqual(report["total_events"], 1)
            self.assertEqual(report["total_observed_duration_ms"], 2000)
            self.assertTrue(any("correlated telemetry event ignored" in diagnostic for diagnostic in report["diagnostics"]))

    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_runtime_command_operations_are_sanitized_before_reporting(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            tracker = SessionTelemetry.get_instance()
            tracker.configure_context("octo/example", "77")
            tracker.record("echo ghp_secret", 0, 1, 0, execution_id="unsafe-runtime-command")

            report = build_efficiency_report("octo/example", "77")

            self.assertEqual(report["slowest_operations"][0]["operation"], "echo")
            self.assertNotIn("ghp_secret", json.dumps(report))

    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_runtime_command_operations_scrub_private_identifiers(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            tracker = SessionTelemetry.get_instance()
            tracker.configure_context("octo/example", "77")
            tracker.record("ssh username-alice-laptop", 0, 1, 0, execution_id="private-runtime-command")

            report = build_efficiency_report("octo/example", "77")

            self.assertEqual(report["slowest_operations"][0]["operation"], "ssh")
            self.assertNotIn("username-alice-laptop", json.dumps(report))

    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_import_external_telemetry_redacts_private_source_in_early_failure(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)

            result = import_external_telemetry(
                "octo/example", "77", source="username-alice-laptop", fmt="xml", raw=""
            )

            self.assertEqual(result["reason_code"], "UNSUPPORTED_TELEMETRY_FORMAT")
            self.assertEqual(result["source"], "[redacted]")
            self.assertNotIn("username-alice-laptop", json.dumps(result))

    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_import_external_telemetry_allows_safe_metadata_keys_with_user_or_host_words(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            payload = {
                "schema_version": "1.0",
                "source": "generic-agent",
                "source_session_id": "run-1",
                "event_id": "safe-user-agent",
                "kind": "tool_call",
                "operation": "collect browser telemetry",
                "duration_ms": 1,
                "status": "success",
                "metadata": {
                    "user_agent": "Mozilla/5.0",
                    "host_status": "available",
                    "customer_id": "public-cohort-1",
                },
            }

            result = import_external_telemetry(
                "octo/example", "77", source="generic-agent", fmt="agent-jsonl", raw=json.dumps(payload)
            )

            self.assertEqual(result["status"], "SUCCESS")
            self.assertEqual(result["accepted_count"], 1)

    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_import_external_telemetry_rejects_reserved_runtime_source(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            payload = {
                "schema_version": "1.0",
                "source": "runtime",
                "source_session_id": "run-1",
                "event_id": "external-runtime",
                "kind": "command",
                "operation": "exec_command",
                "duration_ms": 1,
                "status": "success",
            }

            result = import_external_telemetry(
                "octo/example", "77", source="generic-agent", fmt="agent-jsonl", raw=json.dumps(payload)
            )

            self.assertEqual(result["reason_code"], "UNSAFE_TELEMETRY_CONTENT")
            self.assertTrue(any("reserved source label" in diagnostic for diagnostic in result["diagnostics"]))

    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_import_external_telemetry_rejects_operation_control_characters(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            payload = {
                "schema_version": "1.0",
                "source": "generic-agent",
                "source_session_id": "run-1",
                "event_id": "newline-operation",
                "kind": "tool_call",
                "operation": "exec_command\ninjected line",
                "duration_ms": 1,
                "status": "success",
            }

            result = import_external_telemetry(
                "octo/example", "77", source="generic-agent", fmt="agent-jsonl", raw=json.dumps(payload)
            )

            self.assertEqual(result["reason_code"], "UNSAFE_TELEMETRY_CONTENT")
            self.assertTrue(any("control character" in diagnostic for diagnostic in result["diagnostics"]))

    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_import_external_telemetry_rejects_non_string_operation(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            payload = {
                "schema_version": "1.0",
                "source": "generic-agent",
                "source_session_id": "run-1",
                "event_id": "array-operation",
                "kind": "tool_call",
                "operation": ["run", "tests"],
                "duration_ms": 1,
                "status": "success",
            }

            result = import_external_telemetry(
                "octo/example", "77", source="generic-agent", fmt="agent-jsonl", raw=json.dumps(payload)
            )

            self.assertEqual(result["status"], "FAILED")
            self.assertEqual(result["reason_code"], "MALFORMED_TELEMETRY")
            self.assertTrue(any("operation must be a string" in diagnostic for diagnostic in result["diagnostics"]))
            self.assertFalse(core_paths.external_telemetry_file("octo/example", "77").exists())

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
    def test_non_object_stored_external_telemetry_is_fail_open_with_diagnostics(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            path = core_paths.external_telemetry_file("octo/example", "77")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("[]\n", encoding="utf-8")

            report = build_efficiency_report("octo/example", "77")

            self.assertEqual(report["status"], "SUCCESS")
            self.assertEqual(report["coverage_label"], "unavailable")
            self.assertEqual(report["total_events"], 0)
            self.assertTrue(any("external telemetry line 1: record must be a JSON object" in item for item in report["diagnostics"]))

    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_stored_external_telemetry_without_source_is_corrupted(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            path = core_paths.external_telemetry_file("octo/example", "77")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "source_session_id": "run-1",
                        "event_id": "e1",
                        "kind": "tool_call",
                        "operation": "exec_command",
                        "duration_ms": 1,
                        "status": "success",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            report = build_efficiency_report("octo/example", "77")

            self.assertEqual(report["coverage_label"], "unavailable")
            self.assertEqual(report["total_events"], 0)
            self.assertTrue(any("missing required field(s): source" in item for item in report["diagnostics"]))

    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_stored_external_telemetry_rejects_non_string_source(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            path = core_paths.external_telemetry_file("octo/example", "77")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "source": ["generic-agent"],
                        "source_session_id": "run-1",
                        "event_id": "e1",
                        "kind": "tool_call",
                        "operation": "exec_command",
                        "duration_ms": 1,
                        "status": "success",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            report = build_efficiency_report("octo/example", "77")

            self.assertEqual(report["coverage_label"], "unavailable")
            self.assertEqual(report["total_events"], 0)
            self.assertTrue(any("source must be a string" in item for item in report["diagnostics"]))

    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_stored_external_telemetry_rejects_unsafe_operation_fast_path(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            path = core_paths.external_telemetry_file("octo/example", "77")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "source": "generic-agent",
                        "source_session_id": "run-1",
                        "event_id": "e1",
                        "kind": "tool_call",
                        "operation": "/Users/snow/private/repo/run-tests",
                        "duration_ms": 1,
                        "status": "success",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            report = build_efficiency_report("octo/example", "77")

            self.assertEqual(report["coverage_label"], "unavailable")
            self.assertEqual(report["total_events"], 0)
            self.assertTrue(any("unsafe absolute path in operation label" in item for item in report["diagnostics"]))

    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_stored_external_telemetry_rejects_unsupported_kind(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            path = core_paths.external_telemetry_file("octo/example", "77")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "source": "generic-agent",
                        "source_session_id": "run-1",
                        "event_id": "e1",
                        "kind": "totally-new-kind",
                        "operation": "exec_command",
                        "duration_ms": 1,
                        "status": "success",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            report = build_efficiency_report("octo/example", "77")

            self.assertEqual(report["coverage_label"], "unavailable")
            self.assertEqual(report["total_events"], 0)
            self.assertTrue(any("unsupported kind: totally-new-kind" in item for item in report["diagnostics"]))

    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_stored_external_telemetry_rejects_unsafe_source_session_id(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            path = core_paths.external_telemetry_file("octo/example", "77")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "source": "generic-agent",
                        "source_session_id": "/Users/snow/private/workspace",
                        "event_id": "e1",
                        "kind": "tool_call",
                        "operation": "exec_command",
                        "duration_ms": 1,
                        "status": "success",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            report = build_efficiency_report("octo/example", "77")

            self.assertEqual(report["coverage_label"], "unavailable")
            self.assertEqual(report["total_events"], 0)
            self.assertTrue(any("unsafe absolute path in source_session_id" in item for item in report["diagnostics"]))

    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_stored_external_telemetry_rejects_unsafe_correlation_id(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            path = core_paths.external_telemetry_file("octo/example", "77")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "source": "generic-agent",
                        "source_session_id": "run-1",
                        "event_id": "e1",
                        "kind": "tool_call",
                        "operation": "exec_command",
                        "duration_ms": 1,
                        "status": "success",
                        "correlation_id": "username-alice-laptop",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            report = build_efficiency_report("octo/example", "77")

            self.assertEqual(report["coverage_label"], "unavailable")
            self.assertEqual(report["total_events"], 0)
            self.assertTrue(any("unsafe correlation_id" in item for item in report["diagnostics"]))

    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_stored_external_telemetry_rejects_timestamp_control_characters(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            path = core_paths.external_telemetry_file("octo/example", "77")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "source": "generic-agent",
                        "source_session_id": "run-1",
                        "event_id": "e1",
                        "kind": "tool_call",
                        "operation": "exec_command",
                        "duration_ms": 1,
                        "status": "success",
                        "started_at": "2020-01-01\n12:00:00",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            report = build_efficiency_report("octo/example", "77")

            self.assertEqual(report["coverage_label"], "unavailable")
            self.assertEqual(report["total_events"], 0)
            self.assertTrue(any("unsafe control character in started_at" in item for item in report["diagnostics"]))

    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_stored_external_telemetry_redacts_unsafe_metadata_key_diagnostic(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            path = core_paths.external_telemetry_file("octo/example", "77")
            path.parent.mkdir(parents=True, exist_ok=True)
            unsafe_key = "github_token_ghp_secret"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "source": "generic-agent",
                        "source_session_id": "run-1",
                        "event_id": "e1",
                        "kind": "tool_call",
                        "operation": "exec_command",
                        "duration_ms": 1,
                        "status": "success",
                        "metadata": {unsafe_key: "value"},
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            report = build_efficiency_report("octo/example", "77")

            self.assertEqual(report["coverage_label"], "unavailable")
            self.assertEqual(report["total_events"], 0)
            self.assertTrue(any("[redacted]" in item for item in report["diagnostics"]))
            self.assertFalse(any(unsafe_key in item for item in report["diagnostics"]))

    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_stored_external_telemetry_rejects_unsafe_metadata(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            path = core_paths.external_telemetry_file("octo/example", "77")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "source": "generic-agent",
                        "source_session_id": "run-1",
                        "event_id": "e1",
                        "kind": "tool_call",
                        "operation": "exec_command",
                        "duration_ms": 1,
                        "status": "success",
                        "metadata": {"token": "ghp_secret"},
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            report = build_efficiency_report("octo/example", "77")

            self.assertEqual(report["coverage_label"], "unavailable")
            self.assertEqual(report["total_events"], 0)
            self.assertTrue(any("unsafe metadata field: token" in item for item in report["diagnostics"]))

    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_stored_external_telemetry_recomputes_mismatched_fingerprint(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            path = core_paths.external_telemetry_file("octo/example", "77")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "source": "generic-agent",
                        "source_session_id": "run-1",
                        "event_id": "e1",
                        "kind": "tool_call",
                        "operation": "exec_command",
                        "duration_ms": 1,
                        "status": "success",
                        "event_fingerprint": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    }
                )
                + "\n"
                + json.dumps(
                    {
                        "schema_version": "1.0",
                        "source": "generic-agent",
                        "source_session_id": "run-1",
                        "event_id": "e1",
                        "kind": "tool_call",
                        "operation": "exec_command",
                        "duration_ms": 1,
                        "status": "success",
                        "event_fingerprint": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            report = build_efficiency_report("octo/example", "77")

            self.assertEqual(report["coverage_label"], "partial")
            self.assertEqual(report["total_events"], 1)
            self.assertTrue(any("duplicate event fingerprint ignored" in item for item in report["diagnostics"]))

    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_corrupted_external_store_blocks_new_import(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            path = core_paths.external_telemetry_file("octo/example", "77")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{not-json}\n", encoding="utf-8")
            payload = {
                "schema_version": "1.0",
                "source": "generic-agent",
                "source_session_id": "run-1",
                "event_id": "e1",
                "kind": "tool_call",
                "operation": "exec_command",
                "duration_ms": 1,
                "status": "success",
            }

            result = import_external_telemetry(
                "octo/example", "77", source="generic-agent", fmt="agent-jsonl", raw=json.dumps(payload)
            )

            self.assertEqual(result["status"], "FAILED")
            self.assertEqual(result["reason_code"], "CORRUPTED_TELEMETRY_STORE")
            self.assertEqual(result["accepted_count"], 0)
            self.assertTrue(any("external telemetry line 1" in diagnostic for diagnostic in result["diagnostics"]))
            self.assertEqual(path.read_text(encoding="utf-8"), "{not-json}\n")

    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_external_store_directory_blocks_new_import(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            path = core_paths.external_telemetry_file("octo/example", "77")
            path.mkdir(parents=True)
            payload = {
                "schema_version": "1.0",
                "source": "generic-agent",
                "source_session_id": "run-1",
                "event_id": "e1",
                "kind": "tool_call",
                "operation": "exec_command",
                "duration_ms": 1,
                "status": "success",
            }

            result = import_external_telemetry(
                "octo/example", "77", source="generic-agent", fmt="agent-jsonl", raw=json.dumps(payload)
            )

            self.assertEqual(result["status"], "FAILED")
            self.assertEqual(result["reason_code"], "CORRUPTED_TELEMETRY_STORE")
            self.assertEqual(result["accepted_count"], 0)
            self.assertTrue(any("external telemetry store is not a regular file" in item for item in result["diagnostics"]))

    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_fingerprint_ledger_directory_blocks_import_without_appending_events(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            fingerprint_path = core_paths.telemetry_fingerprints_file("octo/example", "77")
            fingerprint_path.mkdir(parents=True)
            external_path = core_paths.external_telemetry_file("octo/example", "77")
            payload = {
                "schema_version": "1.0",
                "source": "generic-agent",
                "source_session_id": "run-1",
                "event_id": "e1",
                "kind": "tool_call",
                "operation": "exec_command",
                "duration_ms": 1,
                "status": "success",
            }

            result = import_external_telemetry(
                "octo/example", "77", source="generic-agent", fmt="agent-jsonl", raw=json.dumps(payload)
            )

            self.assertEqual(result["status"], "FAILED")
            self.assertEqual(result["reason_code"], "CORRUPTED_TELEMETRY_STORE")
            self.assertEqual(result["accepted_count"], 0)
            self.assertTrue(any("telemetry fingerprint ledger is not a regular file" in item for item in result["diagnostics"]))
            self.assertFalse(external_path.exists())

    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_corrupted_fingerprint_ledger_blocks_import_without_rewriting(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            fingerprint_path = core_paths.telemetry_fingerprints_file("octo/example", "77")
            fingerprint_path.parent.mkdir(parents=True, exist_ok=True)
            fingerprint_path.write_text("{not-json}\n", encoding="utf-8")
            external_path = core_paths.external_telemetry_file("octo/example", "77")
            payload = {
                "schema_version": "1.0",
                "source": "generic-agent",
                "source_session_id": "run-1",
                "event_id": "e1",
                "kind": "tool_call",
                "operation": "exec_command",
                "duration_ms": 1,
                "status": "success",
            }

            result = import_external_telemetry(
                "octo/example", "77", source="generic-agent", fmt="agent-jsonl", raw=json.dumps(payload)
            )

            self.assertEqual(result["status"], "FAILED")
            self.assertEqual(result["reason_code"], "CORRUPTED_TELEMETRY_STORE")
            self.assertTrue(any("telemetry fingerprint ledger invalid JSON" in item for item in result["diagnostics"]))
            self.assertEqual(fingerprint_path.read_text(encoding="utf-8"), "{not-json}\n")
            self.assertFalse(external_path.exists())

    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_non_file_import_ledger_is_reported_as_corrupted_storage(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            import_path = core_paths.telemetry_imports_file("octo/example", "77")
            import_path.mkdir(parents=True)

            report = build_efficiency_report("octo/example", "77")

            self.assertEqual(report["status"], "SUCCESS")
            self.assertEqual(report["coverage_label"], "unavailable")
            self.assertTrue(any("telemetry import summary is not a regular file" in item for item in report["diagnostics"]))

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
    def test_import_external_telemetry_rejects_private_metadata_values(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            payload = {
                "schema_version": "1.0",
                "source": "generic-agent",
                "source_session_id": "run-1",
                "event_id": "e1",
                "kind": "tool_call",
                "operation": "exec_command",
                "duration_ms": 1,
                "status": "success",
                "metadata": {"label": "username-alice-laptop"},
            }

            result = import_external_telemetry(
                "octo/example", "77", source="generic-agent", fmt="agent-jsonl", raw=json.dumps(payload)
            )

            self.assertEqual(result["status"], "FAILED")
            self.assertEqual(result["reason_code"], "UNSAFE_TELEMETRY_CONTENT")
            self.assertFalse(core_paths.external_telemetry_file("octo/example", "77").exists())

    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_import_external_telemetry_rejects_private_operation_labels(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            payload = {
                "schema_version": "1.0",
                "source": "generic-agent",
                "source_session_id": "run-1",
                "event_id": "e1",
                "kind": "tool_call",
                "operation": "machine-id-laptop",
                "duration_ms": 1,
                "status": "success",
            }

            result = import_external_telemetry(
                "octo/example", "77", source="generic-agent", fmt="agent-jsonl", raw=json.dumps(payload)
            )

            self.assertEqual(result["status"], "FAILED")
            self.assertEqual(result["reason_code"], "UNSAFE_TELEMETRY_CONTENT")
            self.assertFalse(core_paths.external_telemetry_file("octo/example", "77").exists())

    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_import_external_telemetry_rejects_unsafe_correlation_id(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            payload = {
                "schema_version": "1.0",
                "source": "generic-agent",
                "source_session_id": "run-1",
                "event_id": "e1",
                "kind": "tool_call",
                "operation": "exec_command",
                "duration_ms": 1,
                "status": "success",
                "correlation_id": "username-alice-laptop",
            }

            result = import_external_telemetry(
                "octo/example", "77", source="generic-agent", fmt="agent-jsonl", raw=json.dumps(payload)
            )

            self.assertEqual(result["status"], "FAILED")
            self.assertEqual(result["reason_code"], "UNSAFE_TELEMETRY_CONTENT")
            self.assertFalse(core_paths.external_telemetry_file("octo/example", "77").exists())

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
    def test_import_external_telemetry_rejects_common_absolute_workspace_paths(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            payloads = [
                {
                    "schema_version": "1.0",
                    "source": "generic-agent",
                    "source_session_id": "run-1",
                    "event_id": "workspace-path",
                    "kind": "tool_call",
                    "operation": "python /workspace/gh-address-cr/src/tool.py",
                    "duration_ms": 1,
                    "status": "success",
                },
                {
                    "schema_version": "1.0",
                    "source": "generic-agent",
                    "source_session_id": "run-1",
                    "event_id": "tmp-path",
                    "kind": "tool_call",
                    "operation": "safe operation",
                    "duration_ms": 1,
                    "status": "success",
                    "metadata": {"log": "/tmp/agent/run.log"},
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
            self.assertFalse(core_paths.external_telemetry_file("octo/example", "77").exists())

    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_import_external_telemetry_allows_safe_labels_with_sk_substrings(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            payload = {
                "schema_version": "1.0",
                "source": "disk-usage-agent",
                "source_session_id": "run-1",
                "event_id": "flask-tests",
                "kind": "tool_call",
                "operation": "run flask-tests",
                "duration_ms": 1,
                "status": "success",
                "metadata": {"suite": "flask-tests"},
            }

            result = import_external_telemetry(
                "octo/example", "77", source="disk-usage-agent", fmt="agent-jsonl", raw=json.dumps(payload)
            )

            self.assertEqual(result["status"], "SUCCESS")
            self.assertEqual(result["accepted_count"], 1)
            report = build_efficiency_report("octo/example", "77")
            self.assertIn("disk-usage-agent", json.dumps(report))
            self.assertIn("flask-tests", json.dumps(report))

    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_import_external_telemetry_allows_public_api_routes(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            payload = {
                "schema_version": "1.0",
                "source": "generic-agent",
                "source_session_id": "run-1",
                "event_id": "github-route",
                "kind": "tool_call",
                "operation": "GET /repos/owner/repo/pulls",
                "duration_ms": 25,
                "status": "success",
                "metadata": {"endpoint": "/repos/owner/repo/pulls/76"},
            }

            result = import_external_telemetry(
                "octo/example", "77", source="generic-agent", fmt="agent-jsonl", raw=json.dumps(payload)
            )
            report = build_efficiency_report("octo/example", "77")

            self.assertEqual(result["status"], "SUCCESS")
            self.assertEqual(result["accepted_count"], 1)
            self.assertEqual(report["total_events"], 1)
            self.assertEqual(report["slowest_operations"][0]["operation"], "GET /repos/owner/repo/pulls")

    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_import_external_telemetry_allows_safe_metadata_keys_containing_key(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            payload = {
                "schema_version": "1.0",
                "source": "generic-agent",
                "source_session_id": "run-1",
                "event_id": "safe-key-words",
                "kind": "tool_call",
                "operation": "collect input stats",
                "duration_ms": 1,
                "status": "success",
                "metadata": {"keyboard_layout": "us", "hotkey_count": 4},
            }

            result = import_external_telemetry(
                "octo/example", "77", source="generic-agent", fmt="agent-jsonl", raw=json.dumps(payload)
            )

            self.assertEqual(result["status"], "SUCCESS")
            self.assertEqual(result["accepted_count"], 1)

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
    def test_error_prone_operations_respect_error_rate_threshold(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            payloads = []
            for index in range(10):
                payloads.append(
                    {
                        "schema_version": "1.0",
                        "source": "codex",
                        "source_session_id": "run-1",
                        "event_id": f"event-{index}",
                        "kind": "tool_call",
                        "operation": "exec_command",
                        "duration_ms": 100,
                        "status": "failure" if index == 0 else "success",
                    }
                )

            imported = import_external_telemetry(
                "octo/example",
                "77",
                source="codex",
                fmt="agent-jsonl",
                raw="\n".join(json.dumps(payload) for payload in payloads),
            )
            report = build_efficiency_report("octo/example", "77")

            self.assertEqual(imported["accepted_count"], 10)
            self.assertEqual(report["error_prone_operations"], [])
            self.assertEqual(report["inefficiency_flags"], [])

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
            self.assertEqual(report["coverage_label"], "partial")
            self.assertTrue(any("unsupported kind" in diagnostic for diagnostic in imported["diagnostics"]))
            self.assertTrue(any("unsupported kind" in diagnostic for diagnostic in report["diagnostics"]))

    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_runtime_plus_partial_external_import_is_partial_coverage(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            tracker = SessionTelemetry.get_instance()
            tracker.configure_context("octo/example", "77")
            tracker.record("python3 -m unittest discover -s tests", 0, 2, 0)
            valid = {
                "schema_version": "1.0",
                "source": "generic-agent",
                "source_session_id": "run-1",
                "event_id": "accepted-event",
                "kind": "tool_call",
                "operation": "exec_command",
                "duration_ms": 1,
                "status": "success",
            }

            import_external_telemetry(
                "octo/example",
                "77",
                source="generic-agent",
                fmt="agent-jsonl",
                raw="\n".join([json.dumps(valid), "{not-json}"]),
            )
            report = build_efficiency_report("octo/example", "77")

            self.assertEqual(report["coverage_label"], "partial")
            self.assertTrue(any("invalid JSON" in diagnostic for diagnostic in report["diagnostics"]))

    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_successful_reimport_restores_complete_coverage_after_partial_import(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            tracker = SessionTelemetry.get_instance()
            tracker.configure_context("octo/example", "77")
            tracker.record("python3 -m unittest discover -s tests", 0, 2, 0)
            partial_event = {
                "schema_version": "1.0",
                "source": "generic-agent",
                "source_session_id": "run-1",
                "event_id": "partial-event",
                "kind": "tool_call",
                "operation": "exec_command",
                "duration_ms": 1,
                "status": "success",
            }
            recovered_event = {**partial_event, "event_id": "recovered-event", "operation": "review"}

            import_external_telemetry(
                "octo/example",
                "77",
                source="generic-agent",
                fmt="agent-jsonl",
                raw="\n".join([json.dumps(partial_event), "{not-json}"]),
            )
            import_external_telemetry(
                "octo/example",
                "77",
                source="generic-agent",
                fmt="agent-jsonl",
                raw=json.dumps(recovered_event),
            )
            report = build_efficiency_report("octo/example", "77")

            self.assertEqual(report["coverage_label"], "complete")
            self.assertTrue(any("invalid JSON" in diagnostic for diagnostic in report["diagnostics"]))

    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_successful_import_from_other_source_does_not_recover_failed_source(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            tracker = SessionTelemetry.get_instance()
            tracker.configure_context("octo/example", "77")
            tracker.record("python3 -m unittest discover -s tests", 0, 2, 0)
            failed_event = {
                "schema_version": "1.0",
                "source": "generic-agent",
                "source_session_id": "run-1",
                "event_id": "accepted-event",
                "kind": "tool_call",
                "operation": "exec_command",
                "duration_ms": 1,
                "status": "success",
            }
            recovered_other_source = {**failed_event, "source": "codex", "event_id": "codex-event"}

            import_external_telemetry(
                "octo/example",
                "77",
                source="generic-agent",
                fmt="agent-jsonl",
                raw="\n".join([json.dumps(failed_event), "{not-json}"]),
            )
            import_external_telemetry(
                "octo/example",
                "77",
                source="codex",
                fmt="agent-jsonl",
                raw=json.dumps(recovered_other_source),
            )
            report = build_efficiency_report("octo/example", "77")

            self.assertEqual(report["coverage_label"], "partial")
            self.assertTrue(any("invalid JSON" in diagnostic for diagnostic in report["diagnostics"]))

    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_import_external_telemetry_rejects_unsupported_format(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)

            result = import_external_telemetry("octo/example", "77", source="generic-agent", fmt="xml", raw="")
            report = build_efficiency_report("octo/example", "77")

            self.assertEqual(result["status"], "FAILED")
            self.assertEqual(result["reason_code"], "UNSUPPORTED_TELEMETRY_FORMAT")
            self.assertTrue(core_paths.telemetry_imports_file("octo/example", "77").exists())
            self.assertTrue(any("Unsupported telemetry format" in diagnostic for diagnostic in report["diagnostics"]))

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

            with patch.object(Path, "open", side_effect=OSError("denied")):
                tracker.configure_file(telemetry_file)

            self.assertEqual(tracker.metrics, [])

    def test_configure_file_does_not_append_partial_metrics_when_stream_read_fails_midway(self):
        class _BrokenTelemetryStream:
            def __init__(self, first_line: str):
                self._first_line = first_line
                self._yielded = False

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def __iter__(self):
                return self

            def __next__(self):
                if not self._yielded:
                    self._yielded = True
                    return self._first_line
                raise OSError("denied")

        with tempfile.TemporaryDirectory() as tmp:
            telemetry_file = Path(tmp) / "telemetry.jsonl"
            telemetry_file.write_text("{}", encoding="utf-8")
            tracker = SessionTelemetry.get_instance()
            valid_line = '{"command":"pytest","start_time":0.0,"end_time":1.0,"exit_code":0}\n'

            with patch.object(Path, "open", return_value=_BrokenTelemetryStream(valid_line)):
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

        from gh_address_cr.core.command_runner import run_cmd
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

        from gh_address_cr.core.command_runner import run_cmd
        run_cmd(["ls"])

        self.assertIsNone(mock_run.call_args.kwargs["timeout"])

    @patch("time.sleep")
    @patch("subprocess.run")
    def test_run_cmd_retries_transient_gh_failure(self, mock_run, mock_sleep):
        mock_run.side_effect = [
            subprocess.CompletedProcess(args=["gh", "api", "graphql"], returncode=1, stdout="", stderr="graphql failed"),
            subprocess.CompletedProcess(args=["gh", "api", "graphql"], returncode=0, stdout="{}", stderr=""),
        ]

        from gh_address_cr.core.command_runner import run_cmd
        res = run_cmd(["gh", "api", "graphql"], retries=2)

        self.assertEqual(res.returncode, 0)
        self.assertEqual(mock_run.call_count, 2)
        mock_sleep.assert_called_once_with(1)

    @patch("time.sleep")
    @patch("subprocess.run")
    def test_run_cmd_does_not_retry_non_transient_gh_failure(self, mock_run, mock_sleep):
        mock_run.return_value = subprocess.CompletedProcess(
            args=["gh", "api", "graphql"], returncode=1, stdout="", stderr="validation failed"
        )

        from gh_address_cr.core.command_runner import run_cmd
        res = run_cmd(["gh", "api", "graphql"], retries=3)

        self.assertEqual(res.returncode, 1)
        self.assertEqual(mock_run.call_count, 1)
        mock_sleep.assert_not_called()

    @patch("sys.stderr")
    @patch("gh_address_cr.core.telemetry.SessionTelemetry.record")
    @patch("subprocess.run")
    def test_run_cmd_fail_open(self, mock_run, mock_record, mock_stderr):
        mock_run.return_value = subprocess.CompletedProcess(args=["ls"], returncode=0, stdout="ok", stderr="")
        mock_record.side_effect = Exception("Telemetry DB error")
        
        from gh_address_cr.core.command_runner import run_cmd
        res = run_cmd(["ls"])
        self.assertEqual(res.returncode, 0)
        self.assertEqual(res.stdout, "ok")
        self.assertEqual(res.stderr, "")
        mock_stderr.write.assert_not_called()

    @patch("gh_address_cr.core.agent_protocol.submit_lease")
    @patch("gh_address_cr.core.agent_protocol.accept_lease")
    @patch("gh_address_cr.core.agent_protocol.apply_response_to_item")
    def test_accept_action_response_submission_records_validation_telemetry(self, mock_apply, mock_accept, mock_submit):
        import tempfile
        from pathlib import Path
        from unittest.mock import MagicMock

        from gh_address_cr.core.agent_protocol import _accept_action_response_submission

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

    @patch("gh_address_cr.core.agent_protocol.submit_lease")
    @patch("gh_address_cr.core.agent_protocol.accept_lease")
    @patch("gh_address_cr.core.agent_protocol.apply_response_to_item")
    def test_shared_batch_seen_deduplicates_validation_telemetry(self, mock_apply, mock_accept, mock_submit):
        import tempfile
        from pathlib import Path
        from unittest.mock import MagicMock

        from gh_address_cr.core.agent_protocol import _accept_action_response_submission

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

    @patch("gh_address_cr.core.agent_protocol.submit_lease")
    @patch("gh_address_cr.core.agent_protocol.accept_lease")
    def test_verifier_rejection_records_validation_telemetry(self, mock_accept, mock_submit):
        import tempfile
        from pathlib import Path
        from unittest.mock import MagicMock

        from gh_address_cr.core.agent_protocol import _accept_action_response_submission
        from gh_address_cr.core.errors import WorkflowError

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
        import tempfile
        from pathlib import Path

        from gh_address_cr.commands.high_level import _run_adapter_command

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
            self.assertEqual(mock_run.call_args.kwargs["timeout"], 300.0)
            
            self.assertEqual(len(tracker.metrics), 1)
            self.assertEqual(tracker.metrics[0].command, "my-adapter")
            self.assertEqual(tracker.metrics[0].exit_code, 0)
            self.assertNotIn("ghp_secret", tracker.metrics[0].command)

    def test_custom_telemetry_adapter_registration(self):
        from gh_address_cr.core.telemetry import (
            ExternalTelemetryEvent,
            TelemetryAdapter,
            TelemetryParseResult,
            register_adapter,
            unregister_adapter,
        )
        
        class MockCustomAdapter(TelemetryAdapter):
            def parse(self, raw: str, source: str) -> TelemetryParseResult:
                parts = raw.strip().split(":")
                if len(parts) != 4:
                    return TelemetryParseResult(
                        events=[],
                        rejected_count=1,
                        unsafe_seen=False,
                        malformed_seen=True,
                        diagnostics=["malformed mock payload"],
                    )
                session_id, event_id, operation, duration_str = parts
                event = ExternalTelemetryEvent(
                    schema_version="1.0",
                    source=source,
                    source_session_id=session_id,
                    event_id=event_id,
                    kind="tool_call",
                    operation=operation,
                    status="success",
                    duration_ms=int(duration_str),
                )
                return TelemetryParseResult(
                    events=[event],
                    rejected_count=0,
                    unsafe_seen=False,
                    malformed_seen=False,
                    diagnostics=[],
                )

        register_adapter("mock-custom", MockCustomAdapter())
        self.addCleanup(lambda: unregister_adapter("mock-custom"))
        
        with tempfile.TemporaryDirectory() as tmp:
            with patch("gh_address_cr.core.telemetry.core_paths.state_dir", return_value=Path(tmp)):
                raw_payload = "session-abc:event-123:custom_op:4500"
                result = import_external_telemetry(
                    "octo/example",
                    "77",
                    source="custom-source",
                    fmt="mock-custom",
                    raw=raw_payload,
                )
                self.assertEqual(result["status"], "SUCCESS")
                self.assertEqual(result["accepted_count"], 1)
                
                report = build_efficiency_report("octo/example", "77")
                self.assertEqual(report["total_events"], 1)
                self.assertEqual(report["total_observed_duration_ms"], 4500)
                self.assertEqual(report["slowest_operations"][0]["operation"], "custom_op")

    def test_custom_telemetry_adapter_registration_duplicate_fails(self):
        from gh_address_cr.core.telemetry import (
            TelemetryAdapter,
            TelemetryParseResult,
            register_adapter,
            unregister_adapter,
        )
        
        class MockCustomAdapter(TelemetryAdapter):
            def parse(self, raw: str, source: str) -> TelemetryParseResult:
                return TelemetryParseResult([], 0, False, False, [])

        register_adapter("mock-dup", MockCustomAdapter())
        self.addCleanup(lambda: unregister_adapter("mock-dup"))

        with self.assertRaises(ValueError) as context:
            register_adapter("mock-dup", MockCustomAdapter())
        self.assertIn("already registered", str(context.exception))

        # Check that registering the same format with a specific source also raises error on duplicate
        register_adapter("mock-dup", MockCustomAdapter(), source="special-src")
        self.addCleanup(lambda: unregister_adapter("mock-dup", source="special-src"))

        with self.assertRaises(ValueError) as context_src:
            register_adapter("mock-dup", MockCustomAdapter(), source="special-src")
        self.assertIn("already registered", str(context_src.exception))

    def test_custom_telemetry_adapter_source_override(self):
        from gh_address_cr.core.telemetry import (
            ExternalTelemetryEvent,
            TelemetryAdapter,
            TelemetryParseResult,
            register_adapter,
            unregister_adapter,
        )

        class DefaultMockAdapter(TelemetryAdapter):
            def parse(self, raw: str, source: str) -> TelemetryParseResult:
                event = ExternalTelemetryEvent(
                    schema_version="1.0",
                    source=source,
                    source_session_id="session-1",
                    event_id="event-1",
                    kind="tool_call",
                    operation="op-default",
                    status="success",
                    duration_ms=1000,
                )
                return TelemetryParseResult([event], 0, False, False, [])

        class SpecialMockAdapter(TelemetryAdapter):
            def parse(self, raw: str, source: str) -> TelemetryParseResult:
                event = ExternalTelemetryEvent(
                    schema_version="1.0",
                    source=source,
                    source_session_id="session-1",
                    event_id="event-1",
                    kind="tool_call",
                    operation="op-override",
                    status="success",
                    duration_ms=2000,
                )
                return TelemetryParseResult([event], 0, False, False, [])

        # Register format default adapter
        register_adapter("multi-source", DefaultMockAdapter())
        self.addCleanup(lambda: unregister_adapter("multi-source"))

        # Register source-specific override adapter
        register_adapter("multi-source", SpecialMockAdapter(), source="special-host")
        self.addCleanup(lambda: unregister_adapter("multi-source", source="special-host"))

        # 1. Verification with default fallback
        with tempfile.TemporaryDirectory() as tmp:
            with patch("gh_address_cr.core.telemetry.core_paths.state_dir", return_value=Path(tmp)):
                result_default = import_external_telemetry(
                    "octo/example",
                    "77",
                    source="ordinary-host",
                    fmt="multi-source",
                    raw="dummy",
                )
                self.assertEqual(result_default["status"], "SUCCESS")
                report_default = build_efficiency_report("octo/example", "77")
                self.assertEqual(report_default["slowest_operations"][0]["operation"], "op-default")

        # 2. Verification with source override priority
        with tempfile.TemporaryDirectory() as tmp:
            with patch("gh_address_cr.core.telemetry.core_paths.state_dir", return_value=Path(tmp)):
                result_override = import_external_telemetry(
                    "octo/example",
                    "77",
                    source="special-host",
                    fmt="multi-source",
                    raw="dummy",
                )
                self.assertEqual(result_override["status"], "SUCCESS")
                report_override = build_efficiency_report("octo/example", "77")
                self.assertEqual(report_override["slowest_operations"][0]["operation"], "op-override")

    def test_custom_telemetry_adapter_unsafe_normalization_rejection(self):
        from gh_address_cr.core.telemetry import (
            ExternalTelemetryEvent,
            TelemetryAdapter,
            TelemetryParseResult,
            register_adapter,
            unregister_adapter,
        )
        
        class MockUnsafeAdapter(TelemetryAdapter):
            def parse(self, raw: str, source: str) -> TelemetryParseResult:
                # Return an event containing unsafe metadata keys (e.g. password)
                event = ExternalTelemetryEvent(
                    schema_version="1.0",
                    source=source,
                    source_session_id="session-abc",
                    event_id="event-unsafe",
                    kind="tool_call",
                    operation="op",
                    status="success",
                    duration_ms=100,
                    metadata={"password": "should_be_rejected"}
                )
                return TelemetryParseResult(
                    events=[event],
                    rejected_count=0,
                    unsafe_seen=False,
                    malformed_seen=False,
                    diagnostics=[],
                )

        register_adapter("mock-unsafe", MockUnsafeAdapter())
        self.addCleanup(lambda: unregister_adapter("mock-unsafe"))

        with tempfile.TemporaryDirectory() as tmp:
            with patch("gh_address_cr.core.telemetry.core_paths.state_dir", return_value=Path(tmp)):
                result = import_external_telemetry(
                    "octo/example",
                    "77",
                    source="custom-source",
                    fmt="mock-unsafe",
                    raw="dummy_payload",
                )
                self.assertEqual(result["status"], "FAILED")
                self.assertEqual(result["reason_code"], "UNSAFE_TELEMETRY_CONTENT")
                self.assertEqual(result["accepted_count"], 0)
                self.assertEqual(result["rejected_count"], 1)
                self.assertTrue(any("unsafe key" in diag or "password" in diag for diag in result["diagnostics"]))

    def test_custom_telemetry_adapter_normalized_flag_still_revalidates_events(self):
        from gh_address_cr.core.telemetry import (
            ExternalTelemetryEvent,
            TelemetryAdapter,
            TelemetryParseResult,
            register_adapter,
            unregister_adapter,
        )

        class MockUnsafeNormalizedAdapter(TelemetryAdapter):
            def parse(self, raw: str, source: str) -> TelemetryParseResult:
                event = ExternalTelemetryEvent(
                    schema_version="1.0",
                    source=source,
                    source_session_id="session-abc",
                    event_id="event-unsafe-normalized",
                    kind="tool_call",
                    operation="username-alice-laptop",
                    status="success",
                    duration_ms=100,
                )
                return TelemetryParseResult(
                    events=[event],
                    rejected_count=0,
                    unsafe_seen=False,
                    malformed_seen=False,
                    diagnostics=[],
                    events_are_normalized=True,
                )

        register_adapter("mock-unsafe-normalized", MockUnsafeNormalizedAdapter())
        self.addCleanup(lambda: unregister_adapter("mock-unsafe-normalized"))

        with tempfile.TemporaryDirectory() as tmp:
            with patch("gh_address_cr.core.telemetry.core_paths.state_dir", return_value=Path(tmp)):
                result = import_external_telemetry(
                    "octo/example",
                    "77",
                    source="custom-source",
                    fmt="mock-unsafe-normalized",
                    raw="dummy_payload",
                )

                self.assertEqual(result["status"], "FAILED")
                self.assertEqual(result["reason_code"], "UNSAFE_TELEMETRY_CONTENT")
                self.assertEqual(result["accepted_count"], 0)
                self.assertEqual(result["rejected_count"], 1)
                self.assertTrue(any("unsafe private identifier in operation label" in diag for diag in result["diagnostics"]))

    def test_custom_telemetry_adapter_non_json_metadata_rejection(self):
        from gh_address_cr.core.telemetry import (
            ExternalTelemetryEvent,
            TelemetryAdapter,
            TelemetryParseResult,
            register_adapter,
            unregister_adapter,
        )
        
        class MockNonJsonMetadataAdapter(TelemetryAdapter):
            def parse(self, raw: str, source: str) -> TelemetryParseResult:
                # Return metadata with a non-serializable datetime object
                event = ExternalTelemetryEvent(
                    schema_version="1.0",
                    source=source,
                    source_session_id="session-abc",
                    event_id="event-non-json",
                    kind="tool_call",
                    operation="op",
                    status="success",
                    duration_ms=100,
                    metadata={"created_at": datetime.now()}
                )
                return TelemetryParseResult(
                    events=[event],
                    rejected_count=0,
                    unsafe_seen=False,
                    malformed_seen=False,
                    diagnostics=[],
                )

        register_adapter("mock-non-json", MockNonJsonMetadataAdapter())
        self.addCleanup(lambda: unregister_adapter("mock-non-json"))

        with tempfile.TemporaryDirectory() as tmp:
            with patch("gh_address_cr.core.telemetry.core_paths.state_dir", return_value=Path(tmp)):
                result = import_external_telemetry(
                    "octo/example",
                    "77",
                    source="custom-source",
                    fmt="mock-non-json",
                    raw="dummy_payload",
                )
                self.assertEqual(result["status"], "FAILED")
                self.assertEqual(result["reason_code"], "MALFORMED_TELEMETRY")
                self.assertEqual(result["accepted_count"], 0)
                self.assertEqual(result["rejected_count"], 1)
                self.assertTrue(any("non-JSON serializable" in diag for diag in result["diagnostics"]))

    def test_custom_telemetry_adapter_parsing_exception_handling(self):
        from gh_address_cr.core.telemetry import (
            TelemetryAdapter,
            TelemetryParseResult,
            register_adapter,
            unregister_adapter,
        )
        
        class MockCrashedAdapter(TelemetryAdapter):
            def parse(self, raw: str, source: str) -> TelemetryParseResult:
                # Raise ValueError simulating a parsing crash
                raise ValueError("Int conversion failed on dummy payload")

        register_adapter("mock-crash", MockCrashedAdapter())
        self.addCleanup(lambda: unregister_adapter("mock-crash"))

        with tempfile.TemporaryDirectory() as tmp:
            with patch("gh_address_cr.core.telemetry.core_paths.state_dir", return_value=Path(tmp)):
                result = import_external_telemetry(
                    "octo/example",
                    "77",
                    source="custom-source",
                    fmt="mock-crash",
                    raw="dummy_payload",
                )
                self.assertEqual(result["status"], "FAILED")
                self.assertEqual(result["reason_code"], "MALFORMED_TELEMETRY")
                self.assertEqual(result["accepted_count"], 0)
                # Confirm we only expose the exception type name and NOT the raw exception message for safety
                self.assertTrue(any(diag == "Adapter parsing failed: ValueError" for diag in result["diagnostics"]))

    def test_custom_telemetry_adapter_unexpected_exception_fails_loud(self):
        from gh_address_cr.core.telemetry import (
            TelemetryAdapter,
            TelemetryParseResult,
            register_adapter,
            unregister_adapter,
        )

        class MockCrashedAdapter(TelemetryAdapter):
            def parse(self, raw: str, source: str) -> TelemetryParseResult:
                raise RuntimeError("unexpected adapter bug")

        register_adapter("mock-unexpected-crash", MockCrashedAdapter())
        self.addCleanup(lambda: unregister_adapter("mock-unexpected-crash"))

        with tempfile.TemporaryDirectory() as tmp:
            with patch("gh_address_cr.core.telemetry.core_paths.state_dir", return_value=Path(tmp)):
                with self.assertRaisesRegex(RuntimeError, "unexpected adapter bug"):
                    import_external_telemetry(
                        "octo/example",
                        "77",
                        source="custom-source",
                        fmt="mock-unexpected-crash",
                        raw="dummy_payload",
                    )

    def test_custom_telemetry_adapter_nan_metadata_rejection(self):
        from gh_address_cr.core.telemetry import (
            ExternalTelemetryEvent,
            TelemetryAdapter,
            TelemetryParseResult,
            register_adapter,
            unregister_adapter,
        )
        
        class MockNaNMetadataAdapter(TelemetryAdapter):
            def parse(self, raw: str, source: str) -> TelemetryParseResult:
                # Return metadata with a NaN float constant
                event = ExternalTelemetryEvent(
                    schema_version="1.0",
                    source=source,
                    source_session_id="session-abc",
                    event_id="event-nan",
                    kind="tool_call",
                    operation="op",
                    status="success",
                    duration_ms=100,
                    metadata={"ratio": float("nan")}
                )
                return TelemetryParseResult(
                    events=[event],
                    rejected_count=0,
                    unsafe_seen=False,
                    malformed_seen=False,
                    diagnostics=[],
                )

        register_adapter("mock-nan", MockNaNMetadataAdapter())
        self.addCleanup(lambda: unregister_adapter("mock-nan"))

        with tempfile.TemporaryDirectory() as tmp:
            with patch("gh_address_cr.core.telemetry.core_paths.state_dir", return_value=Path(tmp)):
                result = import_external_telemetry(
                    "octo/example",
                    "77",
                    source="custom-source",
                    fmt="mock-nan",
                    raw="dummy_payload",
                )
                self.assertEqual(result["status"], "FAILED")
                self.assertEqual(result["reason_code"], "MALFORMED_TELEMETRY")
                self.assertEqual(result["accepted_count"], 0)
                self.assertEqual(result["rejected_count"], 1)
                self.assertTrue(any("non-finite" in diag for diag in result["diagnostics"]))

    def test_custom_telemetry_adapter_non_json_diagnostics_coercion(self):
        from gh_address_cr.core.telemetry import (
            ExternalTelemetryEvent,
            TelemetryAdapter,
            TelemetryParseResult,
            register_adapter,
            unregister_adapter,
        )
        
        class MockNonJsonDiagnosticsAdapter(TelemetryAdapter):
            def parse(self, raw: str, source: str) -> TelemetryParseResult:
                event = ExternalTelemetryEvent(
                    schema_version="1.0",
                    source=source,
                    source_session_id="session-abc",
                    event_id="event-diag-coerce",
                    kind="tool_call",
                    operation="op",
                    status="success",
                    duration_ms=100,
                )
                # Return a diagnostic item that is an Exception instance rather than a string
                return TelemetryParseResult(
                    events=[event],
                    rejected_count=0,
                    unsafe_seen=False,
                    malformed_seen=False,
                    diagnostics=[ValueError("Non-JSON error object")],
                )

        register_adapter("mock-diag-coerce", MockNonJsonDiagnosticsAdapter())
        self.addCleanup(lambda: unregister_adapter("mock-diag-coerce"))

        with tempfile.TemporaryDirectory() as tmp:
            with patch("gh_address_cr.core.telemetry.core_paths.state_dir", return_value=Path(tmp)):
                result = import_external_telemetry(
                    "octo/example",
                    "77",
                    source="custom-source",
                    fmt="mock-diag-coerce",
                    raw="dummy_payload",
                )
                self.assertEqual(result["status"], "SUCCESS")
                self.assertEqual(result["accepted_count"], 1)
                # Ensure the ValueError diagnostic element was converted to a string and did not crash json.dumps
                self.assertIn("Non-JSON error object", result["diagnostics"])

    def test_custom_telemetry_adapter_invalid_return_type_rejection(self):
        from gh_address_cr.core.telemetry import (
            TelemetryAdapter,
            register_adapter,
            unregister_adapter,
        )

        class MockInvalidReturnAdapter(TelemetryAdapter):
            def parse(self, raw: str, source: str):
                # Invalid: returns None instead of a TelemetryParseResult instance
                return None

        register_adapter("mock-invalid-ret", MockInvalidReturnAdapter())
        self.addCleanup(lambda: unregister_adapter("mock-invalid-ret"))

        with tempfile.TemporaryDirectory() as tmp:
            with patch("gh_address_cr.core.telemetry.core_paths.state_dir", return_value=Path(tmp)):
                result = import_external_telemetry(
                    "octo/example",
                    "77",
                    source="custom-source",
                    fmt="mock-invalid-ret",
                    raw="dummy_payload",
                )
                self.assertEqual(result["status"], "FAILED")
                self.assertEqual(result["reason_code"], "MALFORMED_TELEMETRY")
                self.assertEqual(result["accepted_count"], 0)
                self.assertTrue(any("Adapter parsing failed: TypeError" in diag for diag in result["diagnostics"]))

    def test_custom_telemetry_adapter_diagnostics_sanitization(self):
        from gh_address_cr.core.telemetry import (
            TelemetryAdapter,
            TelemetryParseResult,
            register_adapter,
            unregister_adapter,
        )

        class MockSensitiveDiagnosticsAdapter(TelemetryAdapter):
            def parse(self, raw: str, source: str):
                return TelemetryParseResult(
                    events=[],
                    rejected_count=0,
                    unsafe_seen=False,
                    malformed_seen=False,
                    diagnostics=[
                        "Safe diagnostic message",
                        "Rejected secret token: github_token=123",
                        "Path failure: /Users/alice/private/key.pem",
                        "User info: username=bob",
                    ]
                )

        register_adapter("mock-sensitive-diag", MockSensitiveDiagnosticsAdapter())
        self.addCleanup(lambda: unregister_adapter("mock-sensitive-diag"))

        with tempfile.TemporaryDirectory() as tmp:
            with patch("gh_address_cr.core.telemetry.core_paths.state_dir", return_value=Path(tmp)):
                result = import_external_telemetry(
                    "octo/example",
                    "77",
                    source="custom-source",
                    fmt="mock-sensitive-diag",
                    raw="dummy_payload",
                )
                self.assertIn("Safe diagnostic message", result["diagnostics"])
                redacted_count = sum(1 for diag in result["diagnostics"] if diag == "[redacted]")
                self.assertEqual(redacted_count, 3)

    def test_custom_telemetry_adapter_invalid_diagnostics_container_rejection(self):
        from gh_address_cr.core.telemetry import (
            ExternalTelemetryEvent,
            TelemetryAdapter,
            TelemetryParseResult,
            register_adapter,
            unregister_adapter,
        )

        class MockInvalidDiagnosticsAdapter(TelemetryAdapter):
            def parse(self, raw: str, source: str):
                event = ExternalTelemetryEvent(
                    schema_version="1.0",
                    source=source,
                    source_session_id="session-abc",
                    event_id="event-invalid-diagnostics",
                    kind="tool_call",
                    operation="op",
                    status="success",
                    duration_ms=100,
                )
                return TelemetryParseResult(
                    events=[event],
                    rejected_count=0,
                    unsafe_seen=False,
                    malformed_seen=False,
                    diagnostics=None,
                )

        register_adapter("mock-invalid-diag-container", MockInvalidDiagnosticsAdapter())
        self.addCleanup(lambda: unregister_adapter("mock-invalid-diag-container"))

        with tempfile.TemporaryDirectory() as tmp:
            with patch("gh_address_cr.core.telemetry.core_paths.state_dir", return_value=Path(tmp)):
                result = import_external_telemetry(
                    "octo/example",
                    "77",
                    source="custom-source",
                    fmt="mock-invalid-diag-container",
                    raw="dummy_payload",
                )
                self.assertEqual(result["status"], "FAILED")
                self.assertEqual(result["reason_code"], "MALFORMED_TELEMETRY")
                self.assertEqual(result["accepted_count"], 0)
                self.assertTrue(
                    any("Adapter diagnostics processing failed: TypeError" in diag for diag in result["diagnostics"])
                )

    def test_import_external_telemetry_event_id_redaction_in_normalization_diagnostics(self):
        from gh_address_cr.core.telemetry import (
            ExternalTelemetryEvent,
            TelemetryAdapter,
            TelemetryParseResult,
            register_adapter,
            unregister_adapter,
        )

        class MockUnsafeEventIdAdapter(TelemetryAdapter):
            def parse(self, raw: str, source: str):
                return TelemetryParseResult(
                    events=[
                        ExternalTelemetryEvent(
                            schema_version="1.0",
                            source="custom-source",
                            source_session_id="run-1",
                            event_id="ghp_unsafe_event_id",
                            kind="tool_call",
                            operation="safe operation",
                            duration_ms=10,
                            status="success",
                        )
                    ],
                    rejected_count=0,
                    unsafe_seen=False,
                    malformed_seen=False,
                    diagnostics=[]
                )

        register_adapter("mock-unsafe-event-id", MockUnsafeEventIdAdapter())
        self.addCleanup(lambda: unregister_adapter("mock-unsafe-event-id"))

        with tempfile.TemporaryDirectory() as tmp:
            with patch("gh_address_cr.core.telemetry.core_paths.state_dir", return_value=Path(tmp)):
                result = import_external_telemetry(
                    "octo/example",
                    "77",
                    source="custom-source",
                    fmt="mock-unsafe-event-id",
                    raw="dummy_payload",
                )
                self.assertEqual(result["status"], "FAILED")
                self.assertEqual(result["reason_code"], "UNSAFE_TELEMETRY_CONTENT")
                self.assertEqual(result["rejected_count"], 1)
                
                self.assertFalse(any("ghp_unsafe_event_id" in diag for diag in result["diagnostics"]))
                self.assertTrue(any("event index 0" in diag for diag in result["diagnostics"]))

    def test_custom_telemetry_adapter_invalid_event_type_rejection(self):
        from gh_address_cr.core.telemetry import (
            TelemetryAdapter,
            TelemetryParseResult,
            register_adapter,
            unregister_adapter,
        )

        class MockInvalidEventAdapter(TelemetryAdapter):
            def parse(self, raw: str, source: str):
                return TelemetryParseResult(
                    events=[{"kind": "tool_call", "operation": "safe", "status": "success"}],
                    rejected_count=0,
                    unsafe_seen=False,
                    malformed_seen=False,
                    diagnostics=[]
                )

        register_adapter("mock-invalid-event", MockInvalidEventAdapter())
        self.addCleanup(lambda: unregister_adapter("mock-invalid-event"))

        with tempfile.TemporaryDirectory() as tmp:
            with patch("gh_address_cr.core.telemetry.core_paths.state_dir", return_value=Path(tmp)):
                result = import_external_telemetry(
                    "octo/example",
                    "77",
                    source="custom-source",
                    fmt="mock-invalid-event",
                    raw="dummy_payload",
                )
                self.assertEqual(result["status"], "FAILED")
                self.assertEqual(result["reason_code"], "MALFORMED_TELEMETRY")
                self.assertTrue(any("Adapter event processing failed: TypeError" in diag for diag in result["diagnostics"]))

    def test_import_external_telemetry_rejects_unsafe_metadata_keys(self):
        from gh_address_cr.core.telemetry import (
            ExternalTelemetryEvent,
            TelemetryAdapter,
            TelemetryParseResult,
            register_adapter,
            unregister_adapter,
        )

        class MockUnsafeMetadataKeyAdapter(TelemetryAdapter):
            def parse(self, raw: str, source: str):
                return TelemetryParseResult(
                    events=[
                        ExternalTelemetryEvent(
                            schema_version="1.0",
                            source="custom-source",
                            source_session_id="run-1",
                            event_id="evt-1",
                            kind="tool_call",
                            operation="safe operation",
                            duration_ms=10,
                            status="success",
                            metadata={"ghp_unsafe_token_as_key": "some_value"},
                        )
                    ],
                    rejected_count=0,
                    unsafe_seen=False,
                    malformed_seen=False,
                    diagnostics=[]
                )

        register_adapter("mock-unsafe-meta-key", MockUnsafeMetadataKeyAdapter())
        self.addCleanup(lambda: unregister_adapter("mock-unsafe-meta-key"))

        with tempfile.TemporaryDirectory() as tmp:
            with patch("gh_address_cr.core.telemetry.core_paths.state_dir", return_value=Path(tmp)):
                result = import_external_telemetry(
                    "octo/example",
                    "77",
                    source="custom-source",
                    fmt="mock-unsafe-meta-key",
                    raw="dummy_payload",
                )
                self.assertEqual(result["status"], "FAILED")
                self.assertEqual(result["reason_code"], "UNSAFE_TELEMETRY_CONTENT")
                self.assertEqual(result["rejected_count"], 1)
                self.assertFalse(any("ghp_unsafe_token_as_key" in diag for diag in result["diagnostics"]))
                self.assertTrue(any("[redacted]" in diag for diag in result["diagnostics"]))

    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_report_marks_timing_unavailable_when_all_durations_zero(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            tracker = SessionTelemetry.get_instance()
            tracker.configure_context("octo/example", "77")
            # start == end => duration 0 (the validation-backfill fallback case)
            tracker.record("ruff check", 100.0, 100.0, 0)
            tracker.record("python3 -m unittest discover -s tests", 100.0, 100.0, 0)

            report = build_efficiency_report("octo/example", "77")

            self.assertEqual(report["total_events"], 2)
            self.assertFalse(report["duration_observed"])
            self.assertEqual(report["total_observed_duration_ms"], 0)
            self.assertEqual(report["slowest_operations"], [])
            self.assertIn("TELEMETRY_TIMING_UNAVAILABLE", report["diagnostics"])

    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_report_keeps_timing_when_durations_present(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            tracker = SessionTelemetry.get_instance()
            tracker.configure_context("octo/example", "77")
            tracker.record("python3 -m unittest discover -s tests", 100.0, 102.0, 0)  # 2000ms

            report = build_efficiency_report("octo/example", "77")

            self.assertTrue(report["duration_observed"])
            self.assertEqual(report["total_observed_duration_ms"], 2000)
            self.assertEqual(len(report["slowest_operations"]), 1)
            self.assertEqual(report["slowest_operations"][0]["duration_ms"], 2000)
            self.assertNotIn("TELEMETRY_TIMING_UNAVAILABLE", report["diagnostics"])

    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_markdown_omits_slowest_and_notes_when_timing_unavailable(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            tracker = SessionTelemetry.get_instance()
            tracker.configure_context("octo/example", "77")
            tracker.record("ruff check", 100.0, 100.0, 0)

            report = build_efficiency_report("octo/example", "77")
            markdown = efficiency_report_markdown(report)

            self.assertNotIn("### Slowest Operations", markdown)
            self.assertIn("operation timing was not reported", markdown)

    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_timed_validation_shorthand_yields_nonzero_report_duration(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            tracker = SessionTelemetry.get_instance()
            tracker.configure_context("octo/example", "77")

            # The skill reports a validation command with measured timing.
            _record_validation_command_telemetry({}, ["ruff check=passed@1500ms"])

            report = build_efficiency_report("octo/example", "77")

            self.assertEqual(report["total_events"], 1)
            self.assertTrue(report["duration_observed"])
            self.assertGreaterEqual(report["total_observed_duration_ms"], 1400)
            self.assertLessEqual(report["total_observed_duration_ms"], 1600)
            self.assertEqual(len(report["slowest_operations"]), 1)
            self.assertNotIn("TELEMETRY_TIMING_UNAVAILABLE", report["diagnostics"])

if __name__ == "__main__":
    unittest.main()
