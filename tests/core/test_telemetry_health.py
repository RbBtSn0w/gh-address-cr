import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gh_address_cr.core.host_telemetry.profile import HostProfile
from gh_address_cr.core.telemetry_health import autodiscovery_profile_check, load_host_profiles


def _profile() -> HostProfile:
    return HostProfile(
        source="codex",
        strategy="record-pair-timestamp",
        discovery={"glob": "{project_slug}/missing-{session_id}.jsonl", "session_id_env": ["CODEX_THREAD_ID"]},
        record={"container": "jsonl-lines", "session_id_path": "payload.id"},
        fields={"timestamp_path": "timestamp"},
        safety_allowlist=("operation", "status", "timestamp", "correlation_id"),
    )


class TelemetryHealthTests(unittest.TestCase):
    def test_load_host_profiles_turns_unexpected_profile_error_into_health_issue(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "bad.json").write_text("{}", encoding="utf-8")
            with patch("gh_address_cr.core.telemetry_health.profile_dir", return_value=Path(tmp)):
                with patch(
                    "gh_address_cr.core.telemetry_health.host_profile.load_profile",
                    side_effect=TypeError("bad shape"),
                ):
                    profiles, issues = load_host_profiles()

            self.assertEqual(profiles, [])
            self.assertEqual(len(issues), 1)
            self.assertEqual(issues[0].reason_code, "TELEMETRY_PROFILE_INVALID")
            self.assertIn("bad.json", issues[0].detail)

    def test_autodiscovery_profile_check_falls_back_when_cwd_is_unavailable(self):
        with patch("gh_address_cr.core.telemetry_health.os.getcwd", side_effect=OSError("cwd missing")):
            check = autodiscovery_profile_check(_profile(), environ={"CODEX_THREAD_ID": "session-1"})

        self.assertEqual(check["status"], "failed")
        self.assertEqual(check["reason_code"], "TELEMETRY_TRANSCRIPT_NOT_FOUND")
