import inspect
import unittest

from gh_address_cr.core.reply_templates import _normalize_severity, clarify_reply, defer_reply, fix_reply


class TestReplyTemplates(unittest.TestCase):
    def test_normalize_severity_p0_p4(self):
        self.assertEqual(_normalize_severity("p0"), "P0")
        self.assertEqual(_normalize_severity("P4"), "P4")
        with self.assertRaises(SystemExit):
            _normalize_severity("P5")

    def test_normalize_severity_edge_cases(self):
        self.assertEqual(_normalize_severity("  p1  "), "P1")
        self.assertEqual(_normalize_severity(None), None)
        self.assertEqual(_normalize_severity(""), None)
        with self.assertRaises(SystemExit):
            _normalize_severity("invalid")

    def test_fix_reply_p0_rendering(self):
        # Long enough for P0
        long_why = "Critical fix rationale.\n\nMulti-line explanation that is long enough to pass the validation rule."
        result = fix_reply("P0", ["sha123", "src/file.py", "pytest", "Passed", long_why])
        self.assertIn("Review signal: `P0`", result)
        self.assertNotIn("Severity:", result)
        self.assertNotIn("Reviewer priority:", result)
        self.assertIn("Critical fix rationale.", result)
        self.assertIn("Multi-line explanation", result)

    def test_fix_reply_p1_rendering(self):
        # Two paragraphs should pass
        result = fix_reply("P1", ["sha123", "src/file.py", "pytest", "Passed", "Para one.\n\nPara two."])
        self.assertIn("Review signal: `P1`", result)

    def test_fix_reply_p4_rendering(self):
        result = fix_reply("P4", ["sha123", "src/file.py", "pytest", "Passed", "Minor nit."])
        self.assertIn("Review signal: `P4`", result)
        self.assertNotIn("Risk note:", result)

    def test_reply_templates_do_not_accept_efficiency_summary_parameter(self):
        for renderer in (fix_reply, clarify_reply, defer_reply):
            self.assertNotIn("efficiency_summary", inspect.signature(renderer).parameters)

    def test_fix_reply_surfaces_reviewer_priority_without_p_scale_severity(self):
        result = fix_reply(
            None,
            ["sha123", "src/file.py", "pytest", "Passed", "Centralized command listing to avoid drift."],
            review_priority="medium",
            review_priority_note="Reviewer-provided priority from the original review comment.",
        )

        self.assertNotIn("Severity:", result)
        self.assertNotIn("Reviewer priority:", result)
        self.assertIn("Review signal: `Medium Priority`", result)
        self.assertIn("Reviewer-provided priority from the original review comment.", result)
        self.assertNotIn("Risk note:", result)

    def test_fix_reply_without_summary_omits_placeholder_file_summary(self):
        result = fix_reply(None, ["sha123", "src/a.py,src/b.py", "pytest", "Passed", "Rationale."])

        self.assertNotIn("updated per CR scope", result)
        self.assertIn("- `src/a.py`\n", result)
        self.assertIn("- `src/b.py`\n", result)

    def test_defer_reply_has_no_unfilled_placeholder_tokens(self):
        result = defer_reply(["Needs a broader cleanup outside this PR."])

        self.assertNotIn("<issue_or_followup_pr>", result)
        self.assertNotIn("<exact scope>", result)
        self.assertNotIn("<low/medium/high", result)
        self.assertIn("Needs a broader cleanup outside this PR.", result)

    def test_fix_reply_usage_uses_supported_cli_surface(self):
        with self.assertRaises(SystemExit) as context:
            fix_reply(None, [])

        message = str(context.exception)
        self.assertNotIn("generate_reply.py", message)
        self.assertIn("gh-address-cr agent submit", message)
        self.assertIn("gh-address-cr submit-action", message)

if __name__ == "__main__":
    unittest.main()
