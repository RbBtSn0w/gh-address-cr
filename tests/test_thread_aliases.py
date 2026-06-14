import json

from gh_address_cr.commands.high_level import _native_thread_rows
from tests.helpers import PythonScriptTestCase
from tests.test_control_plane_workflow import github_thread, open_item


class ThreadAliasTest(PythonScriptTestCase):
    def write_session(self, *, items):
        self.workspace_dir().mkdir(parents=True, exist_ok=True)
        payload = {
            "session_id": "session_77",
            "repo": self.repo,
            "pr_number": self.pr,
            "status": "WAITING_FOR_FIX",
            "items": {item["item_id"]: item for item in items},
            "leases": {},
            "ledger_path": str(self.workspace_dir() / "evidence.jsonl"),
            "metrics": {"blocking_items_count": len(items)},
        }
        self.session_file().write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def load_session(self):
        return json.loads(self.session_file().read_text(encoding="utf-8"))

    def test_lean_rows_assign_stable_sequential_aliases(self):
        session = {
            "items": {
                "github-thread:abc": github_thread("github-thread:abc"),
                "local-finding:1": open_item("local-finding:1"),
                "github-thread:def": github_thread("github-thread:def"),
            }
        }

        rows = _native_thread_rows(session, lean=True)

        aliases = {row["item_id"]: row["alias"] for row in rows}
        # Aliases follow sorted github_thread item-id order and skip the local finding.
        self.assertEqual(aliases, {"github-thread:abc": "T1", "github-thread:def": "T2"})

    def test_resolve_accepts_thread_alias_in_place_of_item_id(self):
        self.write_session(
            items=[
                github_thread("github-thread:abc"),
                github_thread("github-thread:def"),
            ]
        )

        result = self.run_runtime_module(
            "agent", "resolve", self.repo, self.pr,
            "T2",
            "--commit", "abc123",
            "--files", "src/shared.py",
            "--summary", "Addressed the second thread.",
            "--why", "The shared guard now covers the reviewed case.",
            "--validation", "python3 -m unittest tests.test_shared=passed",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        session = self.load_session()
        # T2 maps to the second github_thread in sorted order.
        self.assertEqual(session["items"]["github-thread:def"]["state"], "publish_ready")
        self.assertEqual(session["items"]["github-thread:abc"]["state"], "open")

    def test_resolve_stale_alias_reports_actionable_error(self):
        self.write_session(items=[github_thread("github-thread:abc")])

        result = self.run_runtime_module(
            "agent", "resolve", self.repo, self.pr,
            "T9",
            "--commit", "abc123",
            "--files", "src/shared.py",
            "--summary", "x",
            "--why", "y",
            "--validation", "cmd=passed",
        )

        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["reason_code"], "THREAD_ALIAS_NOT_FOUND")
