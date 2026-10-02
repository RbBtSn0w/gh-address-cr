"""Contract tests for the batch claim/submit recovery surface (#273 class).

The single-item compositions got a rollback in #275. The batch path was described
there as "untouched, needs its own design"; probing it showed that framing was wrong
on both halves:

1. **Claim phase (`agent next --batch`) is already transactional.**
   `issue_batch_action_request` rolls the whole batch back on any exception, which is
   broader than `claimed_fixer_lease` (WorkflowError only). Nothing to add; these
   tests pin it so it cannot regress.

2. **Submit phase (`agent resolve --input`) retains leases on purpose.** The agent
   holds the skeleton and resubmits against the same lease ids, the same two-step
   shape `claimed_fixer_lease` deliberately does not roll back. Releasing there would
   delete the retry handle.

What was actually wrong is narrower: submit is not atomic (rows are accepted one by
one and appended to the evidence ledger), yet the recovery text said "no partial
evidence was accepted" and told the agent to edit and resubmit a file that can only
fail with STALE_LEASE. The state is recoverable -- `agent next --batch` skips accepted
items and reuses the still-active leases -- so the fix is a truthful message, not an
atomicity change nobody specified.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.test_control_plane_workflow import github_thread


def _thread(index):
    item = github_thread(f"github-thread:T{index}")
    item["path"] = f"src/f{index}.py"
    item["line"] = 10 + index
    return item


class BatchClaimRollbackTest(unittest.TestCase):
    def _session(self, repo, pr_number, count=3):
        from gh_address_cr.core.session import SessionManager

        manager = SessionManager(repo, pr_number)
        session = manager.create(status="WAITING_FOR_FIX")
        session["items"] = {f"github-thread:T{i}": _thread(i) for i in range(1, count + 1)}
        manager.save(session)
        return manager

    def test_claim_failure_on_a_later_item_rolls_back_the_whole_batch(self):
        from gh_address_cr.core import agent_batch

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                manager = self._session("owner/repo", "901")
                real = agent_batch.write_json_atomic
                calls = {"n": 0}

                def flaky(path, data):
                    # One action-request file is written per newly leased item.
                    if "action-request-" in str(path):
                        calls["n"] += 1
                        if calls["n"] == 2:
                            raise OSError("disk full (injected)")
                    return real(path, data)

                with patch.object(agent_batch, "write_json_atomic", side_effect=flaky):
                    with self.assertRaises(OSError):
                        agent_batch.issue_batch_action_request("owner/repo", "901", agent_id="agent-1")

                after = manager.load()
                # The first item's lease was created before the failure; it must not
                # survive it, or that item is locked behind a lease no one holds.
                self.assertEqual(after.get("leases", {}), {})
                for item in after["items"].values():
                    self.assertEqual(item.get("state"), "open")
                    self.assertIsNone(item.get("active_lease_id"))

                # And the agent can simply claim again.
                retry = agent_batch.issue_batch_action_request("owner/repo", "901", agent_id="agent-1")
                self.assertEqual(retry["status"], "BATCH_ACTION_REQUESTED")
                self.assertGreater(retry["lease_count"], 0)

    def test_batch_claim_reports_created_then_reentered_provenance(self):
        from gh_address_cr.core import agent_batch

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                self._session("owner/repo", "906", count=1)

                created = agent_batch.issue_batch_action_request(
                    "owner/repo", "906", agent_id="agent-1"
                )
                reentered = agent_batch.issue_batch_action_request(
                    "owner/repo", "906", agent_id="agent-1"
                )

        self.assertEqual(created["leased_items"][0]["acquisition"], "created")
        self.assertEqual(reentered["leased_items"][0]["acquisition"], "reentered")
        self.assertEqual(
            created["leased_items"][0]["lease_id"],
            reentered["leased_items"][0]["lease_id"],
        )


class BatchPartialAcceptanceRecoveryTest(unittest.TestCase):
    def _claim_and_fill(self, repo, pr_number):
        from gh_address_cr.core import agent_batch
        from gh_address_cr.core.session import SessionManager

        manager = SessionManager(repo, pr_number)
        session = manager.create(status="WAITING_FOR_FIX")
        session["items"] = {f"github-thread:T{i}": _thread(i) for i in (1, 2, 3)}
        manager.save(session)

        claimed = agent_batch.issue_batch_action_request(repo, pr_number, agent_id="agent-1")
        skeleton_path = Path(claimed["response_skeleton_path"])
        skeleton = json.loads(skeleton_path.read_text(encoding="utf-8"))
        skeleton["common"]["files"] = ["src/f1.py", "src/f2.py", "src/f3.py"]
        skeleton["common"]["commit_hash"] = "abc123"
        skeleton["common"]["validation_commands"] = [{"command": "unit", "result": "passed", "duration_ms": 5}]
        skeleton["common"]["fix_reply"] = {"summary": "fixed", "why": "because " * 30}
        for row in skeleton["items"]:
            row["fix_reply"] = {"summary": f"fixed {row['item_id']}", "why": "because " * 30}
        skeleton_path.write_text(json.dumps(skeleton), encoding="utf-8")
        return manager, skeleton_path

    def _fail_on_second_row(self):
        from gh_address_cr.core import agent_batch
        from gh_address_cr.core.errors import WorkflowError

        real = agent_batch.accept_action_response_submission
        calls = {"n": 0}

        def flaky(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 2:
                raise WorkflowError(
                    status="BATCH_ACTION_REJECTED",
                    reason_code="INJECTED_ROW_FAILURE",
                    waiting_on="batch_action_response",
                    exit_code=5,
                    message="row 2 failed",
                )
            return real(*args, **kwargs)

        return patch.object(agent_batch, "accept_action_response_submission", side_effect=flaky)

    def test_first_failure_does_not_deny_the_rows_it_already_accepted(self):
        from gh_address_cr.core import agent_batch
        from gh_address_cr.core.errors import WorkflowError

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                manager, skeleton_path = self._claim_and_fill("owner/repo", "902")

                with self._fail_on_second_row(), self.assertRaises(WorkflowError) as ctx:
                    agent_batch.submit_batch_action_response("owner/repo", "902", batch_path=skeleton_path)

                # Precondition: the partial acceptance really is persisted.
                statuses = sorted(lease["status"] for lease in manager.load()["leases"].values())
                self.assertEqual(statuses, ["accepted", "active"])

                message = str(ctx.exception)
                self.assertNotIn("no partial evidence was accepted", message)
                self.assertEqual(ctx.exception.payload["accepted_item_ids"], ["github-thread:T1"])
                self.assertEqual(ctx.exception.payload["recovery_action"], "regenerate_batch_response_skeleton")

    def test_resubmitting_the_same_file_names_the_accepted_rows_and_the_recovery_command(self):
        # This is the rejection the agent actually sees. It fails while *preparing* the
        # first row (its lease is already accepted), so no row is prepared -- detection
        # that keyed off prepared rows would miss it and keep the old, false text.
        from gh_address_cr.core import agent_batch
        from gh_address_cr.core.errors import WorkflowError

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                _, skeleton_path = self._claim_and_fill("owner/repo", "903")
                with self._fail_on_second_row(), self.assertRaises(WorkflowError):
                    agent_batch.submit_batch_action_response("owner/repo", "903", batch_path=skeleton_path)

                with self.assertRaises(WorkflowError) as ctx:
                    agent_batch.submit_batch_action_response("owner/repo", "903", batch_path=skeleton_path)

                self.assertEqual(ctx.exception.reason_code, "STALE_LEASE")
                message = str(ctx.exception)
                self.assertNotIn("no partial evidence was accepted", message)
                self.assertIn("github-thread:T1", message)
                self.assertIn("agent next", message)
                summary = ctx.exception.to_summary(repo="owner/repo", pr_number="903")
                # Structured readers must not be sent somewhere else than the message says.
                self.assertIn("agent next", summary["remediation"]["command"])
                # ...and specifically not the generic `address --lean` fallback that STALE_LEASE
                # would otherwise carry (the program name itself contains "address").
                self.assertNotIn("address owner/repo", summary["remediation"]["command"])
                self.assertNotIn("--lean", summary["remediation"]["command"])

    def test_structured_submit_command_points_at_the_regenerated_skeleton(self):
        # `agent next --batch` rewrites the runtime-owned skeleton at a fixed path, so
        # `commands.resolve_batch` must point there. The agent may well have submitted a
        # copy from elsewhere; pointing the command at that file would send a reader of
        # structured fields straight back into STALE_LEASE (PR #278 review). Submit a
        # copy so the two paths differ and the assertion can tell them apart.
        import shutil

        from gh_address_cr.core import agent_batch
        from gh_address_cr.core.errors import WorkflowError
        from gh_address_cr.core.paths import SessionPaths

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                _, skeleton_path = self._claim_and_fill("owner/repo", "905")
                submitted_copy = Path(tmp) / "my-batch-copy.json"
                shutil.copy(skeleton_path, submitted_copy)
                self.assertNotEqual(submitted_copy, skeleton_path)

                with self._fail_on_second_row(), self.assertRaises(WorkflowError) as ctx:
                    agent_batch.submit_batch_action_response("owner/repo", "905", batch_path=submitted_copy)

                runtime_skeleton = str(SessionPaths("owner/repo", "905").workspace_dir / "batch-response-skeleton.json")
                payload = ctx.exception.payload
                self.assertIn(runtime_skeleton, payload["commands"]["resolve_batch"])
                self.assertNotIn(str(submitted_copy), payload["commands"]["resolve_batch"])
                self.assertEqual(payload["batch_response_skeleton_path"], runtime_skeleton)
                # The human-readable text agrees with the structured field.
                self.assertIn(payload["commands"]["resolve_batch"], str(ctx.exception))

    def test_the_recommended_recovery_actually_recovers(self):
        # Asserting the text mentions `agent next --batch` is not enough: the advice is
        # only worth giving if running it yields a submittable batch for the rest.
        from gh_address_cr.core import agent_batch
        from gh_address_cr.core.errors import WorkflowError

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                manager, skeleton_path = self._claim_and_fill("owner/repo", "904")
                with self._fail_on_second_row(), self.assertRaises(WorkflowError):
                    agent_batch.submit_batch_action_response("owner/repo", "904", batch_path=skeleton_path)

                retry = agent_batch.issue_batch_action_request("owner/repo", "904", agent_id="agent-1")

                recovered = {row["item_id"] for row in retry["leased_items"]}
                # The accepted item is excluded; the one still holding a lease is reused.
                self.assertNotIn("github-thread:T1", recovered)
                self.assertIn("github-thread:T2", recovered)
                # Reusing the active lease must not have minted a second one for it.
                t2_leases = [
                    lease for lease in manager.load()["leases"].values() if lease["item_id"] == "github-thread:T2"
                ]
                self.assertEqual(len(t2_leases), 1)


if __name__ == "__main__":
    unittest.main()
