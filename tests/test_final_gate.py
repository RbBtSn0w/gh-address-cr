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
                    "validation_evidence": [{"command": "python3 -m unittest tests.test_final_gate", "exit_code": 0}],
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
        self.assertIsNone(summary["check_requirement"])
        self.assertEqual(
            summary["counts"],
            {
                "unresolved_github_threads_count": 0,
                "pending_review_count": 0,
                "blocking_items_count": 0,
                "blocking_github_items_count": 0,
                "github_threads_missing_reply_count": 0,
                "missing_validation_evidence_count": 0,
                "blocking_local_items_count": 0,
                "pending_current_login_review_count": 0,
                "unresolved_remote_threads_count": 0,
                "pr_checks_count": 0,
                "pr_checks_failed_count": 0,
                "pr_checks_pending_count": 0,
                "pr_checks_not_green_count": 0,
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
        summary = result.to_machine_summary()
        self.assertEqual(summary["waiting_on"], "remote_threads")
        self.assertIn("gh-address-cr address octo/example 77 --lean", summary["next_action"])
        self.assertEqual(summary["commands"]["final_gate"], "gh-address-cr final-gate octo/example 77")

    def test_unknown_next_action_fails_closed(self):
        gate = load_gate_module()

        self.assertEqual(gate._next_action(None), "Status unknown: pending check results.")

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
        summary = result.to_machine_summary()
        self.assertEqual(summary["waiting_on"], "reply_evidence")
        self.assertIn("gh-address-cr agent publish octo/example 77", summary["next_action"])

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

    def test_build_completion_summary_guidance_clean(self):
        from gh_address_cr.commands.final_gate import build_completion_summary_guidance
        result = self.evaluate(
            self.passing_session(),
            remote_threads=[{"id": "THREAD_DONE", "isResolved": True}],
        )
        telemetry_report = {
            "coverage_label": "complete",
            "total_events": 10,
            "success_rate": 100.0,
            "inefficiency_flags": [],
            "report_artifact": "path/to/report.json",
        }
        guidance = build_completion_summary_guidance(result, telemetry_report, summary_path=None)

        self.assertIn("[gh-address-cr: PASSED | threads: 0 | reviews: 0 | checks: N/A | telemetry: complete (10 events, 100.0%) | inefficiency: none]", guidance)
        self.assertNotIn("Attention Items", guidance)
        self.assertNotIn("IMPLICATION PROMPT", guidance)

    def test_build_completion_summary_guidance_abnormal(self):
        from gh_address_cr.commands.final_gate import build_completion_summary_guidance
        result = self.evaluate(
            self.passing_session(),
            remote_threads=[{"id": "THREAD_OPEN", "isResolved": False}],
        )
        telemetry_report = {
            "coverage_label": "partial",
            "total_events": 5,
            "success_rate": 80.0,
            "inefficiency_flags": ["excessive_loops"],
            "report_artifact": "path/to/report.json",
        }
        guidance = build_completion_summary_guidance(result, telemetry_report, summary_path=None)

        self.assertIn("[gh-address-cr: FAILED | threads: 1 | reviews: 0 | checks: N/A | telemetry: partial (5 events, 80.0%) | inefficiency: excessive_loops]", guidance)
        self.assertIn("Gate FAILED: Do not send completion summary. Recommended status update:", guidance)
        self.assertIn("Attention Items & Implications", guidance)
        self.assertIn("IMPLICATION PROMPT", guidance)
        self.assertIn("incomplete telemetry coverage (partial)", guidance)
        self.assertIn("success rate below 100% (80.0%)", guidance)
        self.assertIn("inefficiency flags present (excessive_loops)", guidance)
        self.assertIn("unresolved threads/checks/blocking items (1 unresolved threads)", guidance)

    def test_build_completion_summary_guidance_edge_cases(self):
        from gh_address_cr.commands.final_gate import build_completion_summary_guidance
        session = self.passing_session()
        # Make a thread missing reply evidence
        session["items"]["github-thread:THREAD_DONE"].pop("reply_evidence")
        # Make a local finding missing validation evidence
        session["items"]["local-finding:FIXED"].pop("validation_evidence")

        result = self.evaluate(
            session,
            remote_threads=[{"id": "THREAD_DONE", "isResolved": True}],
        )

        telemetry_report = {
            "coverage_label": "unavailable",
            "total_events": 0,
            "success_rate": 0.0,
            "inefficiency_flags": [],
            "report_artifact": "path/to/report.json",
        }
        guidance = build_completion_summary_guidance(result, telemetry_report, summary_path=None)

        self.assertIn("Gate FAILED: Do not send completion summary. Recommended status update:", guidance)
        self.assertNotIn("success rate below 100%", guidance)
        self.assertIn("1 threads missing reply", guidance)
        self.assertIn("1 local items missing validation", guidance)
        self.assertIn("Telemetry coverage is unavailable. No usable efficiency telemetry events exist for the current session.", guidance)
        self.assertIn("PR completion is blocked until all threads are resolved, reviews submitted, checks pass, reply/validation evidence is recorded, and all blocking items are addressed.", guidance)

        # Test runtime-only coverage label
        telemetry_report["coverage_label"] = "runtime-only"
        guidance_runtime = build_completion_summary_guidance(result, telemetry_report, summary_path=None)
        self.assertIn("Telemetry coverage is runtime-only. This indicates that host-side telemetry was not explicitly", guidance_runtime)
