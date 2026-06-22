import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from gh_address_cr.core import paths as core_paths
from gh_address_cr.core.host_telemetry.attribution import distinct_sessions_in_window, lines_in_window
from gh_address_cr.core.host_telemetry.capture import capture_agent_jsonl
from gh_address_cr.core.host_telemetry.discovery import (
    consent_notice_once,
    discover_transcript,
    first_env_value,
    project_slug_from_cwd,
)
from gh_address_cr.core.host_telemetry.profile import HostProfile, load_profile
from gh_address_cr.core.host_telemetry.strategies import paired_correlation_timestamp, record_pair_timestamp
from gh_address_cr.core.telemetry import SessionTelemetry, build_efficiency_report


class HostProfileTests(unittest.TestCase):
    def _write(self, tmp, payload):
        path = Path(tmp) / "p.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_load_minimal_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, {
                "profile_version": "1.0",
                "source": "claude-code",
                "strategy": "paired-correlation-timestamp",
                "discovery": {"glob": "~/.claude/projects/{project_slug}/*.jsonl", "project_slug_from": "cwd"},
                "record": {"container": "jsonl-lines", "session_id_path": "sessionId"},
                "fields": {"timestamp_path": "timestamp"},
                "kind_classification": {"default": "tool_call", "wait": ["AskUserQuestion"]},
                "safety_allowlist": ["operation", "status", "timestamp"],
                "scope_attribution": {"mode": "active-pr-time-window"},
            })
            profile = load_profile(path)
            self.assertEqual(profile.source, "claude-code")
            self.assertEqual(profile.strategy, "paired-correlation-timestamp")
            self.assertEqual(profile.kind_for("AskUserQuestion"), "wait")
            self.assertEqual(profile.kind_for("Bash"), "tool_call")

    def test_load_rejects_missing_required_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, {"source": "x"})
            with self.assertRaises(ValueError):
                load_profile(path)


def _cc_profile():
    return HostProfile(
        source="claude-code",
        strategy="paired-correlation-timestamp",
        discovery={},
        record={"container": "jsonl-lines", "session_id_path": "sessionId"},
        fields={
            "event_blocks_path": "message.content[]",
            "tool_use": {"match": {"type": "tool_use"}, "id_path": "id", "operation_path": "name"},
            "tool_result": {"match": {"type": "tool_result"}, "correlation_path": "tool_use_id",
                            "status_path": "is_error", "status_map": {"true": "failure", "false": "success"}},
            "timestamp_path": "timestamp",
        },
        kind_classification={"default": "tool_call", "wait": ["AskUserQuestion"], "by_operation": {"Bash": "command"}},
        safety_allowlist=("operation", "status", "timestamp", "correlation_id"),
    )


def _codex_profile():
    return HostProfile(
        source="codex",
        strategy="record-pair-timestamp",
        discovery={
            "glob": "~/.codex/sessions/*/*/*/rollout-*{session_id}.jsonl",
            "session_id_env": ["CODEX_THREAD_ID"],
        },
        record={"container": "jsonl-lines", "session_id_path": "payload.id"},
        fields={
            "timestamp_path": "timestamp",
            "record_type_path": "type",
            "event_type_path": "payload.type",
            "correlation_id_path": "payload.call_id",
            "session_record_match": {"type": "session_meta"},
            "event_record_match": {"type": "response_item"},
            "start_match": {"payload.type": "function_call"},
            "end_match": {"payload.type": "function_call_output"},
            "operation_path": "payload.name",
        },
        kind_classification={
            "default": "tool_call",
            "by_operation": {"exec_command": "command", "write_stdin": "command", "apply_patch": "command"},
        },
        safety_allowlist=("operation", "status", "timestamp", "correlation_id"),
    )


class PairedStrategyTests(unittest.TestCase):
    def _lines(self):
        return [
            {"sessionId": "s1", "timestamp": "2026-06-21T10:00:00Z",
             "message": {"content": [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "secret"}}]}},
            {"sessionId": "s1", "timestamp": "2026-06-21T10:00:02Z",
             "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "is_error": False, "content": "SECRET OUTPUT"}]}},
            {"sessionId": "s1", "timestamp": "2026-06-21T10:00:05Z",
             "message": {"content": [{"type": "tool_use", "id": "t2", "name": "AskUserQuestion", "input": {}}]}},
            {"sessionId": "s1", "timestamp": "2026-06-21T10:00:35Z",
             "message": {"content": [{"type": "tool_result", "tool_use_id": "t2", "is_error": True}]}},
        ]

    def test_pairs_and_derives_duration(self):
        events, stats = paired_correlation_timestamp(self._lines(), _cc_profile(), session_id="s1")
        by_op = {e["operation"]: e for e in events}
        self.assertEqual(by_op["Bash"]["duration_ms"], 2000)
        self.assertEqual(by_op["Bash"]["status"], "success")
        self.assertEqual(by_op["Bash"]["kind"], "command")
        self.assertEqual(by_op["AskUserQuestion"]["duration_ms"], 30000)
        self.assertEqual(by_op["AskUserQuestion"]["status"], "failure")
        self.assertEqual(by_op["AskUserQuestion"]["kind"], "wait")
        self.assertEqual(stats["tool_use_seen"], 2)
        self.assertEqual(stats["paired"], 2)

    def test_never_emits_input_or_content(self):
        events, _ = paired_correlation_timestamp(self._lines(), _cc_profile(), session_id="s1")
        blob = json.dumps(events)
        self.assertNotIn("secret", blob)
        self.assertNotIn("SECRET OUTPUT", blob)
        for e in events:
            self.assertNotIn("input", e)
            self.assertNotIn("content", e)

    def test_filters_other_sessions(self):
        lines = self._lines() + [
            {"sessionId": "other", "timestamp": "2026-06-21T10:00:00Z",
             "message": {"content": [{"type": "tool_use", "id": "x", "name": "Bash"}]}},
        ]
        events, stats = paired_correlation_timestamp(lines, _cc_profile(), session_id="s1")
        self.assertEqual(stats["tool_use_seen"], 2)

    def test_unpaired_tool_use_has_zero_duration(self):
        # Regression: unpaired tool_use must still carry duration_ms (0) so
        # import_external_telemetry does not reject the event for a missing field.
        lines = [
            {"sessionId": "s1", "timestamp": "2026-06-21T10:00:00Z",
             "message": {"content": [{"type": "tool_use", "id": "u1", "name": "Bash"}]}},
        ]
        events, stats = paired_correlation_timestamp(lines, _cc_profile(), session_id="s1")
        self.assertEqual(events[0]["duration_ms"], 0)
        self.assertEqual(events[0]["status"], "unknown")
        self.assertEqual(stats["paired"], 0)

    def test_missing_is_error_is_unknown_not_success(self):
        # Regression: a tool_result lacking is_error must not be counted as success.
        lines = [
            {"sessionId": "s1", "timestamp": "2026-06-21T10:00:00Z",
             "message": {"content": [{"type": "tool_use", "id": "u1", "name": "Bash"}]}},
            {"sessionId": "s1", "timestamp": "2026-06-21T10:00:01Z",
             "message": {"content": [{"type": "tool_result", "tool_use_id": "u1"}]}},
        ]
        events, _ = paired_correlation_timestamp(lines, _cc_profile(), session_id="s1")
        self.assertEqual(events[0]["status"], "unknown")

    def test_honors_custom_event_blocks_path(self):
        # A profile pointing event_blocks_path elsewhere must be honored, not
        # ignored in favor of the hard-coded message.content[] shape.
        profile = _cc_profile()
        profile.fields["event_blocks_path"] = "event.blocks[]"
        lines = [
            {"sessionId": "s1", "timestamp": "2026-06-21T10:00:00Z",
             "event": {"blocks": [{"type": "tool_use", "id": "t1", "name": "Bash"}]}},
            {"sessionId": "s1", "timestamp": "2026-06-21T10:00:02Z",
             "event": {"blocks": [{"type": "tool_result", "tool_use_id": "t1", "is_error": False}]}},
        ]
        events, stats = paired_correlation_timestamp(lines, profile, session_id="s1")
        self.assertEqual(stats["paired"], 1)
        self.assertEqual(events[0]["duration_ms"], 2000)

    def test_blocks_path_shape_mismatch_fails_open(self):
        # Wrong shape for the configured path yields no blocks instead of raising.
        profile = _cc_profile()
        profile.fields["event_blocks_path"] = "event.blocks[]"
        lines = [
            {"sessionId": "s1", "timestamp": "2026-06-21T10:00:00Z",
             "message": {"content": [{"type": "tool_use", "id": "t1", "name": "Bash"}]}},
        ]
        events, stats = paired_correlation_timestamp(lines, profile, session_id="s1")
        self.assertEqual(stats["tool_use_seen"], 0)
        self.assertEqual(events, [])


class RecordPairStrategyTests(unittest.TestCase):
    def _lines(self):
        return [
            {"timestamp": "2026-06-21T10:00:00Z", "type": "session_meta",
             "payload": {"id": "codex-s1", "cwd": "/repo"}},
            {"timestamp": "2026-06-21T10:00:01Z", "type": "response_item",
             "payload": {"type": "function_call", "name": "exec_command", "call_id": "call-1",
                         "arguments": "SECRET ARGUMENTS"}},
            {"timestamp": "2026-06-21T10:00:04Z", "type": "response_item",
             "payload": {"type": "function_call_output", "call_id": "call-1", "output": "SECRET OUTPUT"}},
        ]

    def test_pairs_function_call_records(self):
        events, stats = record_pair_timestamp(self._lines(), _codex_profile(), session_id="codex-s1")

        self.assertEqual(stats["call_started"], 1)
        self.assertEqual(stats["paired"], 1)
        self.assertEqual(events[0]["source"], "codex")
        self.assertEqual(events[0]["operation"], "exec_command")
        self.assertEqual(events[0]["kind"], "command")
        self.assertEqual(events[0]["duration_ms"], 3000)
        self.assertEqual(events[0]["status"], "unknown")

    def test_never_emits_arguments_or_output(self):
        events, _ = record_pair_timestamp(self._lines(), _codex_profile(), session_id="codex-s1")
        blob = json.dumps(events)

        self.assertNotIn("SECRET ARGUMENTS", blob)
        self.assertNotIn("SECRET OUTPUT", blob)
        for event in events:
            self.assertNotIn("arguments", event)
            self.assertNotIn("output", event)

    def test_rejects_other_session_meta(self):
        events, stats = record_pair_timestamp(self._lines(), _codex_profile(), session_id="other")

        self.assertEqual(events, [])
        self.assertEqual(stats["call_started"], 0)


class AttributionTests(unittest.TestCase):
    def _lines(self):
        return [
            {"sessionId": "s1", "timestamp": "2026-06-21T10:00:30Z"},  # in window
            {"sessionId": "s1", "timestamp": "2026-06-21T09:59:00Z"},  # before window
            {"sessionId": "s1", "timestamp": "not-a-date"},            # unparseable -> excluded
        ]

    def test_window_filters_by_time(self):
        kept = lines_in_window(self._lines(), start_iso="2026-06-21T10:00:00Z", now_iso="2026-06-21T10:01:00Z")
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["timestamp"], "2026-06-21T10:00:30Z")

    def test_distinct_sessions_detects_ambiguity(self):
        lines = self._lines() + [{"sessionId": "s2", "timestamp": "2026-06-21T10:00:40Z"}]
        sessions = distinct_sessions_in_window(lines, start_iso="2026-06-21T10:00:00Z",
                                               now_iso="2026-06-21T10:01:00Z", session_id_path="sessionId")
        self.assertEqual(sessions, {"s1", "s2"})


class DiscoveryTests(unittest.TestCase):
    def test_project_slug_replaces_separators(self):
        self.assertEqual(project_slug_from_cwd("/Users/me/Documents/GitHub/repo"),
                         "-Users-me-Documents-GitHub-repo")

    def test_discover_picks_newest_transcript(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "proj"
            d.mkdir()
            old = d / "old.jsonl"
            old.write_text("{}", encoding="utf-8")
            new = d / "new.jsonl"
            new.write_text("{}", encoding="utf-8")
            os.utime(old, (1, 1))
            os.utime(new, (time.time(), time.time()))
            found = discover_transcript(str(d / "*.jsonl"))
            self.assertEqual(found, new)

    def test_consent_notice_only_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "consent.marker"
            self.assertTrue(consent_notice_once("claude-code", marker))
            self.assertFalse(consent_notice_once("claude-code", marker))

    def test_resolve_glob_includes_session_id(self):
        resolved = project_slug_from_cwd("/repo")
        from gh_address_cr.core.host_telemetry.discovery import resolve_glob

        self.assertIn("codex-s1", resolve_glob("/tmp/*{session_id}.jsonl", project_slug=resolved, session_id="codex-s1"))

    def test_first_env_value_handles_single_and_multiple_names(self):
        env = {"CODEX_THREAD_ID": "codex-s1"}

        self.assertEqual(first_env_value("CODEX_THREAD_ID", env), "codex-s1")
        self.assertEqual(first_env_value(["SESSION_ID", "CODEX_THREAD_ID"], env), "codex-s1")
        self.assertIsNone(first_env_value(["SESSION_ID"], env))


class CaptureTests(unittest.TestCase):
    def _transcript(self, path):
        rows = [
            {"sessionId": "s1", "timestamp": "2026-06-21T10:00:00Z",
             "message": {"content": [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "x"}}]}},
            {"sessionId": "s1", "timestamp": "2026-06-21T10:00:02Z",
             "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "is_error": False}]}},
        ]
        path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")

    def test_capture_produces_agent_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp) / "s1.jsonl"
            self._transcript(t)
            text, outcome = capture_agent_jsonl(
                _cc_profile(), transcript=t, session_id="s1",
                start_iso="2026-06-21T09:59:00Z", now_iso="2026-06-21T10:01:00Z",
            )
            self.assertEqual(outcome, "captured")
            line = json.loads(text.splitlines()[0])
            self.assertEqual(line["operation"], "Bash")
            self.assertEqual(line["duration_ms"], 2000)
            self.assertNotIn("input", text)

    def test_capture_degraded_when_pairing_low(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp) / "s1.jsonl"
            rows = [
                {"sessionId": "s1", "timestamp": "2026-06-21T10:00:00Z",
                 "message": {"content": [{"type": "tool_use", "id": "a", "name": "Bash"}]}},
                {"sessionId": "s1", "timestamp": "2026-06-21T10:00:01Z",
                 "message": {"content": [{"type": "tool_use", "id": "b", "name": "Edit"}]}},
            ]
            t.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
            text, outcome = capture_agent_jsonl(
                _cc_profile(), transcript=t, session_id="s1",
                start_iso="2026-06-21T09:59:00Z", now_iso="2026-06-21T10:01:00Z",
            )
            self.assertEqual(outcome, "degraded")
            self.assertEqual(text, "")

    def test_capture_codex_session_produces_agent_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp) / "codex.jsonl"
            t.write_text(
                "\n".join(json.dumps(row) for row in RecordPairStrategyTests()._lines()),
                encoding="utf-8",
            )
            text, outcome = capture_agent_jsonl(
                _codex_profile(), transcript=t, session_id="codex-s1",
                start_iso="2026-06-21T09:59:00Z", now_iso="2026-06-21T10:01:00Z",
            )

            self.assertEqual(outcome, "captured")
            line = json.loads(text.splitlines()[0])
            self.assertEqual(line["source"], "codex")
            self.assertEqual(line["operation"], "exec_command")
            self.assertEqual(line["duration_ms"], 3000)


class FinalGateAutodiscoveryTests(unittest.TestCase):
    def _seed_session(self, repo, pr, created_at):
        wd = core_paths.workspace_dir(repo, pr)
        wd.mkdir(parents=True, exist_ok=True)
        core_paths.session_file(repo, pr).write_text(json.dumps({"created_at": created_at}), encoding="utf-8")

    @patch("gh_address_cr.commands.final_gate.host_attribution.now_iso", return_value="2026-06-21T10:01:00Z")
    @patch("gh_address_cr.commands.final_gate.host_discovery.discover_transcript")
    def test_autodiscovery_ingests_when_enabled(self, discover, _now):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict("os.environ", {"GH_ADDRESS_CR_STATE_DIR": tmp,
                                           "GH_ADDRESS_CR_HOST_TELEMETRY_AUTO": "1",
                                           "GH_ADDRESS_CR_HOST_TELEMETRY_INPUT": ""}, clear=False):
                self._seed_session("octo/example", "5", "2026-06-21T09:59:00Z")
                transcript = Path(tmp) / "s1.jsonl"
                rows = [
                    {"sessionId": "s1", "timestamp": "2026-06-21T10:00:00Z",
                     "message": {"content": [{"type": "tool_use", "id": "t1", "name": "Bash"}]}},
                    {"sessionId": "s1", "timestamp": "2026-06-21T10:00:03Z",
                     "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "is_error": False}]}},
                ]
                transcript.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
                discover.return_value = transcript

                from gh_address_cr.commands import final_gate
                summary = final_gate.ingest_host_telemetry_via_autodiscovery("octo/example", "5", session_id="s1")
            self.assertIsNotNone(summary)
            self.assertIn(summary["status"], {"SUCCESS", "PARTIAL"})

    @patch("gh_address_cr.commands.final_gate.host_attribution.now_iso", return_value="2026-06-21T10:01:00Z")
    @patch("gh_address_cr.commands.final_gate.host_discovery.discover_transcript")
    def test_autodiscovery_ingests_codex_profile(self, discover, _now):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict("os.environ", {"GH_ADDRESS_CR_STATE_DIR": tmp,
                                           "GH_ADDRESS_CR_HOST_TELEMETRY_AUTO": "1",
                                           "GH_ADDRESS_CR_HOST_TELEMETRY_INPUT": "",
                                           "CODEX_THREAD_ID": "codex-s1",
                                           "SESSION_ID": ""}, clear=False):
                self._seed_session("octo/example", "5", "2026-06-21T09:59:00Z")
                transcript = Path(tmp) / "codex-s1.jsonl"
                transcript.write_text(
                    "\n".join(json.dumps(row) for row in RecordPairStrategyTests()._lines()),
                    encoding="utf-8",
                )
                discover.return_value = transcript

                from gh_address_cr.commands import final_gate
                summary = final_gate.ingest_host_telemetry_via_autodiscovery("octo/example", "5")
            self.assertIsNotNone(summary)
            self.assertIn(summary["status"], {"SUCCESS", "PARTIAL"})

    def test_autodiscovery_skipped_when_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            from gh_address_cr.commands import final_gate
            with patch.dict("os.environ", {"GH_ADDRESS_CR_STATE_DIR": tmp,
                                           "GH_ADDRESS_CR_HOST_TELEMETRY_AUTO": "0"}, clear=False):
                self.assertIsNone(final_gate.ingest_host_telemetry_via_autodiscovery("octo/example", "5", session_id="s1"))


class EndToEndReportTests(unittest.TestCase):
    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_captured_transcript_flows_into_report(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            SessionTelemetry.reset()
            fixture = Path(__file__).resolve().parents[1] / "fixtures" / "host_telemetry" / "claude-code-sample.jsonl"
            text, outcome = capture_agent_jsonl(
                _cc_profile(), transcript=fixture, session_id="sess-e2e",
                start_iso="2026-06-21T09:59:00Z", now_iso="2026-06-21T10:01:00Z",
            )
            self.assertEqual(outcome, "captured")
            from gh_address_cr.core.telemetry import import_external_telemetry
            summary = import_external_telemetry("octo/example", "5", source="claude-code", fmt="agent-jsonl", raw=text)
            self.assertEqual(summary["status"], "SUCCESS")

            report = build_efficiency_report("octo/example", "5")
            self.assertTrue(report["duration_observed"])
            ops = {row["operation"]: row for row in report["slowest_operations"]}
            self.assertEqual(ops["Bash"]["duration_ms"], 4000)
            self.assertNotIn("DO NOT LEAK", json.dumps(report))

    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_wait_kind_not_counted_as_command_failure(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            SessionTelemetry.reset()
            fixture = Path(__file__).resolve().parents[1] / "fixtures" / "host_telemetry" / "claude-code-sample.jsonl"
            text, _ = capture_agent_jsonl(
                _cc_profile(), transcript=fixture, session_id="sess-e2e",
                start_iso="2026-06-21T09:59:00Z", now_iso="2026-06-21T10:01:00Z",
            )
            line_kinds = {json.loads(ln)["operation"]: json.loads(ln)["kind"] for ln in text.splitlines()}
            self.assertEqual(line_kinds["AskUserQuestion"], "wait")
            self.assertEqual(line_kinds["Bash"], "command")

    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_codex_captured_transcript_flows_into_report(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            SessionTelemetry.reset()
            fixture = Path(__file__).resolve().parents[1] / "fixtures" / "host_telemetry" / "codex-session-sample.jsonl"
            text, outcome = capture_agent_jsonl(
                _codex_profile(), transcript=fixture, session_id="codex-sess-e2e",
                start_iso="2026-06-21T09:59:00Z", now_iso="2026-06-21T10:01:00Z",
            )
            self.assertEqual(outcome, "captured")
            from gh_address_cr.core.telemetry import import_external_telemetry
            summary = import_external_telemetry("octo/example", "5", source="codex", fmt="agent-jsonl", raw=text)
            self.assertEqual(summary["status"], "SUCCESS")

            report = build_efficiency_report("octo/example", "5")
            self.assertTrue(report["duration_observed"])
            self.assertIn("codex", json.dumps(report))
            self.assertNotIn("DO NOT LEAK", json.dumps(report))
