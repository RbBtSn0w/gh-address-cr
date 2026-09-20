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
        self.assertEqual(self.publish_outcome_status("FAST_FIX", publish=False), "FAST_FIX_ACCEPTED")
        self.assertEqual(
            self.publish_outcome_status("FAST_FIX", publish=False, published={"published_items": ["x"]}),
            "FAST_FIX_ACCEPTED",
        )

    def test_a_no_op_publish_is_not_complete(self):
        self.assertEqual(self.publish_outcome_status("DECLINE_ALL", publish=True, published=NO_OP_PUBLISH), "DECLINE_ALL_ACCEPTED")
        self.assertEqual(self.publish_outcome_status("DECLINE_ALL", publish=True, published=None), "DECLINE_ALL_ACCEPTED")

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

    def test_item_ids_none_accepts_any_published_item(self):
        self.assertEqual(
            self.publish_outcome_status("STALE_RESOLUTION", publish=True, published={"published_items": ["any"]}),
            "STALE_RESOLUTION_COMPLETE",
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
                        "owner/repo", "701",
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
                        "owner/repo", "702",
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


if __name__ == "__main__":
    unittest.main()
