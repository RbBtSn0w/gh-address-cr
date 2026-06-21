import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from gh_address_cr.core import paths as core_paths

from gh_address_cr.core.host_telemetry.attribution import lines_in_window, distinct_sessions_in_window
from gh_address_cr.core.host_telemetry.discovery import project_slug_from_cwd, discover_transcript, consent_notice_once
from gh_address_cr.core.host_telemetry.profile import HostProfile, load_profile
from gh_address_cr.core.host_telemetry.capture import capture_agent_jsonl
from gh_address_cr.core.host_telemetry.strategies import paired_correlation_timestamp


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
            old = d / "old.jsonl"; old.write_text("{}", encoding="utf-8")
            new = d / "new.jsonl"; new.write_text("{}", encoding="utf-8")
            os.utime(old, (1, 1))
            os.utime(new, (time.time(), time.time()))
            found = discover_transcript(str(d / "*.jsonl"))
            self.assertEqual(found, new)

    def test_consent_notice_only_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "consent.marker"
            self.assertTrue(consent_notice_once("claude-code", marker))
            self.assertFalse(consent_notice_once("claude-code", marker))


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

    def test_autodiscovery_skipped_when_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            from gh_address_cr.commands import final_gate
            with patch.dict("os.environ", {"GH_ADDRESS_CR_STATE_DIR": tmp,
                                           "GH_ADDRESS_CR_HOST_TELEMETRY_AUTO": "0"}, clear=False):
                self.assertIsNone(final_gate.ingest_host_telemetry_via_autodiscovery("octo/example", "5", session_id="s1"))
