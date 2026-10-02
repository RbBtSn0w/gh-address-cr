"""Spec 039 R1: needs-action outcomes are counted separately from failures (#307)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from gh_address_cr.core import protocol_codes
from gh_address_cr.core.stack_gate import StackGateResult
from gh_address_cr.core.telemetry_runtime import SessionTelemetry, classify_command_outcome


class ClassifyCommandOutcomeTests(unittest.TestCase):
    def test_policy_table(self):
        cases = [
            (0, None, "success"),
            (0, "PASSED", "success"),
            (5, "WAITING_FOR_SIMPLE_ADDRESS", "needs_action"),
            (5, "BLOCKING_ITEMS_REMAIN", "needs_action"),
            (5, "FINAL_GATE_UNRESOLVED_REMOTE_THREADS", "needs_action"),
            (5, "FINAL_GATE_MISSING_REPLY_EVIDENCE", "needs_action"),
            (5, "FINAL_GATE_REQUIRED_CHECKS_MISSING", "needs_action"),
            # exit 5 is also used for errors and rejected agent input; those stay failures.
            (5, None, "failure"),
            (5, "SESSION_ERROR", "failure"),
            (5, "INVALID_FINDINGS_INPUT", "failure"),
            (5, "MISSING_CLASSIFICATION", "failure"),
            (5, "GH_NETWORK_FAILED", "failure"),
            # A needs-action reason code only counts with the documented exit code.
            (2, "WAITING_FOR_SIMPLE_ADDRESS", "failure"),
            (124, None, "timeout"),
            (1, None, "failure"),
        ]
        for exit_code, reason_code, expected in cases:
            with self.subTest(exit_code=exit_code, reason_code=reason_code):
                self.assertEqual(classify_command_outcome(exit_code, reason_code), expected)


class StackGateBlockingReasonTests(unittest.TestCase):
    def stack_result(self, reason_code, member_outcomes=()):
        return StackGateResult(
            repo="octo/example",
            selected_pr_number="2",
            stack_context=None,  # not read by blocking_reason_code
            covered_pr_numbers=("1", "2"),
            member_outcomes=tuple(member_outcomes),
            reason_code=reason_code,
            first_blocked_pr_number="1",
        )

    def test_member_block_reports_the_member_gate_reason(self):
        result = self.stack_result(
            protocol_codes.STACK_MEMBER_BLOCKED,
            [{"pr_number": "1", "layer_reason_code": "FINAL_GATE_UNRESOLVED_REMOTE_THREADS"}],
        )

        self.assertEqual(result.blocking_reason_code, "FINAL_GATE_UNRESOLVED_REMOTE_THREADS")
        self.assertEqual(classify_command_outcome(result.exit_code, result.blocking_reason_code), "needs_action")

    def test_stack_context_failure_stays_a_failure(self):
        result = self.stack_result(protocol_codes.STACK_CONTEXT_INVALID)

        self.assertEqual(result.blocking_reason_code, protocol_codes.STACK_CONTEXT_INVALID)
        self.assertEqual(classify_command_outcome(result.exit_code, result.blocking_reason_code), "failure")


class NeedsActionRetryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.tracker = SessionTelemetry()
        self.tracker.configure_file(Path(self.temp_dir.name) / "telemetry.jsonl")

    def test_repeating_a_needs_action_command_is_not_a_retry(self):
        self.tracker.record("gh-address-cr address", 0, 1, 5, outcome="needs_action")
        self.tracker.record("gh-address-cr address", 2, 3, 5, outcome="needs_action")

        self.assertEqual([metric.is_retry for metric in self.tracker.metrics], [False, False])
        self.assertEqual([metric.outcome for metric in self.tracker.metrics], ["needs_action", "needs_action"])

    def test_repeating_a_failed_command_is_still_a_retry(self):
        self.tracker.record("gh-address-cr address", 0, 1, 5, outcome="failure")
        self.tracker.record("gh-address-cr address", 2, 3, 0, outcome="success")

        self.assertEqual([metric.is_retry for metric in self.tracker.metrics], [False, True])

    def test_outcome_survives_the_jsonl_round_trip(self):
        self.tracker.record("gh-address-cr address", 0, 1, 5, outcome="needs_action")

        reloaded = SessionTelemetry()
        reloaded.configure_file(Path(self.temp_dir.name) / "telemetry.jsonl")

        self.assertEqual([metric.outcome for metric in reloaded.metrics], ["needs_action"])


if __name__ == "__main__":
    unittest.main()
