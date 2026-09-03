import unittest

from gh_address_cr.core.publisher import _publisher_never_replied, _reconcile_in_flight_reply
from gh_address_cr.core.reply_templates import (
    LEGACY_REPLY_ATTRIBUTIONS,
    REPLY_ATTRIBUTION,
)


class FakeThreadsClient:
    def __init__(self, threads):
        self._threads = threads

    def list_threads(self, repo, pr_number):
        return self._threads


class TestPublisherNeverReplied(unittest.TestCase):
    def test_true_when_viewer_replied_is_a_checked_false(self):
        client = FakeThreadsClient([{"id": "T1", "viewer_reply_checked": True, "viewer_replied": False}])

        self.assertTrue(_publisher_never_replied(client, "owner/repo", "1", "T1"))

    def test_false_when_viewer_replied_is_a_checked_true(self):
        client = FakeThreadsClient([{"id": "T1", "viewer_reply_checked": True, "viewer_replied": True}])

        self.assertFalse(_publisher_never_replied(client, "owner/repo", "1", "T1"))

    def test_false_when_not_checked(self):
        client = FakeThreadsClient([{"id": "T1", "viewer_reply_checked": False, "viewer_replied": False}])

        self.assertFalse(_publisher_never_replied(client, "owner/repo", "1", "T1"))

    def test_false_when_viewer_replied_is_missing_despite_checked_true(self):
        # Regression: `not bool(thread.get("viewer_replied"))` treats a missing/None
        # viewer_replied the same as an explicit False, wrongly proving "never replied"
        # for a client that sets viewer_reply_checked=True without reliably populating
        # viewer_replied as an actual bool. A proof check must not guess.
        client = FakeThreadsClient([{"id": "T1", "viewer_reply_checked": True}])

        self.assertFalse(_publisher_never_replied(client, "owner/repo", "1", "T1"))

    def test_false_when_viewer_replied_is_a_non_bool_truthy_value(self):
        client = FakeThreadsClient([{"id": "T1", "viewer_reply_checked": True, "viewer_replied": "no"}])

        self.assertFalse(_publisher_never_replied(client, "owner/repo", "1", "T1"))

    def test_false_when_thread_not_found(self):
        client = FakeThreadsClient([{"id": "OTHER", "viewer_reply_checked": True, "viewer_replied": False}])

        self.assertFalse(_publisher_never_replied(client, "owner/repo", "1", "T1"))

    def test_false_when_list_threads_raises(self):
        class RaisingClient:
            def list_threads(self, repo, pr_number):
                raise RuntimeError("network error")

        self.assertFalse(_publisher_never_replied(RaisingClient(), "owner/repo", "1", "T1"))


class TestReconcileInFlightReply(unittest.TestCase):
    def test_non_string_latest_body_does_not_raise(self):
        # Regression: `thread.get("latest_body") or ""` only substitutes for a falsy
        # value, so a truthy non-string (e.g. bytes) would reach `REPLY_ATTRIBUTION in
        # latest_body` and raise TypeError instead of just failing to match.
        client = FakeThreadsClient(
            [
                {
                    "id": "T1",
                    "latest_author_login": "agent-login",
                    "latest_body": b"not a str",
                    "latest_url": "https://github.test/reply",
                }
            ]
        )

        result = _reconcile_in_flight_reply(client, "owner/repo", "1", "T1", "agent-login")

        self.assertIsNone(result)

    def test_non_string_latest_body_does_not_false_positive_match(self):
        # This is a proof match: str()-coercing a structured latest_body (dict/list)
        # could accidentally contain REPLY_ATTRIBUTION as a substring of its repr,
        # wrongly adopting a URL that was never a genuine attributed reply. A non-str
        # latest_body must fail the match, never be stringified and searched.
        client = FakeThreadsClient(
            [
                {
                    "id": "T1",
                    "latest_author_login": "agent-login",
                    "latest_body": {"note": REPLY_ATTRIBUTION},
                    "latest_url": "https://github.test/reply",
                }
            ]
        )

        result = _reconcile_in_flight_reply(client, "owner/repo", "1", "T1", "agent-login")

        self.assertIsNone(result)

    def test_matches_when_latest_body_is_a_real_string(self):
        client = FakeThreadsClient(
            [
                {
                    "id": "T1",
                    "latest_author_login": "agent-login",
                    "latest_body": f"Reply text.\n\n{REPLY_ATTRIBUTION}",
                    "latest_url": "https://github.test/reply",
                }
            ]
        )

        result = _reconcile_in_flight_reply(client, "owner/repo", "1", "T1", "agent-login")

        self.assertEqual(result, "https://github.test/reply")

    def test_matches_when_latest_body_has_legacy_attribution(self):
        legacy_attr = LEGACY_REPLY_ATTRIBUTIONS[0]
        client = FakeThreadsClient(
            [
                {
                    "id": "T1",
                    "latest_author_login": "agent-login",
                    "latest_body": f"Reply text.\n\n{legacy_attr}",
                    "latest_url": "https://github.test/reply",
                }
            ]
        )

        result = _reconcile_in_flight_reply(client, "owner/repo", "1", "T1", "agent-login")

        self.assertEqual(result, "https://github.test/reply")


if __name__ == "__main__":
    unittest.main()
