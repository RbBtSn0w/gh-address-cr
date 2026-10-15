import unittest

from gh_address_cr.core import protocol_codes
from gh_address_cr.core.errors import WorkflowError
from gh_address_cr.core.remediation import remediation_for


class TestRemediation(unittest.TestCase):
    def test_registered_response_shape_code_points_at_the_skeleton(self):
        result = remediation_for("INVALID_RESPONSE_JSON", repo="owner/repo", pr_number="123")

        self.assertIn("response_skeleton_path", result["summary"])
        self.assertIn("agent submit", result["command"])

    def test_pr_scope_code_tells_the_agent_to_pass_the_target(self):
        result = remediation_for("AMBIGUOUS_PR_SCOPE", repo="owner/repo", pr_number="123")

        self.assertIn("explicitly", result["summary"])
        self.assertIn("owner/repo", result["command"])

    def test_classification_code_routes_to_classify_not_submit(self):
        result = remediation_for(protocol_codes.MISSING_CLASSIFICATION, repo="owner/repo", pr_number="123")

        self.assertIn("agent classify", result["command"])

    def test_commit_not_in_pr_says_push_and_rerun_the_rejected_command(self):
        # Abbreviations of four or more characters already match (commit_membership), so
        # an agent told only "COMMIT_NOT_IN_PR" blames the short SHA instead of the push (#366).
        # The code is raised from resolve, submit, --closed, --input and --files routes, so
        # the summary must send the agent back to the command it ran, flags included.
        result = remediation_for(protocol_codes.COMMIT_NOT_IN_PR, repo="owner/repo", pr_number="123")

        summary = result["summary"]
        self.assertNotIn("Consult `references/status-action-map.md`", summary)
        self.assertIn("push", summary.lower())
        self.assertIn("four or more characters", summary)
        self.assertIn("HEAD", summary)
        self.assertIn("rerun the rejected command", summary)
        self.assertIn("--closed", summary)
        self.assertIn("fix_reply.commit_hash", summary)
        self.assertIn("agent resolve", result["command"])

    def test_commit_not_in_pr_on_publish_routes_to_publish(self):
        from unittest.mock import MagicMock, patch

        from gh_address_cr.core import publisher

        client = MagicMock()
        client.list_pr_commit_shas.return_value = ["a" * 40]
        session = {"items": {}}
        with (
            patch.object(publisher, "_record_publish_blocked"),
            patch.object(publisher.session_store, "save_session"),
            patch.object(
                publisher,
                "project_context_summary",
                return_value={"pull_request": {"head_ref": "feature"}},
            ),
        ):
            with self.assertRaises(WorkflowError) as ctx:
                publisher._require_fallback_commit_in_pr(
                    session, None, "github-thread:T1", "agent", "owner/repo", "123", client, "b" * 40
                )

        summary = ctx.exception.to_summary(repo="owner/repo", pr_number="123")
        self.assertEqual(summary["reason_code"], protocol_codes.COMMIT_NOT_IN_PR)
        self.assertIn("agent publish", summary["remediation"]["command"])
        self.assertNotIn("agent resolve", summary["remediation"]["command"])
        self.assertIn("`feature`", summary["remediation"]["summary"])

    def test_commit_not_in_pr_on_batch_leaves_batch_recovery_in_charge(self):
        # BATCH_ACTION_REJECTED also comes from the runtime-written `--files`/`--stale`
        # batches, and `_augment_batch_recovery_error` merges the raise-site payload last.
        # A raise-site remediation would name a batch file those callers never wrote and
        # would replace the partial-acceptance "do not resubmit this file" remediation.
        from unittest.mock import patch

        from gh_address_cr.core import agent_protocol_submission as submission

        session = {"repo": "owner/repo", "pr_number": "123"}
        with patch.object(submission, "record_response_rejected"):
            with self.assertRaises(WorkflowError) as ctx:
                submission.raise_response_rejected(
                    session,
                    None,
                    {"lease_id": "lease_1"},
                    protocol_codes.COMMIT_NOT_IN_PR,
                    status=protocol_codes.BATCH_ACTION_REJECTED,
                )

        self.assertNotIn("remediation", ctx.exception.payload)
        message = str(ctx.exception)
        self.assertIn("rerun the rejected command", message)
        self.assertIn("batch file", message)

    def test_stale_route_code_routes_to_resolve_stale(self):
        result = remediation_for(
            protocol_codes.STALE_THREADS_REQUIRE_RESOLVE_STALE, repo="owner/repo", pr_number="123"
        )

        self.assertNotIn("Consult `references/status-action-map.md`", result["summary"])
        # Only the `--input` batch guard can emit this code: `--files` selections drop
        # stale rows before routing, so the summary must lead with the batch.
        self.assertIn("`--input` batch", result["summary"])
        self.assertIn("--stale", result["command"])
        self.assertIn("--commit", result["command"])

    def test_open_missing_family_is_absorbed_by_the_prefix_rule(self):
        # `required_response_field` mints codes from f"MISSING_{field.upper()}", so codes
        # that exist in no table must still resolve to something actionable.
        result = remediation_for("MISSING_SOME_FIELD_INVENTED_TOMORROW", repo="owner/repo", pr_number="123")

        self.assertIn("MISSING_SOME_FIELD_INVENTED_TOMORROW", result["summary"])
        self.assertIn("agent submit", result["command"])

    def test_unregistered_code_falls_back_instead_of_raising(self):
        for code in ("TOTALLY_UNKNOWN_CODE", "", None):
            with self.subTest(code=code):
                result = remediation_for(code, repo="owner/repo", pr_number="123")

                self.assertTrue(result["summary"])
                self.assertTrue(result["command"])

    def test_every_protocol_code_constant_yields_a_non_empty_remediation(self):
        constants = [
            getattr(protocol_codes, name)
            for name in dir(protocol_codes)
            if name.isupper() and not name.startswith("_")
        ]
        self.assertGreater(len(constants), 0)

        for code in constants:
            with self.subTest(reason_code=code):
                result = remediation_for(code, repo="owner/repo", pr_number="123")

                self.assertTrue(result["summary"].strip())
                self.assertTrue(result["command"].strip())

    def test_error_summary_carries_remediation(self):
        error = WorkflowError(
            status="ACTION_REJECTED",
            reason_code="INVALID_RESPONSE_SHAPE",
            exit_code=5,
            message="ActionResponse shape is invalid.",
        )

        summary = error.to_summary(repo="owner/repo", pr_number="123")

        self.assertIn("response_skeleton_path", summary["remediation"]["summary"])
        self.assertIn("agent submit", summary["remediation"]["command"])


if __name__ == "__main__":
    unittest.main()
