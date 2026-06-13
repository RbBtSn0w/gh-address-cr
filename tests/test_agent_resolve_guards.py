"""CR fixes for the unified `agent resolve` surface: published flag + trivial guard."""

import argparse
import unittest

from gh_address_cr.commands.agent import _dispatch_agent_resolve, _resolve_published_flag
from gh_address_cr.core.errors import WorkflowError


class ResolvePublishedFlagTest(unittest.TestCase):
    def test_nested_submit_publish_counts_as_published(self):
        # #5/#7: single-item resolve --publish tucks the result under submit.publish.
        payload = {"status": "FAST_FIX_COMPLETE", "submit": {"publish": {"published_count": 1}}}
        self.assertTrue(_resolve_published_flag(payload))

    def test_top_level_publish_counts_as_published(self):
        self.assertTrue(_resolve_published_flag({"publish": {"published_count": 2}}))

    def test_zero_published_count_is_false(self):
        self.assertFalse(_resolve_published_flag({"publish": {"published_count": 0}}))

    def test_no_publish_is_false(self):
        self.assertFalse(_resolve_published_flag({"status": "FAST_FIX_ACCEPTED", "submit": {}}))


class TrivialResolveGuardTest(unittest.TestCase):
    def _ns(self, **kw):
        base = dict(
            repo="o/r", pr_number="1", item_id=None, agent_id="a", commit=None, files=None, file=[],
            summary=None, why=None, severity=None, severity_note=None, review_priority=None, validation=[],
            input=None, batch=False, trivial=False, stale=False, homogeneous_reason=None, concern_label=None,
            match_files=False, include_stale=False, publish=False, now=None,
        )
        base.update(kw)
        return argparse.Namespace(**base)

    def test_trivial_without_item_id_is_rejected(self):
        # #9: --trivial must require a single item_id, not fall into match-all.
        with self.assertRaises(WorkflowError) as ctx:
            _dispatch_agent_resolve(self._ns(trivial=True, commit="abc", homogeneous_reason="x"), now_dt=None)
        self.assertEqual(ctx.exception.reason_code, "TRIVIAL_REQUIRES_ITEM_ID")

    def test_item_id_with_batch_or_stale_is_rejected(self):
        # CR: <item_id> with a match-all/batch mode must fail fast, not be ignored.
        for kw in ({"batch": True, "input": "b.json"}, {"stale": True, "match_files": True, "commit": "abc"},
                   {"homogeneous_reason": "x", "commit": "abc"}):
            with self.subTest(kw=kw):
                with self.assertRaises(WorkflowError) as ctx:
                    _dispatch_agent_resolve(self._ns(item_id="github-thread:abc", **kw), now_dt=None)
                self.assertEqual(ctx.exception.reason_code, "ITEM_ID_NOT_ALLOWED_FOR_MODE")


if __name__ == "__main__":
    unittest.main()
