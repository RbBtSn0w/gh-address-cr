"""Hidden oracle: Windows-style gh executables match; other executables still do not."""

import unittest

from app.pr_checks import is_pr_checks_command


class Oracle(unittest.TestCase):
    def test_windows_paths_and_exe_suffix_match(self):
        for executable in ("gh.exe", "C:\\Program Files\\GitHub CLI\\gh.exe", "C:\\tools\\gh"):
            with self.subTest(executable=executable):
                self.assertTrue(is_pr_checks_command([executable, "pr", "checks", "7"]))

    def test_posix_paths_still_match(self):
        for executable in ("gh", "/opt/homebrew/bin/gh"):
            with self.subTest(executable=executable):
                self.assertTrue(is_pr_checks_command([executable, "pr", "checks"]))

    def test_other_executables_and_subcommands_do_not_match(self):
        for cmd in (
            ["/usr/local/bin/sigh", "pr", "checks"],
            ["C:\\bin\\sigh.exe", "pr", "checks"],
            ["gh-dash", "pr", "checks"],
            ["gh", "pr", "view"],
            ["gh.exe", "pr"],
        ):
            with self.subTest(cmd=cmd):
                self.assertFalse(is_pr_checks_command(cmd))
