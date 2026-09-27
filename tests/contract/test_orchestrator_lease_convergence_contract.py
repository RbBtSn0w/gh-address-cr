"""Spec 034 Phase C / Spec 035 F7: the orchestrator projects canonical leases and owns none.

These are behavior contracts. The previous version asserted that certain names
were absent from the module source, which proved nothing about what the
orchestrator actually decides.
"""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from gh_address_cr.core import leases, protocol_codes
from gh_address_cr.core.session import SessionManager, load_session
from gh_address_cr.orchestrator.harness import _record_reconciliation_event, handle_agent_orchestrate
from gh_address_cr.orchestrator.session import (
    DISPATCH_RECEIPT_SCHEMA_VERSION,
    load_orchestration_session,
    save_orchestration_session,
)
from tests.test_native_workflow import UnstackedGitHubClient

REPO = "owner/repo"
PR_NUMBER = "123"


def _item(item_id: str, *, path: str = "src/a.py", line: int = 1) -> dict:
    return {
        "item_id": item_id,
        "item_kind": "local_finding",
        "source": "local",
        "title": "Example finding",
        "body": "Fix me",
        "path": path,
        "line": line,
        "state": "open",
        "status": "OPEN",
        "blocking": True,
        "handled": False,
        "allowed_actions": ["fix", "clarify", "defer", "reject"],
        "classification_evidence": {
            "event_type": "classification_recorded",
            "classification": "fix",
            "note": "verified",
            "record_id": f"rec-{item_id}",
        },
    }


class OrchestratorLeaseConvergenceContractTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        for patcher in (
            patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": self.temp_dir.name}, clear=False),
            patch("gh_address_cr.core.agent_protocol_submission.GitHubClient", return_value=UnstackedGitHubClient()),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _write_items(self, *items: dict) -> None:
        manager = SessionManager(REPO, PR_NUMBER)
        payload = manager.create(status="ACTIVE")
        payload["items"] = {item["item_id"]: item for item in items}
        manager.save(payload)

    def _orchestrate(self, command: str, *args: str) -> tuple[int, dict]:
        stdout = io.StringIO()
        with patch("gh_address_cr.orchestrator.harness.sys.stdout", stdout):
            exit_code = handle_agent_orchestrate(command, [REPO, PR_NUMBER, *args])
        lines = [line for line in stdout.getvalue().splitlines() if line.strip()]
        return exit_code, json.loads(lines[-1]) if lines else {}

    def _step(self) -> tuple[int, dict]:
        return self._orchestrate("step", "--role", "fixer")

    def test_dispatch_token_is_the_canonical_lease_resume_token(self):
        self._write_items(_item("finding-1"))
        self.assertEqual(self._orchestrate("start")[0], 0)

        exit_code, payload = self._step()
        receipt = payload["packet"]["dispatch_receipt"]
        lease = load_session(REPO, PR_NUMBER)["leases"][receipt["lease_id"]]

        self.assertEqual(exit_code, 0)
        self.assertEqual(receipt["schema_version"], DISPATCH_RECEIPT_SCHEMA_VERSION)
        self.assertEqual(receipt["delivery_token"], lease["resume_token"])
        self.assertNotIn("expires_at", receipt)
        self.assertNotIn("context_key", receipt)

    def test_lost_dispatch_is_rebuilt_and_the_original_token_still_submits(self):
        self._write_items(_item("finding-1"))
        self._orchestrate("start")
        _, dispatched = self._step()
        token = dispatched["packet"]["dispatch_receipt"]["delivery_token"]
        orchestration = load_orchestration_session(REPO, PR_NUMBER)
        orchestration.active_dispatches = {}
        save_orchestration_session(orchestration)

        _, status = self._orchestrate("status")
        rebuilt = load_orchestration_session(REPO, PR_NUMBER).active_dispatches["finding-1"]
        response = Path(self.temp_dir.name) / "response.json"
        response.write_text("{}", encoding="utf-8")
        with patch("gh_address_cr.orchestrator.harness.parse_and_validate_response"), patch(
            "gh_address_cr.core.agent_protocol.submit_action_response", return_value={"status": "ACTION_ACCEPTED"}
        ):
            exit_code, submitted = self._orchestrate(
                "submit", "--item-id", "finding-1", "--token", token, "--input", str(response)
            )

        self.assertEqual(status["active_dispatches"], 1)
        self.assertEqual(rebuilt.delivery_token, token)
        self.assertEqual(exit_code, 0)
        self.assertEqual(submitted["reason_code"], "SUBMITTED")

    def test_same_file_dispatch_follows_core_lease_policy_only(self):
        self._write_items(_item("finding-1", line=1), _item("finding-2", line=80))
        self._orchestrate("start")

        first_code, _ = self._step()
        second_code, second = self._step()
        core_leases = [
            lease for lease in load_session(REPO, PR_NUMBER)["leases"].values() if lease["status"] == "active"
        ]
        dispatches = load_orchestration_session(REPO, PR_NUMBER).active_dispatches

        self.assertEqual(first_code, 0)
        self.assertEqual(second_code, 0)
        # The orchestrator neither grants nor refuses on its own: every dispatch is a
        # committed core lease, and every committed orchestrator lease has a dispatch.
        self.assertEqual(sorted(dispatches), sorted(lease["item_id"] for lease in core_leases))
        self.assertEqual(second.get("status") == "DISPATCHED", len(core_leases) == 2)

    def test_post_claim_failure_releases_the_canonical_lease(self):
        self._write_items(_item("finding-1"))
        self._orchestrate("start")

        with patch("gh_address_cr.orchestrator.harness.build_worker_packet", side_effect=RuntimeError("packet boom")):
            exit_code, failed = self._step()
        after_failure = load_session(REPO, PR_NUMBER)
        retry_code, retried = self._step()

        self.assertEqual(exit_code, 5)
        self.assertEqual(failed["reason_code"], protocol_codes.DISPATCH_PROJECTION_FAILED)
        self.assertEqual([lease["status"] for lease in after_failure["leases"].values()], ["released"])
        self.assertEqual(retry_code, 0)
        self.assertEqual(retried["packet"]["action_request"]["item"]["item_id"], "finding-1")

    def test_expired_canonical_lease_rejects_a_stale_dispatch_submit(self):
        self._write_items(_item("finding-1"))
        self._orchestrate("start")
        _, dispatched = self._step()
        token = dispatched["packet"]["dispatch_receipt"]["delivery_token"]
        leases.reclaim_leases(REPO, PR_NUMBER, now=datetime.now(timezone.utc) + timedelta(days=1))
        response = Path(self.temp_dir.name) / "response.json"
        response.write_text("{}", encoding="utf-8")

        with patch("gh_address_cr.core.agent_protocol.submit_action_response") as core_submit:
            exit_code, rejected = self._orchestrate(
                "submit", "--item-id", "finding-1", "--token", token, "--input", str(response)
            )

        self.assertEqual(exit_code, 2)
        self.assertEqual(rejected["reason_code"], protocol_codes.STALE_REQUEST_CONTEXT)
        core_submit.assert_not_called()
        self.assertEqual(load_orchestration_session(REPO, PR_NUMBER).active_dispatches, {})

    def test_reconciliation_telemetry_is_bounded_and_identity_free(self):
        with patch("gh_address_cr.otel_tracing.add_current_span_event") as emit:
            _record_reconciliation_event({"retained": 2, "removed": 1, "rebuilt": 1, "runtime_revision": 42})

        emit.assert_called_once_with(
            "orchestrator.reconcile",
            {
                "gh_address_cr.orchestrator.reconcile.outcome": "rebuilt",
                "gh_address_cr.orchestrator.reconcile.count_bucket": "2-5",
            },
        )


if __name__ == "__main__":
    unittest.main()
