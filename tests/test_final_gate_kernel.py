import sys
import unittest

from tests.helpers import SRC_ROOT

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


class FinalGateKernelTestIntent:
    risk = "Final-gate completion can drift when remote threads, local findings, reviews, checks, and validation evidence are counted in scattered branches."
    why_automation = "The gate decision is deterministic projection and policy logic that should replay without GitHub IO or artifact writes."
    why_existing_tests_insufficient = (
        "Existing gate tests assert the facade behavior, but not the pure runtime-kernel facts-to-policy boundary."
    )
    chosen_layer = "Unit Test - pure runtime logic is the smallest effective layer."
    fragility_analysis = "Tests assert public counts and failure codes, not private helper call order."
    if_omitted = "A later CLI refactor could preserve visible summaries while reintroducing hidden state flags or branch-only completion logic."


def passing_session():
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
                "validation_evidence": [{"command": "python3 -m unittest", "exit_code": 0}],
            },
            "local-finding:FIXED": {
                "item_id": "local-finding:FIXED",
                "item_kind": "local_finding",
                "state": "fixed",
                "blocking": False,
                "validation_evidence": [{"command": "python3 -m unittest", "exit_code": 0}],
            },
        },
    }


class FinalGateKernelTests(unittest.TestCase):
    def test_projection_and_policy_pass_for_clean_facts(self):
        from gh_address_cr.core.runtime_kernel.final_gate import (
            COUNT_KEYS,
            build_final_gate_facts,
            evaluate_final_gate_policy,
            project_final_gate,
        )

        facts = build_final_gate_facts(
            passing_session(),
            remote_threads=[{"id": "THREAD_DONE", "isResolved": True}],
            current_login="agent-login",
        )
        projection = project_final_gate(facts, current_login="agent-login")
        decision = evaluate_final_gate_policy(projection)

        self.assertEqual(tuple(projection.counts.keys()), COUNT_KEYS)
        self.assertTrue(all(value == 0 for value in projection.counts.values()))
        self.assertEqual(decision.failure_codes, ())
        self.assertIsNone(decision.reason_code)
        self.assertIsNone(decision.waiting_on)

    def test_policy_reports_all_blockers_in_existing_failure_order(self):
        from gh_address_cr.core.runtime_kernel.final_gate import (
            build_final_gate_facts,
            evaluate_final_gate_policy,
            project_final_gate,
        )

        session = passing_session()
        session["items"]["github-thread:THREAD_DONE"].pop("reply_evidence")
        session["items"]["github-thread:THREAD_BLOCKED"] = {
            "item_id": "github-thread:THREAD_BLOCKED",
            "item_kind": "github_thread",
            "thread_id": "THREAD_BLOCKED",
            "state": "publish_ready",
            "blocking": True,
        }
        session["items"]["local-finding:FIXED"].pop("validation_evidence")
        session["items"]["local-finding:OPEN"] = {
            "item_id": "local-finding:OPEN",
            "item_kind": "local_finding",
            "state": "open",
            "blocking": True,
        }

        facts = build_final_gate_facts(
            session,
            remote_threads=[
                {"id": "THREAD_DONE", "isResolved": True},
                {"id": "THREAD_OPEN", "isResolved": False},
            ],
            pending_reviews=[{"id": "review-agent", "state": "PENDING", "user": {"login": "agent-login"}}],
            current_login="agent-login",
            check_runs=[
                {"name": "unit", "state": "failure"},
                {"name": "lint", "state": "queued"},
            ],
            check_requirement="all",
            logic_validation_signals=[
                {
                    "signal_type": "manual_blocker",
                    "gate_effect": "blocking",
                    "item_id": "local-finding:FIXED",
                }
            ],
        )
        projection = project_final_gate(facts, current_login="agent-login", check_requirement="all")
        decision = evaluate_final_gate_policy(projection)

        self.assertEqual(
            list(decision.failure_codes),
            [
                "FINAL_GATE_UNRESOLVED_REMOTE_THREADS",
                "FINAL_GATE_MISSING_REPLY_EVIDENCE",
                "FINAL_GATE_PENDING_CURRENT_LOGIN_REVIEW",
                "FINAL_GATE_BLOCKING_GITHUB_ITEMS",
                "FINAL_GATE_BLOCKING_LOCAL_ITEMS",
                "FINAL_GATE_MISSING_VALIDATION_EVIDENCE",
                "FINAL_GATE_LOGIC_VALIDATION_BLOCKING",
                "FINAL_GATE_PR_CHECKS_NOT_GREEN",
            ],
        )
        self.assertEqual(decision.reason_code, "FINAL_GATE_UNRESOLVED_REMOTE_THREADS")
        self.assertEqual(decision.waiting_on, "remote_threads")
        self.assertEqual(projection.counts["unresolved_remote_threads_count"], 1)
        self.assertEqual(projection.counts["github_threads_missing_reply_count"], 1)
        self.assertEqual(projection.counts["pending_current_login_review_count"], 1)
        self.assertEqual(projection.counts["blocking_github_items_count"], 1)
        self.assertEqual(projection.counts["blocking_local_items_count"], 1)
        self.assertEqual(projection.counts["missing_validation_evidence_count"], 1)
        self.assertEqual(projection.counts["logic_validation_blocking_count"], 1)
        self.assertEqual(projection.counts["pr_checks_not_green_count"], 2)


if __name__ == "__main__":
    unittest.main()
