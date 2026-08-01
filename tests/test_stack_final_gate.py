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
