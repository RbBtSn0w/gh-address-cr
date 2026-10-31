"""CI execution receipts must prove the same event-bound merge was tested."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.release import branch_validation as validation


class BranchValidationTests(unittest.TestCase):
    def setUp(self):
        self.expected = {
            "schema_version": "branch-validation.v1", "repository": "owner/repo",
            "pr_number": 42, "head_sha": "a" * 40, "base_sha": "b" * 40,
            "run_id": 12, "run_attempt": 2,
        }
        self.context = {**self.expected, "tested_merge_sha": "c" * 40,
                        "merge_parents": ["b" * 40, "a" * 40]}
        self.rows = [{**self.context, "source": source} for source in validation.SOURCES]

    def test_aggregate_matching_tested_contexts(self):
        self.assertEqual(validation.validate_sources(self.rows, self.expected), self.context)

    def test_reject_mixed_revision_stale_identity_and_malformed_receipts(self):
        changes = {
            "tested_merge_sha": "d" * 40, "base_sha": "d" * 40,
            "head_sha": "d" * 40, "schema_version": "branch-validation.v2",
            "merge_parents": ["a" * 40, "b" * 40], "run_attempt": 1,
            "run_id": 11, "repository": "other/repo", "pr_number": True,
        }
        for field, value in changes.items():
            with self.subTest(field=field):
                rows = copy.deepcopy(self.rows)
                rows[-1][field] = value
                with self.assertRaises(ValueError):
                    validation.validate_sources(rows, self.expected)

    def test_reject_missing_duplicate_unknown_source_and_extra_fields(self):
        for rows in (self.rows[:-1], self.rows + self.rows[:1],
                     [{**row, "source": "unknown"} for row in self.rows],
                     [{**row, "unexpected": "data"} for row in self.rows]):
            with self.assertRaises(ValueError):
                validation.validate_sources(rows, self.expected)

    def test_capture_records_git_checkout_not_event_merge_guess(self):
        result = unittest.mock.Mock(stdout="c" * 40 + " " + "b" * 40 + " " + "a" * 40 + "\n")
        with patch.object(validation.shared, "command", return_value=result):
            self.assertEqual(validation.capture(self.expected), self.context)
        result.stdout = "a" * 40 + " " + "b" * 40
        with patch.object(validation.shared, "command", return_value=result):
            with self.assertRaises(ValueError):
                validation.capture(self.expected)

    def test_event_is_ordinary_pr_only(self):
        event = {"repository": {"full_name": "owner/repo"}, "number": 42,
                 "pull_request": {"head": {"sha": "a" * 40}, "base": {"sha": "b" * 40}}}
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "event.json"
            path.write_text(json.dumps(event))
            env = {"GITHUB_EVENT_NAME": "pull_request", "GITHUB_EVENT_PATH": str(path),
                   "GITHUB_REPOSITORY": "owner/repo", "GITHUB_RUN_ID": "12", "GITHUB_RUN_ATTEMPT": "2"}
            with patch.dict(validation.os.environ, env, clear=True):
                self.assertEqual(validation.event_identity(), self.expected)
            env["GITHUB_EVENT_NAME"] = "pull_request_target"
            with patch.dict(validation.os.environ, env, clear=True):
                with self.assertRaises(ValueError):
                    validation.event_identity()

    def test_ci_binds_each_source_before_testing_and_requires_all_successes(self):
        workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/ci.yml").read_text()
        lint = workflow.split("  lint-and-test:\n", 1)[1].split("  otel-minimum-versions:\n", 1)[0]
        floor = workflow.split("  otel-minimum-versions:\n", 1)[1].split("  record-pr-validation-context:\n", 1)[0]
        for block, test_step in ((lint, "Unit tests (with coverage)"),
                                 (floor, "Unit tests at the minimum versions")):
            self.assertLess(block.index("Capture tested PR revision"), block.index(test_step))
            self.assertGreater(block.index("Upload tested PR revision"), block.index(test_step))
            self.assertIn("fetch-depth: 2", block)
            self.assertIn("persist-credentials: false", block)
            self.assertNotIn("secrets.", block)
        aggregate = workflow.split("  record-pr-validation-context:\n", 1)[1].split("  pr-dev-preview:\n", 1)[0]
        self.assertIn("needs: [validate-base, lint-and-test, otel-minimum-versions]", aggregate)
        self.assertIn("if: github.event_name == 'pull_request'", aggregate)
        self.assertNotIn("always()", aggregate)
        self.assertNotIn("secrets.", aggregate)
        self.assertIn("name: branch-validation-${{ github.run_id }}-${{ github.run_attempt }}", aggregate)
