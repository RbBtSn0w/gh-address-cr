import unittest
from gh_address_cr.core.reply_templates import fix_reply, _normalize_severity

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
        self.assertIn("Severity: `P0` 🛑", result)
        self.assertIn("Critical fix rationale.", result)
        self.assertIn("Multi-line explanation", result)

    def test_fix_reply_p1_rendering(self):
        # Two paragraphs should pass
        result = fix_reply("P1", ["sha123", "src/file.py", "pytest", "Passed", "Para one.\n\nPara two."])
        self.assertIn("Severity: `P1` 🔴", result)

    def test_fix_reply_p4_rendering(self):
        result = fix_reply("P4", ["sha123", "src/file.py", "pytest", "Passed", "Minor nit."])
        self.assertIn("Severity: `P4` 🔘", result)
        self.assertIn("Nit/Suggestion path verified", result)

if __name__ == "__main__":
    unittest.main()
