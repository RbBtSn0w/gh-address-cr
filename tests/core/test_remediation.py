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
