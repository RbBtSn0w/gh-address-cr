import unittest

from gh_address_cr.core import gate


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
        self.assertEqual(summary["gate_scope"], "final")  # #119: authoritative scope
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
        self.assertIn("gh-address-cr agent evidence add octo/example 77", summary["next_action"])
        self.assertIn("--reply-url", summary["next_action"])
        self.assertEqual(summary["reply_evidence_blockers"][0]["recoverability"], "reconcile")

    def test_historical_closed_thread_without_reply_evidence_is_non_blocking(self):
        result = self.evaluate(
            {
                "repo": "octo/example",
                "pr_number": "77",
                "items": {
                    "github-thread:THREAD_HISTORY": {
                        "item_id": "github-thread:THREAD_HISTORY",
                        "item_kind": "github_thread",
                        "thread_id": "THREAD_HISTORY",
                        "state": "closed",
                        "status": "CLOSED",
                        "historical_remote_only": True,
                        "blocking": False,
                    }
                },
            },
            remote_threads=[{"id": "THREAD_HISTORY", "isResolved": True}],
        )

        self.assertTrue(result.passed, result.to_machine_summary())
        self.assertEqual(result.counts["github_threads_missing_reply_count"], 0)
        summary = result.to_machine_summary()
        self.assertEqual(summary["historical_reply_items"][0]["reason_code"], "CLOSED_HISTORICAL_ITEM")
        self.assertEqual(summary["historical_reply_items"][0]["recoverability"], "non_blocking")

    def test_historical_closed_thread_without_remote_fact_still_blocks(self):
        result = self.evaluate(
            {
                "repo": "octo/example",
                "pr_number": "77",
                "items": {
                    "github-thread:THREAD_HISTORY": {
                        "item_id": "github-thread:THREAD_HISTORY",
                        "item_kind": "github_thread",
                        "thread_id": "THREAD_HISTORY",
                        "state": "closed",
                        "status": "CLOSED",
                        "historical_remote_only": True,
                        "blocking": False,
                    }
                },
            },
            remote_threads=[],
        )

        self.assertFalse(result.passed)
        self.assertEqual(result.reason_code, "FINAL_GATE_MISSING_REPLY_EVIDENCE")
        summary = result.to_machine_summary()
        self.assertEqual(summary["reply_evidence_blockers"][0]["recoverability"], "reconcile")
        self.assertEqual(summary["historical_reply_items"], [])

    def test_historical_non_terminal_thread_with_resolved_remote_still_blocks(self):
        result = self.evaluate(
            {
                "repo": "octo/example",
                "pr_number": "77",
                "items": {
                    "github-thread:THREAD_HISTORY": {
                        "item_id": "github-thread:THREAD_HISTORY",
                        "item_kind": "github_thread",
                        "thread_id": "THREAD_HISTORY",
                        "state": "open",
                        "status": "OPEN",
                        "historical_remote_only": True,
                        "blocking": True,
                    }
                },
            },
            remote_threads=[{"id": "THREAD_HISTORY", "isResolved": True}],
        )

        self.assertFalse(result.passed)
        self.assertEqual(result.reason_code, "FINAL_GATE_MISSING_REPLY_EVIDENCE")
        summary = result.to_machine_summary()
        self.assertEqual(summary["reply_evidence_blockers"][0]["recoverability"], "reconcile")
        self.assertEqual(summary["historical_reply_items"], [])

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

    def test_terminal_local_finding_with_failing_validation_fails(self):
        # #117: failing validation logs must not satisfy the gate.
        session = self.passing_session()
        session["items"]["local-finding:FIXED"]["validation_evidence"] = [
            {"command": "python3 -m unittest", "result": "failed"}
        ]

        result = self.evaluate(
            session,
            remote_threads=[{"id": "THREAD_DONE", "isResolved": True}],
        )

        self.assertFalse(result.passed)
        self.assertEqual(result.reason_code, "FINAL_GATE_MISSING_VALIDATION_EVIDENCE")
        self.assertEqual(result.counts["missing_validation_evidence_count"], 1)

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
            "confidence": "high",
            "total_observed_duration_ms": 91234,
            "sources": [
                {"source": "runtime", "source_type": "runtime", "event_count": 2, "coverage_status": "available"},
                {"source": "codex", "source_type": "host-adapter", "event_count": 8, "coverage_status": "available"},
            ],
            "slowest_operations": [
                {"source": "codex", "operation": "run unit tests", "duration_ms": 89105, "status": "success"},
            ],
            "inefficiency_flags": [],
            "diagnostics": [],
            "report_artifact": "path/to/report.json",
        }
        guidance = build_completion_summary_guidance(result, telemetry_report, summary_path=None)
        summary_line = build_completion_summary_line(result, telemetry_report)

        self.assertEqual(
            summary_line,
            "[gh-address-cr: PASSED | threads: 0 | reviews: 0 | checks: N/A | telemetry: complete/high (10 events, 100.0%) | sources: runtime 2; codex 8 | duration: 91.2s observed | slowest: run unit tests 89.1s success | issues: none]",
        )
        self.assertEqual(guidance.count(summary_line), 1)
        self.assertNotIn("Attention Items", guidance)
        self.assertNotIn("IMPLICATION PROMPT", guidance)

    def test_build_completion_summary_line_reports_runtime_only_telemetry_for_issue_103(self):
        from gh_address_cr.commands.final_gate import build_completion_summary_line, build_completion_summary_model
        result = self.evaluate(
            self.passing_session(),
            remote_threads=[{"id": "THREAD_DONE", "isResolved": True}],
        )
        telemetry_report = {
            "coverage_label": "runtime-only",
            "total_events": 2,
            "success_rate": 100.0,
            "confidence": "medium",
            "total_observed_duration_ms": 0,
            "sources": [
                {"source": "runtime", "source_type": "runtime", "event_count": 2, "coverage_status": "available"},
            ],
            "slowest_operations": [],
            "inefficiency_flags": [],
            "report_artifact": "path/to/report.json",
        }

        summary_line = build_completion_summary_line(result, telemetry_report)
        summary_model = build_completion_summary_model(result, telemetry_report)

        self.assertEqual(
            summary_line,
            "[gh-address-cr: PASSED | threads: 0 | reviews: 0 | checks: N/A | telemetry: runtime-only/medium (2 events, 100.0%; runtime only, no host import) | sources: runtime 2 | duration: no observed duration | slowest: none | issues: none]",
        )
        self.assertIn("host telemetry was not imported", summary_model["coverage_note"])
        self.assertIn("runtime command events only", summary_model["coverage_note"])

    def test_runtime_only_telemetry_does_not_trigger_abnormal_guidance(self):
        from gh_address_cr.commands.final_gate import build_completion_summary_guidance

        result = self.evaluate(
            self.passing_session(),
            remote_threads=[{"id": "THREAD_DONE", "isResolved": True}],
        )
        telemetry_report = {
            "coverage_label": "runtime-only",
            "total_events": 2,
            "success_rate": 100.0,
            "confidence": "medium",
            "inefficiency_flags": [],
            "report_artifact": "path/to/report.json",
        }

        guidance = build_completion_summary_guidance(result, telemetry_report, summary_path=None)

        self.assertNotIn("Attention Items & Implications", guidance)
        self.assertNotIn("IMPLICATION PROMPT", guidance)

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
            "error_prone_operations": [
                {
                    "operation": "agent publish",
                    "events": 3,
                    "failures": 1,
                    "timeouts": 0,
                    "retries": 2,
                    "sources": ["runtime"],
                }
            ],
            "diagnostics": ["TELEMETRY_OVERHEAD_EXCEEDED"],
            "report_artifact": "path/to/report.json",
        }

        summary_line = build_completion_summary_line(result, telemetry_report)

        self.assertIn("issues: success 66.7%; flags: excessive_loops; repeated_failures", summary_line)
        self.assertIn("agent publish failures=1 timeouts=0 retries=2", summary_line)
        self.assertIn("diagnostics: TELEMETRY_OVERHEAD_EXCEEDED]", summary_line)

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
            "[gh-address-cr: PASSED | threads: 0 | reviews: 0 | checks: N/A | telemetry: partial/medium (0 events, 0.0%) | sources: none | duration: no observed duration | slowest: none | issues: flags: retry-loop]",
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
            "[gh-address-cr: PASSED | threads: 0 | reviews: 0 | checks: N/A | telemetry: partial/medium (2 events, 0.0%) | sources: none | duration: no observed duration | slowest: none | issues: success 0.0%]",
        )

    def test_build_completion_summary_line_normalizes_non_finite_total_events(self):
        from gh_address_cr.commands.final_gate import build_completion_summary_line

        result = self.evaluate(
            self.passing_session(),
            remote_threads=[{"id": "THREAD_DONE", "isResolved": True}],
        )
        telemetry_report = {
            "coverage_label": "partial",
            "total_events": float("inf"),
            "success_rate": 100.0,
            "inefficiency_flags": [],
            "report_artifact": "path/to/report.json",
        }

        summary_line = build_completion_summary_line(result, telemetry_report)

        self.assertEqual(
            summary_line,
            "[gh-address-cr: PASSED | threads: 0 | reviews: 0 | checks: N/A | telemetry: partial/medium (0 events, 100.0%) | sources: none | duration: no observed duration | slowest: none | issues: none]",
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
            "[gh-address-cr: FAILED | threads: 0 | reviews: 0 | checks: 1/1 | telemetry: complete/high (4 events, 100.0%) | sources: none | duration: no observed duration | slowest: none | issues: none]",
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

        self.assertIn("[gh-address-cr: FAILED | threads: 1 | reviews: 0 | checks: N/A | telemetry: partial/medium (5 events, 80.0%) | sources: none | duration: no observed duration | slowest: none | issues: success 80.0%; flags: excessive_loops]", guidance)
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

    def test_logic_validation_blocker_next_action_points_to_validation_reconcile_command(self):
        session = self.passing_session()
        thread = session["items"]["github-thread:THREAD_DONE"]
        thread["state"] = "published"
        thread["status"] = "CLOSED"
        thread["decision"] = "fix"
        thread["classification_evidence"] = {"classification": "fix"}
        thread["reply_evidence"] = {"reply_url": "https://example.test/reply", "author_login": "agent-login"}
        thread.pop("validation_evidence")

        result = self.evaluate(
            session,
            remote_threads=[{"id": "THREAD_DONE", "isResolved": True}],
        )

        summary = result.to_machine_summary()
        self.assertEqual(summary["reason_code"], "FINAL_GATE_LOGIC_VALIDATION_BLOCKING")
        self.assertIn("agent evidence add", summary["next_action"])
        self.assertIn("--item-id github-thread:THREAD_DONE", summary["next_action"])

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
        self.assertNotIn("Telemetry coverage is runtime-only.", guidance_runtime)

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
        self.assertIn("[gh-address-cr: PASSED | threads: 0 | reviews: 0 | checks: N/A | telemetry: unavailable/low (0 events, 0.0%) | sources: none | duration: no observed duration | slowest: none | issues: none]", guidance)

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
            "[gh-address-cr: PASSED | threads: 0 | reviews: 0 | checks: N/A | telemetry: partial/medium (0 events, 0.0%) | sources: none | duration: no observed duration | slowest: none | issues: flags: retry-loop; diagnostics: host telemetry degraded]",
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
            "[gh-address-cr: PASSED | threads: 0 | reviews: 0 | checks: N/A | telemetry: partial/medium (1 events, 100.0%) | sources: none | duration: no observed duration | slowest: none | issues: none]",
            guidance,
        )
        self.assertNotIn("inefficiency flags present", guidance)

    def test_build_completion_summary_guidance_treats_falsey_scalar_list_fields_as_absent(self):
        from gh_address_cr.commands.final_gate import build_completion_summary_guidance

        result = self.evaluate(
            self.passing_session(),
            remote_threads=[{"id": "THREAD_DONE", "isResolved": True}],
        )
        telemetry_report = {
            "coverage_label": "partial",
            "total_events": 1,
            "success_rate": 100.0,
            "inefficiency_flags": False,
            "diagnostics": 0,
            "report_artifact": "report.json",
        }

        guidance = build_completion_summary_guidance(result, telemetry_report, summary_path=None)

        self.assertIn(
            "[gh-address-cr: PASSED | threads: 0 | reviews: 0 | checks: N/A | telemetry: partial/medium (1 events, 100.0%) | sources: none | duration: no observed duration | slowest: none | issues: none]",
            guidance,
        )
        self.assertNotIn("inefficiency flags present", guidance)
        self.assertNotIn("Telemetry diagnostics:", guidance)
