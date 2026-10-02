"""Spec 039 Q3: near-miss agent input is rejected with the exact correction, never rewritten."""

from __future__ import annotations

import json

from tests.helpers import PythonScriptTestCase
from tests.test_control_plane_workflow import open_item

THREAD_ID = "PRRT_kwDOTzg--86oMBRT"
ITEM_ID = f"github-thread:{THREAD_ID}"


class AgentInputHintTests(PythonScriptTestCase):
    def setUp(self):
        super().setUp()
        self.install_fake_pr_commits()
        self.workspace_dir().mkdir(parents=True, exist_ok=True)
        item = open_item(
            ITEM_ID,
            item_kind="github_thread",
            source="github",
            path="src/example.py",
            body="Unused import.",
            state="open",
            status="OPEN",
            thread_id=THREAD_ID,
        )
        self.session_file().write_text(
            json.dumps(
                {
                    "session_id": "session_hints",
                    "repo": self.repo,
                    "pr_number": self.pr,
                    "status": "WAITING_FOR_FIX",
                    "items": {ITEM_ID: item},
                    "leases": {},
                    "ledger_path": str(self.workspace_dir() / "evidence.jsonl"),
                    "metrics": {},
                }
            ),
            encoding="utf-8",
        )

    def resolve(self, item_id, *extra):
        return self.run_runtime_module(
            "agent", "resolve", self.repo, self.pr, item_id,
            "--commit", "abc1234", "--files", "src/example.py",
            "--summary", "Removed the import.", "--validation", "unit=passed",
            *extra,
        )

    def item(self):
        from gh_address_cr.core.session import load_session

        return load_session(self.repo, self.pr)["items"][ITEM_ID]

    def test_bare_thread_id_is_rejected_with_the_full_item_id(self):
        result = self.resolve(THREAD_ID, "--why", "It was unused.")

        self.assertNotEqual(result.returncode, 0, result.stdout)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["reason_code"], "ITEM_NOT_FOUND")
        self.assertIn(f"Did you mean `{ITEM_ID}`", payload["next_action"])
        self.assertNotIn("decision", self.item(), "a rejected id must not be rewritten into a classification")

    def test_reason_flag_is_rejected_with_a_why_hint(self):
        result = self.resolve(ITEM_ID, "--reason", "It was unused.")

        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["reason_code"], "UNSUPPORTED_FLAG")
        self.assertIn("--why", payload["next_action"])
        self.assertNotIn("decision", self.item())


class HandlerDocstringTest(PythonScriptTestCase):
    def test_resolve_handler_keeps_its_docstring(self):
        # The near-miss check must not displace the docstring into a no-op expression.
        from gh_address_cr.commands.agent import handle_agent_resolve

        self.assertTrue((handle_agent_resolve.__doc__ or "").startswith("Unified GitHub review-thread resolution surface"))
