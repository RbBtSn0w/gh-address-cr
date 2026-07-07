import json
import unittest

from gh_address_cr.core import gate
from gh_address_cr.github.diagnostics import classify_github_failure, github_waiting_on
from tests.helpers import PythonScriptTestCase, load_workflow_gap_fixture


class WorkflowGapRecoveryContractTests(unittest.TestCase):
    def test_final_gate_reply_reconcile_contract(self):
        fixture = load_workflow_gap_fixture("reply_reconcile_blocker")

        result = gate.evaluate_final_gate(
            fixture["session"],
            remote_threads=fixture["remote_threads"],
            current_login=fixture["current_login"],
        )

        self.assertFalse(result.passed)
        summary = result.to_machine_summary()
        self.assertEqual(summary["reason_code"], "FINAL_GATE_MISSING_REPLY_EVIDENCE")
        self.assertEqual(summary["reply_evidence_blockers"][0]["recoverability"], "reconcile")
        self.assertEqual(summary["reply_evidence_blockers"][0]["item_id"], "github-thread:THREAD_DONE")
        self.assertIn("agent evidence add octo/example 77", summary["next_action"])
        self.assertIn("--reply-url", summary["commands"]["evidence_add_reply"])

    def test_final_gate_historical_closed_item_contract(self):
        fixture = load_workflow_gap_fixture("historical_closed_item")

        result = gate.evaluate_final_gate(
            fixture["session"],
            remote_threads=fixture["remote_threads"],
            current_login=fixture["current_login"],
        )

        self.assertTrue(result.passed, result.to_machine_summary())
        summary = result.to_machine_summary()
        self.assertEqual(summary["historical_reply_items"][0]["reason_code"], "CLOSED_HISTORICAL_ITEM")
        self.assertEqual(summary["historical_reply_items"][0]["recoverability"], "non_blocking")

    def test_permission_mismatch_diagnostics_contract(self):
        diagnostics = classify_github_failure(
            load_workflow_gap_fixture("permission_mismatch_stderr"),
            "",
            1,
            ["gh", "pr", "create"],
        )

        self.assertEqual(
            diagnostics,
            {
                "stderr_category": "permission_mismatch",
                "severity": "blocking",
                "source_scope": "github_wrapper",
                "command": ["gh", "pr", "create"],
                "returncode": 1,
                "stderr_excerpt": "safeclis/gh: Permission denied for gh.create despite granted runner permission",
            },
        )
        self.assertEqual(github_waiting_on(diagnostics), "github_permission")


class WorkflowGapRecoveryLeaseContractTests(PythonScriptTestCase):
    def test_direct_item_resolution_reports_lease_recovery_contract(self):
        fixture = load_workflow_gap_fixture("lease_locked_item")
        payload = dict(fixture["session"])
        payload["ledger_path"] = str(self.workspace_dir() / "evidence.jsonl")
        self.workspace_dir().mkdir(parents=True, exist_ok=True)
        self.session_file().write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

        result = self.run_runtime_module(
            "agent",
            "resolve",
            self.repo,
            self.pr,
            "github-thread:THREAD_LOCKED",
            "--agent-id",
            "codex-1",
            "--commit",
            "abc123",
            "--files",
            "src/locked.py",
            "--summary",
            "Fix locked item.",
            "--why",
            "Apply the requested change.",
            "--validation",
            "python3 -m unittest tests.test_locked=passed",
            "--now",
            "2026-04-24T12:00:00+00:00",
        )

        self.assertEqual(result.returncode, 4, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["reason_code"], "LEASE_LOCKED_ITEM")
        self.assertEqual(summary["waiting_on"], "lease")
        self.assertEqual(summary["lease_recovery"]["lease_id"], "lease-existing")
        self.assertEqual(summary["lease_recovery"]["agent_id"], "batch-agent")
        self.assertIn("agent leases", summary["next_action"])
