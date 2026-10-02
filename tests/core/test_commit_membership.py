"""Spec 039 R3: matching a cited commit against the pull request's commits."""

from __future__ import annotations

import unittest

from gh_address_cr.core.commit_membership import cited_commit, commit_in_pr

PR_COMMITS = ["0b941cf" + "1" * 33, "876a911" + "2" * 33]


class CommitInPrTests(unittest.TestCase):
    def test_full_sha_and_abbreviations_match(self):
        self.assertTrue(commit_in_pr(PR_COMMITS[1], PR_COMMITS))
        self.assertTrue(commit_in_pr("876a911", PR_COMMITS))
        self.assertTrue(commit_in_pr("876A", PR_COMMITS))

    def test_commits_outside_the_pr_and_too_short_prefixes_do_not_match(self):
        self.assertFalse(commit_in_pr("6583c8d", PR_COMMITS))
        self.assertFalse(commit_in_pr("876", PR_COMMITS))
        self.assertFalse(commit_in_pr("", PR_COMMITS))
        self.assertFalse(commit_in_pr("876a911", []))


class CitedCommitTests(unittest.TestCase):
    def test_reads_the_fix_reply_commit(self):
        self.assertEqual(cited_commit({"fix_reply": {"commit_hash": " 876a911 "}}), "876a911")
        self.assertEqual(cited_commit({"fix_reply": {"summary": "s"}}), "")
        self.assertEqual(cited_commit({"reply_markdown": "x"}), "")


if __name__ == "__main__":
    unittest.main()
