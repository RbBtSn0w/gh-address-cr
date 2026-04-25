import contextlib
import io
import json
from argparse import Namespace
from unittest.mock import patch

from gh_address_cr.core import session_engine

from tests.helpers import PythonScriptTestCase, ROOT


FIXTURE = ROOT / "tests" / "fixtures" / "session_engine" / "legacy_native_session.json"
FIXED_NOW = "2026-04-24T12:00:00+00:00"


class SessionEngineParityTest(PythonScriptTestCase):
    def test_native_session_flow_matches_legacy_golden_snapshot_byte_for_byte(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.run_representative_session_flow()

        actual = self.session_file().read_text(encoding="utf-8")
        expected = FIXTURE.read_text(encoding="utf-8")

        self.assertEqual(actual, expected)

    def run_representative_session_flow(self):
        with patch.object(session_engine, "utc_now", return_value=FIXED_NOW):
            session_engine.cmd_init(Namespace(repo=self.repo, pr_number=self.pr))

            self.run_with_stdin(
                [
                    {
                        "id": "THREAD_PARITY",
                        "isResolved": False,
                        "isOutdated": False,
                        "path": "src/parity.py",
                        "line": 12,
                        "body": "Please keep the native session state compatible.",
                        "url": "https://example.test/thread/parity",
                    }
                ],
                session_engine.cmd_sync_github,
                Namespace(repo=self.repo, pr_number=self.pr, scan_id="scan-github-parity"),
            )

            self.run_with_stdin(
                [
                    {
                        "title": "Local parity finding",
                        "body": "Ensure local findings preserve the legacy session shape.",
                        "path": "src/local_parity.py",
                        "line": 7,
                        "severity": "P2",
                    }
                ],
                session_engine.cmd_ingest_local,
                Namespace(
                    repo=self.repo,
                    pr_number=self.pr,
                    source="local-agent:parity",
                    scan_id="scan-local-parity",
                    sync=False,
                    handoff_sha256="handoff-parity-sha",
                ),
            )

            session = json.loads(self.session_file().read_text(encoding="utf-8"))
            local_item_id = next(
                item_id
                for item_id, item in session["items"].items()
                if item["item_kind"] == "local_finding"
            )

            session_engine.cmd_update_item(
                Namespace(
                    repo=self.repo,
                    pr_number=self.pr,
                    item_id=local_item_id,
                    status="CLARIFIED",
                    decision="clarify",
                    note="Clarified by the parity fixture.",
                    actor="parity-agent",
                    handled=False,
                )
            )

            self.run_with_stdin(
                [
                    {
                        "item_id": "github-thread:THREAD_PARITY",
                        "status": "CLOSED",
                        "handled": True,
                        "note": "Replied and resolved in the parity fixture.",
                        "reply_posted": True,
                        "reply_url": "https://example.test/thread/parity#reply",
                        "clear_claim": True,
                    }
                ],
                session_engine.cmd_update_items_batch,
                Namespace(repo=self.repo, pr_number=self.pr),
            )

    def run_with_stdin(self, payload, func, args):
        raw = json.dumps(payload)
        with patch("sys.stdin", io.StringIO(raw)):
            return func(args)
