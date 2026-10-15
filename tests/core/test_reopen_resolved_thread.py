"""`agent resolve --closed` reopens a resolved thread with the state GitHub implies (#366).

The journey contract proves a resolved-and-outdated thread replies and passes
final-gate, but publish overwrites the reopened state in the same call. This pins
the reopen itself: an outdated thread comes back as STALE, a current one as OPEN.
"""

import unittest
from unittest.mock import patch

from gh_address_cr.core import workflow

ITEM_ID = "github-thread:PRRT_1"


def _reopen(item):
    session = {"items": {ITEM_ID: item}}

    def apply(repo, pr_number, mutation, *, operation):
        mutation(session)

    with patch.object(workflow.session_store, "transact_session", side_effect=apply):
        workflow.reopen_resolved_thread_for_reply("owner/repo", "1", item_id=ITEM_ID)
    return session["items"][ITEM_ID]


def _resolved_thread(**extra):
    return {"item_kind": "github_thread", "state": "resolved", "status": "CLOSED", "isResolved": True, **extra}


class ReopenResolvedThreadTests(unittest.TestCase):
    def test_outdated_thread_reopens_as_stale(self):
        item = _reopen(_resolved_thread(is_outdated=True))

        self.assertEqual((item["state"], item["status"]), ("stale", "STALE"))
        self.assertNotIn("isResolved", item)
        self.assertTrue(item["blocking"])
        self.assertIn("reopened_for_reply_at", item)

    def test_current_thread_reopens_as_open(self):
        item = _reopen(_resolved_thread())

        self.assertEqual((item["state"], item["status"]), ("open", "OPEN"))


if __name__ == "__main__":
    unittest.main()
