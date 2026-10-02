"""Contract tests for the publish precondition and outcome-driven status (#273 Phase 2).

Two related contracts:

1. **Precondition altitude.** `--publish` eligibility depends only on `item_kind`,
   which is known before anything is mutated. Validating it inside
   `submit_action_response` meant the rejection landed after
   `issue_action_request` had already claimed a lease and marked the item.

2. **Outcome-driven status.** `<prefix>_COMPLETE` used to be keyed on the
   `--publish` *flag*, so a run whose publish posted nothing still reported
   COMPLETE. `commands/agent.py` compensated by re-deriving its own `published`
   boolean from `published_count` -- evidence that the status itself was not
   trustworthy.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from tests.test_control_plane_workflow import github_thread
from tests.test_native_workflow import UnstackedGitHubClient, open_item

VALIDATION = [{"command": "unit-tests", "result": "passed", "duration_ms": 10}]
WHY = "A rationale long enough to satisfy the evidence threshold for this path." * 2
NO_OP_PUBLISH = {"status": "NO_PUBLISH_READY_ITEMS", "published_count": 0}


class PublishOutcomeStatusTest(unittest.TestCase):
    """Unit coverage for the shared derivation the compositions now share.

    Imported lazily so a run against a tree without the helper fails these tests
    alone, instead of a module-level ImportError masking the behavioral ones below.
    """

    def setUp(self):
        from gh_address_cr.core.utils import publish_outcome_status

        self.publish_outcome_status = staticmethod(publish_outcome_status).__func__

    def test_without_publish_it_is_always_accepted(self):
        self.assertEqual(
            self.publish_outcome_status("FAST_FIX", publish=False, published=None, item_ids=["a"]),
            "FAST_FIX_ACCEPTED",
        )
        self.assertEqual(
            self.publish_outcome_status(
                "FAST_FIX", publish=False, published={"published_items": ["a"]}, item_ids=["a"]
            ),
            "FAST_FIX_ACCEPTED",
        )

    def test_a_no_op_publish_is_not_complete(self):
        self.assertEqual(
            self.publish_outcome_status("DECLINE_ALL", publish=True, published=NO_OP_PUBLISH, item_ids=["a"]),
            "DECLINE_ALL_ACCEPTED",
        )
        self.assertEqual(
            self.publish_outcome_status("DECLINE_ALL", publish=True, published=None, item_ids=["a"]),
            "DECLINE_ALL_ACCEPTED",
        )

    def test_publish_that_skipped_these_items_is_not_complete(self):
        # A session-wide publish can post for other items; that is not evidence
        # for the item this call owns.
        self.assertEqual(
            self.publish_outcome_status(
                "FAST_FIX", publish=True, published={"published_items": ["other"]}, item_ids=["mine"]
            ),
            "FAST_FIX_ACCEPTED",
        )

    def test_publish_covering_the_item_is_complete(self):
        self.assertEqual(
            self.publish_outcome_status(
                "FAST_FIX", publish=True, published={"published_items": ["mine"]}, item_ids=["mine"]
            ),
            "FAST_FIX_COMPLETE",
        )

    def test_partial_coverage_of_what_the_call_owns_is_not_complete(self):
        # The cell the single-item callers could never reach, and so never exposed:
        # with several items owned, "any one published" read as done, and the caller
        # was told its evidence was published while some threads had no reply posted.
        self.assertEqual(
            self.publish_outcome_status(
                "DECLINE_ALL", publish=True, published={"published_items": ["a"]}, item_ids=["a", "b", "c"]
            ),
            "DECLINE_ALL_ACCEPTED",
        )
        # Unrelated items publishing alongside does not make up the difference.
        self.assertEqual(
            self.publish_outcome_status(
                "DECLINE_ALL", publish=True, published={"published_items": ["a", "z"]}, item_ids=["a", "b"]
            ),
            "DECLINE_ALL_ACCEPTED",
        )
        # Every owned item covered, with extras alongside, is complete.
        self.assertEqual(
            self.publish_outcome_status(
                "DECLINE_ALL", publish=True, published={"published_items": ["a", "b", "z"]}, item_ids=["a", "b"]
            ),
            "DECLINE_ALL_COMPLETE",
        )

    def test_an_empty_item_list_owns_nothing_so_it_is_never_complete(self):
        # An empty list means "this call owns no items". Collapsing it to a
        # permissive mode reported COMPLETE off a session-wide publish for other,
        # previously accepted items.
        self.assertEqual(
            self.publish_outcome_status(
                "FAST_FIX_ALL", publish=True, published={"published_items": ["other"]}, item_ids=[]
            ),
            "FAST_FIX_ALL_ACCEPTED",
        )


class PublishPreconditionTest(unittest.TestCase):
    def _session(self, repo, pr_number, item):
        from gh_address_cr.core.session import SessionManager

        manager = SessionManager(repo, pr_number)
        session = manager.create(status="WAITING_FOR_FIX")
        session["items"] = {item["item_id"]: item}
        manager.save(session)
        return manager

    def test_fast_fix_publish_on_a_local_finding_is_rejected_before_any_claim(self):
        # Previously this reached submit_action_response and was rejected only
        # after issue_action_request had minted a fixer lease.
        from gh_address_cr.core import workflow
        from gh_address_cr.core.errors import WorkflowError

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                manager = self._session("owner/repo", "701", open_item("local:1"))

                with self.assertRaises(WorkflowError) as ctx:
                    workflow.fast_fix_item(
                        "owner/repo",
                        "701",
                        item_id="local:1",
                        agent_id="fixer-1",
                        commit_hash="abc123",
                        files=["src/shared.py"],
                        validation_commands=VALIDATION,
                        summary="Fixed it",
                        why=WHY,
                        publish=True,
                        github_client=UnstackedGitHubClient(),
                    )

                self.assertEqual(ctx.exception.reason_code, "PUBLISH_UNSUPPORTED_RESPONSE")
                # No lease was ever minted -- not merely released afterwards.
                self.assertEqual(manager.load().get("leases", {}), {})

    def test_fast_fix_reports_accepted_when_publish_posts_nothing(self):
        from gh_address_cr.core import workflow

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                self._session("owner/repo", "702", github_thread("github-thread:A"))

                with patch(
                    "gh_address_cr.core.publisher.publish_github_thread_responses",
                    return_value=NO_OP_PUBLISH,
                ):
                    result = workflow.fast_fix_item(
                        "owner/repo",
                        "702",
                        item_id="github-thread:A",
                        agent_id="fixer-1",
                        commit_hash="abc123",
                        files=["src/shared.py"],
                        validation_commands=VALIDATION,
                        summary="Fixed it",
                        why=WHY,
                        publish=True,
                        github_client=UnstackedGitHubClient(),
                    )

                # Flag-keyed derivation reported FAST_FIX_COMPLETE here.
                self.assertEqual(result["status"], "FAST_FIX_ACCEPTED")
                # next_action comes from submit_action_response, which used to say
                # "was published" whenever publish=True regardless of the outcome,
                # contradicting the _ACCEPTED status above (PR #276 review).
                self.assertNotIn("was published", result["next_action"])
                self.assertNotIn("was published", result["submit"]["next_action"])
                self.assertIn("agent publish", result["submit"]["next_action"])

    def test_fast_fix_next_action_says_published_when_the_item_was_published(self):
        # The other half: a real publish must still claim it, so the fix is not
        # just "never say published".
        from gh_address_cr.core import workflow

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                self._session("owner/repo", "705", github_thread("github-thread:P"))

                with patch(
                    "gh_address_cr.core.publisher.publish_github_thread_responses",
                    return_value={
                        "status": "PUBLISH_COMPLETE",
                        "published_count": 1,
                        "published_items": ["github-thread:P"],
                    },
                ):
                    result = workflow.fast_fix_item(
                        "owner/repo",
                        "705",
                        item_id="github-thread:P",
                        agent_id="fixer-1",
                        commit_hash="abc123",
                        files=["src/shared.py"],
                        validation_commands=VALIDATION,
                        summary="Fixed it",
                        why=WHY,
                        publish=True,
                        github_client=UnstackedGitHubClient(),
                    )

                self.assertEqual(result["status"], "FAST_FIX_COMPLETE")
                self.assertIn("was published", result["next_action"])
                self.assertIn("was published", result["submit"]["next_action"])

    def test_matching_decline_next_action_follows_the_derived_status(self):
        # _finalize_matching_threads derives status from the publish outcome, so a
        # no-op publish reports _ACCEPTED. next_action must agree with that, not
        # with the --publish flag, or it claims evidence was published when the
        # publisher posted nothing.
        from gh_address_cr.core import workflow_matching

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                self._session("owner/repo", "703", github_thread("github-thread:M"))

                with patch(
                    "gh_address_cr.core.publisher.publish_github_thread_responses",
                    return_value=NO_OP_PUBLISH,
                ):
                    result = workflow_matching.decline_matching_threads(
                        "owner/repo",
                        "703",
                        agent_id="fixer-1",
                        files=["src/shared.py"],
                        resolution="reject",
                        homogeneous_reason="Shared style nit; declining with rationale.",
                        publish=True,
                        github_client=UnstackedGitHubClient(),
                    )

                self.assertEqual(result["status"], "DECLINE_ALL_ACCEPTED")
                self.assertNotIn("was published", result["next_action"])
                self.assertIn("agent publish", result["next_action"])

    def test_batch_that_accepted_nothing_is_not_complete_off_another_items_publish(self):
        # The call-site half of the empty-list contract: `item_ids or None` turned
        # "this batch owns no items" into "any published item counts", so a
        # session-wide publish for other, earlier items reported FAST_FIX_ALL_COMPLETE.
        import json
        from pathlib import Path

        from gh_address_cr.core import workflow

        with tempfile.TemporaryDirectory() as tmp:
            batch_path = Path(tmp) / "batch.json"
            batch_path.write_text(json.dumps({"items": []}), encoding="utf-8")
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                with (
                    patch(
                        "gh_address_cr.core.agent_batch.submit_batch_action_response",
                        return_value={"accepted_count": 0, "item_ids": [], "next_action": "n/a"},
                    ),
                    patch(
                        "gh_address_cr.core.publisher.publish_github_thread_responses",
                        return_value={
                            "status": "PUBLISH_COMPLETE",
                            "published_count": 1,
                            "published_items": ["github-thread:earlier"],
                        },
                    ),
                ):
                    result = workflow.fast_fix_from_batch_input(
                        "owner/repo", "704", batch_path=batch_path, publish=True
                    )

                self.assertEqual(result["status"], "FAST_FIX_ALL_ACCEPTED")

    def test_a_partially_published_multi_item_decline_is_not_reported_as_complete(self):
        # The end-to-end form of the same cell, through a path that really owns several
        # items. Before, this said DECLINE_ALL_COMPLETE and "evidence was published"
        # while one of the two threads had no reply posted.
        from gh_address_cr.core import workflow_matching

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                from gh_address_cr.core.session import SessionManager

                manager = SessionManager("owner/repo", "706")
                session = manager.create(status="WAITING_FOR_FIX")
                session["items"] = {}
                for index in (1, 2):
                    item = github_thread(f"github-thread:T{index}")
                    item["path"] = "src/shared.py"
                    item["line"] = 10 + index
                    session["items"][item["item_id"]] = item
                manager.save(session)

                with patch(
                    "gh_address_cr.core.publisher.publish_github_thread_responses",
                    return_value={
                        "status": "PUBLISH_COMPLETE",
                        "published_count": 1,
                        "published_items": ["github-thread:T1"],
                    },
                ):
                    result = workflow_matching.decline_matching_threads(
                        "owner/repo",
                        "706",
                        agent_id="fixer-1",
                        files=["src/shared.py"],
                        resolution="reject",
                        homogeneous_reason="Shared style nit; declining with rationale.",
                        publish=True,
                        github_client=UnstackedGitHubClient(),
                    )

                self.assertEqual(sorted(result["item_ids"]), ["github-thread:T1", "github-thread:T2"])
                self.assertEqual(result["status"], "DECLINE_ALL_ACCEPTED")
                self.assertNotIn("was published", result["next_action"])
                # The recovery is to publish again, which picks up what is still ready.
                self.assertIn("agent publish", result["next_action"])


if __name__ == "__main__":
    unittest.main()
