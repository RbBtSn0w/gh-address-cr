"""#116: session items are a replayable projection of the evidence ledger."""

import unittest

from gh_address_cr.core.runtime_kernel.session_projection import apply_ledger_events


def _event(event_type, item_id, payload, record_id="rec"):
    return {"event_type": event_type, "item_id": item_id, "payload": payload, "record_id": record_id}


class SessionProjectionTest(unittest.TestCase):
    def test_github_fix_lifecycle_is_reconstructed_from_events(self):
        # A fact-derived base item (as if freshly synced, agent deltas lost).
        base = {
            "github-thread:abc": {
                "item_id": "github-thread:abc",
                "item_kind": "github_thread",
                "thread_id": "abc",
                "path": "src/a.py",
                "state": "open",
                "status": "OPEN",
                "blocking": True,
            }
        }
        events = [
            _event(
                "classification_recorded",
                "github-thread:abc",
                {"classification": "fix", "note": "Real defect."},
                record_id="ev_cls",
            ),
            _event(
                "response_accepted",
                "github-thread:abc",
                {
                    "resolution": "fix",
                    "note": "Real defect.",
                    "response": {
                        "resolution": "fix",
                        "note": "Real defect.",
                        "files": ["src/a.py"],
                        "validation_commands": [{"command": "python3 -m unittest", "result": "passed"}],
                        "fix_reply": {"commit_hash": "abc123", "summary": "Fixed."},
                    },
                },
            ),
            _event("reply_posted", "github-thread:abc", {"thread_id": "abc", "reply_url": "https://x/reply"}),
            _event("thread_resolved", "github-thread:abc", {"thread_id": "abc"}),
            _event("response_published", "github-thread:abc", {"thread_id": "abc", "reply_url": "https://x/reply"}),
        ]

        rebuilt = apply_ledger_events(base, events)
        item = rebuilt["github-thread:abc"]

        # Classification evidence restored.
        self.assertEqual(item["classification_evidence"]["classification"], "fix")
        self.assertEqual(item["decision"], "fix")
        # Accepted response restored from the enriched response_accepted event.
        self.assertEqual(item["accepted_response"]["resolution"], "fix")
        self.assertEqual(item["accepted_response"]["fix_reply"]["commit_hash"], "abc123")
        # Publish terminal state restored.
        self.assertEqual(item["state"], "closed")
        self.assertEqual(item["status"], "CLOSED")
        self.assertFalse(item["blocking"])
        self.assertTrue(item["handled"])
        self.assertTrue(item["thread_resolved"])
        self.assertEqual(item["reply_url"], "https://x/reply")

    def test_fold_is_idempotent(self):
        base = {
            "github-thread:abc": {
                "item_id": "github-thread:abc",
                "item_kind": "github_thread",
                "thread_id": "abc",
                "state": "open",
            }
        }
        events = [
            _event(
                "response_accepted",
                "github-thread:abc",
                {"response": {"resolution": "fix", "note": "n", "files": [], "validation_commands": []}},
            ),
        ]
        once = apply_ledger_events(base, events)
        twice = apply_ledger_events(once, events)
        self.assertEqual(once, twice)

    def test_does_not_mutate_base(self):
        base = {"github-thread:abc": {"item_id": "github-thread:abc", "item_kind": "github_thread", "state": "open"}}
        events = [_event("thread_resolved", "github-thread:abc", {"thread_id": "abc"})]
        apply_ledger_events(base, events)
        self.assertNotIn("thread_resolved", base["github-thread:abc"])

    def test_unknown_item_events_are_ignored(self):
        base = {"github-thread:abc": {"item_id": "github-thread:abc", "item_kind": "github_thread"}}
        events = [_event("thread_resolved", "github-thread:missing", {"thread_id": "missing"})]
        rebuilt = apply_ledger_events(base, events)
        self.assertEqual(set(rebuilt), {"github-thread:abc"})


if __name__ == "__main__":
    unittest.main()
