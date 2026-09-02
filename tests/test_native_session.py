import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class NativeSessionTests(unittest.TestCase):
    def test_session_manager_creates_loads_and_saves_pr_scoped_session(self):
        from gh_address_cr.core.session import SessionManager

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                manager = SessionManager("owner/repo", "123")
                session = manager.create(status="ACTIVE")
                session["items"] = {"local:1": {"item_id": "local:1", "blocking": True}}
                manager.save(session)

                loaded = manager.load()

                self.assertEqual(loaded["repo"], "owner/repo")
                self.assertEqual(loaded["pr_number"], "123")
                self.assertEqual(loaded["status"], "ACTIVE")
                self.assertEqual(loaded["items"]["local:1"]["blocking"], True)
                self.assertEqual(Path(loaded["ledger_path"]).name, "evidence.jsonl")
                self.assertEqual(manager.session_path.name, "session.json")

    def test_session_manager_rejects_invalid_json_with_reason_code(self):
        from gh_address_cr.core.session import SessionError, SessionManager

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                manager = SessionManager("owner/repo", "123")
                manager.session_path.parent.mkdir(parents=True, exist_ok=True)
                manager.session_path.write_text("{invalid json", encoding="utf-8")

                with self.assertRaises(SessionError) as context:
                    manager.load()

                self.assertEqual(context.exception.reason_code, "INVALID_SESSION_JSON")

    def test_high_level_reports_corrupt_session_as_session_recovery(self):
        from gh_address_cr.commands.high_level import HighLevelReviewRuntime
        from gh_address_cr.core.session import SessionManager

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                manager = SessionManager("owner/repo", "123")
                manager.session_path.parent.mkdir(parents=True, exist_ok=True)
                manager.session_path.write_text("{invalid json", encoding="utf-8")
                runtime = HighLevelReviewRuntime()

                with patch.object(runtime, "_run_preflight_checks", return_value=(None, None)):
                    with patch("gh_address_cr.commands.high_level._emit_native_summary") as emit:
                        result = runtime.handle("address", ["owner/repo", "123", "--lean"], human=False, lean=True)

                self.assertEqual(result, 5)
                summary = emit.call_args.args[0]
                self.assertEqual(summary["reason_code"], "INVALID_SESSION_JSON")
                self.assertEqual(summary["waiting_on"], "session")

    def test_save_session_uses_atomic_json_writer(self):
        from gh_address_cr.core.session import SessionManager

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                manager = SessionManager("owner/repo", "123")
                manager.save(manager.create(status="ACTIVE"))
                manager.save(manager.create(status="WAITING_FOR_FIX"))

                payload = json.loads(manager.session_path.read_text(encoding="utf-8"))
                self.assertEqual(payload["status"], "WAITING_FOR_FIX")
                self.assertEqual(list(manager.session_path.parent.glob("*.tmp")), [])

    def test_state_dir_reports_actionable_error_when_directory_is_not_writable(self):
        from gh_address_cr.core import session

        with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": "/unwritable/state"}, clear=False):
            with patch("gh_address_cr.core.session.Path.mkdir", side_effect=PermissionError("operation not permitted")):
                with self.assertRaises(session.SessionError) as context:
                    session.state_dir()

        self.assertEqual(context.exception.reason_code, "STATE_DIR_NOT_WRITABLE")
        self.assertIn("GH_ADDRESS_CR_STATE_DIR", str(context.exception))

    def test_cli_reports_state_directory_failure_without_traceback(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            state_file = Path(tmp) / "state-file"
            state_file.write_text("not a directory", encoding="utf-8")
            env = os.environ.copy()
            env.update(
                {
                    "GH_ADDRESS_CR_STATE_DIR": str(state_file),
                    "DISABLE_TELEMETRY": "1",
                    "PYTHONPATH": str(root / "src"),
                }
            )
            result = subprocess.run(
                [sys.executable, "-m", "gh_address_cr", "address", "owner/repo", "123", "--lean"],
                cwd=root,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

        payload = json.loads(result.stdout)
        self.assertEqual(result.returncode, 5)
        self.assertEqual(payload["reason_code"], "STATE_DIR_NOT_WRITABLE")
        self.assertNotIn("Traceback", result.stderr)

    def test_writable_override_supports_session_when_home_is_read_only(self):
        from gh_address_cr.core.session import SessionManager

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            override = Path(tmp) / "agent-state"
            home.mkdir()
            home.chmod(0o555)
            try:
                with patch.dict(
                    os.environ,
                    {"HOME": str(home), "GH_ADDRESS_CR_STATE_DIR": str(override)},
                    clear=False,
                ):
                    manager = SessionManager("owner/repo", "123")
                    manager.save(manager.create(status="ACTIVE"))
                    self.assertTrue(manager.session_path.is_file())
                    self.assertTrue(override.exists())
            finally:
                home.chmod(0o700)


if __name__ == "__main__":
    unittest.main()
