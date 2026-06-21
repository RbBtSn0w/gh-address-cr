import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gh_address_cr.core import paths as core_paths
from gh_address_cr.core.cr_metrics import build_cr_summary, cr_summary_markdown

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "cr_metrics" / "evidence-sample.jsonl"


class BuildCrSummaryTests(unittest.TestCase):
    def _seed(self, state, repo, pr, ledger_text):
        with patch("gh_address_cr.core.paths.state_dir", return_value=Path(state)):
            wd = core_paths.workspace_dir(repo, pr)
            wd.mkdir(parents=True, exist_ok=True)
            core_paths.evidence_ledger_file(repo, pr).write_text(ledger_text, encoding="utf-8")

    def test_happy_path_spans_and_stats(self):
        with tempfile.TemporaryDirectory() as state:
            self._seed(state, "o/r", "5", FIXTURE.read_text(encoding="utf-8"))
            with patch("gh_address_cr.core.paths.state_dir", return_value=Path(state)):
                r = build_cr_summary("o/r", "5")
            self.assertEqual(r["status"], "SUCCESS")
            self.assertEqual(r["reason_code"], "CR_SUMMARY_READY")
            self.assertEqual(r["cr_count_total"], 3)
            self.assertEqual(r["cr_count_completed"], 2)
            self.assertEqual(r["cr_count_incomplete"], 1)
            self.assertEqual(r["span_ms"]["max"], 30000)
            self.assertEqual(r["span_ms"]["min"], 4000)
            self.assertEqual(r["active_cr_time_ms"], 34000)
            self.assertEqual(r["classification_mix"], {"fix": 1, "reply": 1, "defer": 1})
            self.assertEqual(r["incomplete_crs"], [{"item_id": "C", "last_event_type": "classification_recorded"}])
            self.assertTrue(Path(r["report_artifact"]).exists())

    def test_empty_ledger_is_success_empty(self):
        with tempfile.TemporaryDirectory() as state:
            self._seed(state, "o/r", "5", "")
            with patch("gh_address_cr.core.paths.state_dir", return_value=Path(state)):
                r = build_cr_summary("o/r", "5")
            self.assertEqual(r["status"], "SUCCESS")
            self.assertEqual(r["reason_code"], "CR_LEDGER_EMPTY")
            self.assertEqual(r["cr_count_total"], 0)
            self.assertIsNone(r["span_ms"]["median"])

    def test_missing_ledger_is_success_empty(self):
        with tempfile.TemporaryDirectory() as state:
            with patch("gh_address_cr.core.paths.state_dir", return_value=Path(state)):
                core_paths.workspace_dir("o/r", "5").mkdir(parents=True, exist_ok=True)
                r = build_cr_summary("o/r", "5")
            self.assertEqual(r["reason_code"], "CR_LEDGER_EMPTY")


class EdgeAndMarkdownTests(unittest.TestCase):
    def _build(self, state, ledger_text):
        with patch("gh_address_cr.core.paths.state_dir", return_value=Path(state)):
            wd = core_paths.workspace_dir("o/r", "5")
            wd.mkdir(parents=True, exist_ok=True)
            core_paths.evidence_ledger_file("o/r", "5").write_text(ledger_text, encoding="utf-8")
            return build_cr_summary("o/r", "5")

    def test_malformed_line_is_skipped_with_diagnostic(self):
        with tempfile.TemporaryDirectory() as state:
            good = FIXTURE.read_text(encoding="utf-8")
            r = self._build(state, good + "\nnot json at all\n")
            self.assertEqual(r["status"], "SUCCESS")
            self.assertTrue(any("invalid JSON" in d for d in r["diagnostics"]))
            self.assertEqual(r["cr_count_total"], 3)

    def test_unreadable_ledger_fails_loud(self):
        with tempfile.TemporaryDirectory() as state:
            with patch("gh_address_cr.core.paths.state_dir", return_value=Path(state)):
                core_paths.workspace_dir("o/r", "5").mkdir(parents=True, exist_ok=True)
                core_paths.evidence_ledger_file("o/r", "5").mkdir()
                r = build_cr_summary("o/r", "5")
            self.assertEqual(r["status"], "FAILED")
            self.assertEqual(r["reason_code"], "CR_SUMMARY_UNAVAILABLE")

    def test_markdown_renders_counts_and_slowest(self):
        with tempfile.TemporaryDirectory() as state:
            r = self._build(state, FIXTURE.read_text(encoding="utf-8"))
            md = cr_summary_markdown(r)
            self.assertIn("CR Processing Summary", md)
            self.assertIn("2 completed, 1 incomplete", md)
            self.assertIn("Slowest CRs", md)

    def test_markdown_handles_empty(self):
        with tempfile.TemporaryDirectory() as state:
            r = self._build(state, "")
            md = cr_summary_markdown(r)
            self.assertIn("0 completed", md)
