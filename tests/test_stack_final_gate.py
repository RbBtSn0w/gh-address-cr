import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from gh_address_cr.core.gate import GateResult
from gh_address_cr.core.runtime_kernel.stack import project_stack_context
from tests.helpers import stack_member, stack_observation


def layer_result(pr_number, *, passed=True, reason=None):
    return GateResult(
        repo="octo/example",
        pr_number=str(pr_number),
        counts={},
        failure_codes=[] if passed else [reason or "FINAL_GATE_BLOCKING_LOCAL_ITEMS"],
    )


class StackFinalGateTests(unittest.TestCase):
    def test_unavailable_stack_gate_reports_unknown_readiness(self):
        from gh_address_cr.core.stack_gate import evaluate_stack_gate

        context = project_stack_context(
            {
                "schema_version": "stack_observation.v1",
                "availability": "unavailable",
                "repo": "octo/example",
                "selected_pr_number": "102",
                "observed_at": "2026-08-01T12:00:00Z",
                "members": [],
            }
        )

        summary = evaluate_stack_gate(
            "octo/example",
            "102",
            context,
            session_exists=lambda pr: True,
            evaluate_member=lambda pr: layer_result(pr),
            closing_context=context,
        ).to_machine_summary()

        self.assertEqual(summary["reason_code"], "STACK_CONTEXT_UNAVAILABLE")
        self.assertEqual(summary["stack_merge_readiness"], "unknown")

    def test_member_evaluation_errors_preserve_their_original_type(self):
        from gh_address_cr.core.session import SessionError
        from gh_address_cr.core.stack_gate import evaluate_stack_gate

        context = project_stack_context(stack_observation(selected_pr_number="102"))
        with self.assertRaises(FileNotFoundError):
            evaluate_stack_gate(
                "octo/example",
                "102",
                context,
                session_exists=lambda pr: True,
                evaluate_member=lambda pr: (_ for _ in ()).throw(FileNotFoundError("missing.json")),
                closing_context=context,
            )

        invalid = evaluate_stack_gate(
            "octo/example",
            "102",
            context,
            session_exists=lambda pr: True,
            evaluate_member=lambda pr: (_ for _ in ()).throw(SessionError("INVALID_SESSION_JSON", "bad")),
            closing_context=context,
        )
        self.assertEqual(invalid.reason_code, "STACK_MEMBER_SESSION_INVALID")

    def test_stack_gate_uses_only_opening_and_closing_stack_observations(self):
        from gh_address_cr.core.session import SessionManager
        from gh_address_cr.core.stack_gate import run_stack_gate

        context = project_stack_context(stack_observation(selected_pr_number="102"))
        client = Mock()
        client.get_stack_context.return_value = context
        client.viewer_login.return_value = "agent-login"
        client.list_threads.return_value = []
        client.list_pending_reviews.return_value = []
        client.list_pr_checks.return_value = []
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                for pr_number in ("101", "102"):
                    manager = SessionManager("octo/example", pr_number)
                    manager.save(manager.create(status="WAITING_FOR_GATE"))

                result = run_stack_gate("octo/example", "102", github_client=client)

        self.assertTrue(result.passed)
        self.assertEqual(client.get_stack_context.call_count, 2)

    def test_machine_summary_and_result_record_requested_check_policy(self):
        from gh_address_cr.core.stack_gate import evaluate_stack_gate

        context = project_stack_context(stack_observation(selected_pr_number="102"))
        result = evaluate_stack_gate(
            "octo/example",
            "102",
            context,
            session_exists=lambda pr: True,
            evaluate_member=lambda pr: layer_result(pr),
            closing_context=context,
            check_requirement="required",
        )

        summary = result.to_machine_summary()
        self.assertEqual(result.check_requirement, "required")
        self.assertEqual(summary["check_requirement"], "required")
        self.assertEqual(summary["stack_gate"]["check_requirement"], "required")

    def test_member_draft_closed_and_queued_states_have_specific_reasons(self):
        from gh_address_cr.core.stack_gate import evaluate_stack_gate

        cases = (
            ({"is_draft": True}, "STACK_MEMBER_DRAFT"),
            ({"state": "CLOSED"}, "STACK_MEMBER_CLOSED"),
            ({"merge_queue_state": "queued"}, "STACK_MEMBER_QUEUED"),
        )
        for overrides, reason in cases:
            with self.subTest(reason=reason):
                member = stack_member(1, 101, base="main", head="feature/base", **overrides)
                upper = stack_member(2, 102, base="feature/base", head="feature/top")
                context = project_stack_context(
                    stack_observation(selected_pr_number="101", members=[member, upper])
                )
                result = evaluate_stack_gate(
                    "octo/example",
                    "101",
                    context,
                    session_exists=lambda pr: True,
                    evaluate_member=lambda pr: layer_result(pr),
                    closing_context=context,
                )

                self.assertEqual(result.reason_code, reason)

    def test_aggregate_evaluates_bottom_up_through_selected_member(self):
        from gh_address_cr.core.stack_gate import evaluate_stack_gate

        context = project_stack_context(stack_observation(selected_pr_number="102"))
        order = []

        result = evaluate_stack_gate(
            "octo/example",
            "102",
            context,
            session_exists=lambda pr: True,
            evaluate_member=lambda pr: order.append(pr) or layer_result(pr),
            closing_context=context,
        )

        self.assertTrue(result.passed)
        self.assertEqual(order, ["101", "102"])
        self.assertEqual(result.covered_pr_numbers, ("101", "102"))
        self.assertEqual(result.to_machine_summary()["completion_scope"], "stack_segment")

    def test_missing_session_and_nested_member_failure_are_stable_blockers(self):
        from gh_address_cr.core.stack_gate import evaluate_stack_gate

        context = project_stack_context(stack_observation(selected_pr_number="103"))
        result = evaluate_stack_gate(
            "octo/example",
            "103",
            context,
            session_exists=lambda pr: pr != "101",
            evaluate_member=lambda pr: layer_result(pr, passed=False),
            closing_context=context,
        )

        self.assertEqual(result.reason_code, "STACK_MEMBER_SESSION_MISSING")
        self.assertEqual(result.first_blocked_pr_number, "101")

    def test_nested_member_failure_returns_the_layer_recovery_action(self):
        from gh_address_cr.core.gate import FINAL_GATE_UNRESOLVED_REMOTE_THREADS
        from gh_address_cr.core.stack_gate import evaluate_stack_gate

        context = project_stack_context(stack_observation(selected_pr_number="102"))
        result = evaluate_stack_gate(
            "octo/example",
            "102",
            context,
            session_exists=lambda pr: True,
            evaluate_member=lambda pr: layer_result(
                pr,
                passed=False,
                reason=FINAL_GATE_UNRESOLVED_REMOTE_THREADS,
            ),
            closing_context=context,
        )

        summary = result.to_machine_summary()
        self.assertEqual(summary["reason_code"], "STACK_MEMBER_BLOCKED")
        self.assertEqual(summary["waiting_on"], "remote_threads")
        self.assertIn("gh-address-cr address octo/example 101 --lean", summary["next_action"])
        self.assertEqual(
            summary["commands"]["member_recovery"],
            "gh-address-cr address octo/example 101 --lean",
        )

    def test_missing_reply_member_recovery_reconciles_reply_evidence(self):
        from gh_address_cr.core.gate import FINAL_GATE_MISSING_REPLY_EVIDENCE
        from gh_address_cr.core.stack_gate import evaluate_stack_gate

        context = project_stack_context(stack_observation(selected_pr_number="102"))
        result = evaluate_stack_gate(
            "octo/example",
            "102",
            context,
            session_exists=lambda pr: True,
            evaluate_member=lambda pr: layer_result(
                pr,
                passed=False,
                reason=FINAL_GATE_MISSING_REPLY_EVIDENCE,
            ),
            closing_context=context,
        )

        summary = result.to_machine_summary()
        self.assertIn("agent evidence add octo/example 101", summary["commands"]["member_recovery"])
        self.assertIn("--reply-url", summary["commands"]["member_recovery"])
        self.assertNotIn("agent publish", summary["commands"]["member_recovery"])

    def test_local_revision_blocker_member_recovery_records_item_evidence(self):
        from gh_address_cr.core import protocol_codes
        from gh_address_cr.core.stack_gate import evaluate_stack_gate

        context = project_stack_context(stack_observation(selected_pr_number="102"))
        result = evaluate_stack_gate(
            "octo/example",
            "102",
            context,
            session_exists=lambda pr: True,
            evaluate_member=lambda pr: GateResult(
                repo="octo/example",
                pr_number=str(pr),
                counts={},
                failure_codes=[protocol_codes.FINAL_GATE_STALE_REVISION_EVIDENCE],
                logic_validation_signals=[
                    {
                        "item_id": "local:stale-finding",
                        "item_kind": "local_finding",
                        "signal_type": "stale_revision_evidence",
                        "gate_effect": "blocking",
                    }
                ],
            ),
            closing_context=context,
        )

        summary = result.to_machine_summary()
        self.assertIn("agent evidence add octo/example 101", summary["commands"]["member_recovery"])
        self.assertNotIn("gh-address-cr findings", summary["commands"]["member_recovery"])

    def test_blocking_local_member_recovery_uses_normal_review(self):
        from gh_address_cr.core.gate import FINAL_GATE_BLOCKING_LOCAL_ITEMS
        from gh_address_cr.core.stack_gate import evaluate_stack_gate

        context = project_stack_context(stack_observation(selected_pr_number="102"))
        result = evaluate_stack_gate(
            "octo/example",
            "102",
            context,
            session_exists=lambda pr: True,
            evaluate_member=lambda pr: layer_result(
                pr,
                passed=False,
                reason=FINAL_GATE_BLOCKING_LOCAL_ITEMS,
            ),
            closing_context=context,
        )

        recovery = result.to_machine_summary()["commands"]["member_recovery"]
        self.assertEqual(recovery, "gh-address-cr review octo/example 101")
        self.assertNotIn("--auto-simple", recovery)

    def test_closing_topology_change_suppresses_pass(self):
        from gh_address_cr.core.stack_gate import evaluate_stack_gate

        context = project_stack_context(stack_observation(selected_pr_number="102"))
        changed = stack_observation(selected_pr_number="102")
        changed["members"][1]["head_oid"] = "f" * 40
        result = evaluate_stack_gate(
            "octo/example",
            "102",
            context,
            session_exists=lambda pr: True,
            evaluate_member=lambda pr: layer_result(pr),
            closing_context=project_stack_context(changed),
        )

        self.assertFalse(result.passed)
        self.assertEqual(result.reason_code, "STACK_CONTEXT_STALE")


if __name__ == "__main__":
    unittest.main()
