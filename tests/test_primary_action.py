import unittest

from gh_address_cr.core.primary_action import (
    PRIMARY_ACTION_KINDS,
    build_recommendation_observation,
    project_context_summary,
    project_primary_action,
)
from gh_address_cr.core.runtime_kernel.stack import project_stack_context
from tests.helpers import stack_observation


class PrimaryActionProjectionTests(unittest.TestCase):
    def test_action_vocabulary_stays_minimal(self):
        self.assertEqual(
            PRIMARY_ACTION_KINDS,
            {"claim", "resolve", "publish", "wait", "run_final_gate", "repair_environment", "complete"},
        )

    def test_head_update_invalidates_recommendation_fingerprint(self):
        action = {
            "kind": "claim",
            "command": "gh-address-cr agent next octo/example 77",
            "item_id": "github-thread:1",
            "why_now": "Highest priority.",
            "requires_human": False,
        }
        session = {
            "items": {"github-thread:1": {"item_id": "github-thread:1", "state": "open"}},
            "metadata": {"pull_request_context": {"head_sha": "a" * 40}},
        }

        before = build_recommendation_observation(session, action, emitted_at="2026-08-31T00:00:00Z")
        session["metadata"]["pull_request_context"]["head_sha"] = "b" * 40
        after = build_recommendation_observation(session, action, emitted_at="2026-08-31T00:01:00Z")

        self.assertNotEqual(before["fingerprint"], after["fingerprint"])
        self.assertEqual(after["head_sha"], "b" * 40)

    def test_serialized_stack_context_supplies_revision_and_refs(self):
        first = project_stack_context(stack_observation()).to_dict()
        session = {
            "items": {},
            "metadata": {"pull_request_context": {"stack_context": first}},
        }
        action = {
            "kind": "run_final_gate",
            "command": "gh-address-cr final-gate octo/example 102",
            "item_id": None,
            "why_now": "Ready.",
            "requires_human": False,
        }

        before = build_recommendation_observation(session, action, emitted_at="2026-08-31T00:00:00Z")
        context = project_context_summary(session, selected_item_id=None)
        session["metadata"]["pull_request_context"]["stack_context"]["selected_pr"]["head_oid"] = "f" * 40
        after = build_recommendation_observation(session, action, emitted_at="2026-08-31T00:01:00Z")

        self.assertEqual(context["pull_request"]["base_ref"], "feature/base")
        self.assertEqual(context["pull_request"]["head_ref"], "feature/middle")
        self.assertEqual(before["head_sha"], "2" * 40)
        self.assertNotEqual(before["fingerprint"], after["fingerprint"])

    def test_publish_ready_evidence_precedes_unresolved_thread(self):
        session = {
            "items": {
                "github-thread:later": {
                    "item_id": "github-thread:later",
                    "item_kind": "github_thread",
                    "state": "open",
                    "blocking": True,
                },
                "github-thread:ready": {
                    "item_id": "github-thread:ready",
                    "item_kind": "github_thread",
                    "state": "publish_ready",
                    "blocking": True,
                    "accepted_response": {"resolution": "fix"},
                },
            }
        }

        action = project_primary_action(
            repo="octo/example",
            pr_number="77",
            command="address",
            status="BLOCKED",
            reason_code="WAITING_FOR_SIMPLE_ADDRESS",
            waiting_on="agent_fix",
            session=session,
        )

        self.assertEqual(action["kind"], "publish")
        self.assertEqual(action["item_id"], "github-thread:ready")
        self.assertEqual(action["command"], "gh-address-cr agent publish octo/example 77")

    def test_p1_thread_precedes_unprioritized_thread(self):
        session = {
            "items": {
                "github-thread:a": {
                    "item_id": "github-thread:a",
                    "item_kind": "github_thread",
                    "state": "open",
                    "blocking": True,
                },
                "github-thread:z": {
                    "item_id": "github-thread:z",
                    "item_kind": "github_thread",
                    "state": "open",
                    "blocking": True,
                    "severity": "P1",
                },
            }
        }

        action = project_primary_action(
            repo="octo/example",
            pr_number="77",
            command="address",
            status="BLOCKED",
            reason_code="WAITING_FOR_SIMPLE_ADDRESS",
            waiting_on="agent_fix",
            session=session,
        )

        self.assertEqual(action["kind"], "claim")
        self.assertEqual(action["item_id"], "github-thread:z")
        self.assertIn("--item-id github-thread:z", action["command"])

    def test_published_side_effect_waits_for_remote_convergence(self):
        session = {
            "items": {
                "github-thread:1": {
                    "item_id": "github-thread:1",
                    "item_kind": "github_thread",
                    "state": "open",
                    "blocking": True,
                    "reply_evidence": {"reply_url": "https://example.invalid/reply"},
                }
            }
        }

        action = project_primary_action(
            repo="octo/example",
            pr_number="77",
            command="address",
            status="BLOCKED",
            reason_code="BLOCKING_ITEMS_REMAIN",
            waiting_on="unresolved_items",
            session=session,
        )

        self.assertEqual(action["kind"], "wait")
        self.assertIsNone(action["command"])

    def test_pending_checks_wait_after_items_are_clear(self):
        action = project_primary_action(
            repo="octo/example",
            pr_number="77",
            command="address",
            status="PASSED",
            reason_code="PASSED",
            waiting_on=None,
            session={
                "items": {},
                "metadata": {"check_summary": {"availability": "present", "counts": {"pending": 1}}},
            },
        )

        self.assertEqual(action["kind"], "wait")
        self.assertIsNone(action["command"])

    def test_local_finding_does_not_return_placeholder_command(self):
        action = project_primary_action(
            repo="octo/example",
            pr_number="77",
            command="review",
            status="BLOCKED",
            reason_code="WAITING_FOR_FIX",
            waiting_on="human_fix",
            session={
                "items": {
                    "finding:1": {
                        "item_id": "finding:1",
                        "item_kind": "local_finding",
                        "blocking": True,
                    }
                }
            },
        )

        self.assertEqual(action["kind"], "resolve")
        self.assertIsNone(action["command"])

    def test_passed_inline_summary_runs_final_gate(self):
        action = project_primary_action(
            repo="octo/example",
            pr_number="77",
            command="address",
            status="PASSED",
            reason_code="PASSED",
            waiting_on=None,
            session={"items": {}},
        )

        self.assertEqual(action["kind"], "run_final_gate")
        self.assertEqual(action["command"], "gh-address-cr final-gate octo/example 77")

    def test_final_completion_has_no_synthetic_command(self):
        action = project_primary_action(
            repo="octo/example",
            pr_number="77",
            command="final-gate",
            status="PASSED",
            reason_code="FINAL_GATE_PASSED",
            waiting_on=None,
            session={"items": {}},
        )

        self.assertEqual(action["kind"], "complete")
        self.assertIsNone(action["command"])

    def test_environment_failure_returns_non_executable_repair_action(self):
        action = project_primary_action(
            repo="octo/example",
            pr_number="77",
            command="address",
            status="BLOCKED",
            reason_code="ACTIVE_PR_QUERY_FAILED",
            waiting_on="network",
            session={"items": {}},
        )

        self.assertEqual(action["kind"], "repair_environment")
        self.assertIsNone(action["command"])
        self.assertTrue(action["requires_human"])

    def test_context_summary_is_bounded_to_selected_item_and_file_metadata(self):
        session = {
            "items": {
                "github-thread:1": {
                    "item_id": "github-thread:1",
                    "item_kind": "github_thread",
                    "path": "src/app.py",
                    "line": 42,
                    "body": "Explain this branch.",
                    "state": "open",
                },
                "github-thread:2": {
                    "item_id": "github-thread:2",
                    "item_kind": "github_thread",
                    "path": "tests/test_app.py",
                    "body": "Add coverage.",
                    "state": "open",
                },
            },
            "metadata": {
                "changed_files": [
                    {"path": "README.md", "status": "modified", "additions": 3, "deletions": 1},
                ],
                "pull_request_context": {
                    "stack_context": {
                        "selected_pr_number": "77",
                        "members": [
                            {
                                "pr_number": "77",
                                "base_ref_name": "main",
                                "head_ref_name": "feature/ux",
                                "head_oid": "a" * 40,
                            }
                        ],
                    }
                }
            },
        }

        context = project_context_summary(session, selected_item_id="github-thread:1")

        self.assertEqual(context["pull_request"]["head_ref"], "feature/ux")
        self.assertEqual(
            context["changed_files"],
            [{"path": "README.md", "status": "modified", "additions": 3, "deletions": 1}],
        )
        self.assertEqual(context["selected_item"]["path"], "src/app.py")
        self.assertNotIn("threads", context)


if __name__ == "__main__":
    unittest.main()
