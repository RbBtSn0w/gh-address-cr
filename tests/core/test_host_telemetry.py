import json
import tempfile
import unittest
from pathlib import Path

from gh_address_cr.core.host_telemetry.profile import HostProfile, load_profile


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
