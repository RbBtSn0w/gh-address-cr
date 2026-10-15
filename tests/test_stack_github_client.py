import json
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from gh_address_cr.github.client import HEAD_REF_LAG_READS, GitHubClient
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

    def test_stack_query_reads_head_tree_for_the_same_commit(self):
        runner = fixture_runner("three_layer.json")

        context = GitHubClient(runner=runner).get_stack_context("octo/example", "102")

        query_arg = next(part for part in runner.calls[0] if part.startswith("query="))
        self.assertIn("tree{ oid }", query_arg)
        self.assertEqual(
            [member.head_tree_oid for member in context.members],
            ["e" + "1" * 39, "e" + "2" * 39, "e" + "3" * 39],
        )

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


def lagging(payload: dict) -> dict:
    """Simulate the post-push window: ``headRef`` still points at the previous commit."""
    pull_request = payload["data"]["repository"]["pullRequest"]
    pull_request["headRef"]["target"]["oid"] = "f" * 40
    return payload


def lagging_member(payload: dict, index: int) -> dict:
    member = payload["data"]["repository"]["pullRequest"]["stack"]["entries"]["nodes"][index]["pullRequest"]
    member["headRef"]["target"]["oid"] = "f" * 40
    return payload


def payload_runner(*payloads: dict):
    queue = list(payloads)
    calls: list[list[str]] = []

    def run(cmd: list[str]) -> subprocess.CompletedProcess:
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, json.dumps(queue.pop(0)), "")

    run.calls = calls
    return run


@patch("gh_address_cr.github.client.time.sleep")
class HeadRefLagTests(unittest.TestCase):
    """#365: right after a push, ``headRef.target.oid`` briefly trails ``headRefOid``."""

    def test_unstacked_head_ref_lag_is_reread_until_it_converges(self, sleep):
        runner = payload_runner(lagging(load_stacked_pr_fixture("absent.json")), load_stacked_pr_fixture("absent.json"))

        with patch("gh_address_cr.otel_tracing.add_current_span_event") as event:
            context = GitHubClient(runner=runner).get_stack_context("octo/example", "101")

        self.assertEqual(context.availability, "absent")
        self.assertEqual(context.selected_pr.head_tree_oid, "e" + "1" * 39)
        self.assertEqual(len(runner.calls), 2)
        sleep.assert_called_once()
        event.assert_called_once_with(
            "gh_address_cr.github.stack.head_ref_lag",
            {
                "gh_address_cr.github.stack.head_ref_lag.reads": 2,
                "gh_address_cr.github.stack.head_ref_lag.outcome": "converged",
            },
        )

    def test_stacked_member_head_ref_lag_is_reread_until_it_converges(self, sleep):
        runner = payload_runner(
            lagging_member(load_stacked_pr_fixture("three_layer.json"), 1),
            load_stacked_pr_fixture("three_layer.json"),
        )

        context = GitHubClient(runner=runner).get_stack_context("octo/example", "102")

        self.assertEqual(context.availability, "present")
        self.assertEqual(context.selected_pr.head_tree_oid, "e" + "2" * 39)
        self.assertEqual(len(runner.calls), 2)

    def test_persistent_head_ref_lag_projects_unavailable_not_invalid(self, sleep):
        runner = payload_runner(*(lagging(load_stacked_pr_fixture("absent.json")) for _ in range(HEAD_REF_LAG_READS)))

        with patch("gh_address_cr.otel_tracing.add_current_span_event") as event:
            context = GitHubClient(runner=runner).get_stack_context("octo/example", "101")

        self.assertEqual(context.availability, "unavailable")
        self.assertEqual(context.diagnostic_code, "STACK_CONTEXT_UNAVAILABLE")
        self.assertEqual(context.to_dict()["diagnostic"]["invariant"], "head_ref_oid_lag")
        self.assertEqual(len(runner.calls), HEAD_REF_LAG_READS)
        self.assertEqual(sleep.call_count, HEAD_REF_LAG_READS - 1)
        event.assert_called_once_with(
            "gh_address_cr.github.stack.head_ref_lag",
            {
                "gh_address_cr.github.stack.head_ref_lag.reads": HEAD_REF_LAG_READS,
                "gh_address_cr.github.stack.head_ref_lag.outcome": "exhausted",
            },
        )

    def test_missing_head_ref_on_open_pr_stays_invalid_without_reread(self, sleep):
        payload = load_stacked_pr_fixture("absent.json")
        payload["data"]["repository"]["pullRequest"]["headRef"] = None
        runner = payload_runner(payload)

        context = GitHubClient(runner=runner).get_stack_context("octo/example", "101")

        self.assertEqual(context.availability, "invalid")
        self.assertEqual(context.invalid_invariant, "missing_head_tree_oid")
        self.assertEqual(len(runner.calls), 1)
        sleep.assert_not_called()

    def test_missing_tree_on_matching_commit_stays_invalid_without_reread(self, sleep):
        payload = load_stacked_pr_fixture("three_layer.json")
        member = payload["data"]["repository"]["pullRequest"]["stack"]["entries"]["nodes"][1]["pullRequest"]
        member["headRef"]["target"]["tree"] = None
        runner = payload_runner(payload)

        context = GitHubClient(runner=runner).get_stack_context("octo/example", "102")

        self.assertEqual(context.availability, "invalid")
        self.assertEqual(context.invalid_invariant, "missing_head_tree_oid")
        self.assertEqual(len(runner.calls), 1)
        sleep.assert_not_called()

    def test_merged_member_with_moved_head_ref_is_not_lag(self, sleep):
        payload = load_stacked_pr_fixture("three_layer.json")
        nodes = payload["data"]["repository"]["pullRequest"]["stack"]["entries"]["nodes"]
        nodes[0]["pullRequest"]["state"] = "MERGED"
        # GitHub retargets the lowest unmerged layer onto trunk once the bottom merges.
        nodes[1]["pullRequest"]["baseRefName"] = "main"
        payload["data"]["repository"]["pullRequest"]["baseRefName"] = "main"
        lagging_member(payload, 0)
        runner = payload_runner(payload)

        context = GitHubClient(runner=runner).get_stack_context("octo/example", "102")

        self.assertEqual(context.availability, "present")
        self.assertEqual(context.members[0].head_tree_oid, "")
        self.assertEqual(len(runner.calls), 1)
        sleep.assert_not_called()

    def test_persistent_stacked_lag_stays_invalid_so_binding_fails_closed(self, sleep):
        runner = payload_runner(
            *(lagging_member(load_stacked_pr_fixture("three_layer.json"), 1) for _ in range(HEAD_REF_LAG_READS))
        )

        context = GitHubClient(runner=runner).get_stack_context("octo/example", "102")

        self.assertEqual(context.availability, "invalid")
        self.assertEqual(context.diagnostic_code, "STACK_CONTEXT_INVALID")
        self.assertEqual(context.invalid_invariant, "head_ref_oid_lag")
        self.assertEqual(len(runner.calls), HEAD_REF_LAG_READS)

    def test_lag_on_one_member_does_not_mask_a_missing_tree_on_another(self, sleep):
        payload = lagging_member(load_stacked_pr_fixture("three_layer.json"), 0)
        payload["data"]["repository"]["pullRequest"]["stack"]["entries"]["nodes"][2]["pullRequest"]["headRef"] = None
        runner = payload_runner(payload)

        context = GitHubClient(runner=runner).get_stack_context("octo/example", "102")

        self.assertEqual(context.invalid_invariant, "missing_head_tree_oid")
        self.assertEqual(len(runner.calls), 1)
        sleep.assert_not_called()

    def test_closed_pr_with_moved_head_ref_is_not_lag(self, sleep):
        payload = lagging(load_stacked_pr_fixture("absent.json"))
        payload["data"]["repository"]["pullRequest"]["state"] = "CLOSED"
        runner = payload_runner(payload)

        context = GitHubClient(runner=runner).get_stack_context("octo/example", "101")

        self.assertEqual(context.invalid_invariant, "missing_head_tree_oid")
        self.assertEqual(len(runner.calls), 1)
        sleep.assert_not_called()

    def test_reread_that_turns_into_a_real_defect_is_not_reported_converged(self, sleep):
        defect = load_stacked_pr_fixture("absent.json")
        defect["data"]["repository"]["pullRequest"]["headRef"] = None
        runner = payload_runner(lagging(load_stacked_pr_fixture("absent.json")), defect)

        with patch("gh_address_cr.otel_tracing.add_current_span_event") as event:
            context = GitHubClient(runner=runner).get_stack_context("octo/example", "101")

        self.assertEqual(context.invalid_invariant, "missing_head_tree_oid")
        event.assert_called_once_with(
            "gh_address_cr.github.stack.head_ref_lag",
            {
                "gh_address_cr.github.stack.head_ref_lag.reads": 2,
                "gh_address_cr.github.stack.head_ref_lag.outcome": "invalid",
            },
        )


@patch("gh_address_cr.github.client.time.sleep")
class HeadRefLagRequestBindingTests(unittest.TestCase):
    """The first request after a push must not be rejected for a lag the runtime can outwait."""

    def test_request_after_push_is_issued_once_head_ref_converges(self, sleep):
        from gh_address_cr.core.agent_protocol_submission import refresh_stack_context_for_request

        runner = payload_runner(lagging(load_stacked_pr_fixture("absent.json")), load_stacked_pr_fixture("absent.json"))

        context = refresh_stack_context_for_request(
            "octo/example", "101", {"metadata": {}}, github_client=GitHubClient(runner=runner)
        )

        self.assertEqual(context.availability, "absent")

    def test_persistent_lag_on_known_stacked_pr_still_rejects_as_unavailable(self, sleep):
        from gh_address_cr.core.agent_protocol_submission import refresh_stack_context_for_request
        from gh_address_cr.core.errors import WorkflowError

        session = {"metadata": {"pull_request_context": {"stack_membership_observed": True}}}
        runner = payload_runner(*(lagging(load_stacked_pr_fixture("absent.json")) for _ in range(HEAD_REF_LAG_READS)))

        with self.assertRaises(WorkflowError) as caught:
            refresh_stack_context_for_request("octo/example", "101", session, github_client=GitHubClient(runner=runner))

        self.assertEqual(caught.exception.status, "REQUEST_REJECTED")
        self.assertEqual(caught.exception.reason_code, "STACK_CONTEXT_UNAVAILABLE")

    def test_persistent_lag_on_first_observed_stacked_pr_rejects_request(self, sleep):
        from gh_address_cr.core.agent_protocol_submission import refresh_stack_context_for_request
        from gh_address_cr.core.errors import WorkflowError

        runner = payload_runner(
            *(lagging_member(load_stacked_pr_fixture("three_layer.json"), 1) for _ in range(HEAD_REF_LAG_READS))
        )

        with self.assertRaises(WorkflowError) as caught:
            refresh_stack_context_for_request(
                "octo/example", "102", {"metadata": {}}, github_client=GitHubClient(runner=runner)
            )

        summary = caught.exception.to_summary(repo="octo/example", pr_number="102")
        self.assertEqual(summary["reason_code"], "STACK_CONTEXT_INVALID")

    def test_unbound_response_is_rejected_when_stacked_lag_persists_at_submit(self, sleep):
        from gh_address_cr.core import agent_protocol_submission
        from gh_address_cr.core.errors import WorkflowError

        runner = payload_runner(
            *(lagging_member(load_stacked_pr_fixture("three_layer.json"), 1) for _ in range(HEAD_REF_LAG_READS))
        )
        with tempfile.TemporaryDirectory() as tmp:
            request_path = os.path.join(tmp, "request.json")
            with open(request_path, "w", encoding="utf-8") as handle:
                # A request issued while the observation was unavailable carries no revision binding.
                json.dump({"repository_context": {"stack_context": {"availability": "unavailable"}}}, handle)
            prepared = {
                "item_id": "github-thread:PRRT_lag",
                "lease_id": "lease_1",
                "lease": {"request_path": request_path},
            }
            with (
                patch.object(agent_protocol_submission, "record_response_rejected"),
                self.assertRaises(WorkflowError) as caught,
            ):
                agent_protocol_submission.verify_request_revision_binding(
                    "octo/example",
                    "102",
                    {"metadata": {}},
                    prepared,
                    {},
                    github_client=GitHubClient(runner=runner),
                    ledger=None,
                    rejected_status="ACTION_REJECTED",
                    now=None,
                )

        self.assertEqual(caught.exception.reason_code, "STACK_CONTEXT_INVALID")


if __name__ == "__main__":
    unittest.main()
