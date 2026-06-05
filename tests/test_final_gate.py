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
    def evaluate(
        self,
        session,
        *,
        remote_threads=None,
        pending_reviews=None,
        current_login="agent-login",
        check_runs=None,
        check_requirement=None,
    ):
        gate = load_gate_module()
        return gate.evaluate_final_gate(
            session,
            remote_threads=remote_threads or [],
            pending_reviews=pending_reviews or [],
            current_login=current_login,
            check_runs=check_runs or [],
            check_requirement=check_requirement,
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
                    "validation_evidence": [{"command": "python3 -m unittest tests.test_final_gate", "exit_code": 0}],
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
                "logic_validation_blocking_count": 0,
                "logic_validation_advisory_count": 0,
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

    def test_blocking_github_items_fail(self):
        session = self.passing_session()
        session["items"]["github-thread:THREAD_BLOCKED"] = {
            "item_id": "github-thread:THREAD_BLOCKED",
            "item_kind": "github_thread",
            "thread_id": "THREAD_BLOCKED",
            "state": "publish_ready",
            "blocking": True,
        }

        result = self.evaluate(
            session,
            remote_threads=[{"id": "THREAD_DONE", "isResolved": True}],
        )

        self.assertFalse(result.passed)
        self.assertEqual(result.reason_code, "FINAL_GATE_BLOCKING_GITHUB_ITEMS")
        self.assertEqual(result.failure_codes, ["FINAL_GATE_BLOCKING_GITHUB_ITEMS"])
        self.assertEqual(result.counts["blocking_github_items_count"], 1)
        self.assertEqual(result.counts["blocking_items_count"], 1)
        self.assertEqual(result.to_machine_summary()["waiting_on"], "github_items")

    def test_terminal_local_finding_without_validation_evidence_fails(self):
        session = self.passing_session()
        session["items"]["local-finding:FIXED"].pop("validation_evidence")

        result = self.evaluate(
            session,
            remote_threads=[{"id": "THREAD_DONE", "isResolved": True}],
        )

        self.assertFalse(result.passed)
        self.assertEqual(result.reason_code, "FINAL_GATE_MISSING_VALIDATION_EVIDENCE")
        self.assertEqual(
            result.failure_codes,
            ["FINAL_GATE_MISSING_VALIDATION_EVIDENCE", "FINAL_GATE_LOGIC_VALIDATION_BLOCKING"],
        )
        self.assertEqual(result.counts["missing_validation_evidence_count"], 1)
        self.assertEqual(result.to_machine_summary()["waiting_on"], "validation_evidence")

    def test_logic_validation_blocking_signal_fails_final_gate(self):
        session = self.passing_session()
        session["items"]["github-thread:THREAD_DONE"]["completion_claim"] = "ready_to_publish"
        session["items"]["github-thread:THREAD_DONE"]["state"] = "open"

        result = self.evaluate(session, remote_threads=[{"id": "THREAD_DONE", "isResolved": True}])

        self.assertFalse(result.passed)
        self.assertIn("FINAL_GATE_LOGIC_VALIDATION_BLOCKING", result.failure_codes)
        self.assertEqual(result.counts["logic_validation_blocking_count"], 1)
        summary = result.to_machine_summary()
        self.assertEqual(summary["logic_validation_signals"][0]["signal_type"], "state_contradiction")

    def test_missing_required_evidence_counts_as_blocking_logic_validation(self):
        session = self.passing_session()
        session["items"]["local-finding:FIXED"].pop("validation_evidence")

        result = self.evaluate(session, remote_threads=[{"id": "THREAD_DONE", "isResolved": True}])

        blocking_signals = [
            signal
            for signal in result.to_machine_summary()["logic_validation_signals"]
            if signal["gate_effect"] == "blocking"
        ]
        self.assertEqual(len(blocking_signals), 1)
        self.assertEqual(blocking_signals[0]["signal_type"], "missing_required_evidence")
        self.assertEqual(result.counts["logic_validation_blocking_count"], len(blocking_signals))

    def test_logic_validation_advisory_signal_does_not_block_final_gate(self):
        session = self.passing_session()
        session["items"]["github-thread:THREAD_DONE"]["logic_confidence"] = "low"

        result = self.evaluate(session, remote_threads=[{"id": "THREAD_DONE", "isResolved": True}])

        self.assertTrue(result.passed)
        self.assertEqual(result.counts["logic_validation_advisory_count"], 1)
        self.assertEqual(result.to_machine_summary()["logic_validation_signals"][0]["gate_effect"], "advisory")

    def test_failed_and_pending_checks_fail_when_required(self):
        result = self.evaluate(
            self.passing_session(),
            remote_threads=[{"id": "THREAD_DONE", "isResolved": True}],
            check_runs=[
                {"name": "unit", "state": "failure"},
                {"name": "lint", "state": "queued"},
                {"name": "docs", "state": "success"},
            ],
            check_requirement="all",
        )

        self.assertFalse(result.passed)
        self.assertEqual(result.reason_code, "FINAL_GATE_PR_CHECKS_NOT_GREEN")
        self.assertEqual(result.failure_codes, ["FINAL_GATE_PR_CHECKS_NOT_GREEN"])
        self.assertEqual(result.counts["pr_checks_count"], 3)
        self.assertEqual(result.counts["pr_checks_failed_count"], 1)
        self.assertEqual(result.counts["pr_checks_pending_count"], 1)
        self.assertEqual(result.counts["pr_checks_not_green_count"], 2)
        self.assertEqual(result.check_requirement, "all")
        self.assertEqual(result.to_machine_summary()["waiting_on"], "checks")

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
                "FINAL_GATE_LOGIC_VALIDATION_BLOCKING",
            ],
        )
        self.assertEqual(result.reason_code, "FINAL_GATE_UNRESOLVED_REMOTE_THREADS")

    def test_build_completion_summary_guidance_clean(self):
        from gh_address_cr.commands.final_gate import build_completion_summary_guidance, build_completion_summary_line
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
        summary_line = build_completion_summary_line(result, telemetry_report)

        self.assertEqual(
            summary_line,
            "[gh-address-cr: PASSED | threads: 0 | reviews: 0 | checks: N/A | telemetry: complete (10 events, 100.0%) | inefficiency: none]",
        )
        self.assertEqual(guidance.count(summary_line), 1)
        self.assertNotIn("Attention Items", guidance)
        self.assertNotIn("IMPLICATION PROMPT", guidance)

    def test_build_completion_summary_line_reports_runtime_only_telemetry_for_issue_103(self):
        from gh_address_cr.commands.final_gate import build_completion_summary_line
        result = self.evaluate(
            self.passing_session(),
            remote_threads=[{"id": "THREAD_DONE", "isResolved": True}],
        )
        telemetry_report = {
            "coverage_label": "runtime-only",
            "total_events": 10,
            "success_rate": 100.0,
            "inefficiency_flags": [],
            "report_artifact": "path/to/report.json",
        }

        summary_line = build_completion_summary_line(result, telemetry_report)

        self.assertEqual(
            summary_line,
            "[gh-address-cr: PASSED | threads: 0 | reviews: 0 | checks: N/A | telemetry: runtime-only (10 events, 100.0%) | inefficiency: none]",
        )

    def test_build_completion_summary_line_renders_inefficiency_flags(self):
        from gh_address_cr.commands.final_gate import build_completion_summary_line
        result = self.evaluate(
            self.passing_session(),
            remote_threads=[{"id": "THREAD_DONE", "isResolved": True}],
        )
        telemetry_report = {
            "coverage_label": "partial",
            "total_events": 3,
            "success_rate": 66.7,
            "inefficiency_flags": ["excessive_loops", "repeated_failures"],
            "report_artifact": "path/to/report.json",
        }

        summary_line = build_completion_summary_line(result, telemetry_report)

        self.assertIn("inefficiency: excessive_loops; repeated_failures]", summary_line)

    def test_build_completion_summary_line_tolerates_malformed_telemetry_fields(self):
        from gh_address_cr.commands.final_gate import build_completion_summary_line
        result = self.evaluate(
            self.passing_session(),
            remote_threads=[{"id": "THREAD_DONE", "isResolved": True}],
        )
        telemetry_report = {
            "coverage_label": "partial",
            "total_events": "not-a-number",
            "success_rate": "also-not-a-number",
            "inefficiency_flags": "retry-loop",
            "report_artifact": "path/to/report.json",
        }

        summary_line = build_completion_summary_line(result, telemetry_report)

        self.assertEqual(
            summary_line,
            "[gh-address-cr: PASSED | threads: 0 | reviews: 0 | checks: N/A | telemetry: partial (0 events, 0.0%) | inefficiency: retry-loop]",
        )

    def test_build_completion_summary_line_normalizes_non_finite_success_rate(self):
        from gh_address_cr.commands.final_gate import build_completion_summary_line

        result = self.evaluate(
            self.passing_session(),
            remote_threads=[{"id": "THREAD_DONE", "isResolved": True}],
        )
        telemetry_report = {
            "coverage_label": "partial",
            "total_events": 2,
            "success_rate": "NaN",
            "inefficiency_flags": [],
            "report_artifact": "path/to/report.json",
        }

        summary_line = build_completion_summary_line(result, telemetry_report)

        self.assertEqual(
            summary_line,
            "[gh-address-cr: PASSED | threads: 0 | reviews: 0 | checks: N/A | telemetry: partial (2 events, 0.0%) | inefficiency: none]",
        )

    def test_build_completion_summary_line_reports_required_check_counts(self):
        from gh_address_cr.commands.final_gate import build_completion_summary_line
        result = self.evaluate(
            self.passing_session(),
            remote_threads=[{"id": "THREAD_DONE", "isResolved": True}],
            check_runs=[
                {"name": "unit", "state": "failure"},
                {"name": "lint", "state": "queued"},
                {"name": "docs", "state": "success"},
            ],
            check_requirement="all",
        )
        telemetry_report = {
            "coverage_label": "complete",
            "total_events": 4,
            "success_rate": 100.0,
            "inefficiency_flags": [],
            "report_artifact": "path/to/report.json",
        }

        summary_line = build_completion_summary_line(result, telemetry_report)

        self.assertEqual(
            summary_line,
            "[gh-address-cr: FAILED | threads: 0 | reviews: 0 | checks: 1/1 | telemetry: complete (4 events, 100.0%) | inefficiency: none]",
        )

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

    def test_completion_summary_guidance_reports_logic_validation_blockers(self):
        from gh_address_cr.commands.final_gate import build_completion_summary_guidance
        session = self.passing_session()
        session["items"]["github-thread:THREAD_DONE"]["classification_evidence"] = {"classification": "fix"}
        session["items"]["github-thread:THREAD_DONE"].pop("validation_evidence")

        result = self.evaluate(
            session,
            remote_threads=[{"id": "THREAD_DONE", "isResolved": True}],
        )
        telemetry_report = {
            "coverage_label": "complete",
            "total_events": 1,
            "success_rate": 100.0,
            "inefficiency_flags": [],
            "report_artifact": "path/to/report.json",
        }

        guidance = build_completion_summary_guidance(result, telemetry_report, summary_path=None)

        self.assertIn("Gate FAILED: Do not send completion summary. Recommended status update:", guidance)
        self.assertIn("1 blocking logic-validation signals", guidance)

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

    def test_completion_summary_guidance_keeps_telemetry_degradation_fail_open(self):
        from gh_address_cr.commands.final_gate import build_completion_summary_guidance
        result = self.evaluate(
            self.passing_session(),
            remote_threads=[{"id": "THREAD_DONE", "isResolved": True}],
        )
        telemetry_report = {
            "coverage_label": "partial",
            "total_events": 1,
            "success_rate": 100.0,
            "inefficiency_flags": [],
            "diagnostics": ["TELEMETRY_OVERHEAD_EXCEEDED"],
            "report_artifact": "/tmp/efficiency-report.json",
        }

        guidance = build_completion_summary_guidance(result, telemetry_report, summary_path=None)

        self.assertTrue(result.passed)
        self.assertIn("telemetry: partial", guidance)
        self.assertIn("Telemetry diagnostics: TELEMETRY_OVERHEAD_EXCEEDED", guidance)

    def test_build_completion_summary_guidance_none_telemetry_fields(self):
        from gh_address_cr.commands.final_gate import build_completion_summary_guidance
        result = self.evaluate(
            self.passing_session(),
            remote_threads=[{"id": "THREAD_DONE", "isResolved": True}],
        )
        telemetry_report = {
            "coverage_label": None,
            "total_events": None,
            "success_rate": None,
            "inefficiency_flags": None,
            "report_artifact": None,
        }
        guidance = build_completion_summary_guidance(result, telemetry_report, summary_path=None)
        self.assertIn("[gh-address-cr: PASSED | threads: 0 | reviews: 0 | checks: N/A | telemetry: unavailable (0 events, 0.0%) | inefficiency: none]", guidance)

    def test_build_completion_summary_guidance_tolerates_malformed_telemetry_fields(self):
        from gh_address_cr.commands.final_gate import build_completion_summary_guidance

        result = self.evaluate(
            self.passing_session(),
            remote_threads=[{"id": "THREAD_DONE", "isResolved": True}],
        )
        telemetry_report = {
            "coverage_label": "partial",
            "total_events": "NaN",
            "success_rate": "oops",
            "inefficiency_flags": "retry-loop",
            "diagnostics": "host telemetry degraded",
            "report_artifact": "report.json",
        }

        guidance = build_completion_summary_guidance(result, telemetry_report, summary_path=None)

        self.assertIn(
            "[gh-address-cr: PASSED | threads: 0 | reviews: 0 | checks: N/A | telemetry: partial (0 events, 0.0%) | inefficiency: retry-loop]",
            guidance,
        )
        self.assertIn("Telemetry diagnostics: host telemetry degraded", guidance)

    def test_build_completion_summary_guidance_filters_blank_inefficiency_flags(self):
        from gh_address_cr.commands.final_gate import build_completion_summary_guidance

        result = self.evaluate(
            self.passing_session(),
            remote_threads=[{"id": "THREAD_DONE", "isResolved": True}],
        )
        telemetry_report = {
            "coverage_label": "partial",
            "total_events": 1,
            "success_rate": 100.0,
            "inefficiency_flags": "",
            "diagnostics": "",
            "report_artifact": "report.json",
        }

        guidance = build_completion_summary_guidance(result, telemetry_report, summary_path=None)

        self.assertIn(
            "[gh-address-cr: PASSED | threads: 0 | reviews: 0 | checks: N/A | telemetry: partial (1 events, 100.0%) | inefficiency: none]",
            guidance,
        )
        self.assertNotIn("inefficiency flags present", guidance)
