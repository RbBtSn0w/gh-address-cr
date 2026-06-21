"""Regression tests for the resolved-thread validation-evidence gap (#142 follow-up).

A GitHub review thread classified ``fix`` and then resolved out-of-band (manual
``Resolve``, reviewer dismiss, or auto-outdated) leaves the session with no
item-level validation evidence. ``final-gate``'s logic-validation keeps blocking
with ``missing_required_evidence`` and no claim path can attach it
(``agent resolve --stale`` returns ``NO_MATCHING_GITHUB_THREADS`` once resolved).

``agent evidence add --item-id ... --validation ...`` (no ``--reply-url``, no
``--name``) ingests that validation evidence so the gate can reconcile it.
"""

import json
import unittest

from gh_address_cr.core.logic_validation import generate_logic_validation_signals
from tests.helpers import PythonScriptTestCase
from tests.test_control_plane_workflow import open_item


def _resolved_fix_thread(thread_id: str = "PRRT_recon") -> dict:
    """A github_thread classified fix and resolved out-of-band, missing validation."""
    item = open_item(
        f"github-thread:{thread_id}",
        item_kind="github_thread",
        source="github",
        path="src/recon.py",
        body="Please fix this concern.",
        state="closed",
        status="CLOSED",
        thread_id=thread_id,
    )
    item["decision"] = "fix"
    item["reply_posted"] = True
    item["reply_evidence"] = {"reply_url": "https://x/y#1", "author_login": "agent-login"}
    item["classification_evidence"] = {"classification": "fix", "note": "Fixed in commit abc1234."}
    return item


class ResolvedThreadValidationGapReproTest(unittest.TestCase):
    def test_logic_validation_blocks_resolved_fix_thread_without_validation(self):
        """REPRODUCE: the gap surfaces as a blocking logic-validation signal."""
        session = {"items": {it["item_id"]: it for it in [_resolved_fix_thread()]}}
        signals = generate_logic_validation_signals(session)
        blocking = [s for s in signals if s.gate_effect == "blocking"]
        self.assertTrue(blocking, "expected a blocking signal for the unreconciled thread")
        self.assertEqual(blocking[0].signal_type, "missing_required_evidence")

    def test_attaching_validation_evidence_clears_the_signal(self):
        """The recorded shape (``item['validation_evidence']``) clears the block."""
        item = _resolved_fix_thread()
        item["validation_evidence"] = [{"command": "python3 -m unittest", "result": "passed"}]
        session = {"items": {item["item_id"]: item}}
        blocking = [s for s in generate_logic_validation_signals(session) if s.gate_effect == "blocking"]
        self.assertEqual(blocking, [])


class ValidationEvidenceIngestTest(PythonScriptTestCase):
    def write_session(self, *, items):
        self.workspace_dir().mkdir(parents=True, exist_ok=True)
        payload = {
            "session_id": "session_recon",
            "repo": self.repo,
            "pr_number": self.pr,
            "status": "WAITING_FOR_GATE",
            "items": {item["item_id"]: item for item in items},
            "leases": {},
            "ledger_path": str(self.workspace_dir() / "evidence.jsonl"),
            "metrics": {},
        }
        self.session_file().write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def load_session(self):
        return json.loads(self.session_file().read_text(encoding="utf-8"))

    def ledger_rows(self):
        ledger = self.workspace_dir() / "evidence.jsonl"
        if not ledger.exists():
            return []
        return [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines() if line.strip()]

    def _add_validation(self, *extra):
        return self.run_runtime_module(
            "agent",
            "evidence",
            "add",
            self.repo,
            self.pr,
            "--item-id",
            "github-thread:PRRT_recon",
            "--commit",
            "abc1234",
            "--files",
            "src/recon.py",
            *extra,
        )

    def test_evidence_add_item_id_records_validation_and_clears_gate(self):
        self.write_session(items=[_resolved_fix_thread()])

        result = self._add_validation("--validation", "python3 -m unittest=passed")
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "VALIDATION_EVIDENCE_RECORDED")

        session = self.load_session()
        item = session["items"]["github-thread:PRRT_recon"]
        self.assertTrue(item.get("validation_evidence"))

        # Gate-equivalent: the blocking signal is gone.
        blocking = [s for s in generate_logic_validation_signals(session) if s.gate_effect == "blocking"]
        self.assertEqual(blocking, [])

        self.assertIn("validation_evidence_recorded", [r.get("event_type") for r in self.ledger_rows()])

    def test_failing_validation_result_is_rejected(self):
        """A failing verdict must not satisfy the gate (#117 carried forward)."""
        self.write_session(items=[_resolved_fix_thread()])
        result = self._add_validation("--validation", "python3 -m unittest=failed")
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertEqual(json.loads(result.stdout)["reason_code"], "VALIDATION_EVIDENCE_NOT_SUCCESS")

    def test_open_thread_is_rejected_not_a_resolve_backdoor(self):
        """Ingest is reconcile-only: an open (claimable) thread must be rejected."""
        open_thread = open_item(
            "github-thread:PRRT_recon",
            item_kind="github_thread",
            source="github",
            path="src/recon.py",
            body="Open concern.",
            state="open",
            status="OPEN",
            thread_id="PRRT_recon",
        )
        self.write_session(items=[open_thread])
        result = self._add_validation("--validation", "python3 -m unittest=passed")
        self.assertEqual(result.returncode, 4, result.stdout)
        self.assertEqual(json.loads(result.stdout)["reason_code"], "THREAD_NOT_TERMINAL")


if __name__ == "__main__":
    unittest.main()
