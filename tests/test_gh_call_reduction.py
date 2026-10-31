"""Issue #347: fewer and overlapping `gh` calls per command, with unchanged contracts."""

import json
import os
import subprocess
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from gh_address_cr.github.client import GitHubClient
from gh_address_cr.github.errors import GitHubError

THREADS_PAYLOAD = {
    "data": {
        "repository": {
            "pullRequest": {
                "reviewThreads": {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": []}
            }
        }
    }
}
STACK_PAYLOAD = {
    "data": {
        "repository": {
            "pullRequest": {
                "number": 1,
                "state": "OPEN",
                "isDraft": False,
                "baseRefName": "main",
                "headRefName": "topic",
                "headRefOid": "abc",
                "stack": None,
            }
        }
    }
}


class FakeGh:
    """Thread-safe fake `gh` runner that records calls and can force overlap via a barrier."""

    def __init__(self, *, fail_on=None, barrier_parties=0):
        self.calls = []
        self._lock = threading.Lock()
        self.fail_on = fail_on or {}
        self.barrier_parties = barrier_parties
        self._barriers = {}

    def kind(self, cmd):
        joined = " ".join(cmd)
        if "query=query { viewer { login } }" in cmd:
            return "user"
        if "stackEntry" in joined:
            return "stack"
        if "graphql" in joined:
            return "threads"
        if "reviews" in joined:
            return "reviews"
        if cmd[1:3] == ["pr", "checks"]:
            return "checks"
        if "files" in joined:
            return "files"
        return "other"

    def __call__(self, cmd):
        kind = self.kind(cmd)
        with self._lock:
            self.calls.append(kind)
        barrier = self._barriers.get(kind)
        if barrier is not None:
            barrier.wait(timeout=5)  # raises BrokenBarrierError if the reads were serial
        if kind in self.fail_on:
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr=self.fail_on[kind])
        payload = {
            "user": {"data": {"viewer": {"login": "me"}}},
            "stack": STACK_PAYLOAD,
            "threads": THREADS_PAYLOAD,
        }.get(kind, [])
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload), stderr="")

    def overlap(self, *kinds):
        barrier = threading.Barrier(len(kinds))
        for kind in kinds:
            self._barriers[kind] = barrier


class InstallationViewerLoginTests(unittest.TestCase):
    def test_installation_and_human_tokens_use_the_same_graphql_identity(self):
        for login in ("merge-app[bot]", "octocat"):
            with self.subTest(login=login):
                calls = []

                def runner(cmd, calls=calls, login=login):
                    calls.append(cmd)
                    if cmd[1:3] == ["api", "user"]:
                        return subprocess.CompletedProcess(cmd, 1, "", "HTTP 403: Resource not accessible by integration")
                    self.assertEqual(cmd[1:], ["api", "graphql", "-f", "query=query { viewer { login } }"])
                    return subprocess.CompletedProcess(cmd, 0, json.dumps({"data": {"viewer": {"login": login}}}), "")

                client = GitHubClient(runner=runner)
                self.assertEqual(client.viewer_login(), login)
                self.assertEqual(client.viewer_login(), login)
                self.assertEqual(len(calls), 1)

    def test_malformed_graphql_identity_is_not_cached(self):
        for payload in (None, [], {}, {"data": []}, {"data": {"viewer": []}},
                        {"data": {"viewer": {"login": " "}}},
                        {"data": {"viewer": {"login": 123}}},
                        {"login": "rest-only"}):
            with self.subTest(payload=payload):
                responses = [payload, {"data": {"viewer": {"login": "merge-app[bot]"}}}]

                def runner(cmd, responses=responses):
                    return subprocess.CompletedProcess(cmd, 0, json.dumps(responses.pop(0)), "")

                client = GitHubClient(runner=runner)
                with self.assertRaises(GitHubError) as caught:
                    client.viewer_login()
                self.assertEqual(caught.exception.reason_code, "GITHUB_INCOMPLETE_RESPONSE")
                self.assertEqual(client.viewer_login(), "merge-app[bot]")

    def test_graphql_errors_with_partial_identity_fail_closed_and_are_not_cached(self):
        responses = [
            {"data": {"viewer": {"login": "untrusted"}},
             "errors": [{"message": "Resource not accessible by integration"}]},
            {"data": {"viewer": {"login": "merge-app[bot]"}}},
        ]

        def runner(cmd):
            return subprocess.CompletedProcess(cmd, 0, json.dumps(responses.pop(0)), "")

        client = GitHubClient(runner=runner)
        with self.assertRaises(GitHubError):
            client.viewer_login()
        self.assertEqual(client.viewer_login(), "merge-app[bot]")


class ViewerLoginMemoTests(unittest.TestCase):
    def test_viewer_login_is_read_once_per_client(self):
        gh = FakeGh()
        client = GitHubClient(runner=gh)

        self.assertEqual(client.viewer_login(), "me")
        self.assertEqual(client.viewer_login(), "me")
        client.list_threads("o/r", "1")
        client.list_threads("o/r", "1")

        self.assertEqual(gh.calls.count("user"), 1)
        self.assertEqual(gh.calls.count("threads"), 2)

    def test_failed_viewer_read_is_not_cached(self):
        gh = FakeGh(fail_on={"user": "HTTP 401: Bad credentials"})
        client = GitHubClient(runner=gh)

        with self.assertRaises(GitHubError):
            client.viewer_login()
        gh.fail_on = {}

        self.assertEqual(client.viewer_login(), "me")
        self.assertEqual(gh.calls.count("user"), 2)


class ProcessViewerLoginTests(unittest.TestCase):
    def setUp(self):
        GitHubClient.reset_process_cache()
        self.addCleanup(GitHubClient.reset_process_cache)

    def test_default_runner_clients_share_one_login_read(self):
        calls = []

        def fake_run_cmd(cmd, **kwargs):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps({"data": {"viewer": {"login": "me"}}}), stderr="")

        with (
            tempfile.TemporaryDirectory() as state,
            patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": state}),
            patch("gh_address_cr.core.command_runner.run_cmd", side_effect=fake_run_cmd),
        ):
            self.assertEqual(GitHubClient().viewer_login(), "me")
            self.assertEqual(GitHubClient().viewer_login(), "me")

        self.assertEqual(len(calls), 1)

    def test_injected_runner_clients_never_share_the_process_cache(self):
        first, second = FakeGh(), FakeGh()
        GitHubClient(runner=first).viewer_login()
        GitHubClient(runner=second).viewer_login()

        self.assertEqual((first.calls.count("user"), second.calls.count("user")), (1, 1))


class AdapterInvalidatesLoginTests(unittest.TestCase):
    def test_adapter_run_drops_the_cached_login_even_when_it_fails(self):
        from gh_address_cr.commands.high_level import FindingsFormatError, HighLevelReviewRuntime

        GitHubClient._process_viewer_login = "before-adapter"
        self.addCleanup(GitHubClient.reset_process_cache)
        parsed = SimpleNamespace(input=None, adapter_cmd=["adapter"], sync=False, source=None)

        with patch("gh_address_cr.commands.high_level._run_adapter_command", return_value=(None, "adapter failed")):
            with self.assertRaises(FindingsFormatError):
                HighLevelReviewRuntime()._ingest_and_load_threads("adapter", parsed, {}, None, "o/r", "1")

        self.assertIsNone(GitHubClient._process_viewer_login)


class FinalGateCallTests(unittest.TestCase):
    def run_gate(self, gh, **kwargs):
        from gh_address_cr.core.gate import Gatekeeper
        from gh_address_cr.core.session import SessionManager

        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}):
            manager = SessionManager("o/r", "1")
            manager.save(manager.create(status="WAITING_FOR_GATE"))
            return Gatekeeper(github_client=GitHubClient(runner=gh)).run("o/r", "1", **kwargs)

    def test_final_gate_reads_viewer_once(self):
        gh = FakeGh()

        self.run_gate(gh, require_checks=True)

        # Before #347: 6 calls with viewer query issued twice.
        self.assertEqual(len(gh.calls), 5)
        self.assertEqual(gh.calls.count("user"), 1)

    def test_final_gate_without_checks_issues_four_calls(self):
        gh = FakeGh()

        self.run_gate(gh)

        self.assertEqual(sorted(gh.calls), ["reviews", "stack", "threads", "user"])

    def test_independent_reads_overlap(self):
        gh = FakeGh()
        gh.overlap("stack", "user")  # wave 1 only completes if both are in flight together
        self.run_gate(gh)

        gh = FakeGh()
        gh.overlap("threads", "reviews", "checks")  # wave 2
        self.run_gate(gh, require_checks=True)

    def test_first_failing_read_in_original_order_surfaces(self):
        gh = FakeGh(fail_on={"threads": "HTTP 404: Not Found", "reviews": "HTTP 403: forbidden"})

        with self.assertRaises(GitHubError) as ctx:
            self.run_gate(gh)

        self.assertIn("404", str(ctx.exception))

    def test_stack_failure_stays_fail_open(self):
        gh = FakeGh(fail_on={"stack": "HTTP 500: boom"})

        result = self.run_gate(gh)

        self.assertEqual(result.stack_context["availability"], "unavailable")


class AddressCallTests(unittest.TestCase):
    def test_address_collection_overlaps_independent_reads(self):
        from gh_address_cr.commands.high_level import HighLevelReviewRuntime

        gh = FakeGh()
        gh.overlap("stack", "threads", "checks", "files")
        parsed = SimpleNamespace(input=None, adapter_cmd=None, sync=False, source=None)
        session = {"items": {}, "metadata": {}, "repo": "o/r", "pr_number": "1"}

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}),
            patch("gh_address_cr.commands.high_level.GitHubClient", return_value=GitHubClient(runner=gh)),
        ):
            HighLevelReviewRuntime()._ingest_and_load_threads("address", parsed, session, None, "o/r", "1")

        # Same 5 calls as before #347, but issued together instead of five serial round trips.
        self.assertEqual(sorted(gh.calls), ["checks", "files", "stack", "threads", "user"])


class PendingReviewPaginationTests(unittest.TestCase):
    def test_short_page_stops_without_an_extra_empty_page_call(self):
        calls = []

        def runner(cmd):
            calls.append(cmd)
            rows = [{"state": "PENDING", "user": {"login": "me"}}, {"state": "APPROVED", "user": {"login": "x"}}]
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(rows), stderr="")

        pending = GitHubClient(runner=runner).list_pending_reviews("o/r", "1", "me")

        self.assertEqual(len(pending), 1)
        self.assertEqual(len(calls), 1)

    def test_full_page_fetches_the_next_page(self):
        pages = [[{"state": "COMMENTED"}] * 100, [{"state": "PENDING", "user": {"login": "me"}}]]
        calls = []

        def runner(cmd):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(pages[len(calls) - 1]), stderr="")

        pending = GitHubClient(runner=runner).list_pending_reviews("o/r", "1", "me")

        self.assertEqual(len(pending), 1)
        self.assertEqual(len(calls), 2)


class ThreadResolvedLookupTests(unittest.TestCase):
    def test_is_thread_resolved_uses_a_single_node_query(self):
        calls = []

        def runner(cmd):
            calls.append(cmd)
            return subprocess.CompletedProcess(
                cmd, 0, stdout=json.dumps({"data": {"node": {"isResolved": True}}}), stderr=""
            )

        self.assertTrue(GitHubClient(runner=runner).is_thread_resolved("T1"))
        self.assertEqual(len(calls), 1)
        self.assertIn("node(id:$threadId)", " ".join(calls[0]))

    def test_unresolved_or_missing_node_is_false(self):
        for node in ({"isResolved": False}, None, {}):
            with self.subTest(node=node):

                def gh(cmd, node=node):
                    return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps({"data": {"node": node}}), stderr="")

                self.assertFalse(GitHubClient(runner=gh).is_thread_resolved("T1"))


class PublishWaitCallTests(unittest.TestCase):
    """Per-thread gh budget of the publish settle-wait: node lookups only, never a PR-wide listing."""

    def run_wait(self, resolved_on):
        from gh_address_cr.core import publisher

        class Client:
            def __init__(self):
                self.lookups = 0
                self.listings = 0

            def is_thread_resolved(self, thread_id):
                self.lookups += 1
                return self.lookups >= resolved_on

            def list_threads(self, repo, pr_number):
                self.listings += 1
                return []

        client = Client()
        with patch("gh_address_cr.core.publisher.time.sleep"):
            publisher._wait_for_remote_thread_resolution(client, "T1")
        return client

    def test_settled_thread_costs_one_lookup(self):
        client = self.run_wait(resolved_on=1)

        self.assertEqual((client.lookups, client.listings), (1, 0))

    def test_unsettled_thread_is_bounded_at_two_lookups(self):
        client = self.run_wait(resolved_on=99)

        self.assertEqual((client.lookups, client.listings), (2, 0))


class GatherReadsTests(unittest.TestCase):
    def test_outcomes_keep_submission_order_and_capture_errors(self):
        from gh_address_cr.core.parallel_reads import gather_reads

        def boom():
            raise ValueError("x")

        outcomes = gather_reads(lambda: 1, boom, lambda: 3)

        self.assertEqual(outcomes[0].unwrap(), 1)
        with self.assertRaises(ValueError):
            outcomes[1].unwrap()
        self.assertEqual(outcomes[2].unwrap(), 3)

    def test_workers_inherit_caller_context(self):
        import contextvars

        from gh_address_cr.core.parallel_reads import gather_reads

        var = contextvars.ContextVar("v", default="unset")
        var.set("parent")

        self.assertEqual([o.unwrap() for o in gather_reads(var.get, var.get)], ["parent", "parent"])


class TelemetryRecordThreadSafetyTests(unittest.TestCase):
    def test_concurrent_records_are_not_lost(self):
        from gh_address_cr.core.telemetry_runtime import SessionTelemetry

        telemetry = SessionTelemetry()
        threads = [
            threading.Thread(
                target=lambda: [telemetry.record("gh api", 0.0, 0.1, 0) for _ in range(50)]
            )
            for _ in range(8)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(len(telemetry.metrics), 400)


if __name__ == "__main__":
    unittest.main()
