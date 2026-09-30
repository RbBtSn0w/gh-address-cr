import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gh_address_cr.core.cr_metrics import _median, _percentile, _read_ledger, build_cr_summary, project_cr_lifecycle


class CRMetricsTest(unittest.TestCase):
    def test_ledger_reader_retains_only_latest_session_rows(self):
        rows = [
            {
                "record_id": "old",
                "timestamp": "2026-01-01T00:00:00Z",
                "session_id": "session-old",
                "item_id": "old-item",
                "event_type": "finding_observed",
            },
            {
                "record_id": "new",
                "timestamp": "2026-01-02T00:00:00Z",
                "session_id": "session-new",
                "item_id": "new-item",
                "event_type": "finding_observed",
            },
        ]
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "evidence.jsonl"
            ledger.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

            events, unreadable, diagnostics = _read_ledger(ledger)

        self.assertFalse(unreadable)
        self.assertEqual([event["session_id"] for event in events], ["session-new"])
        self.assertIn("multiple sessions in ledger: 2; using latest", diagnostics)

    def test_linear_order_statistics_match_contract_for_odd_even_and_duplicate_values(self):
        cases = [
            [9],
            [9, 1],
            [9, 1, 5],
            [9, 1, 5, 3],
            [9, 1, 5, 3, 7, 7, 7, 2, 11, 0],
        ]
        for values in cases:
            with self.subTest(values=values):
                ordered = sorted(values)
                midpoint = len(values) // 2
                expected_median = (
                    ordered[midpoint]
                    if len(values) % 2
                    else int((ordered[midpoint - 1] + ordered[midpoint]) / 2)
                )
                expected_p90 = ordered[max(1, math.ceil(0.9 * len(values))) - 1]
                self.assertEqual(_median(values), expected_median)
                self.assertEqual(_percentile(values, 0.9), expected_p90)

    def test_lifecycle_projector_derives_exact_github_first_pass_and_merge_ready(self):
        events = [
            {
                "record_id": "observed-a",
                "timestamp": "2026-01-01T00:00:00Z",
                "session_id": "session-1",
                "item_id": "item-a",
                "role": "intake",
                "event_type": "finding_observed",
                "payload": {"item_kind": "github_thread"},
            },
            {
                "record_id": "accepted-a",
                "timestamp": "2026-01-01T00:00:05Z",
                "session_id": "session-1",
                "item_id": "item-a",
                "role": "fixer",
                "event_type": "response_accepted",
                "payload": {"resolution": "fix"},
            },
            {
                "record_id": "published-a",
                "timestamp": "2026-01-01T00:00:09Z",
                "session_id": "session-1",
                "item_id": "item-a",
                "role": "publisher",
                "event_type": "response_published",
                "payload": {},
            },
        ]

        report = project_cr_lifecycle(
            list(reversed(events)),
            repo="octo/example",
            pr_number="77",
            gate_completed_at="2026-01-01T00:00:12Z",
        )

        self.assertEqual(report["schema_version"], "cr-lifecycle.v1")
        self.assertEqual(report["completeness"], "complete")
        item = report["items"][0]
        self.assertEqual(item["observation_provenance"], "finding_observed")
        self.assertEqual(item["durations_ms"]["observed_to_addressed"], 5000)
        self.assertEqual(item["durations_ms"]["addressed_to_verified"], 4000)
        self.assertEqual(item["durations_ms"]["observed_to_verified"], 9000)
        self.assertTrue(item["first_pass_verified"])
        self.assertEqual(report["aggregates"]["observed_to_verified_ms"]["median"], 9000)
        self.assertEqual(report["aggregates"]["observed_to_verified_ms"]["sample_count"], 1)
        self.assertEqual(report["aggregates"]["observed_to_verified_ms"]["excluded"], 0)
        self.assertEqual(report["aggregates"]["verified_items"], 1)
        self.assertEqual(
            report["aggregates"]["slowest_stage"],
            {"item_id": "item-a", "stage": "observed_to_addressed", "duration_ms": 5000},
        )
        self.assertEqual(
            report["aggregates"]["first_pass_verified_rate"],
            {"numerator": 1, "denominator": 1, "rate": 1.0, "excluded": 0},
        )
        self.assertEqual(report["pr_durations_ms"]["first_observed_to_merge_ready"], 12000)
        self.assertEqual(report["pr_durations_ms"]["last_verified_to_merge_ready"], 3000)

    def test_lifecycle_projector_uses_post_rejection_local_acceptance_as_verification(self):
        events = [
            {
                "record_id": "observed-local",
                "timestamp": "2026-01-01T00:00:00Z",
                "session_id": "session-1",
                "item_id": "local-a",
                "role": "intake",
                "event_type": "finding_observed",
                "payload": {"item_kind": "local_finding"},
            },
            {
                "record_id": "accepted-1",
                "timestamp": "2026-01-01T00:00:05Z",
                "session_id": "session-1",
                "item_id": "local-a",
                "role": "fixer",
                "event_type": "response_accepted",
                "payload": {"resolution": "fix"},
            },
            {
                "record_id": "rejected-1",
                "timestamp": "2026-01-01T00:00:07Z",
                "session_id": "session-1",
                "item_id": "local-a",
                "role": "verifier",
                "event_type": "verification_rejected",
                "payload": {},
            },
            {
                "record_id": "accepted-2",
                "timestamp": "2026-01-01T00:00:10Z",
                "session_id": "session-1",
                "item_id": "local-a",
                "role": "fixer",
                "event_type": "response_accepted",
                "payload": {"resolution": "fix"},
            },
            {
                "record_id": "verified-1",
                "timestamp": "2026-01-01T00:00:12Z",
                "session_id": "session-1",
                "item_id": "local-a",
                "role": "verifier",
                "event_type": "response_accepted",
                "payload": {"resolution": "accept"},
            },
        ]

        report = project_cr_lifecycle(events, repo="octo/example", pr_number="77")

        item = report["items"][0]
        self.assertEqual(item["durations_ms"]["addressed_to_verified"], 7000)
        self.assertEqual(item["counts"]["address_attempts"], 2)
        self.assertEqual(item["counts"]["verification_rejections"], 1)
        self.assertFalse(item["first_pass_verified"])
        self.assertEqual(
            report["aggregates"]["first_pass_verified_rate"],
            {"numerator": 0, "denominator": 1, "rate": 0.0, "excluded": 0},
        )

    def test_lifecycle_projector_deduplicates_records_and_diagnoses_bad_timestamps(self):
        observed = {
            "record_id": "observed-a",
            "timestamp": "2026-01-01T00:00:00Z",
            "session_id": "session-1",
            "item_id": "item-a",
            "role": "intake",
            "event_type": "finding_observed",
            "payload": {"item_kind": "local_finding"},
        }
        accepted = {
            "record_id": "accepted-a",
            "timestamp": "2026-01-01T00:00:05Z",
            "session_id": "session-1",
            "item_id": "item-a",
            "role": "fixer",
            "event_type": "response_accepted",
            "payload": {"resolution": "fix"},
        }
        malformed = {
            "record_id": "bad-time",
            "timestamp": "not-a-time",
            "session_id": "session-1",
            "item_id": "item-a",
            "event_type": "response_rejected",
        }

        report = project_cr_lifecycle(
            [observed, accepted, dict(accepted), malformed],
            repo="octo/example",
            pr_number="77",
        )

        self.assertEqual(report["items"][0]["counts"]["address_attempts"], 1)
        self.assertEqual(report["diagnostics"], ["skipped 1 event(s) with missing or unparseable timestamp"])

    def test_lifecycle_projector_diagnoses_conflicting_duplicate_record(self):
        first = {
            "record_id": "same-id",
            "timestamp": "2026-01-01T00:00:00Z",
            "session_id": "session-1",
            "item_id": "item-a",
            "event_type": "finding_observed",
            "payload": {"item_kind": "local_finding"},
        }
        conflict = {**first, "item_id": "item-b"}

        report = project_cr_lifecycle([first, conflict], repo="octo/example", pr_number="77")

        self.assertIn("conflicting duplicate evidence record(s): 1", report["diagnostics"])

    def test_lifecycle_projector_excludes_conflicting_observed_item_kinds(self):
        events = [
            {
                "record_id": "observed-thread",
                "timestamp": "2026-01-01T00:00:00Z",
                "session_id": "session-1",
                "item_id": "item-a",
                "event_type": "finding_observed",
                "payload": {"item_kind": "github_thread"},
            },
            {
                "record_id": "observed-local",
                "timestamp": "2026-01-01T00:00:01Z",
                "session_id": "session-1",
                "item_id": "item-a",
                "event_type": "finding_observed",
                "payload": {"item_kind": "local_finding"},
            },
        ]

        report = project_cr_lifecycle(events, repo="octo/example", pr_number="77")

        item = report["items"][0]
        self.assertIsNone(item["item_kind"])
        self.assertIn("item_kind_ambiguous", item["exclusion_reasons"])
        self.assertNotIn("item_kind_unknown", item["exclusion_reasons"])

    def test_lifecycle_projector_excludes_historical_inferred_observation(self):
        events = [
            {
                "record_id": "accepted-a",
                "timestamp": "2026-01-01T00:00:05Z",
                "session_id": "session-1",
                "item_id": "item-a",
                "role": "fixer",
                "event_type": "response_accepted",
                "payload": {"resolution": "fix"},
            },
            {
                "record_id": "published-a",
                "timestamp": "2026-01-01T00:00:09Z",
                "session_id": "session-1",
                "item_id": "item-a",
                "role": "publisher",
                "event_type": "response_published",
                "payload": {},
            },
        ]

        report = project_cr_lifecycle(events, repo="octo/example", pr_number="77")

        item = report["items"][0]
        self.assertEqual(item["observation_provenance"], "first_evidence")
        self.assertIn("observation_inferred", item["exclusion_reasons"])
        self.assertEqual(report["aggregates"]["eligible_items"], 0)
        self.assertEqual(report["aggregates"]["observed_to_verified_ms"]["median"], None)

    def test_lifecycle_projector_counts_rejection_blocking_and_incomplete_items_in_latest_session(self):
        def event(
            record_id: str,
            timestamp: str,
            item_id: str,
            event_type: str,
            *,
            role: str,
            payload: dict[str, str] | None = None,
            session_id: str = "session-new",
        ) -> dict[str, object]:
            return {
                "record_id": record_id,
                "timestamp": timestamp,
                "session_id": session_id,
                "item_id": item_id,
                "role": role,
                "event_type": event_type,
                "payload": payload or {},
            }

        events = [
            event(
                "old-observed",
                "2025-12-31T23:00:00Z",
                "old-item",
                "finding_observed",
                role="intake",
                payload={"item_kind": "github_thread"},
                session_id="session-old",
            ),
            event("a-observed", "2026-01-01T00:00:00Z", "item-a", "finding_observed", role="intake", payload={"item_kind": "github_thread"}),
            event("b-observed", "2026-01-01T00:00:01Z", "item-b", "finding_observed", role="intake", payload={"item_kind": "github_thread"}),
            event("a-rejected", "2026-01-01T00:00:02Z", "item-a", "response_rejected", role="runtime"),
            event("a-accepted", "2026-01-01T00:00:03Z", "item-a", "response_accepted", role="fixer"),
            event("a-blocked", "2026-01-01T00:00:04Z", "item-a", "publish_blocked", role="publisher"),
            event("a-published", "2026-01-01T00:00:05Z", "item-a", "response_published", role="publisher"),
        ]

        report = project_cr_lifecycle(events, repo="octo/example", pr_number="77")

        self.assertEqual(report["session_id"], "session-new")
        self.assertEqual([item["item_id"] for item in report["items"]], ["item-a", "item-b"])
        item_a, item_b = report["items"]
        self.assertEqual(item_a["counts"]["response_rejections"], 1)
        self.assertEqual(item_a["counts"]["publish_blocked"], 1)
        self.assertFalse(item_a["first_pass_verified"])
        self.assertFalse(item_b["eligible"])
        self.assertIn("addressed_at_missing", item_b["exclusion_reasons"])
        self.assertIn("verified_at_missing", item_b["exclusion_reasons"])
        self.assertEqual(report["aggregates"]["eligible_items"], 1)
        self.assertEqual(report["aggregates"]["excluded_items"], 1)
        self.assertEqual(report["completeness"], "partial")
        self.assertEqual(
            report["aggregates"]["friction"]["publish_blocked"],
            {"count": 1, "denominator": 1, "per_verified_item": 1.0, "excluded": 1},
        )

    def test_lifecycle_projector_does_not_treat_verifier_acceptance_as_addressing(self):
        events = [
            {
                "record_id": "observed-local",
                "timestamp": "2026-01-01T00:00:00Z",
                "session_id": "session-1",
                "item_id": "local-a",
                "role": "intake",
                "event_type": "finding_observed",
                "payload": {"item_kind": "local_finding"},
            },
            {
                "record_id": "verified-local",
                "timestamp": "2026-01-01T00:00:05Z",
                "session_id": "session-1",
                "item_id": "local-a",
                "role": "verifier",
                "event_type": "response_accepted",
                "payload": {"resolution": "accept"},
            },
        ]

        report = project_cr_lifecycle(events, repo="octo/example", pr_number="77")

        item = report["items"][0]
        self.assertIsNone(item["timestamps"]["addressed_at"])
        self.assertIn("addressed_at_missing", item["exclusion_reasons"])
        self.assertFalse(item["first_pass_verified"])

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
            self.assertEqual(report["schema_version"], "cr-lifecycle.v1")
            self.assertEqual(report["aggregates"]["eligible_items"], 0)
            self.assertTrue((root / "cr-metrics.json").is_file())

    def test_projection_emits_bounded_private_health_event(self):
        events = [
            {
                "record_id": "observed-a",
                "timestamp": "2026-01-01T00:00:00Z",
                "session_id": "secret-session",
                "item_id": "secret-item",
                "role": "intake",
                "event_type": "finding_observed",
                "payload": {"item_kind": "local_finding", "path": "/Users/private/file.py"},
            },
            {
                "record_id": "accepted-a",
                "timestamp": "2026-01-01T00:00:05Z",
                "session_id": "secret-session",
                "item_id": "secret-item",
                "role": "fixer",
                "event_type": "response_accepted",
                "payload": {"resolution": "fix"},
            },
            {
                "record_id": "verified-a",
                "timestamp": "2026-01-01T00:00:06Z",
                "session_id": "secret-session",
                "item_id": "secret-item",
                "role": "verifier",
                "event_type": "response_accepted",
                "payload": {"resolution": "accept"},
            },
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = root / "evidence.jsonl"
            ledger.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")
            with (
                patch("gh_address_cr.core.cr_metrics.core_paths.evidence_ledger_file", return_value=ledger),
                patch("gh_address_cr.core.cr_metrics.core_paths.workspace_dir", return_value=root),
                patch("gh_address_cr.otel_tracing.add_current_span_event") as emit,
            ):
                build_cr_summary("secret/repo", "77")

        event_name, attributes = emit.call_args.args
        self.assertEqual(event_name, "cr_metrics.projection")
        self.assertEqual(attributes["gh_address_cr.cr_metrics.outcome"], "ready")
        self.assertEqual(attributes["gh_address_cr.cr_metrics.completeness"], "complete")
        self.assertEqual(attributes["gh_address_cr.cr_metrics.eligible_bucket"], "one")
        self.assertGreaterEqual(attributes["gh_address_cr.cr_metrics.duration_ms"], 0.0)
        serialized = json.dumps(attributes, sort_keys=True)
        for forbidden in ("secret/repo", "secret-session", "secret-item", "/Users/private", "2026-01-01"):
            self.assertNotIn(forbidden, serialized)
