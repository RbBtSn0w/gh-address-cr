"""Request-time diagnostics remain durable observations, never completion truth."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from gh_address_cr.core import agent_batch, agent_protocol
from gh_address_cr.core import session as session_store
from gh_address_cr.core.agent_protocol_submission import refresh_stack_context_for_request
from gh_address_cr.core.errors import WorkflowError
from gh_address_cr.core.gate import evaluate_final_gate
from gh_address_cr.core.runtime_kernel.stack import StackContext
from gh_address_cr.core.runtime_store import PersistenceBusyError, RuntimeStore
from tests.contract.test_owner_lease_reentry_contract import _session

REPO = "owner/repo"
PR = "1001"


def context(availability="invalid", invariant="head_ref_oid_lag"):
    code = "STACK_CONTEXT_INVALID" if availability == "invalid" else "STACK_CONTEXT_UNAVAILABLE"
    return StackContext(
        availability=availability, repo=REPO, selected_pr_number=PR,
        observed_at="2026-10-30T00:00:00Z", diagnostic_code=code,
        invalid_invariant=invariant if availability == "invalid" else None,
        diagnostic_cause=invariant if availability == "unavailable" else None,
    )


class RequestRejectionEvidenceContractTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.state_dir = temporary.name
        environ = patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": self.state_dir, "DISABLE_TELEMETRY": "1"})
        environ.start()
        self.addCleanup(environ.stop)
        self.manager = _session(REPO, PR)
        self.store = RuntimeStore(self.manager.workspace_path)

    def reject(self, observation=None, session=None):
        client = SimpleNamespace(get_stack_context=lambda *_: observation or context())
        with self.assertRaises(WorkflowError) as caught:
            refresh_stack_context_for_request(
                REPO, PR, session if session is not None else self.manager.load(), github_client=client,
            )
        self.assertEqual(caught.exception.status, "REQUEST_REJECTED")
        self.assertEqual(caught.exception.exit_code, 5)
        return caught.exception.to_summary(repo=REPO, pr_number=PR)

    def events(self):
        return [row for row in self.store.load_evidence()
                if row["payload"].get("schema_version") == "request-rejection.v1"]

    def test_rejection_is_committed_before_the_error_leaves_the_runtime(self):
        from gh_address_cr.core.cr_metrics import project_cr_lifecycle

        before = self.manager.load()
        summary = self.reject()

        self.assertEqual(len(self.events()), 1)
        row = self.events()[0]
        self.assertEqual(row["event_type"], "request_rejected")
        self.assertEqual(row["item_id"], "")
        self.assertIsNone(row["lease_id"])
        self.assertEqual(row["payload"]["reason_code"], summary["reason_code"])
        self.assertEqual(row["payload"]["stack_diagnostic"], summary["stack_diagnostic"])
        self.assertEqual(summary["rejection_persistence"]["storage"], "committed")
        self.assertEqual(summary["rejection_persistence"]["projection"], "current")
        after = self.manager.load()
        for field in ("items", "leases", "metadata", "status"):
            self.assertEqual(after[field], before[field])
        self.assertEqual(evaluate_final_gate(after).failure_codes, evaluate_final_gate(before).failure_codes)
        self.assertEqual(self.store.load_outbox(), [])
        self.assertEqual(project_cr_lifecycle(self.events(), repo=REPO, pr_number=PR)["items"], [])

    def test_reader_invariants_survive_request_rejection_persistence(self):
        for invariant in (
            "stack_not_object", "entries_not_object", "member_pull_request_missing", "pagination_cursor_invalid",
            "stack_missing_during_pagination", "selected_stack_entry_invalid", "selected_position_mismatch",
        ):
            with self.subTest(invariant=invariant):
                summary = self.reject(context(invariant=invariant))
                self.assertEqual(self.events()[-1]["payload"]["stack_diagnostic"], summary["stack_diagnostic"])

    def test_known_stacked_unavailable_is_recorded_but_unstacked_unavailable_is_not(self):
        observation = context("unavailable")
        refresh_stack_context_for_request(
            REPO, PR, self.manager.load(), github_client=SimpleNamespace(get_stack_context=lambda *_: observation),
        )
        self.assertEqual(self.events(), [])
        session = self.manager.load()
        session["metadata"] = {"pull_request_context": {"stack_membership_observed": True}}
        self.manager.save(session)
        self.assertEqual(self.reject(observation)["reason_code"], "STACK_CONTEXT_UNAVAILABLE")
        self.assertEqual(len(self.events()), 1)

    def test_repeated_observations_are_distinct_and_replay_is_idempotent(self):
        with patch("gh_address_cr.evidence.ledger._utc_now", return_value="2026-10-30T00:00:00Z"):
            self.reject()
            self.reject()
        rows = self.events()
        self.assertEqual(len(rows), 2)
        self.assertNotEqual(rows[0]["record_id"], rows[1]["record_id"])
        self.store.transact(lambda _: None, operation="session_update", evidence=[rows[0]])
        self.assertEqual(len(self.events()), 2)

    def test_diagnostic_preserves_a_newer_canonical_snapshot(self):
        stale = self.manager.load()

        def concurrent(current):
            current["metadata"]["concurrent"] = True
            current["items"]["github-thread:X"]["title"] = "Updated by another command"

        session_store.transact_session(REPO, PR, concurrent, operation="session_update")
        self.reject(session=stale)
        current = self.manager.load()
        self.assertTrue(current["metadata"]["concurrent"])
        self.assertEqual(current["items"]["github-thread:X"]["title"], "Updated by another command")

    def test_both_public_request_entrypoints_record_without_claiming(self):
        agent_protocol.record_classification(
            REPO, PR, item_id="github-thread:X", classification="fix", agent_id="agent", note="Verified",
        )
        client = SimpleNamespace(get_stack_context=lambda *_: context())
        with self.assertRaises(WorkflowError):
            agent_protocol.issue_action_request(
                REPO, PR, role="fixer", agent_id="agent", item_id="github-thread:X", github_client=client,
            )
        with patch("gh_address_cr.core.agent_protocol_submission.GitHubClient", return_value=client):
            with self.assertRaises(WorkflowError):
                agent_batch.issue_batch_action_request(REPO, PR, agent_id="agent")
        self.assertEqual(len(self.events()), 2)
        self.assertEqual(self.manager.load()["leases"], {})

    def test_rejected_request_rebuild_preserves_its_existing_lease(self):
        # Get a real absent observation without making a GitHub request.
        from gh_address_cr.github.client import GitHubClient
        from tests.helpers import load_stacked_pr_fixture
        from tests.test_stack_github_client import payload_runner

        agent_protocol.record_classification(
            REPO, PR, item_id="github-thread:X", classification="fix", agent_id="agent", note="Verified",
        )
        payload = load_stacked_pr_fixture("absent.json")
        payload["data"]["repository"]["pullRequest"]["number"] = int(PR)
        client = GitHubClient(runner=payload_runner(payload))
        issued = agent_protocol.issue_action_request(
            REPO, PR, role="fixer", agent_id="agent", item_id="github-thread:X", github_client=client,
        )
        Path(issued["request_path"]).unlink()
        before = self.manager.load()
        with self.assertRaises(WorkflowError):
            agent_protocol.issue_action_request(
                REPO, PR, role="fixer", agent_id="agent", item_id="github-thread:X",
                github_client=SimpleNamespace(get_stack_context=lambda *_: context()),
            )
        after = self.manager.load()
        self.assertEqual(after["leases"], before["leases"])
        self.assertEqual(after["items"], before["items"])
        self.assertEqual(len(self.events()), 1)

    def test_missing_store_does_not_create_a_session(self):
        with self.assertRaises(WorkflowError) as caught:
            refresh_stack_context_for_request(
                REPO, "9999", {"metadata": {}},
                github_client=SimpleNamespace(get_stack_context=lambda *_: context()),
            )
        diagnostic = caught.exception.payload["rejection_persistence"]
        self.assertEqual(diagnostic["storage"], "not_committed")
        self.assertEqual(diagnostic["reason_code"], "SESSION_NOT_FOUND")
        workspace = session_store.workspace_dir(REPO, "9999")
        self.assertFalse((workspace / "runtime.sqlite3").exists())
        self.assertFalse((workspace / "session.json").exists())

    def test_projection_failure_does_not_disguise_a_committed_record(self):
        with patch.object(RuntimeStore, "materialize_evidence_artifacts", side_effect=OSError("private/path/token")):
            summary = self.reject()
        self.assertEqual(summary["rejection_persistence"]["storage"], "committed")
        self.assertEqual(summary["rejection_persistence"]["projection"], "failed")
        self.assertEqual(len(self.events()), 1)
        self.assertNotIn("private/path/token", json.dumps(summary))
        self.manager.load()
        rows = [json.loads(line) for line in self.manager.ledger_path.read_text().splitlines()]
        self.assertEqual(rows[0]["record_id"], self.events()[0]["record_id"])

    def test_precommit_failure_preserves_original_rejection(self):
        with patch.object(RuntimeStore, "transact_working_set", side_effect=PersistenceBusyError()):
            summary = self.reject()
        self.assertEqual(summary["reason_code"], "STACK_CONTEXT_INVALID")
        self.assertEqual(summary["rejection_persistence"]["storage"], "not_committed")
        self.assertEqual(summary["rejection_persistence"]["reason_code"], "PERSISTENCE_BUSY")
        self.assertEqual(self.events(), [])

    def test_uncertain_commit_is_confirmed_by_record_identity(self):
        transact = RuntimeStore.transact_working_set

        def committed_then_raised(store, *args, **kwargs):
            transact(store, *args, **kwargs)
            raise OSError("private postcommit detail")

        with patch.object(RuntimeStore, "transact_working_set", committed_then_raised):
            summary = self.reject()
        self.assertEqual(summary["rejection_persistence"]["storage"], "committed")
        self.assertEqual(len(self.events()), 1)

    def test_confirmation_failure_is_unknown_and_never_masks_rejection(self):
        with patch.object(RuntimeStore, "transact_working_set", side_effect=PersistenceBusyError()), patch.object(
            RuntimeStore, "load_evidence", side_effect=OSError("secret failure"),
        ):
            summary = self.reject()
        self.assertEqual(summary["reason_code"], "STACK_CONTEXT_INVALID")
        self.assertEqual(summary["rejection_persistence"]["storage"], "unknown")
        self.assertNotIn("secret failure", json.dumps(summary))

    def test_record_survives_process_exit_and_projection_loss(self):
        self.reject()
        self.manager.ledger_path.unlink()
        self.manager.load()
        code = (
            "import json; from gh_address_cr.core.session import load_canonical_evidence; "
            f"print(json.dumps(load_canonical_evidence({REPO!r}, {PR!r})))"
        )
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
        rows = json.loads(result.stdout)
        self.assertEqual(rows[0]["payload"]["reason_code"], "STACK_CONTEXT_INVALID")
        self.assertTrue(self.manager.ledger_path.is_file())

    def test_unsafe_invariant_is_not_persisted_or_exported(self):
        unsafe = "/Users/private/token=secret"
        with patch("gh_address_cr.otel_tracing.add_current_span_event") as event:
            self.reject(context(invariant=unsafe))
        self.assertNotIn(unsafe, json.dumps(self.events()))
        self.assertNotIn(unsafe, str(event.call_args_list))
        self.assertNotIn("invariant", self.events()[0]["payload"]["stack_diagnostic"])

    def test_telemetry_failure_does_not_mask_or_undo_rejection(self):
        with patch("gh_address_cr.otel_tracing.add_current_span_event", side_effect=RuntimeError("exporter failed")):
            summary = self.reject()
        self.assertEqual(summary["reason_code"], "STACK_CONTEXT_INVALID")
        self.assertEqual(len(self.events()), 1)

    def test_archive_retains_the_canonical_diagnostic(self):
        from gh_address_cr.commands.final_gate import archive_and_clean_workspace

        self.reject()
        archive = archive_and_clean_workspace(REPO, PR, "rejection-contract")
        self.assertIsNotNone(archive)
        rows = RuntimeStore(Path(archive)).load_evidence()
        self.assertEqual(rows[0]["payload"]["schema_version"], "request-rejection.v1")
