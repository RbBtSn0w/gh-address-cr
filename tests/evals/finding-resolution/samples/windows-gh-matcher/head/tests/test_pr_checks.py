import unittest

from app.pr_checks import is_pr_checks_command, pr_checks_result


class PrChecksResultTests(unittest.TestCase):
    def test_states(self):
        self.assertEqual(pr_checks_result(0, "[]", ""), "checks")
        self.assertEqual(pr_checks_result(8, '[{"state": "PENDING"}]', ""), "checks")
        self.assertEqual(pr_checks_result(1, "", "no checks reported on the 'x' branch"), "no_checks")
        self.assertEqual(pr_checks_result(1, "", "HTTP 401"), "error")


class IsPrChecksCommandTests(unittest.TestCase):
    def test_matches_gh_pr_checks(self):
        self.assertTrue(is_pr_checks_command(["gh", "pr", "checks", "7"]))
        self.assertTrue(is_pr_checks_command(["/opt/homebrew/bin/gh", "pr", "checks"]))

    def test_rejects_other_commands_and_executables(self):
        self.assertFalse(is_pr_checks_command(["gh", "pr", "view"]))
        self.assertFalse(is_pr_checks_command(["/usr/local/bin/sigh", "pr", "checks"]))
        self.assertFalse(is_pr_checks_command(["gh-dash", "pr", "checks"]))


if __name__ == "__main__":
    unittest.main()
