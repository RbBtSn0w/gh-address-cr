"""#116: session items are a replayable projection of the evidence ledger."""

import unittest

from gh_address_cr.core.runtime_kernel.session_projection import AGENT_EVENT_TYPES, apply_ledger_events


def _event(event_type, item_id, payload, record_id="rec", timestamp=None):
    ev = {"event_type": event_type, "item_id": item_id, "payload": payload, "record_id": record_id}
    if timestamp is not None:
        ev["timestamp"] = timestamp
    return ev


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

    def test_verification_rejection_reopens_accepted_item(self):
        # #8: a verifier rejection after an accepted response must reopen the item,
        # not leave it terminal, on rebuild.
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
            _event("verification_rejected", "github-thread:abc", {"note": "Does not actually fix it."}),
        ]
        item = apply_ledger_events(base, events)["github-thread:abc"]
        self.assertEqual(item["state"], "open")
        self.assertTrue(item["blocking"])
        self.assertFalse(item["handled"])
        self.assertEqual(item["verification_rejection_note"], "Does not actually fix it.")

    def test_reply_evidence_none_is_replaced(self):
        # #1: reply_evidence stored as None must not silently drop the reply_url.
        base = {"github-thread:abc": {"item_id": "github-thread:abc", "item_kind": "github_thread", "reply_evidence": None}}
        events = [_event("reply_posted", "github-thread:abc", {"reply_url": "https://x/reply"})]
        item = apply_ledger_events(base, events)["github-thread:abc"]
        self.assertEqual(item["reply_evidence"], {"reply_url": "https://x/reply"})

    def test_local_finding_handled_at_is_deterministic_from_event_timestamp(self):
        # CR: rebuild must not stamp handled_at with datetime.now() each run.
        base = {"local:f1": {"item_id": "local:f1", "item_kind": "local_finding", "state": "open"}}
        events = [
            _event(
                "response_accepted",
                "local:f1",
                {"response": {"resolution": "fix", "note": "n", "files": [], "validation_commands": []}},
                timestamp="2026-06-13T00:00:00Z",
            )
        ]
        once = apply_ledger_events(base, events)["local:f1"]
        twice = apply_ledger_events(base, events)["local:f1"]
        self.assertEqual(once["handled_at"], "2026-06-13T00:00:00Z")
        self.assertEqual(once["handled_at"], twice["handled_at"])

    def test_agent_event_types_documents_verification_rejected(self):
        self.assertIn("verification_rejected", AGENT_EVENT_TYPES)

    def test_orphan_item_event_fails_loud(self):
        # #137: a ledger event whose item is missing from the base map signals
        # ledger/cache divergence and must fail loud, not be silently skipped — a
        # silent skip would reconstruct a partial projection and quietly weaken the
        # crash-recovery guarantee.
        base = {"github-thread:abc": {"item_id": "github-thread:abc", "item_kind": "github_thread"}}
        events = [_event("thread_resolved", "github-thread:missing", {"thread_id": "missing"}, record_id="ev_orphan")]
        with self.assertRaises(ValueError) as ctx:
            apply_ledger_events(base, events)
        message = str(ctx.exception)
        self.assertIn("github-thread:missing", message)
        self.assertIn("thread_resolved", message)
        self.assertIn("ev_orphan", message)

    def test_unprojected_event_types_skip_orphan_guard(self):
        # The orphan guard must only fire for event types this fold actually projects.
        # Ledger events outside AGENT_EVENT_TYPES (e.g. request_issued) never mutate
        # item state and may legitimately reference an item absent from the base map;
        # they must be skipped, not crash crash-recovery replay.
        base = {"github-thread:abc": {"item_id": "github-thread:abc", "item_kind": "github_thread"}}
        ignored = [_event("request_issued", "github-thread:missing", {"request_id": "missing"})]
        rebuilt = apply_ledger_events(base, ignored)
        self.assertEqual(set(rebuilt), {"github-thread:abc"})


if __name__ == "__main__":
    unittest.main()
