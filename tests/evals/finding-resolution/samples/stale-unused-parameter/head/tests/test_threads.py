import unittest

from app.commands import reply_to_closed_thread


def session(**item):
    return {"items": {"t1": {"status": "CLOSED", **item}}}


class ReopenTests(unittest.TestCase):
    def test_remote_resolved_thread_without_reply_reopens(self):
        state = session(remote_resolved=True)
        item = reply_to_closed_thread(state, "t1", "agent-1")
        self.assertEqual(item["status"], "OPEN")
        self.assertEqual(state["events"], [{"event": "thread_reopened_for_reply", "item_id": "t1"}])

    def test_thread_with_reply_is_not_reopened(self):
        with self.assertRaises(ValueError):
            reply_to_closed_thread(session(remote_resolved=True, reply_url="https://example.test/r/1"), "t1", "a")


if __name__ == "__main__":
    unittest.main()
