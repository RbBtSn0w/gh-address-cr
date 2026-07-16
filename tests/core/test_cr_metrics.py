import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gh_address_cr.core.cr_metrics import build_cr_summary


class CRMetricsTest(unittest.TestCase):
    def test_summary_groups_interleaved_events_by_item_without_changing_completion_results(self):
        events = [
            {
                "timestamp": "2026-01-01T00:00:00Z",
                "session_id": "session-1",
                "item_id": "item-a",
                "event_type": "classification_recorded",
                "payload": {"classification": "fix"},
            },
            {
                "timestamp": "2026-01-01T00:00:01Z",
                "session_id": "session-1",
                "item_id": "item-b",
                "event_type": "classification_recorded",
                "payload": {"classification": "clarify"},
            },
            {
                "timestamp": "2026-01-01T00:00:04Z",
                "session_id": "session-1",
                "item_id": "item-a",
                "event_type": "thread_resolved",
            },
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = root / "evidence-ledger.jsonl"
            ledger.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")
            with (
                patch("gh_address_cr.core.cr_metrics.core_paths.evidence_ledger_file", return_value=ledger),
                patch("gh_address_cr.core.cr_metrics.core_paths.workspace_dir", return_value=root),
            ):
                report = build_cr_summary("octo/example", "77")

            self.assertEqual(report["cr_count_total"], 2)
            self.assertEqual(report["cr_count_completed"], 1)
            self.assertEqual(report["cr_count_incomplete"], 1)
            self.assertEqual(report["classification_mix"], {"fix": 1, "clarify": 1})
            self.assertEqual(report["per_cr"][0], {"item_id": "item-a", "span_ms": 4000, "completed": True, "classification": "fix"})
            self.assertEqual(report["incomplete_crs"], [{"item_id": "item-b", "last_event_type": "classification_recorded"}])

