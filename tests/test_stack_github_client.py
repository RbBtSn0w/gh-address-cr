import json
import subprocess
import unittest

from gh_address_cr.github.client import GitHubClient
from tests.helpers import load_stacked_pr_fixture


def fixture_runner(*names: str):
    payloads = [load_stacked_pr_fixture(name) for name in names]
    calls: list[list[str]] = []

    def run(cmd: list[str]) -> subprocess.CompletedProcess:
        calls.append(cmd)
        payload = payloads.pop(0)
        return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")

    run.calls = calls
    return run


class StackGitHubClientTests(unittest.TestCase):
    def test_unstacked_pull_request_returns_absent_context(self):
        runner = fixture_runner("absent.json")

        context = GitHubClient(runner=runner).get_stack_context("octo/example", "101")

        self.assertEqual(context.availability, "absent")
        self.assertEqual(context.selected_pr_number, "101")
        self.assertEqual(context.selected_pr.head_ref_name, "feature/standalone")
        self.assertEqual(len(runner.calls), 1)

    def test_absent_stack_uses_reported_stack_entry_position(self):
        payload = load_stacked_pr_fixture("absent.json")
        payload["data"]["repository"]["pullRequest"]["stackEntry"] = {"position": 3}
        payload["data"]["repository"]["pullRequest"]["position"] = 3

        def run(cmd: list[str]) -> subprocess.CompletedProcess:
            return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")

        context = GitHubClient(runner=run).get_stack_context("octo/example", "101")

        self.assertEqual(context.availability, "absent")
        self.assertEqual(context.selected_pr_number, "101")

    def test_valid_stack_returns_ordered_selected_context(self):
        runner = fixture_runner("three_layer.json")

        context = GitHubClient(runner=runner).get_stack_context("octo/example", "102")

        self.assertEqual(context.availability, "present")
        self.assertEqual(context.stack_number, 7)
        self.assertEqual(context.selected_position, 2)
        self.assertEqual([member.pr_number for member in context.members], ["101", "102", "103"])
        query_arg = next(part for part in runner.calls[0] if part.startswith("query="))
        self.assertIn("stackEntry", query_arg)
        self.assertIn("headRefOid", query_arg)

    def test_stack_entries_are_paginated_to_completion(self):
        runner = fixture_runner("multi_page_first.json", "multi_page_second.json")

        context = GitHubClient(runner=runner).get_stack_context("octo/example", "102")

        self.assertEqual(context.availability, "present")
        self.assertEqual([member.position for member in context.members], [1, 2, 3])
        self.assertIn("after=cursor-1", runner.calls[1])

    def test_stack_pagination_rejects_changed_stack_metadata(self):
        first = load_stacked_pr_fixture("multi_page_first.json")
        second = load_stacked_pr_fixture("multi_page_second.json")
        second["data"]["repository"]["pullRequest"]["stack"]["number"] = 8
        payloads = [first, second]

        def run(cmd: list[str]) -> subprocess.CompletedProcess:
            return subprocess.CompletedProcess(cmd, 0, json.dumps(payloads.pop(0)), "")

        context = GitHubClient(runner=run).get_stack_context("octo/example", "102")

        self.assertEqual(context.availability, "invalid")
        self.assertEqual(context.invalid_invariant, "pagination_stack_changed")

    def test_stack_rejects_selected_entry_position_mismatch(self):
        payload = load_stacked_pr_fixture("three_layer.json")
        payload["data"]["repository"]["pullRequest"]["stackEntry"]["position"] = 3

        def run(cmd: list[str]) -> subprocess.CompletedProcess:
            return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")

        context = GitHubClient(runner=run).get_stack_context("octo/example", "102")

        self.assertEqual(context.availability, "invalid")
        self.assertEqual(context.invalid_invariant, "selected_position_mismatch")

    def test_preview_schema_absence_returns_unavailable_context(self):
        runner = fixture_runner("unavailable.json")

        context = GitHubClient(runner=runner).get_stack_context("octo/example", "101")

        self.assertEqual(context.availability, "unavailable")
        self.assertEqual(context.diagnostic_code, "STACK_CONTEXT_UNAVAILABLE")

    def test_stack_entry_schema_absence_returns_unavailable_context(self):
        payload = {
            "errors": [
                {
                    "type": "FIELD_NOT_FOUND",
                    "message": "Field 'stackEntry' doesn't exist on type 'PullRequest'",
                }
            ]
        }

        def run(cmd: list[str]) -> subprocess.CompletedProcess:
            return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")

        context = GitHubClient(runner=run).get_stack_context("octo/example", "101")

        self.assertEqual(context.availability, "unavailable")
        self.assertEqual(context.diagnostic_code, "STACK_CONTEXT_UNAVAILABLE")

    def test_malformed_present_payload_returns_invalid_context(self):
        payload = load_stacked_pr_fixture("three_layer.json")
        payload["data"]["repository"]["pullRequest"]["stack"]["size"] = 4
        runner_payloads = [payload]

        def run(cmd: list[str]) -> subprocess.CompletedProcess:
            return subprocess.CompletedProcess(cmd, 0, json.dumps(runner_payloads.pop()), "")

        context = GitHubClient(runner=run).get_stack_context("octo/example", "102")

        self.assertEqual(context.availability, "invalid")
        self.assertEqual(context.invalid_invariant, "reported_size_mismatch")


if __name__ == "__main__":
    unittest.main()
