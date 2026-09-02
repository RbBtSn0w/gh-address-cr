import unittest

from gh_address_cr.core.command_templates import common_summary_commands
from gh_address_cr.core.errors import WorkflowError


class TestWorkflowErrorCommands(unittest.TestCase):
    def test_error_summary_carries_the_runnable_command_menu(self):
        # Error paths used to ship a diagnosis and nothing runnable, which is what forced
        # a status-action-map.md lookup just to translate one reason_code.
        error = WorkflowError(
            status="PUBLISH_BLOCKED",
            reason_code="MISSING_THREAD_ID",
            exit_code=5,
            message="Publish-ready item has no thread id: github-thread:T1",
        )

        summary = error.to_summary(repo="owner/repo", pr_number="123")

        self.assertEqual(summary["commands"], common_summary_commands("owner/repo", "123"))
        self.assertIn("owner/repo", summary["commands"]["final_gate"])
        self.assertIn("123", summary["commands"]["final_gate"])

    def test_curated_payload_commands_win_over_the_default_menu(self):
        # Three raise sites (workflow_matching.py:253,275,297) hand-pick a narrower menu.
        # The default must not clobber them.
        curated = {"resolve_stale": "gh-address-cr agent resolve --stale ..."}
        error = WorkflowError(
            status="BLOCKED",
            reason_code="STALE_THREADS_REQUIRE_RESOLVE_STALE",
            exit_code=4,
            message="Stale threads require --stale.",
            payload={"commands": curated},
        )

        summary = error.to_summary(repo="owner/repo", pr_number="123")

        self.assertEqual(summary["commands"], curated)

    def test_an_explicitly_empty_curated_commands_dict_is_preserved(self):
        # A truthiness check (`payload.get("commands") or default`) would treat an
        # intentionally empty {} as absent and silently replace it with the default
        # menu. Presence must be checked by key, not by truthiness.
        error = WorkflowError(
            status="BLOCKED",
            reason_code="SOME_CODE",
            exit_code=4,
            message="No commands apply here.",
            payload={"commands": {}},
        )

        summary = error.to_summary(repo="owner/repo", pr_number="123")

        self.assertEqual(summary["commands"], {})

    def test_curated_payload_remediation_wins_over_the_computed_default(self):
        # remediation used to be unconditionally overwritten by remediation_for(),
        # unlike commands (checked by key presence). A raise site that needs a more
        # specific remediation than the generic reason_code lookup must be able to
        # provide one.
        curated = {"summary": "Specific to this raise site.", "command": "gh-address-cr agent leases owner/repo 123"}
        error = WorkflowError(
            status="BLOCKED",
            reason_code="LEASE_LOCKED_ITEM",
            exit_code=4,
            message="Item is locked by an active lease.",
            payload={"remediation": curated},
        )

        summary = error.to_summary(repo="owner/repo", pr_number="123")

        self.assertEqual(summary["remediation"], curated)

    def test_summary_keeps_its_existing_machine_fields(self):
        error = WorkflowError(
            status="PUBLISH_BLOCKED",
            reason_code="MISSING_ACCEPTED_RESPONSE",
            exit_code=5,
            message="Publish-ready item has no accepted response.",
            waiting_on="action_response",
            payload={"item_id": "github-thread:T1"},
        )

        summary = error.to_summary(repo="owner/repo", pr_number="123")

        self.assertEqual(summary["status"], "PUBLISH_BLOCKED")
        self.assertEqual(summary["reason_code"], "MISSING_ACCEPTED_RESPONSE")
        self.assertEqual(summary["waiting_on"], "action_response")
        self.assertEqual(summary["item_id"], "github-thread:T1")
        self.assertEqual(summary["exit_code"], 5)
        self.assertIn("no accepted response", summary["next_action"])


if __name__ == "__main__":
    unittest.main()
