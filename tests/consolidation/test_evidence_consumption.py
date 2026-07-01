"""Read-only evidence adapter tests (feature 024, US3)."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from gh_address_cr.core.consolidation.evidence import evaluation_to_rollout_evidence
from gh_address_cr.core.consolidation.types import RolloutStage
from gh_address_cr.core.protocol_codes import INSUFFICIENT_EVIDENCE
from tests.helpers import CLI_PY, PythonScriptTestCase


class EvidenceConsumptionTests(unittest.TestCase):
    def test_evaluation_results_map_to_read_only_rollout_evidence(self) -> None:
        evidence = evaluation_to_rollout_evidence(
            {
                "schema_version": "evaluation.v1",
                "evaluation_id": "evaluation_123",
                "durable_state": "verified",
                "durable_reason": "DURABLE_VERIFIED",
            }
        )
        self.assertEqual(evidence.status.value, "durable")
        self.assertEqual(evidence.reference, "evaluation.v1:evaluation_123")

    def test_missing_evidence_maps_to_insufficient_evidence(self) -> None:
        evidence = evaluation_to_rollout_evidence({})
        self.assertEqual(evidence.status.value, "insufficient")
        self.assertEqual(evidence.reason_code, INSUFFICIENT_EVIDENCE)
        self.assertEqual(evidence.suggested_stage, RolloutStage.SHADOW)


class EvidenceFailOpenWorkflowTests(PythonScriptTestCase):
    def install_fake_gh_for_threads(self, nodes):
        payload = {
            "data": {
                "repository": {
                    "pullRequest": {
                        "reviewThreads": {
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                            "nodes": nodes,
                        }
                    }
                }
            }
        }
        gh = self.bin_dir / "gh"
        gh.write_text(
            "\n".join(
                [
                    "#!/usr/bin/env python3",
                    "import json",
                    "import sys",
                    "args = sys.argv[1:]",
                    "if args[:2] == ['auth', 'status']:",
                    "    raise SystemExit(0)",
                    "if args[:2] == ['api', 'graphql']:",
                    f"    print(json.dumps({payload!r}))",
                    "    raise SystemExit(0)",
                    "if args[:2] == ['api', 'user']:",
                    "    print(json.dumps({'login': 'agent-login'}))",
                    "    raise SystemExit(0)",
                    "if args[:2] == ['api', 'repos/octo/example/pulls/77/reviews?per_page=100&page=1']:",
                    "    print('[]')",
                    "    raise SystemExit(0)",
                    "raise SystemExit(f'unhandled gh args: {args}')",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        gh.chmod(0o755)

    def test_evaluation_results_do_not_touch_runtime_truth_or_final_gate_inputs(self) -> None:
        self.workspace_dir().mkdir(parents=True, exist_ok=True)
        session_path = self.session_file()
        evidence_path = self.workspace_dir() / "evidence.jsonl"
        session_path.write_text('{"status":"ACTIVE"}\n', encoding="utf-8")
        evidence_path.write_text('{"event":"kept"}\n', encoding="utf-8")
        before_session = session_path.read_text(encoding="utf-8")
        before_evidence = evidence_path.read_text(encoding="utf-8")

        evidence = evaluation_to_rollout_evidence(
            {
                "schema_version": "evaluation.v1",
                "evaluation_id": "evaluation_read_only",
                "durable_state": "verified",
                "durable_reason": "DURABLE_VERIFIED",
            }
        )
        self.assertEqual(evidence.reference, "evaluation.v1:evaluation_read_only")
        self.assertEqual(session_path.read_text(encoding="utf-8"), before_session)
        self.assertEqual(evidence_path.read_text(encoding="utf-8"), before_evidence)

        self.install_fake_gh_for_threads([])
        result = self.run_cmd([self.env.get("PYTHON", "") or Path(__import__("sys").executable), str(CLI_PY), "final-gate", self.repo, self.pr])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("evaluation.v1:evaluation_read_only", result.stdout)
        self.assertNotIn("evaluation.v1:evaluation_read_only", result.stderr)

    def test_missing_evaluation_is_fail_open_for_auto_simple_review(self) -> None:
        self.install_fake_gh_for_threads([])

        result = self.run_cmd([self.env.get("PYTHON", "") or Path(__import__("sys").executable), str(CLI_PY), "review", "--auto-simple", self.repo, self.pr])

        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["status"], "PASSED")
        self.assertEqual(summary["reason_code"], "PASSED")
        self.assertEqual(summary["counts"]["blocking_items_count"], 0)
        self.assertEqual(summary["next_action"], "No action required.")


if __name__ == "__main__":
    unittest.main()
