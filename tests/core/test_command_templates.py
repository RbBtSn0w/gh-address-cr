import unittest

from gh_address_cr.core import command_templates as t


class TestQuoteArg(unittest.TestCase):
    def test_plain_value_is_shell_quoted_when_needed(self):
        self.assertEqual(t.quote_arg("simple"), "simple")
        self.assertEqual(t.quote_arg("has space"), "'has space'")
        self.assertEqual(t.quote_arg("a'b"), "'a'\"'\"'b'")

    def test_angle_bracket_placeholders_are_kept_literal(self):
        self.assertEqual(t.quote_arg("<item_id>"), "<item_id>")
        self.assertEqual(t.quote_arg("<sha>"), "<sha>")

    def test_partial_brackets_are_still_quoted(self):
        # Only fully-wrapped <...> tokens are treated as placeholders.
        self.assertEqual(t.quote_arg("<not-closed"), "'<not-closed'")
        self.assertEqual(t.quote_arg("not-open>"), "'not-open>'")

    def test_non_str_is_coerced(self):
        self.assertEqual(t.quote_arg(123), "123")


class TestShellCommand(unittest.TestCase):
    def test_joins_quoted_parts(self):
        self.assertEqual(
            t.shell_command("gh-address-cr", "address", "owner/repo", "1"),
            "gh-address-cr address owner/repo 1",
        )

    def test_quotes_parts_with_spaces(self):
        self.assertEqual(t.shell_command("cmd", "two words"), "cmd 'two words'")


class TestBatchNext(unittest.TestCase):
    def test_without_files(self):
        self.assertEqual(
            t.batch_next("owner/repo", "1"),
            "gh-address-cr agent next owner/repo 1 --batch --agent-id <agent_id>",
        )

    def test_with_files_is_sorted_and_comma_joined(self):
        out = t.batch_next("owner/repo", "1", files=["b.py", "a.py"])
        self.assertIn("--files a.py,b.py", out)

    def test_drops_empty_paths(self):
        out = t.batch_next("owner/repo", "1", files=["", "a.py"])
        self.assertIn("--files a.py", out)

    def test_drops_comma_bearing_paths_to_keep_command_parseable(self):
        # A path containing a comma cannot round-trip the downstream CSV --files parse.
        out = t.batch_next("owner/repo", "1", files=["a,b.py", "c.py"])
        self.assertIn("--files c.py", out)
        self.assertNotIn("a,b.py", out)

    def test_omits_files_flag_when_only_comma_paths(self):
        # When every path contains a comma, none survive the filter. The
        # command still includes --files with a literal placeholder so the
        # suggestion doesn't silently widen the batch claim to all threads.
        out = t.batch_next("owner/repo", "1", files=["a,b.py"])
        self.assertIn("--files <paths>", out)


class TestCommonSummaryCommands(unittest.TestCase):
    def test_returns_all_expected_keys(self):
        commands = t.common_summary_commands("owner/repo", "1")
        expected = {
            "address",
            "review_auto_simple",
            "threads",
            "classify",
            "next",
            "batch_next",
            "submit",
            "submit_batch",
            "fix_all",
            "fix_all_homogeneous",
            "resolve_stale",
            "publish",
            "final_gate",
        }
        self.assertEqual(set(commands), expected)
        for value in commands.values():
            self.assertTrue(value.startswith("gh-address-cr "))


if __name__ == "__main__":
    unittest.main()
