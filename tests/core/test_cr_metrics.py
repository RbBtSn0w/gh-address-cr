import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gh_address_cr.commands.telemetry import handle_telemetry_command
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

    def test_bad_timestamp_and_missing_item_id_emit_diagnostics(self):
        # Regression: events dropped for unparseable timestamp or missing item_id
        # must surface a diagnostic, not vanish silently.
        ledger = (
            '{"session_id":"s1","item_id":"A","event_type":"classification_recorded","timestamp":"2026-06-21T10:00:00Z","payload":{"classification":"fix"}}\n'
            '{"session_id":"s1","item_id":"A","event_type":"thread_resolved","timestamp":"2026-06-21T10:00:04Z","payload":{}}\n'
            '{"session_id":"s1","item_id":"B","event_type":"classification_recorded","timestamp":"not-a-date","payload":{}}\n'
            '{"session_id":"s1","event_type":"reply_posted","timestamp":"2026-06-21T10:00:05Z","payload":{}}\n'
        )
        with tempfile.TemporaryDirectory() as state:
            r = self._build(state, ledger)
            self.assertEqual(r["status"], "SUCCESS")
            self.assertEqual(r["cr_count_completed"], 1)
            self.assertTrue(any("unparseable timestamp" in d for d in r["diagnostics"]))
            self.assertTrue(any("missing item_id" in d for d in r["diagnostics"]))


class CrSummaryCliTests(unittest.TestCase):
    def _seed(self, state):
        with patch("gh_address_cr.core.paths.state_dir", return_value=Path(state)):
            wd = core_paths.workspace_dir("o/r", "5")
            wd.mkdir(parents=True, exist_ok=True)
            core_paths.evidence_ledger_file("o/r", "5").write_text(
                FIXTURE.read_text(encoding="utf-8"), encoding="utf-8"
            )

    def test_cli_cr_summary_json(self):
        with tempfile.TemporaryDirectory() as state:
            self._seed(state)
            with patch("gh_address_cr.core.paths.state_dir", return_value=Path(state)):
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    rc = handle_telemetry_command("cr-summary", "o/r", ["5"])
            self.assertEqual(rc, 0)
            payload = json.loads(buf.getvalue())
            self.assertEqual(payload["reason_code"], "CR_SUMMARY_READY")
            self.assertEqual(payload["cr_count_completed"], 2)

    def test_cli_cr_summary_markdown(self):
        with tempfile.TemporaryDirectory() as state:
            self._seed(state)
            with patch("gh_address_cr.core.paths.state_dir", return_value=Path(state)):
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    rc = handle_telemetry_command("cr-summary", "o/r", ["5", "--format", "markdown"])
            self.assertEqual(rc, 0)
            self.assertIn("CR Processing Summary", buf.getvalue())
