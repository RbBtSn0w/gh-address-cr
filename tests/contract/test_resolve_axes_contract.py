"""Contract tests for the orthogonal `agent resolve` axes (spec 029).

Enumerates the (disposition x selection x condition) product and asserts:
- every valid cross-axis cell resolves via the expected primitive (SC-002/SC-003)
- every same-axis conflict / incoherent-evidence cell yields exactly one
  directive reason code (C-A3, C-A4)

T008/T009 fill the (single x reject x fresh) and (single x clarify x stale)
cells that #204 previously rejected. T011 locks in final-gate authority and
lease-ownership semantics for the decline path. The full cross-axis product
(T017) is US2 scope.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from tests.helpers import PythonScriptTestCase
from tests.test_control_plane_workflow import github_thread
from tests.test_native_workflow import stale_github_thread_item

DISPOSITIONS = ("fix", "trivial", "reject", "clarify")
SELECTIONS = ("single", "files", "batch")
CONDITIONS = ("fresh", "stale")


class ResolveAxesEnumerationTest(unittest.TestCase):
    """Scaffold: enumerates the product for reference; no assertions yet."""

    def test_product_is_fully_enumerable(self):
        cells = [
            (d, s, c) for d in DISPOSITIONS for s in SELECTIONS for c in CONDITIONS
        ]
        self.assertEqual(len(cells), len(DISPOSITIONS) * len(SELECTIONS) * len(CONDITIONS))


class SingleItemDeclineAxesCLITest(PythonScriptTestCase):
    """T008/T009: drive the real CLI dispatch, not the validators directly.

    The bug #204 fixes lives in the outer `selected_modes` gate, which a
    validator-only unit test would not exercise.
    """

    REASON = "This nit is a style preference, not a defect; declining with rationale."

    def write_session(self, *, items):
        self.workspace_dir().mkdir(parents=True, exist_ok=True)
        payload = {
            "session_id": "session_axes",
            "repo": self.repo,
            "pr_number": self.pr,
            "status": "WAITING_FOR_FIX",
            "items": {item["item_id"]: item for item in items},
            "leases": {},
            "ledger_path": str(self.workspace_dir() / "evidence.jsonl"),
            "metrics": {"blocking_items_count": len(items)},
        }
        self.session_file().write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def load_session(self):
        return json.loads(self.session_file().read_text(encoding="utf-8"))

    def test_single_disposition_reject_on_fresh_thread(self):
        # (single x reject x fresh): the flagship #204 cell.
        self.write_session(items=[github_thread("github-thread:fresh1")])

        result = self.run_runtime_module(
            "agent", "resolve", self.repo, self.pr,
            "github-thread:fresh1",
            "--disposition", "reject",
            "--why", self.REASON,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["item_id"], "github-thread:fresh1")
        session = self.load_session()
        item = session["items"]["github-thread:fresh1"]
        self.assertEqual(item["state"], "publish_ready")
        self.assertEqual(item["publish_resolution"], "reject")

    def test_single_disposition_clarify_on_stale_thread(self):
        # (single x clarify x stale): previously blocked by the flat
        # selected_modes list treating --stale and --clarify as competing
        # "modes" instead of independent axes (R-1/C-A2).
        self.write_session(items=[stale_github_thread_item("github-thread:stale1")])

        result = self.run_runtime_module(
            "agent", "resolve", self.repo, self.pr,
            "github-thread:stale1",
            "--disposition", "clarify",
            "--stale",
            "--why", self.REASON,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["item_id"], "github-thread:stale1")
        session = self.load_session()
        item = session["items"]["github-thread:stale1"]
        self.assertEqual(item["state"], "publish_ready")
        self.assertEqual(item["publish_resolution"], "clarify")


class DeclineFinalGateAndLeaseTest(unittest.TestCase):
    """T011: final-gate authority and lease-ownership hold for decline too."""

    def _write_session(self, repo, pr_number, item):
        from gh_address_cr.core.session import SessionManager

        manager = SessionManager(repo, pr_number)
        session = manager.create(status="WAITING_FOR_CLASSIFICATION")
        session["items"] = {item["item_id"]: item}
        manager.save(session)
        return manager

    def test_decline_reaches_final_gate_pass(self):
        from gh_address_cr.core import gate, publisher, workflow

        class FakeGitHubClient:
            def __init__(self):
                self.replies = []
                self.resolved = []

            def post_reply(self, repo, pr_number, thread_id, body):
                self.replies.append((repo, pr_number, thread_id, body))
                return "https://github.test/reply/decline"

            def resolve_thread(self, repo, pr_number, thread_id):
                self.resolved.append((repo, pr_number, thread_id))
                return True

        repo = "owner/repo"
        pr_number = "509"
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                manager = self._write_session(
                    repo, pr_number, stale_github_thread_item("github-thread:THREAD_DECLINE")
                )

                workflow.decline_item(
                    repo, pr_number,
                    item_id="github-thread:THREAD_DECLINE",
                    agent_id="fixer-1",
                    resolution="reject",
                    why="Style preference only; not a defect.",
                )
                published = publisher.publish_github_thread_responses(
                    repo, pr_number, agent_id="fixer-1", github_client=FakeGitHubClient(),
                )
                result = gate.evaluate_final_gate(
                    manager.load(),
                    remote_threads=[{"id": "THREAD_DECLINE", "isResolved": True}],
                    current_login="fixer-1",
                )

                self.assertEqual(published["status"], "PUBLISH_COMPLETE")
                self.assertEqual(result.counts["unresolved_github_threads_count"], 0)
                self.assertEqual(result.counts["blocking_items_count"], 0)
                self.assertEqual(result.counts["github_threads_missing_reply_count"], 0)

    def test_decline_second_agent_hits_lease_locked(self):
        # An item already leased by another agent blocks a second agent's
        # decline_item(...) the same way it blocks fast_fix_item(...) —
        # decline_item composes the same disposition-agnostic
        # issue_action_request lease primitive (FR-009).
        from datetime import datetime, timedelta, timezone

        from gh_address_cr.core import workflow
        from gh_address_cr.core.errors import WorkflowError

        repo = "owner/repo"
        pr_number = "510"
        now = datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": tmp}, clear=False):
                from gh_address_cr.core.session import SessionManager

                manager = SessionManager(repo, pr_number)
                session = manager.create(status="WAITING_FOR_FIX")
                item = github_thread("github-thread:THREAD_LOCK")
                item["active_lease_id"] = "lease-existing"
                session["items"] = {item["item_id"]: item}
                session["leases"] = {
                    "lease-existing": {
                        "lease_id": "lease-existing",
                        "item_id": "github-thread:THREAD_LOCK",
                        "agent_id": "fixer-1",
                        "role": "fixer",
                        "status": "active",
                        "created_at": now.isoformat(),
                        "expires_at": (now + timedelta(hours=1)).isoformat(),
                        "resume_token": "resume:req_existing",
                        "request_hash": "existing-request-hash",
                        "request_id": "req_existing",
                        "conflict_keys": [],
                    }
                }
                manager.save(session)

                with self.assertRaises(WorkflowError) as ctx:
                    workflow.decline_item(
                        repo, pr_number,
                        item_id="github-thread:THREAD_LOCK",
                        agent_id="fixer-2",
                        resolution="reject",
                        why="Style preference only; not a defect.",
                    )
                self.assertEqual(ctx.exception.reason_code, "LEASE_LOCKED_ITEM")


class CrossAxisCompositionCLITest(PythonScriptTestCase):
    """T017: the full cross-axis product — every valid cell resolves, every
    same-axis conflict / incoherent-evidence cell yields one directive
    reason code."""

    REASON = "This is a shared style nit, not a defect; declining with rationale."

    def write_session(self, *, items):
        self.workspace_dir().mkdir(parents=True, exist_ok=True)
        payload = {
            "session_id": "session_crossaxis",
            "repo": self.repo,
            "pr_number": self.pr,
            "status": "WAITING_FOR_FIX",
            "items": {item["item_id"]: item for item in items},
            "leases": {},
            "ledger_path": str(self.workspace_dir() / "evidence.jsonl"),
            "metrics": {"blocking_items_count": len(items)},
        }
        self.session_file().write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    # --- valid cross-axis cells ---

    def test_files_reject_stale_succeeds_without_match_files(self):
        # (files x reject x stale), no --match-files (F1 regression guard).
        self.write_session(items=[stale_github_thread_item("github-thread:fstale1")])

        result = self.run_runtime_module(
            "agent", "resolve", self.repo, self.pr,
            "--disposition", "reject",
            "--files", "src/example.py",
            "--stale",
            "--why", self.REASON,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_files_fix_stale_succeeds(self):
        # (files x fix x stale): the pre-existing --stale --commit path.
        self.write_session(items=[stale_github_thread_item("github-thread:ffixstale")])

        result = self.run_runtime_module(
            "agent", "resolve", self.repo, self.pr,
            "--commit", "abc123",
            "--files", "src/example.py",
            "--stale",
            "--validation", "unit-tests=passed@100ms",
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_files_clarify_fresh_succeeds(self):
        # (files x clarify x fresh).
        self.write_session(items=[github_thread("github-thread:fclarify")])

        result = self.run_runtime_module(
            "agent", "resolve", self.repo, self.pr,
            "--disposition", "clarify",
            "--files", "src/shared.py",
            "--why", self.REASON,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "DECLINE_ALL_ACCEPTED")

    def test_single_trivial_stale_succeeds(self):
        # (single x trivial x stale): FR-003 is exhaustive over all four
        # dispositions, including trivial — do not skip this cell.
        self.write_session(
            items=[
                stale_github_thread_item("github-thread:trivialstale")
                | {"body": "Fix typo: 'recieve' should be 'receive'.", "title": "Typo in docstring"}
            ]
        )

        result = self.run_runtime_module(
            "agent", "resolve", self.repo, self.pr,
            "github-thread:trivialstale",
            "--disposition", "trivial",
            "--stale",
            "--commit", "abc123",
            "--files", "src/example.py",
            "--summary", "Fixed a typo.",
            "--why", "Docs-only correction.",
            "--validation", "spellcheck=passed@50ms",
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_item_id_reject_with_deprecated_homogeneous_reason_alias_succeeds(self):
        # (U2-dissolved): the deprecated alias still supplies the reason for
        # a single decline; no special item_id+alias conflict rule exists.
        self.write_session(items=[github_thread("github-thread:aliasreason")])

        result = self.run_runtime_module(
            "agent", "resolve", self.repo, self.pr,
            "github-thread:aliasreason",
            "--disposition", "reject",
            "--homogeneous-reason", self.REASON,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_batch_dispatch_routes_to_batch_primitive(self):
        # (batch x mixed): batch dispatch is orthogonal to the disposition
        # axis (each item's resolution lives inside the batch payload, not
        # behind --disposition) and is untouched by this feature; assert
        # only that selection routing still reaches the batch primitive.
        from unittest.mock import patch as mock_patch

        with mock_patch(
            "gh_address_cr.commands.agent.workflow.fast_fix_from_batch_input",
            return_value={"status": "FAST_FIX_ALL_COMPLETE"},
        ) as mocked:
            result = self.run_runtime_module(
                "agent", "resolve", self.repo, self.pr,
                "--batch", "--input", "batch-response.json",
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        mocked.assert_called_once()

    # --- same-axis conflicts / incoherent evidence ---

    def test_item_id_and_files_selection_conflict_for_decline(self):
        self.write_session(items=[github_thread("github-thread:selconflict")])

        result = self.run_runtime_module(
            "agent", "resolve", self.repo, self.pr,
            "github-thread:selconflict",
            "--disposition", "reject",
            "--files", "src/shared.py",
            "--why", self.REASON,
        )

        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)["reason_code"], "RESOLVE_AXIS_CONFLICT")

    def test_legacy_boolean_disagreeing_with_disposition_conflicts(self):
        self.write_session(items=[github_thread("github-thread:legacyconflict")])

        result = self.run_runtime_module(
            "agent", "resolve", self.repo, self.pr,
            "github-thread:legacyconflict",
            "--disposition", "fix",
            "--reject",
            "--why", self.REASON,
        )

        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)["reason_code"], "RESOLVE_AXIS_CONFLICT")

    def test_fix_evidence_with_decline_disposition_is_incoherent(self):
        self.write_session(items=[github_thread("github-thread:incoherent")])

        result = self.run_runtime_module(
            "agent", "resolve", self.repo, self.pr,
            "github-thread:incoherent",
            "--disposition", "clarify",
            "--commit", "abc123",
            "--why", self.REASON,
        )

        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)["reason_code"], "RESOLVE_EVIDENCE_INCOHERENT")

    def test_trivial_with_files_and_no_item_id_requires_item_id(self):
        # (F2): the one retained, intentional cross-axis exclusion.
        self.write_session(items=[github_thread("github-thread:trivialnoitem")])

        result = self.run_runtime_module(
            "agent", "resolve", self.repo, self.pr,
            "--disposition", "trivial",
            "--files", "src/shared.py",
            "--commit", "abc123",
            "--summary", "Fixed a typo.",
            "--why", "Docs-only correction.",
        )

        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)["reason_code"], "TRIVIAL_REQUIRES_ITEM_ID")


class FixEvidenceMissingArgsUnchangedTest(PythonScriptTestCase):
    """T018: fix-disposition missing-evidence codes are preserved, not renamed."""

    def write_session(self, *, items):
        self.workspace_dir().mkdir(parents=True, exist_ok=True)
        payload = {
            "session_id": "session_missingargs",
            "repo": self.repo,
            "pr_number": self.pr,
            "status": "WAITING_FOR_FIX",
            "items": {item["item_id"]: item for item in items},
            "leases": {},
            "ledger_path": str(self.workspace_dir() / "evidence.jsonl"),
            "metrics": {"blocking_items_count": len(items)},
        }
        self.session_file().write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def test_single_fix_missing_evidence_is_missing_resolve_args(self):
        self.write_session(items=[github_thread("github-thread:missingsingle")])

        result = self.run_runtime_module(
            "agent", "resolve", self.repo, self.pr,
            "github-thread:missingsingle",
        )

        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)["reason_code"], "MISSING_RESOLVE_ARGS")

    def test_collective_fix_missing_commit_is_missing_fix_reply_commit_hash(self):
        self.write_session(items=[github_thread("github-thread:missingcollective")])

        result = self.run_runtime_module("agent", "resolve", self.repo, self.pr)

        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)["reason_code"], "MISSING_FIX_REPLY_COMMIT_HASH")


class ResolveHelpDiscoverabilityTest(unittest.TestCase):
    """T019: --help documents the three axes, not a list of mode-preset flags."""

    def test_help_documents_axis_parameters(self):
        import io
        from contextlib import redirect_stdout

        from gh_address_cr.commands.agent import handle_agent_resolve

        buf = io.StringIO()
        with redirect_stdout(buf), self.assertRaises(SystemExit):
            handle_agent_resolve(None, ["o/r", "1", "--help"])
        help_text = buf.getvalue()

        for token in ("--disposition", "--stale", "--files", "--input", "item_id"):
            self.assertIn(token, help_text)

        # PR #206 CR: --why's help text must not read as reject/clarify-only —
        # it is also the shared rationale for a homogeneous fix (files selection).
        options_section = help_text[help_text.index("--why", help_text.index("options:")):]
        why_description = options_section.split("--agent-id")[0]
        self.assertIn("homogeneous", why_description.lower())


if __name__ == "__main__":
    unittest.main()
