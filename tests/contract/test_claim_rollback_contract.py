"""Contract tests for the claim-rollback invariant (#273 class).

> A rejected one-shot `agent resolve` must not leave a lease behind.

Before this invariant was enforced, each composition re-implemented the
claim/submit sequence by hand and `submit_action_response`'s `except
WorkflowError` handler saved the session without releasing. Validation that ran
*after* `issue_action_request` therefore locked the item until the lease TTL:
`agent resolve` then answered `LEASE_LOCKED_ITEM`, `agent next` answered
`NO_ELIGIBLE_ITEM`, and `agent reclaim` reported `expired_count=0`.

These tests pin the invariant at each one-shot claim site rather than at the one
disposition that happened to surface it, so a new validate-after-claim cannot
reopen the dead end unnoticed.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from tests.test_control_plane_workflow import github_thread
from tests.test_native_workflow import UnstackedGitHubClient, open_item, stale_github_thread_item

VALIDATION = [{"command": "unit-tests", "result": "passed", "duration_ms": 10}]
WHY = "Declining with a rationale long enough to satisfy the evidence threshold." * 2
REJECTION_CODE = "TEST_POST_CLAIM_REJECTION"


def _reject_after_claim():
    """Make submit_action_response raise, i.e. a rejection that lands after the claim.

    The original trigger was `fast_fix_item(..., publish=True)` on a non-thread item,
    but `_assert_item_publishable` now rejects that combination before any claim, so it
    no longer reaches the rollback. Patching the submit step exercises the invariant
    directly and keeps it independent of which validation happens to run late.
    """
    from gh_address_cr.core.errors import WorkflowError

    return patch(
        "gh_address_cr.core.agent_protocol.submit_action_response",
        side_effect=WorkflowError(
            status="ACTION_REJECTED",
            reason_code=REJECTION_CODE,
            waiting_on="action_response",
            exit_code=5,
            message="rejected after the lease was claimed",
        ),
    )


class ClaimRollbackContractTest(unittest.TestCase):
    def _session(self, repo, pr_number, item):
        from gh_address_cr.core.session import SessionManager

        manager = SessionManager(repo, pr_number)
        session = manager.create(status="WAITING_FOR_FIX")
        session["items"] = {item["item_id"]: item}
        manager.save(session)
        return manager

    def _active_leases(self, manager):
        return {
            lease_id: lease["status"]
            for lease_id, lease in manager.load().get("leases", {}).items()
            if lease.get("status") in {"active", "submitted"}
        }

    def test_fast_fix_rejection_after_claim_releases_lease(self):
        # The fix-path twin of #273: a rejection raised after `issue_action_request`
        # has already claimed the fixer lease must not leave it behind.
        from gh_address_cr.core import workflow
        from gh_address_cr.core.errors import WorkflowError

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                manager = self._session("owner/repo", "601", github_thread("github-thread:R"))

                with _reject_after_claim(), self.assertRaises(WorkflowError) as ctx:
                    workflow.fast_fix_item(
                        "owner/repo",
                        "601",
                        item_id="github-thread:R",
                        agent_id="fixer-1",
                        commit_hash="abc123",
                        files=["src/shared.py"],
                        validation_commands=VALIDATION,
                        summary="Fixed it",
                        why=WHY,
                        github_client=UnstackedGitHubClient(),
                    )

                self.assertEqual(ctx.exception.reason_code, REJECTION_CODE)
                self.assertEqual(self._active_leases(manager), {})
                # The rollback must record which rejection triggered it, not a fixed
                # "action_rejected": it fires on any WorkflowError, so a fixed label
                # would mislabel the lease events `agent leases` shows.
                (lease,) = manager.load()["leases"].values()
                self.assertEqual(lease["status"], "released")
                self.assertEqual(lease["reason"], f"action_rejected:{REJECTION_CODE}")

    def test_a_lease_the_call_did_not_create_is_not_released(self):
        # issue_action_request re-enters a lease the agent already holds instead of
        # minting a second one, so the rollback must distinguish "claimed here" from
        # "re-entered". Otherwise a failed one-shot resolve destroys the lease the agent
        # acquired through `agent next` -- the retry handle the two-step flow keeps on
        # purpose, and which this context manager's docstring promises not to touch.
        from gh_address_cr.core import agent_protocol, workflow
        from gh_address_cr.core.errors import WorkflowError

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                manager = self._session("owner/repo", "606", github_thread("github-thread:H"))
                agent_protocol.record_classification(
                    "owner/repo",
                    "606",
                    item_id="github-thread:H",
                    classification="fix",
                    agent_id="fixer-1",
                    note=WHY,
                )
                held = agent_protocol.issue_action_request(
                    "owner/repo", "606", role="fixer", agent_id="fixer-1", item_id="github-thread:H"
                )

                with _reject_after_claim(), self.assertRaises(WorkflowError):
                    workflow.fast_fix_item(
                        "owner/repo",
                        "606",
                        item_id="github-thread:H",
                        agent_id="fixer-1",
                        commit_hash="abc123",
                        files=["src/shared.py"],
                        validation_commands=VALIDATION,
                        summary="Fixed it",
                        why=WHY,
                        github_client=UnstackedGitHubClient(),
                    )

                lease = manager.load()["leases"][held["lease_id"]]
                self.assertEqual(lease["status"], "active")
                self.assertIsNone(lease.get("reason"))

    def test_decline_publish_on_a_local_finding_is_rejected_before_any_claim(self):
        # Not a rollback case: decline_item's own --publish guard (#274) rejects
        # before issue_action_request, so no lease is ever minted. Pinned as its
        # own case so a change to that ordering is visible, and named for what it
        # asserts rather than for the rollback the other cases exercise.
        from gh_address_cr.core import workflow
        from gh_address_cr.core.errors import WorkflowError

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                manager = self._session("owner/repo", "602", open_item("local:1"))

                with self.assertRaises(WorkflowError) as ctx:
                    workflow.decline_item(
                        "owner/repo",
                        "602",
                        item_id="local:1",
                        agent_id="fixer-1",
                        resolution="reject",
                        why=WHY,
                        publish=True,
                        github_client=UnstackedGitHubClient(),
                    )

                self.assertEqual(ctx.exception.reason_code, "PUBLISH_UNSUPPORTED_RESPONSE")
                self.assertEqual(self._active_leases(manager), {})

    def test_trivial_fix_is_gated_before_the_claim(self):
        # Not a rollback case: eligibility runs before record_classification, so
        # no lease is ever minted. Pinned so the enumeration stays complete if
        # that ordering is ever changed.
        from gh_address_cr.core import workflow
        from gh_address_cr.core.errors import WorkflowError

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                manager = self._session("owner/repo", "603", open_item("local:1"))

                with self.assertRaises(WorkflowError) as ctx:
                    workflow.trivial_fix_item(
                        "owner/repo",
                        "603",
                        item_id="local:1",
                        agent_id="fixer-1",
                        commit_hash="abc123",
                        files=["docs/readme.md"],
                        validation_commands=VALIDATION,
                        summary="Fix typo",
                        why=WHY,
                        publish=True,
                        github_client=UnstackedGitHubClient(),
                    )

                self.assertEqual(ctx.exception.reason_code, "TRIVIAL_THREAD_NOT_ELIGIBLE")
                self.assertEqual(manager.load().get("leases", {}), {})

    def test_rejected_claim_leaves_the_item_reclaimable(self):
        # The #273 dead end was not the rejection itself but what followed it.
        # Releasing the lease is only half the recovery: issue_action_request also
        # sets item["state"] = "claimed", which _item_is_open rejects, so a
        # lease-only release would degrade LEASE_LOCKED_ITEM into
        # NO_ELIGIBLE_ITEM instead of recovering.
        from gh_address_cr.core import agent_protocol, workflow
        from gh_address_cr.core.errors import WorkflowError

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                self._session("owner/repo", "604", github_thread("github-thread:X"))

                with _reject_after_claim(), self.assertRaises(WorkflowError):
                    workflow.fast_fix_item(
                        "owner/repo",
                        "604",
                        item_id="github-thread:X",
                        agent_id="fixer-1",
                        commit_hash="abc123",
                        files=["src/shared.py"],
                        validation_commands=VALIDATION,
                        summary="Fixed it",
                        why=WHY,
                        github_client=UnstackedGitHubClient(),
                    )

                # Same agent, same item: previously LEASE_LOCKED_ITEM.
                requested = agent_protocol.issue_action_request(
                    "owner/repo",
                    "604",
                    role="fixer",
                    agent_id="fixer-1",
                    item_id="github-thread:X",
                )
                self.assertTrue(requested["lease_id"])

    def test_release_claimed_lease_tolerates_an_already_released_lease(self):
        # agent_protocol_leases releases on stale_request_context, so a blanket
        # rollback could double-release and turn a clean protocol error into a
        # confusing LeaseSubmissionError.
        from gh_address_cr.core import agent_protocol, leases

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                manager = self._session("owner/repo", "605", stale_github_thread_item("github-thread:Y"))
                agent_protocol.record_classification(
                    "owner/repo",
                    "605",
                    item_id="github-thread:Y",
                    classification="reject",
                    agent_id="fixer-1",
                    note=WHY,
                )
                requested = agent_protocol.issue_action_request(
                    "owner/repo",
                    "605",
                    role="fixer",
                    agent_id="fixer-1",
                    item_id="github-thread:Y",
                )
                lease_id = str(requested["lease_id"])

                self.assertTrue(leases.release_claimed_lease("owner/repo", "605", lease_id=lease_id))
                # Second call must be a no-op, not a raise.
                self.assertFalse(leases.release_claimed_lease("owner/repo", "605", lease_id=lease_id))
                self.assertFalse(leases.release_claimed_lease("owner/repo", "605", lease_id="lease_missing"))
                self.assertEqual(self._active_leases(manager), {})


if __name__ == "__main__":
    unittest.main()
