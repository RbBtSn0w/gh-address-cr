"""Contract tests for owner re-entry into its own fixer lease (#273).

`agent next --batch` and `agent next --role fixer` disagreed on the same input. The
batch path reuses an agent's own active lease (`_reconcile_existing_lease`); the
single-item path raised LEASE_LOCKED_ITEM at the very agent that owned the lease.

That is not only an inconsistency. When an agent loses its request file -- workspace
cleaned, context reset -- its lease stays active in the session, so it can neither
submit (no request to answer) nor claim again (locked out by its own lease). It waits
for the TTL. Re-entry makes the single-item path behave as the batch path already does.

Boundaries pinned here, each of which changes behaviour if wrong:

- **Owner only.** Another agent, and another role, must still be locked out and see
  LEASE_RECOVERY_STOP exactly as before.
- **Same request identity.** A re-issued request keeps its original request_id and
  lease_id. Submit re-reads the request file and requires response.request_id to match,
  so a fresh id would strand any response the agent already wrote (STALE_REQUEST_CONTEXT)
  and recover nothing.
- **Active only.** A `submitted` lease means evidence was already sent; it is not
  re-entered.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from gh_address_cr.core.runtime_kernel.stack import project_stack_context
from tests.test_control_plane_workflow import github_thread


def _session(repo, pr_number):
    from gh_address_cr.core.session import SessionManager

    manager = SessionManager(repo, pr_number)
    session = manager.create(status="WAITING_FOR_FIX")
    item = github_thread("github-thread:X")
    item["path"] = "src/x.py"
    item["line"] = 5
    session["items"] = {item["item_id"]: item}
    manager.save(session)
    return manager


def _claim(repo, pr_number, agent_id="agent-a", role="fixer"):
    from gh_address_cr.core import agent_protocol

    agent_protocol.record_classification(
        repo, pr_number, item_id="github-thread:X", classification="fix", agent_id=agent_id, note="n"
    )
    return agent_protocol.issue_action_request(repo, pr_number, role=role, agent_id=agent_id, item_id="github-thread:X")


class OwnerReentryTest(unittest.TestCase):
    def test_owner_gets_its_own_request_back_instead_of_being_locked_out(self):
        from gh_address_cr.core import agent_protocol

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                manager = _session("owner/repo", "1001")
                first = _claim("owner/repo", "1001")

                again = agent_protocol.issue_action_request(
                    "owner/repo", "1001", role="fixer", agent_id="agent-a", item_id="github-thread:X"
                )

                self.assertEqual(again["lease_id"], first["lease_id"])
                self.assertEqual(again["request_path"], first["request_path"])
                self.assertEqual(again["resume_token"], first["resume_token"])
                # Re-entry reuses the lease; it must not mint a second one.
                self.assertEqual(len(manager.load()["leases"]), 1)

    def test_owner_recovers_when_the_request_files_were_lost(self):
        # The case re-entry exists for: the lease is still active but the agent has
        # nothing to answer.
        from gh_address_cr.core import agent_protocol

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                _session("owner/repo", "1002")
                first = _claim("owner/repo", "1002")
                original = json.loads(Path(first["request_path"]).read_text(encoding="utf-8"))
                Path(first["request_path"]).unlink()
                Path(first["response_skeleton_path"]).unlink()

                again = agent_protocol.issue_action_request(
                    "owner/repo", "1002", role="fixer", agent_id="agent-a", item_id="github-thread:X"
                )

                # Files exist again, at the paths the payload names.
                self.assertTrue(Path(again["request_path"]).is_file())
                self.assertTrue(Path(again["response_skeleton_path"]).is_file())
                rebuilt = json.loads(Path(again["request_path"]).read_text(encoding="utf-8"))
                # Same identity, or a response written earlier is stranded.
                self.assertEqual(rebuilt["request_id"], original["request_id"])
                self.assertEqual(rebuilt["lease_id"], original["lease_id"])

    def test_a_response_written_before_the_files_were_lost_still_submits(self):
        from gh_address_cr.core import agent_protocol

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                _session("owner/repo", "1003")
                first = _claim("owner/repo", "1003")
                request = json.loads(Path(first["request_path"]).read_text(encoding="utf-8"))
                response = {
                    "schema_version": request["schema_version"],
                    "request_id": request["request_id"],
                    "lease_id": request["lease_id"],
                    "agent_id": "agent-a",
                    "item_id": "github-thread:X",
                    "resolution": "clarify",
                    "note": "Not a defect; declining with rationale.",
                    "reply_markdown": "Not a defect; declining with rationale.",
                }
                response_path = Path(tmp) / "response.json"
                response_path.write_text(json.dumps(response), encoding="utf-8")
                Path(first["request_path"]).unlink()
                Path(first["response_skeleton_path"]).unlink()

                agent_protocol.issue_action_request(
                    "owner/repo", "1003", role="fixer", agent_id="agent-a", item_id="github-thread:X"
                )
                accepted = agent_protocol.submit_action_response("owner/repo", "1003", response_path=response_path)

                self.assertEqual(accepted["status"], "ACTION_ACCEPTED")

    def test_a_rebuilt_request_keeps_the_leases_hash_in_step_with_the_file(self):
        # A rebuilt request re-observes the stack, and `observed_at` is part of the hash,
        # so the rebuilt file hashes differently from the original. Submit recomputes the
        # hash from the file on disk, so the lease's stored copy must follow it or the two
        # disagree and submit fails opaquely.
        #
        # The clock is injected rather than left to wall time: with real timestamps the
        # two observations land in the same second about one run in five, the hash then
        # does not move, and an assertNotEqual on it is flaky.
        from gh_address_cr.core import agent_protocol
        from gh_address_cr.core.models import ActionRequest

        class TickingClient:
            """An absent-stack observation whose `observed_at` advances on every call."""

            def __init__(self):
                self.calls = 0

            def get_stack_context(self, repo, pr_number):
                self.calls += 1
                return project_stack_context(
                    {
                        "schema_version": "stack_observation.v1",
                        "availability": "absent",
                        "repo": repo,
                        "selected_pr_number": str(pr_number),
                        "observed_at": f"2026-08-01T12:00:{self.calls:02d}Z",
                        "selected_pr": {
                            "position": 1,
                            "pr_number": str(pr_number),
                            "state": "OPEN",
                            "is_draft": False,
                            "base_ref_name": "main",
                            "head_ref_name": "feature/test",
                            "head_oid": "a" * 40,
                            "merge_queue_state": None,
                        },
                        "members": [],
                    }
                )

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                manager = _session("owner/repo", "1008")
                client = TickingClient()
                agent_protocol.record_classification(
                    "owner/repo", "1008", item_id="github-thread:X", classification="fix", agent_id="agent-a", note="n"
                )
                first = agent_protocol.issue_action_request(
                    "owner/repo",
                    "1008",
                    role="fixer",
                    agent_id="agent-a",
                    item_id="github-thread:X",
                    github_client=client,
                )
                original_hash = manager.load()["leases"][first["lease_id"]]["request_hash"]
                Path(first["request_path"]).unlink()
                Path(first["response_skeleton_path"]).unlink()

                again = agent_protocol.issue_action_request(
                    "owner/repo",
                    "1008",
                    role="fixer",
                    agent_id="agent-a",
                    item_id="github-thread:X",
                    github_client=client,
                )

                on_disk = json.loads(Path(again["request_path"]).read_text(encoding="utf-8"))
                disk_hash = ActionRequest.from_dict(on_disk).stable_hash()
                lease_hash = manager.load()["leases"][first["lease_id"]]["request_hash"]
                self.assertEqual(lease_hash, disk_hash)
                # Pin why this matters: the hash really did move, so leaving the lease's
                # copy untouched would have left the two out of step.
                self.assertNotEqual(original_hash, disk_hash)

    def test_only_the_skeleton_missing_leaves_the_request_and_its_hash_alone(self):
        # The request file survives, so there is nothing to rebuild: the skeleton is
        # derived from the request already on disk. Rebuilding the request here moved the
        # lease's hash without rewriting the file, and the two then disagreed on submit.
        from gh_address_cr.core import agent_protocol

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                manager = _session("owner/repo", "1010")
                first = _claim("owner/repo", "1010")
                request = json.loads(Path(first["request_path"]).read_text(encoding="utf-8"))
                before_bytes = Path(first["request_path"]).read_bytes()
                before_hash = manager.load()["leases"][first["lease_id"]]["request_hash"]
                Path(first["response_skeleton_path"]).unlink()

                again = agent_protocol.issue_action_request(
                    "owner/repo", "1010", role="fixer", agent_id="agent-a", item_id="github-thread:X"
                )

                self.assertTrue(Path(again["response_skeleton_path"]).is_file())
                self.assertEqual(Path(first["request_path"]).read_bytes(), before_bytes)
                self.assertEqual(manager.load()["leases"][first["lease_id"]]["request_hash"], before_hash)

                # And the response written against that request still submits.
                response = {
                    "schema_version": request["schema_version"],
                    "request_id": request["request_id"],
                    "lease_id": request["lease_id"],
                    "agent_id": "agent-a",
                    "item_id": "github-thread:X",
                    "resolution": "clarify",
                    "note": "Not a defect; declining with rationale.",
                    "reply_markdown": "Not a defect; declining with rationale.",
                }
                response_path = Path(tmp) / "response.json"
                response_path.write_text(json.dumps(response), encoding="utf-8")
                accepted = agent_protocol.submit_action_response("owner/repo", "1010", response_path=response_path)
                self.assertEqual(accepted["status"], "ACTION_ACCEPTED")

    def test_a_corrupt_request_file_is_rebuilt_rather_than_handed_back(self):
        # `is_file()` alone treats a truncated or garbled request as present and returns
        # it, so the agent gets a file it cannot read. Unreadable means rebuild.
        from gh_address_cr.core import agent_protocol

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                _session("owner/repo", "1011")
                first = _claim("owner/repo", "1011")
                original = json.loads(Path(first["request_path"]).read_text(encoding="utf-8"))
                Path(first["request_path"]).write_text("{ not json", encoding="utf-8")

                again = agent_protocol.issue_action_request(
                    "owner/repo", "1011", role="fixer", agent_id="agent-a", item_id="github-thread:X"
                )

                rebuilt = json.loads(Path(again["request_path"]).read_text(encoding="utf-8"))
                self.assertEqual(rebuilt["request_id"], original["request_id"])
                self.assertEqual(rebuilt["lease_id"], original["lease_id"])

    def test_a_structurally_invalid_request_file_is_rebuilt_not_a_keyerror(self):
        # `{}` is valid JSON but not an ActionRequest. Accepting any JSON object as
        # readable let it through to skeleton generation, which indexes required keys
        # and raised KeyError. Structurally invalid means unreadable, i.e. rebuild.
        from gh_address_cr.core import agent_protocol

        for index, garbage in enumerate(("{}", '{"request_id": "x"}', "[]", "null")):
            with self.subTest(garbage=garbage):
                with tempfile.TemporaryDirectory() as tmp:
                    with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                        pr = str(1020 + index)
                        _session("owner/repo", pr)
                        first = _claim("owner/repo", pr)
                        original = json.loads(Path(first["request_path"]).read_text(encoding="utf-8"))
                        Path(first["request_path"]).write_text(garbage, encoding="utf-8")
                        Path(first["response_skeleton_path"]).unlink()

                        again = agent_protocol.issue_action_request(
                            "owner/repo", pr, role="fixer", agent_id="agent-a", item_id="github-thread:X"
                        )

                        rebuilt = json.loads(Path(again["request_path"]).read_text(encoding="utf-8"))
                        self.assertEqual(rebuilt["request_id"], original["request_id"])
                        self.assertEqual(rebuilt["lease_id"], original["lease_id"])

    def test_a_request_file_that_belongs_to_another_lease_is_rebuilt(self):
        # A file can be a perfectly valid ActionRequest and still not be *this* lease's.
        # Handing it back, with a skeleton named for the current request_id, points the
        # agent at the wrong request and the submit then fails with a mismatched context.
        # Being parseable is not enough: the identity has to match the lease.
        from gh_address_cr.core import agent_protocol

        for index, field in enumerate(("request_id", "lease_id")):
            with self.subTest(mismatched=field):
                with tempfile.TemporaryDirectory() as tmp:
                    with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                        pr = str(1040 + index)
                        _session("owner/repo", pr)
                        first = _claim("owner/repo", pr)
                        original = json.loads(Path(first["request_path"]).read_text(encoding="utf-8"))
                        foreign = dict(original)
                        foreign[field] = f"{field}_from_another_lease"
                        Path(first["request_path"]).write_text(json.dumps(foreign), encoding="utf-8")

                        again = agent_protocol.issue_action_request(
                            "owner/repo", pr, role="fixer", agent_id="agent-a", item_id="github-thread:X"
                        )

                        rebuilt = json.loads(Path(again["request_path"]).read_text(encoding="utf-8"))
                        self.assertEqual(rebuilt["request_id"], original["request_id"])
                        self.assertEqual(rebuilt["lease_id"], original["lease_id"])
                        skeleton = json.loads(Path(again["response_skeleton_path"]).read_text(encoding="utf-8"))
                        self.assertEqual(skeleton["request_id"], original["request_id"])
                        self.assertEqual(skeleton["lease_id"], original["lease_id"])

    def test_the_reentry_payload_carries_handling_boundary_like_a_fresh_claim(self):
        # The normal claim path returns `handling_boundary` at the top level when the
        # item has one; callers read it without opening the request file. Re-entry must
        # return the same shape.
        from gh_address_cr.core import agent_protocol

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                _session("owner/repo", "1030")
                first = _claim("owner/repo", "1030")
                # Precondition: a GitHub-thread fixer item really does have one, so the
                # assertion below is not vacuous.
                self.assertIn("handling_boundary", first)

                again = agent_protocol.issue_action_request(
                    "owner/repo", "1030", role="fixer", agent_id="agent-a", item_id="github-thread:X"
                )

                self.assertEqual(again.get("handling_boundary"), first["handling_boundary"])

    def test_intact_request_files_are_returned_untouched(self):
        # Re-entry must not rewrite a request the agent still has: rewriting would move
        # its hash for no reason and churn the file the agent is reading.
        from gh_address_cr.core import agent_protocol

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                manager = _session("owner/repo", "1009")
                first = _claim("owner/repo", "1009")
                before_bytes = Path(first["request_path"]).read_bytes()
                before_hash = manager.load()["leases"][first["lease_id"]]["request_hash"]

                agent_protocol.issue_action_request(
                    "owner/repo", "1009", role="fixer", agent_id="agent-a", item_id="github-thread:X"
                )

                self.assertEqual(Path(first["request_path"]).read_bytes(), before_bytes)
                self.assertEqual(manager.load()["leases"][first["lease_id"]]["request_hash"], before_hash)


class ReentryBoundaryTest(unittest.TestCase):
    def test_another_agent_is_still_locked_out(self):
        from gh_address_cr.core import agent_protocol
        from gh_address_cr.core.errors import WorkflowError

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                _session("owner/repo", "1004")
                _claim("owner/repo", "1004", agent_id="agent-a")

                with self.assertRaises(WorkflowError) as ctx:
                    agent_protocol.issue_action_request(
                        "owner/repo", "1004", role="fixer", agent_id="agent-b", item_id="github-thread:X"
                    )

                self.assertEqual(ctx.exception.reason_code, "LEASE_LOCKED_ITEM")
                self.assertEqual(ctx.exception.payload["lease_recovery"]["reason_code"], "LEASE_RECOVERY_STOP")

    def test_the_owner_under_a_different_role_is_not_re_entered_as_a_fixer(self):
        # `_active_lease_for_item` matches on item alone, so a naive re-entry check
        # would let a triage or verifier lease be handed back as a fixer request.
        from gh_address_cr.core import agent_protocol
        from gh_address_cr.core.errors import WorkflowError

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                manager = _session("owner/repo", "1005")
                _claim("owner/repo", "1005", agent_id="agent-a")
                # Re-label the lease as another role held by the same agent.
                session = manager.load()
                for lease in session["leases"].values():
                    lease["role"] = "verifier"
                manager.save(session)

                with self.assertRaises(WorkflowError) as ctx:
                    agent_protocol.issue_action_request(
                        "owner/repo", "1005", role="fixer", agent_id="agent-a", item_id="github-thread:X"
                    )

                self.assertEqual(ctx.exception.reason_code, "LEASE_LOCKED_ITEM")

    def test_a_submitted_lease_is_not_re_entered(self):
        # The agent already sent evidence; a fresh request would invite a duplicate.
        from gh_address_cr.core import agent_protocol
        from gh_address_cr.core.errors import WorkflowError

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                manager = _session("owner/repo", "1006")
                _claim("owner/repo", "1006")
                session = manager.load()
                for lease in session["leases"].values():
                    lease["status"] = "submitted"
                manager.save(session)

                with self.assertRaises(WorkflowError) as ctx:
                    agent_protocol.issue_action_request(
                        "owner/repo", "1006", role="fixer", agent_id="agent-a", item_id="github-thread:X"
                    )

                self.assertEqual(ctx.exception.reason_code, "LEASE_LOCKED_ITEM")

    def test_an_expired_lease_is_not_re_entered(self):
        # Re-entry runs after expire_leases, so an expired lease yields a fresh claim
        # (the normal path), never a resurrected old request.
        from gh_address_cr.core import agent_protocol

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                _session("owner/repo", "1007")
                first = _claim("owner/repo", "1007")
                later = datetime.now(timezone.utc) + timedelta(days=1)

                again = agent_protocol.issue_action_request(
                    "owner/repo", "1007", role="fixer", agent_id="agent-a", item_id="github-thread:X", now=later
                )

                self.assertNotEqual(again["lease_id"], first["lease_id"])


if __name__ == "__main__":
    unittest.main()
