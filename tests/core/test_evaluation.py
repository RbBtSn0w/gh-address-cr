from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path


class EvaluationTestIntent:
    risk = "Derived evaluation truth can overstate durable outcomes, double-count work, or produce non-replayable comparisons."
    why_automation = "Projection, deduplication, timing, and cohort policy are deterministic state and persistence contracts."
    why_existing_tests_insufficient = "The repository has telemetry tests but no read-only evaluation-plane contract."
    chosen_layer = "Unit and SQLite integration tests are the smallest reliable layers."
    fragility_analysis = "Tests assert public records and reason codes, not helper calls or generation timestamps."
    if_omitted = "Reports could claim improvement from incomplete or duplicated evidence."


class EvaluationModelTests(unittest.TestCase):
    def test_manifest_validates_identity_and_relative_artifacts(self):
        from gh_address_cr.core.evaluation.models import RunManifestV1

        manifest = RunManifestV1.from_dict(
            {
                "schema_version": "run-manifest.v1",
                "run_id": "run-1",
                "session_id": "owner/repo#12",
                "repo": "owner/repo",
                "pr_number": "12",
                "runtime_version": "3.2.0",
                "final_gate_status": "PASSED",
                "final_gate_counts": {},
                "workflow_variant": "review",
                "telemetry_sources": ["runtime"],
                "complexity": {"review_item_count": 3, "changed_file_count": 2, "diff_line_count": 40, "classification_mix": {"fix": 3}},
                "artifacts": [{"path": "session.json"}],
            }
        )

        self.assertEqual(manifest.complexity.bucket_key, "items:2-5|files:1-3|diff:1-100|mix:fix-only")
        with self.assertRaisesRegex(ValueError, "relative"):
            RunManifestV1.from_dict({**manifest.to_dict(), "artifacts": [{"path": "/tmp/session.json"}]})

    def test_observation_fingerprint_is_stable_and_private_identity_is_not_stored(self):
        from gh_address_cr.core.evaluation.models import EvaluationObservationV1

        payload = {
            "schema_version": "evaluation-observation.v1",
            "repo": "owner/repo",
            "pr_number": "12",
            "run_id": "run-1",
            "observed_at": "2026-06-30T02:00:00Z",
            "observed_head_sha": "abc",
            "review_round_id": "review-2",
            "review_state": "APPROVED",
            "reviewer_relation": "original_concern_author",
            "item_id": "item-1",
            "outcome_kind": "no_reopen",
            "correlation_method": "thread_id",
            "source": "github",
        }
        first = EvaluationObservationV1.from_dict(payload)
        second = EvaluationObservationV1.from_dict(payload)

        self.assertEqual(first.observation_id, second.observation_id)
        self.assertNotIn("username", first.to_dict())


class EvaluationProjectionTests(unittest.TestCase):
    def test_hybrid_projection_distinguishes_provisional_unknown_durable_and_negative(self):
        from gh_address_cr.core.evaluation.projector import project_concern

        item = {
            "item_id": "item-1",
            "classification": "fix",
            "classification_verified": True,
            "reply_evidence": {"record_id": "reply-1"},
            "resolve_evidence": {"record_id": "resolve-1"},
            "publish_evidence": {"record_id": "publish-1"},
            "final_gate_passed": True,
        }
        provisional = project_concern("run-1", item, [])
        reopened = project_concern(
            "run-1",
            item,
            [{"item_id": "item-1", "outcome_kind": "reopened", "observation_id": "obs-1"}],
        )

        self.assertEqual(provisional["provisional_state"], "verified")
        self.assertEqual(provisional["durable_state"], "unknown")
        self.assertEqual(reopened["durable_state"], "negative")
        self.assertEqual(reopened["durable_reason"], "DURABLE_REOPENED")
        self.assertTrue(provisional["first_pass"])

    def test_durable_projection_preserves_observation_attribution(self):
        from gh_address_cr.core.evaluation.projector import project_concern

        item = {
            "item_id": "item-1", "classification": "fix", "classification_verified": True,
            "reply_evidence": {"record_id": "reply"}, "resolve_evidence": {"record_id": "resolve"},
            "publish_evidence": {"record_id": "publish"}, "final_gate_passed": True,
        }
        record = project_concern(
            "run-1",
            item,
            [{"item_id": "item-1", "outcome_kind": "no_reopen", "observation_id": "obs-1", "source": "github", "observed_at": "2099-01-01T00:00:00Z", "correlation_method": "thread_id"}],
        )

        github_evidence = next(row for row in record["evidence"] if row["source"] == "github")
        self.assertEqual(github_evidence["correlation_method"], "thread_id")

    def test_identical_projection_has_identical_fingerprint(self):
        from gh_address_cr.core.evaluation.projector import project_concern

        item = {"item_id": "item-1", "classification": "fix", "final_gate_passed": False}
        self.assertEqual(
            project_concern("run-1", item, [])["evaluation_id"],
            project_concern("run-1", item, [])["evaluation_id"],
        )


class EvaluationEconomicsTests(unittest.TestCase):
    def test_coverage_distinguishes_partial_and_invalid_evidence(self):
        from gh_address_cr.core.evaluation.coverage import evaluate_coverage

        coverage = evaluate_coverage(
            {
                "workflow": [{"source": "runtime"}],
                "timing": [{"source": "runtime"}, {"source": "host", "supported": False}],
                "token": [{"source": "host", "valid": False}],
                "outcome": [{"source": "runtime"}],
            }
        )

        self.assertEqual(coverage["timing"]["status"], "partial")
        self.assertEqual(coverage["token"]["status"], "invalid")

    def test_interval_union_separates_active_and_resource_time(self):
        from gh_address_cr.core.evaluation.timing import compute_workflow_cost

        cost = compute_workflow_cost(
            [
                {"started_at_ms": 0, "ended_at_ms": 100, "duration_ms": 100},
                {"started_at_ms": 50, "ended_at_ms": 150, "duration_ms": 100},
                {"started_at_ms": 200, "ended_at_ms": 250, "duration_ms": 50},
                {"duration_ms": 25},
            ]
        )

        self.assertEqual(cost["active_wall_time_ms"], 200)
        self.assertEqual(cost["summed_resource_time_ms"], 275)

    def test_rejection_taxonomy_defaults_unknown_to_actionable(self):
        from gh_address_cr.core.evaluation.coverage import classify_rejection

        self.assertEqual(classify_rejection("WAITING_FOR_EXTERNAL_REVIEW"), "expected")
        self.assertEqual(classify_rejection("MALFORMED_ACTION_RESPONSE"), "actionable")
        self.assertEqual(classify_rejection("FUTURE_CODE"), "actionable")

    def test_coverage_deficits_are_dimensional(self):
        from gh_address_cr.core.evaluation.coverage import evaluate_coverage

        coverage = evaluate_coverage({"workflow": [1], "timing": [], "token": [], "outcome": [1]})

        self.assertEqual(coverage["workflow"]["status"], "complete")
        self.assertIn("TIMING_INTERVALS_MISSING", coverage["timing"]["deficits"])
        self.assertIn("TOKEN_EVIDENCE_MISSING", coverage["token"]["deficits"])


class EvaluationCatalogAndComparisonTests(unittest.TestCase):
    def _run(self, version: str, index: int, *, durable: bool = True, overhead: float = 10.0) -> dict:
        return {
            "run_id": f"{version}-{index}",
            "repo": "owner/repo",
            "pr_number": str(index),
            "runtime_version": version,
            "cohort_key": "items:1|files:1-3|diff:1-100|mix:fix-only",
            "projection_fingerprint": f"fp-{version}-{index}",
            "coverage": {key: {"status": "complete", "deficits": []} for key in ("workflow", "timing", "token", "outcome")},
            "quality": {"provisional_rate": 1.0, "durable_rate": 1.0 if durable else 0.5, "reopen_rate": 0.0 if durable else 0.5},
            "cost": {"total_tokens": 100 + index, "active_wall_time_ms": 1000 + index, "measurement_overhead_ms": overhead},
        }

    def test_catalog_rebuild_is_idempotent_and_preserves_prior_on_failure(self):
        from gh_address_cr.core.evaluation.catalog import EvaluationCatalog

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "evaluation.sqlite3"
            catalog = EvaluationCatalog(path)
            records = [self._run("1.0", 1), self._run("1.0", 1)]
            first = catalog.rebuild(records)
            second = catalog.rebuild(records)

            self.assertEqual(first["source_fingerprint"], second["source_fingerprint"])
            self.assertEqual(catalog.query_runs("1.0"), [records[0]])
            with self.assertRaises(ValueError):
                catalog.rebuild([{"run_id": "broken"}])
            self.assertEqual(catalog.query_runs("1.0"), [records[0]])

    def test_catalog_contains_all_rebuildable_entity_tables(self):
        from gh_address_cr.core.evaluation.catalog import EvaluationCatalog

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "evaluation.sqlite3"
            EvaluationCatalog(path).rebuild([self._run("1.0", 1)])
            connection = sqlite3.connect(path)
            try:
                names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            finally:
                connection.close()

        self.assertTrue({"runs", "concerns", "coverage", "costs", "observations", "evidence_pointers"} <= names)

    def test_catalog_derives_pr_and_runtime_version_records(self):
        from gh_address_cr.core.evaluation.catalog import EvaluationCatalog

        with tempfile.TemporaryDirectory() as tmp:
            catalog = EvaluationCatalog(Path(tmp) / "evaluation.sqlite3")
            catalog.rebuild([self._run("1.0", 1), self._run("1.0", 2)])

            pr_record = catalog.summarize_pr("owner/repo", "1")
            runtime_record = catalog.summarize_runtime_version("1.0")

        self.assertEqual(pr_record["run_count"], 1)
        self.assertEqual(runtime_record["run_count"], 2)

    def test_comparison_requires_samples_and_reports_distributions(self):
        from gh_address_cr.core.evaluation.comparison import compare_runs

        insufficient = compare_runs([self._run("1.0", 1)], [self._run("2.0", 1)])
        supported = compare_runs(
            [self._run("1.0", index) for index in range(10)],
            [self._run("2.0", index) for index in range(10)],
        )

        self.assertEqual(insufficient["status"], "INSUFFICIENT_EVIDENCE")
        self.assertIn("SAMPLE_SIZE_INSUFFICIENT", insufficient["evidence_deficits"])
        self.assertEqual(supported["status"], "SUPPORTED")
        self.assertIn("median", supported["economics"]["total_tokens"]["baseline"])
        self.assertIn("p90", supported["economics"]["active_wall_time_ms"]["candidate"])
        self.assertEqual(
            set(supported["quality"]),
            {"provisional_rate", "durable_rate", "reopen_rate", "manual_recovery_rate", "final_gate_regression_rate"},
        )
        self.assertIn("latency_ms", supported["operational_health"])

    def test_quality_regression_and_overhead_budget_cannot_be_hidden_by_cost(self):
        from gh_address_cr.core.evaluation.comparison import compare_runs

        result = compare_runs(
            [self._run("1.0", index) for index in range(10)],
            [self._run("2.0", index, durable=False, overhead=300.0) for index in range(10)],
        )

        self.assertEqual(result["status"], "REGRESSED")
        self.assertIn("DURABLE_RATE_REGRESSED", result["guardrail_failures"])
        self.assertEqual(result["operational_health"]["overhead_budget"]["status"], "degraded")

    def test_comparison_fingerprint_is_replay_stable(self):
        from gh_address_cr.core.evaluation.comparison import compare_runs

        baseline = [self._run("1.0", index) for index in range(10)]
        candidate = [self._run("2.0", index) for index in range(10)]
        self.assertEqual(
            compare_runs(baseline, candidate)["report_fingerprint"],
            compare_runs(baseline, candidate)["report_fingerprint"],
        )

    def test_comparison_excludes_unmatched_cohorts_and_reports_quality_bounds(self):
        from gh_address_cr.core.evaluation.comparison import compare_runs

        baseline = [self._run("1.0", index) for index in range(10)]
        unmatched = self._run("1.0", 99)
        unmatched["cohort_key"] = "items:6+|files:11+|diff:501+|mix:mixed"
        candidate = [self._run("2.0", index) for index in range(10)]

        result = compare_runs([*baseline, unmatched], candidate)

        self.assertEqual(result["sample_size"], {"baseline": 10, "candidate": 10})
        self.assertIn("confidence_bounds", result["quality"]["durable_rate"])
        self.assertEqual(result["baseline_runtime_version"], "1.0")
        self.assertEqual(result["candidate_runtime_version"], "2.0")
        self.assertIn("required_coverage", result["cohort_boundaries"])


class EvaluationArchiveTests(unittest.TestCase):
    def test_archive_projection_uses_authoritative_runtime_evidence(self):
        from gh_address_cr.core.evaluation.archive import finalize_run_manifest, project_archive

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            session = {
                "items": {
                    "github-thread:T1": {
                        "item_id": "github-thread:T1", "item_kind": "github_thread",
                        "classification_evidence": {"classification": "fix", "record_id": "class-1"},
                        "reply_evidence": {"record_id": "reply-1"}, "thread_resolved": True,
                    }
                }
            }
            evidence = [
                {"record_id": "resolve-1", "item_id": "github-thread:T1", "event_type": "thread_resolved", "timestamp": "2026-01-01T00:00:01Z"},
                {"record_id": "publish-1", "item_id": "github-thread:T1", "event_type": "response_published", "timestamp": "2026-01-01T00:00:02Z"},
            ]
            (run_dir / "session.json").write_text(json.dumps(session), encoding="utf-8")
            (run_dir / "evidence.jsonl").write_text("\n".join(json.dumps(row) for row in evidence) + "\n", encoding="utf-8")
            finalize_run_manifest(run_dir, repo="owner/repo", pr_number="12", run_id="run-1", final_gate_passed=True, final_gate_counts={})

            record = project_archive(run_dir)

        self.assertEqual(record["concerns"][0]["provisional_state"], "verified")

    def test_evidence_pointer_normalization_deduplicates_without_copying_body(self):
        from gh_address_cr.core.evaluation.archive import normalize_evidence_pointers

        pointers = normalize_evidence_pointers(
            "evidence.jsonl",
            [
                {"record_id": "r1", "event_type": "reply", "observed_at": "2026-01-01T00:00:00Z", "source": "runtime", "body": "private"},
                {"record_id": "r1", "event_type": "reply", "observed_at": "2026-01-01T00:00:00Z", "source": "runtime", "body": "private"},
            ],
        )

        self.assertEqual(len(pointers), 1)
        self.assertNotIn("body", pointers[0])

    def test_observation_must_be_later_and_match_manifest_identity(self):
        from gh_address_cr.core.evaluation.models import EvaluationObservationV1
        from gh_address_cr.core.evaluation.observations import validate_observation

        observation = EvaluationObservationV1.from_dict(
            {
                "repo": "owner/repo", "pr_number": "12", "run_id": "run-1",
                "observed_at": "2026-06-30T02:00:00Z", "observed_head_sha": "abc",
                "review_round_id": "review-2", "review_state": "APPROVED",
                "reviewer_relation": "original_concern_author", "item_id": "item-1",
                "outcome_kind": "no_reopen", "correlation_method": "thread_id",
            }
        )
        manifest = {
            "repo": "owner/repo", "pr_number": "12", "run_id": "run-1",
            "final_gate_observed_at": "2026-06-30T03:00:00Z", "head_sha": "abc",
        }

        with self.assertRaisesRegex(ValueError, "later"):
            validate_observation(observation, manifest)
        with self.assertRaisesRegex(ValueError, "identity"):
            validate_observation(observation, {**manifest, "run_id": "other", "final_gate_observed_at": "2026-06-30T01:00:00Z"})

    def test_observation_ledger_is_append_only_and_deduplicated(self):
        from gh_address_cr.core.evaluation.models import EvaluationObservationV1
        from gh_address_cr.core.evaluation.observations import append_observations

        observation = EvaluationObservationV1.from_dict(
            {
                "repo": "owner/repo", "pr_number": "12", "run_id": "run-1",
                "observed_at": "2026-06-30T02:00:00Z", "observed_head_sha": "abc",
                "review_round_id": "review-2", "review_state": "APPROVED",
                "reviewer_relation": "original_concern_author", "item_id": "item-1",
                "outcome_kind": "no_reopen", "correlation_method": "thread_id",
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "observations.jsonl"
            result = append_observations(path, [observation, observation])

            self.assertEqual(result, {"accepted_count": 1, "duplicate_count": 1})
            self.assertEqual(len(path.read_text(encoding="utf-8").splitlines()), 1)

    def test_manifest_finalization_hashes_final_bytes_and_loader_checks_integrity(self):
        from gh_address_cr.core.evaluation.archive import finalize_run_manifest, load_archive

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "session.json").write_text('{"items": {}}\n', encoding="utf-8")
            manifest = finalize_run_manifest(
                run_dir, repo="owner/repo", pr_number="12", run_id="run-1",
                final_gate_passed=True, final_gate_counts={},
            )

            self.assertEqual(manifest["artifacts"][0]["path"], "session.json")
            self.assertGreaterEqual(manifest["evaluation_capture_overhead_ms"], 0.0)
            self.assertLess(manifest["evaluation_capture_overhead_ms"], 250.0)
            self.assertIn("runtime", manifest["producer_attribution"])
            self.assertNotIn("run-manifest.v1.json", {row["path"] for row in manifest["artifacts"]})
            self.assertEqual(load_archive(run_dir)["manifest"]["run_id"], "run-1")
            (run_dir / "session.json").write_text("tampered", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "integrity"):
                load_archive(run_dir)

    def test_observation_rejects_prompt_and_private_path_fields(self):
        from gh_address_cr.core.evaluation.models import EvaluationObservationV1

        base = {
            "repo": "owner/repo", "pr_number": "12", "run_id": "run-1",
            "observed_at": "2026-06-30T02:00:00Z", "observed_head_sha": "abc",
            "review_round_id": "review-2", "review_state": "APPROVED",
            "reviewer_relation": "unknown", "outcome_kind": "no_reopen", "correlation_method": "thread_id",
        }
        with self.assertRaisesRegex(ValueError, "unsafe"):
            EvaluationObservationV1.from_dict({**base, "raw_prompt": "secret"})
        with self.assertRaisesRegex(ValueError, "unsafe"):
            EvaluationObservationV1.from_dict({**base, "source_url": "/Users/private/review"})


if __name__ == "__main__":
    unittest.main()
