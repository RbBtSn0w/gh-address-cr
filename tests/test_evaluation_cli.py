from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch


class EvaluationCliTestIntent:
    risk = "Machine consumers can receive unstable exit codes or evaluation commands can mutate runtime truth."
    why_automation = "CLI parsing, atomic catalog rebuild, and JSON output are public integration contracts."
    why_existing_tests_insufficient = "No existing command owns the evaluation namespace or derived catalog."
    chosen_layer = "Fixture-backed CLI integration test without live GitHub IO."
    fragility_analysis = "Assertions use public reason codes and output fields, not parser internals."
    if_omitted = "Agents could treat malformed or incomplete evaluation output as verified improvement."


class EvaluationCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state_dir = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": str(self.state_dir)})
        self.env.start()
        self.addCleanup(self.env.stop)

    def _archive(self, version: str, run_id: str, pr_number: str = "12") -> Path:
        from gh_address_cr.core.evaluation.archive import finalize_run_manifest

        target = self.state_dir / "archive" / "owner__repo" / f"pr-{pr_number}" / run_id
        target.mkdir(parents=True)
        session = {
            "items": {
                "item-1": {
                    "item_id": "item-1", "classification": "fix", "classification_verified": True,
                    "reply_evidence": {"record_id": "reply"}, "resolve_evidence": {"record_id": "resolve"},
                    "publish_evidence": {"record_id": "publish"}, "final_gate_passed": True,
                }
            }
        }
        (target / "session.json").write_text(json.dumps(session), encoding="utf-8")
        finalize_run_manifest(
            target, repo="owner/repo", pr_number=pr_number, run_id=run_id,
            final_gate_passed=True, final_gate_counts={},
        )
        manifest_path = target / "run-manifest.v1.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["runtime_version"] = version
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        return target

    def _run(self, argv: list[str]) -> tuple[int, dict]:
        from gh_address_cr.cli import main

        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(argv)
        raw = stdout.getvalue().strip()
        return code, json.loads(raw) if raw else {"stderr": stderr.getvalue()}

    def test_rebuild_and_show_are_derived_and_replay_stable(self):
        target = self._archive("1.0", "run-1")
        session_before = (target / "session.json").read_bytes()

        rebuild_code, first = self._run(["evaluation", "rebuild", "--repo", "owner/repo", "--pr-number", "12"])
        second_code, second = self._run(["evaluation", "rebuild", "--repo", "owner/repo", "--pr-number", "12"])
        show_code, shown = self._run(["evaluation", "show", "owner/repo", "12", "--run-id", "run-1"])

        self.assertEqual((rebuild_code, second_code, show_code), (0, 0, 0))
        self.assertEqual(first["source_fingerprint"], second["source_fingerprint"])
        self.assertEqual(shown["run_id"], "run-1")
        self.assertEqual((target / "session.json").read_bytes(), session_before)

    def test_show_fails_loudly_when_catalog_is_missing(self):
        code, payload = self._run(["evaluation", "show", "owner/repo", "12"])

        self.assertEqual(code, 4)
        self.assertEqual(payload["reason_code"], "EVALUATION_CATALOG_MISSING")

    def test_observe_deduplicates_read_only_github_results(self):
        self._archive("1.0", "run-1")
        observation = {
            "repo": "owner/repo", "pr_number": "12", "run_id": "run-1",
            "observed_at": "2099-06-30T02:00:00Z", "observed_head_sha": "abc",
            "review_round_id": "review-2", "review_state": "APPROVED",
            "reviewer_relation": "original_concern_author", "item_id": "item-1",
            "outcome_kind": "no_reopen", "correlation_method": "thread_id",
        }
        with patch("gh_address_cr.commands.evaluation.GitHubClient.evaluation_observations", return_value=[observation]):
            first_code, first = self._run(["evaluation", "observe", "owner/repo", "12", "--run-id", "run-1"])
            second_code, second = self._run(["evaluation", "observe", "owner/repo", "12", "--run-id", "run-1"])

        self.assertEqual((first_code, second_code), (0, 0))
        self.assertEqual(first["accepted_count"], 1)
        self.assertEqual(second["duplicate_count"], 1)

    def test_compare_returns_insufficient_evidence_as_valid_conclusion(self):
        self._archive("1.0", "run-1")
        self._archive("2.0", "run-2", pr_number="13")
        self._run(["evaluation", "rebuild"])

        code, payload = self._run([
            "evaluation", "compare", "--baseline-version", "1.0", "--candidate-version", "2.0"
        ])

        self.assertEqual(code, 0)
        self.assertEqual(payload["status"], "INSUFFICIENT_EVIDENCE")
        self.assertGreaterEqual(payload["operational_health"]["report_generation_overhead_ms"], 0.0)

    def test_unsafe_observation_fails_with_stable_exit_code(self):
        self._archive("1.0", "run-1")
        unsafe = {
            "repo": "owner/repo", "pr_number": "12", "run_id": "run-1",
            "observed_at": "2099-06-30T02:00:00Z", "observed_head_sha": "abc",
            "review_round_id": "review-2", "review_state": "APPROVED",
            "reviewer_relation": "unknown", "outcome_kind": "no_reopen",
            "correlation_method": "thread_id", "username": "private-user",
        }
        with patch("gh_address_cr.commands.evaluation.GitHubClient.evaluation_observations", return_value=[unsafe]):
            code, payload = self._run(["evaluation", "observe", "owner/repo", "12", "--run-id", "run-1"])

        self.assertEqual(code, 5)
        self.assertEqual(payload["reason_code"], "EVALUATION_INPUT_UNSAFE")


if __name__ == "__main__":
    unittest.main()
