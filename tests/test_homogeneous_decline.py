import json

from tests.helpers import PythonScriptTestCase
from tests.test_control_plane_workflow import github_thread


class HomogeneousDeclineCLITest(PythonScriptTestCase):
    REASON = "All eight threads raise the identical backtick nit; declining as a non-blocking style preference."

    def write_session(self, *, items, leases=None):
        self.workspace_dir().mkdir(parents=True, exist_ok=True)
        payload = {
            "session_id": "session_77",
            "repo": self.repo,
            "pr_number": self.pr,
            "status": "WAITING_FOR_FIX",
            "items": {item["item_id"]: item for item in items},
            "leases": leases or {},
            "ledger_path": str(self.workspace_dir() / "evidence.jsonl"),
            "metrics": {"blocking_items_count": len(items)},
        }
        self.session_file().write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def load_session(self):
        return json.loads(self.session_file().read_text(encoding="utf-8"))

    def _two_identical_threads(self):
        self.write_session(
            items=[
                github_thread("github-thread:abc", body="Wrap `Xcode` in backticks.", first_body="Wrap `Xcode` in backticks."),
                github_thread("github-thread:def", body="Wrap `Xcode` in backticks.", first_body="Wrap `Xcode` in backticks."),
            ]
        )

    def test_homogeneous_reject_accepts_all_matching_threads(self):
        self._two_identical_threads()

        result = self.run_runtime_module(
            "agent", "resolve", self.repo, self.pr,
            "--agent-id", "codex-1",
            "--reject",
            "--match-files",
            "--files", "src/shared.py",
            "--homogeneous-reason", self.REASON,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "DECLINE_ALL_ACCEPTED")
        self.assertEqual(payload["resolution"], "reject")
        self.assertEqual(payload["matched_count"], 2)
        self.assertEqual(payload["accepted_count"], 2)
        session = self.load_session()
        for item_id in ("github-thread:abc", "github-thread:def"):
            item = session["items"][item_id]
            self.assertEqual(item["state"], "publish_ready")
            self.assertEqual(item["publish_resolution"], "reject")
            self.assertEqual(item["accepted_response"]["reply_markdown"], self.REASON)
            self.assertEqual(item["accepted_response"]["resolution"], "reject")

    def test_homogeneous_clarify_accepts_all_matching_threads(self):
        self._two_identical_threads()

        result = self.run_runtime_module(
            "agent", "resolve", self.repo, self.pr,
            "--clarify",
            "--match-files",
            "--files", "src/shared.py",
            "--homogeneous-reason", self.REASON,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "DECLINE_ALL_ACCEPTED")
        self.assertEqual(payload["resolution"], "clarify")
        self.assertEqual(payload["accepted_count"], 2)
        session = self.load_session()
        self.assertEqual(session["items"]["github-thread:abc"]["publish_resolution"], "clarify")

    def test_decline_rejects_distinct_thread_bodies(self):
        self.write_session(
            items=[
                github_thread("github-thread:abc", first_body="Why does this branch skip nil validation?"),
                github_thread("github-thread:def", first_body="Can this log expose private data?"),
            ]
        )

        result = self.run_runtime_module(
            "agent", "resolve", self.repo, self.pr,
            "--reject",
            "--match-files",
            "--files", "src/shared.py",
            "--homogeneous-reason", self.REASON,
        )

        self.assertEqual(result.returncode, 4)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "DECLINE_ALL_REJECTED")
        self.assertEqual(payload["reason_code"], "PER_THREAD_EVIDENCE_REQUIRED")
        # Decline routing must NOT point at the fix-only BatchActionResponse channel; it
        # routes to per-thread classify/next/submit instead (#136 review T4).
        self.assertEqual(payload["waiting_on"], "decline_input")
        self.assertNotIn("BatchActionResponse", payload["next_action"])
        self.assertIn("classify", payload["next_action"])
        self.assertIn("classify", payload["commands"])
        self.assertNotIn("batch_next", payload["commands"])
        session = self.load_session()
        self.assertEqual(session["items"]["github-thread:abc"]["state"], "open")
        self.assertEqual(session["items"]["github-thread:def"]["state"], "open")

    def test_decline_without_match_files_now_succeeds(self):
        # spec 029 / T021 (F1): --match-files is deprecated/implied by
        # --files/--file — a files-scope decline no longer requires it.
        self._two_identical_threads()

        result = self.run_runtime_module(
            "agent", "resolve", self.repo, self.pr,
            "--reject",
            "--files", "src/shared.py",
            "--homogeneous-reason", self.REASON,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "DECLINE_ALL_ACCEPTED")

    def test_decline_requires_homogeneous_reason(self):
        self._two_identical_threads()

        result = self.run_runtime_module(
            "agent", "resolve", self.repo, self.pr,
            "--reject",
            "--match-files",
            "--files", "src/shared.py",
        )

        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "DECLINE_ALL_REJECTED")
        self.assertEqual(payload["reason_code"], "MISSING_HOMOGENEOUS_REASON")
        # Decline-mode validation failures report decline_input, not fast_fix_input (#136 T5).
        self.assertEqual(payload["waiting_on"], "decline_input")

    def test_decline_conflicts_with_commit(self):
        self._two_identical_threads()

        result = self.run_runtime_module(
            "agent", "resolve", self.repo, self.pr,
            "--reject",
            "--match-files",
            "--files", "src/shared.py",
            "--commit", "abc123",
            "--homogeneous-reason", self.REASON,
        )

        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        # spec 029: fix-only evidence + decline disposition is an
        # evidence/disposition incoherence, not an ad-hoc mode conflict.
        self.assertEqual(payload["reason_code"], "RESOLVE_EVIDENCE_INCOHERENT")

    def test_reject_and_clarify_mutually_exclusive(self):
        self._two_identical_threads()

        result = self.run_runtime_module(
            "agent", "resolve", self.repo, self.pr,
            "--reject",
            "--clarify",
            "--match-files",
            "--files", "src/shared.py",
            "--homogeneous-reason", self.REASON,
        )

        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        # spec 029: two dispositions at once is a same-axis conflict.
        self.assertEqual(payload["reason_code"], "RESOLVE_AXIS_CONFLICT")

    def test_decline_single_item_by_id_is_now_valid(self):
        # spec 029 / #204: item_id + --reject used to be rejected
        # (ITEM_ID_NOT_ALLOWED_FOR_MODE); it is now the primary path for
        # declining exactly one thread.
        self._two_identical_threads()

        result = self.run_runtime_module(
            "agent", "resolve", self.repo, self.pr,
            "github-thread:abc",
            "--reject",
            "--why", self.REASON,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["item_id"], "github-thread:abc")
