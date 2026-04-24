import importlib
import importlib.util
import sys
import unittest

from tests.helpers import SRC_ROOT


if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


def load_gate_module():
    if importlib.util.find_spec("gh_address_cr.core.gate") is None:
        raise AssertionError("gh_address_cr.core.gate module is required")
    return importlib.import_module("gh_address_cr.core.gate")


class FinalGateTestCase(unittest.TestCase):
    def evaluate(self, session, *, remote_threads=None, pending_reviews=None, current_login="agent-login"):
        gate = load_gate_module()
        return gate.evaluate_final_gate(
            session,
            remote_threads=remote_threads or [],
            pending_reviews=pending_reviews or [],
            current_login=current_login,
        )

    def passing_session(self):
        return {
            "repo": "octo/example",
            "pr_number": "77",
            "items": {
                "github-thread:THREAD_DONE": {
                    "item_id": "github-thread:THREAD_DONE",
                    "item_kind": "github_thread",
                    "thread_id": "THREAD_DONE",
                    "state": "closed",
                    "reply_evidence": {
                        "reply_url": "https://example.test/reply",
                        "author_login": "agent-login",
                    },
                },
                "local-finding:FIXED": {
                    "item_id": "local-finding:FIXED",
                    "item_kind": "local_finding",
                    "state": "fixed",
                    "blocking": False,
                    "validation_evidence": [
                        {"command": "python3 -m unittest tests.test_final_gate", "exit_code": 0}
                    ],
                },
            },
        }

    def test_machine_summary_fields_are_stable_on_success(self):
        result = self.evaluate(
            self.passing_session(),
            remote_threads=[{"id": "THREAD_DONE", "isResolved": True}],
        )

        self.assertTrue(result.passed)
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.failure_codes, [])

        summary = result.to_machine_summary()
        self.assertEqual(summary["status"], "PASSED")
        self.assertEqual(summary["repo"], "octo/example")
        self.assertEqual(summary["pr_number"], "77")
        self.assertIsNone(summary["reason_code"])
        self.assertIsNone(summary["waiting_on"])
        self.assertEqual(summary["exit_code"], 0)
        self.assertEqual(summary["next_action"], "Completion may be claimed.")
        self.assertEqual(summary["failure_codes"], [])
        self.assertEqual(
            summary["counts"],
            {
                "unresolved_github_threads_count": 0,
                "pending_review_count": 0,
                "blocking_items_count": 0,
                "github_threads_missing_reply_count": 0,
                "missing_validation_evidence_count": 0,
                "blocking_local_items_count": 0,
                "pending_current_login_review_count": 0,
                "unresolved_remote_threads_count": 0,
            },
        )

    def test_unresolved_remote_threads_fail_with_explicit_code(self):
        result = self.evaluate(
            self.passing_session(),
            remote_threads=[{"id": "THREAD_OPEN", "isResolved": False}],
        )

        self.assertFalse(result.passed)
        self.assertEqual(result.exit_code, 5)
        self.assertEqual(result.reason_code, "FINAL_GATE_UNRESOLVED_REMOTE_THREADS")
        self.assertEqual(result.failure_codes, ["FINAL_GATE_UNRESOLVED_REMOTE_THREADS"])
        self.assertEqual(result.counts["unresolved_remote_threads_count"], 1)
        self.assertEqual(result.to_machine_summary()["waiting_on"], "remote_threads")

    def test_resolved_thread_without_reply_evidence_still_fails(self):
        session = self.passing_session()
        session["items"]["github-thread:THREAD_DONE"].pop("reply_evidence")

        result = self.evaluate(
            session,
            remote_threads=[{"id": "THREAD_DONE", "isResolved": True}],
        )

        self.assertFalse(result.passed)
        self.assertEqual(result.reason_code, "FINAL_GATE_MISSING_REPLY_EVIDENCE")
        self.assertEqual(result.failure_codes, ["FINAL_GATE_MISSING_REPLY_EVIDENCE"])
        self.assertEqual(result.counts["github_threads_missing_reply_count"], 1)
        self.assertEqual(result.to_machine_summary()["waiting_on"], "reply_evidence")

    def test_pending_review_from_current_login_fails(self):
        result = self.evaluate(
            self.passing_session(),
            remote_threads=[{"id": "THREAD_DONE", "isResolved": True}],
            pending_reviews=[
                {"id": "review-other", "state": "PENDING", "user": {"login": "other"}},
                {"id": "review-agent", "state": "PENDING", "user": {"login": "agent-login"}},
            ],
        )

        self.assertFalse(result.passed)
        self.assertEqual(result.reason_code, "FINAL_GATE_PENDING_CURRENT_LOGIN_REVIEW")
        self.assertEqual(result.failure_codes, ["FINAL_GATE_PENDING_CURRENT_LOGIN_REVIEW"])
        self.assertEqual(result.counts["pending_current_login_review_count"], 1)
        self.assertEqual(result.to_machine_summary()["waiting_on"], "pending_review")

    def test_blocking_local_items_fail(self):
        session = self.passing_session()
        session["items"]["local-finding:OPEN"] = {
            "item_id": "local-finding:OPEN",
            "item_kind": "local_finding",
            "state": "open",
            "blocking": True,
        }

        result = self.evaluate(
            session,
            remote_threads=[{"id": "THREAD_DONE", "isResolved": True}],
        )

        self.assertFalse(result.passed)
        self.assertEqual(result.reason_code, "FINAL_GATE_BLOCKING_LOCAL_ITEMS")
        self.assertEqual(result.failure_codes, ["FINAL_GATE_BLOCKING_LOCAL_ITEMS"])
        self.assertEqual(result.counts["blocking_local_items_count"], 1)
        self.assertEqual(result.counts["blocking_items_count"], 1)
        self.assertEqual(result.to_machine_summary()["waiting_on"], "local_items")

    def test_terminal_local_finding_without_validation_evidence_fails(self):
        session = self.passing_session()
        session["items"]["local-finding:FIXED"].pop("validation_evidence")

        result = self.evaluate(
            session,
            remote_threads=[{"id": "THREAD_DONE", "isResolved": True}],
        )

        self.assertFalse(result.passed)
        self.assertEqual(result.reason_code, "FINAL_GATE_MISSING_VALIDATION_EVIDENCE")
        self.assertEqual(result.failure_codes, ["FINAL_GATE_MISSING_VALIDATION_EVIDENCE"])
        self.assertEqual(result.counts["missing_validation_evidence_count"], 1)
        self.assertEqual(result.to_machine_summary()["waiting_on"], "validation_evidence")

    def test_failure_codes_are_reported_in_gate_order(self):
        session = self.passing_session()
        session["items"]["github-thread:THREAD_DONE"].pop("reply_evidence")
        session["items"]["local-finding:FIXED"].pop("validation_evidence")
        session["items"]["local-finding:OPEN"] = {
            "item_id": "local-finding:OPEN",
            "item_kind": "local_finding",
            "state": "open",
            "blocking": True,
        }

        result = self.evaluate(
            session,
            remote_threads=[
                {"id": "THREAD_DONE", "isResolved": True},
                {"id": "THREAD_OPEN", "isResolved": False},
            ],
            pending_reviews=[{"id": "review-agent", "state": "PENDING", "user": {"login": "agent-login"}}],
        )

        self.assertEqual(
            result.failure_codes,
            [
                "FINAL_GATE_UNRESOLVED_REMOTE_THREADS",
                "FINAL_GATE_MISSING_REPLY_EVIDENCE",
                "FINAL_GATE_PENDING_CURRENT_LOGIN_REVIEW",
                "FINAL_GATE_BLOCKING_LOCAL_ITEMS",
                "FINAL_GATE_MISSING_VALIDATION_EVIDENCE",
            ],
        )
        self.assertEqual(result.reason_code, "FINAL_GATE_UNRESOLVED_REMOTE_THREADS")
