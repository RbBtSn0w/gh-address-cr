import unittest


class GitHubThreadStateTests(unittest.TestCase):
    def test_stale_is_claimable_but_not_terminal(self):
        from gh_address_cr.core.github_thread_state import (
            GITHUB_THREAD_TERMINAL_STATES,
            is_claimable_github_thread,
            is_terminal_github_thread,
        )

        item = {
            "item_id": "github-thread:THREAD_STALE",
            "item_kind": "github_thread",
            "state": "stale",
            "status": "STALE",
            "is_outdated": True,
        }

        self.assertNotIn("stale", GITHUB_THREAD_TERMINAL_STATES)
        self.assertTrue(is_claimable_github_thread(item))
        self.assertFalse(is_terminal_github_thread(item))

    def test_resolved_thread_is_not_claimable_and_is_terminal(self):
        from gh_address_cr.core.github_thread_state import is_claimable_github_thread, is_terminal_github_thread

        item = {
            "item_id": "github-thread:THREAD_DONE",
            "item_kind": "github_thread",
            "state": "closed",
            "status": "CLOSED",
        }

        self.assertFalse(is_claimable_github_thread(item))
        self.assertTrue(is_terminal_github_thread(item))


if __name__ == "__main__":
    unittest.main()
