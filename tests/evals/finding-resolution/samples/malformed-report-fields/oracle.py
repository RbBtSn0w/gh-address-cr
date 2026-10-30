"""Hidden oracle: malformed archived fields neither invent flag kinds nor abort the summary."""

import unittest

from app.compare_reports import summarize


def report(**fields):
    return {"runtime": {"version": "1.0", "origin": "package"}, **fields}


class Oracle(unittest.TestCase):
    def test_string_flags_are_not_split_into_characters(self):
        kinds = summarize([report(inefficiency_flags="address had 3 failures")])["1.0 package"]["flag_kinds"]
        # Wrapping the string in a list or skipping it are both fixes; per-character kinds are not.
        self.assertNotIn("other", kinds)

    def test_mapping_flags_do_not_count_their_keys(self):
        # The thread names keys as well as characters; a dict is not a flag list.
        kinds = summarize([report(inefficiency_flags={"address had 3 failures": 1})])["1.0 package"]["flag_kinds"]
        self.assertEqual(kinds, {})

    def test_list_flags_still_count(self):
        kinds = summarize([report(inefficiency_flags=["address had 3 failures"])])["1.0 package"]["flag_kinds"]
        self.assertEqual(kinds, {"error_prone:address": 1})

    def test_non_numeric_needs_action_count_does_not_abort(self):
        rows = [report(needs_action_count="seven"), report(needs_action_count={"n": 1}), report(needs_action_count=2)]
        self.assertEqual(summarize(rows)["1.0 package"]["needs_action_total"], 2)
