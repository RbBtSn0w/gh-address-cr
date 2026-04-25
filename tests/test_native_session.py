import json
import os
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


if __name__ == "__main__":
    unittest.main()
