from __future__ import annotations

import math
import statistics
from typing import Any, Mapping, Sequence

from gh_address_cr.core.evaluation.models import stable_fingerprint


def _distribution(values: Sequence[float]) -> dict[str, float | int]:
    ordered = sorted(float(value) for value in values)
    index = max(0, math.ceil(0.9 * len(ordered)) - 1)
    return {"sample_size": len(ordered), "median": statistics.median(ordered), "p90": ordered[index]}


def _complete(run: Mapping[str, Any]) -> bool:
    coverage = run.get("coverage") or {}
    return all((coverage.get(key) or {}).get("status") == "complete" for key in ("workflow", "timing", "token", "outcome"))


def _wilson_bounds(rate: float, sample_size: int) -> dict[str, float]:
    if sample_size <= 0:
        return {"lower": 0.0, "upper": 1.0}
    z = 1.96
    denominator = 1 + z * z / sample_size
    center = (rate + z * z / (2 * sample_size)) / denominator
    margin = z * math.sqrt((rate * (1 - rate) + z * z / (4 * sample_size)) / sample_size) / denominator
    return {"lower": round(max(0.0, center - margin), 6), "upper": round(min(1.0, center + margin), 6)}


def compare_runs(
    baseline: Sequence[Mapping[str, Any]],
    candidate: Sequence[Mapping[str, Any]],
    *,
    minimum_runs_per_cohort: int = 10,
    overhead_budget_ms: float = 250.0,
) -> dict[str, Any]:
    baseline_versions = sorted({str(run.get("runtime_version")) for run in baseline})
    candidate_versions = sorted({str(run.get("runtime_version")) for run in candidate})
    baseline_cohorts = {str(run.get("cohort_key")) for run in baseline}
    candidate_cohorts = {str(run.get("cohort_key")) for run in candidate}
    matched_cohorts = baseline_cohorts & candidate_cohorts
    baseline = [run for run in baseline if str(run.get("cohort_key")) in matched_cohorts]
    candidate = [run for run in candidate if str(run.get("cohort_key")) in matched_cohorts]
    deficits: list[str] = []
    if len(baseline) < minimum_runs_per_cohort or len(candidate) < minimum_runs_per_cohort:
        deficits.append("SAMPLE_SIZE_INSUFFICIENT")
    if any(not _complete(run) for run in [*baseline, *candidate]):
        deficits.append("REQUIRED_COVERAGE_MISSING")
    if not matched_cohorts:
        deficits.append("COHORT_DIMENSION_MISSING")
    semantic: dict[str, Any] = {
        "schema_version": "comparison.v1",
        "baseline_runtime_version": baseline_versions[0] if len(baseline_versions) == 1 else None,
        "candidate_runtime_version": candidate_versions[0] if len(candidate_versions) == 1 else None,
        "sample_size": {"baseline": len(baseline), "candidate": len(candidate)},
        "matched_cohort_keys": sorted(matched_cohorts),
        "cohort_boundaries": {
            "workflow": "normal-github-review-thread",
            "supported_hosts": sorted(
                {
                    str(source)
                    for run in [*baseline, *candidate]
                    for source in ((run.get("manifest") or {}).get("producer_attribution") or ["declared-by-record"])
                }
            ),
            "evidence_inputs": ["run-manifest.v1", "archived-runtime-evidence", "evaluation-observation.v1"],
            "required_coverage": ["workflow", "timing", "token", "outcome"],
            "complexity_dimensions": ["review_item_count", "changed_file_count", "diff_line_count", "classification_mix", "language_toolchain", "required_check_duration_ms"],
            "minimum_runs_per_cohort": minimum_runs_per_cohort,
        },
        "evidence_deficits": sorted(set(deficits)),
        "quality": {},
        "economics": {},
        "operational_health": {},
        "guardrail_failures": [],
    }
    if deficits:
        semantic.update(status="INSUFFICIENT_EVIDENCE", reason_code=sorted(set(deficits))[0])
    else:
        for metric in (
            "total_tokens",
            "active_wall_time_ms",
            "summed_resource_time_ms",
            "invocation_count",
            "github_api_round_trip_count",
            "tool_call_count",
            "retry_count",
            "actionable_rejection_count",
        ):
            if not all(isinstance(run.get("cost", {}).get(metric), (int, float)) for run in [*baseline, *candidate]):
                continue
            semantic["economics"][metric] = {
                "baseline": _distribution([float(run["cost"][metric]) for run in baseline]),
                "candidate": _distribution([float(run["cost"][metric]) for run in candidate]),
            }
        quality_metrics = (
            "provisional_rate",
            "durable_rate",
            "reopen_rate",
            "manual_recovery_rate",
            "final_gate_regression_rate",
        )
        for metric in quality_metrics:
            baseline_rate = statistics.mean(float(run["quality"].get(metric, 0.0)) for run in baseline)
            candidate_rate = statistics.mean(float(run["quality"].get(metric, 0.0)) for run in candidate)
            semantic["quality"][metric] = {
                "baseline": baseline_rate,
                "candidate": candidate_rate,
                "confidence_bounds": {
                    "baseline": _wilson_bounds(baseline_rate, len(baseline)),
                    "candidate": _wilson_bounds(candidate_rate, len(candidate)),
                },
            }
        baseline_durable = semantic["quality"]["durable_rate"]["baseline"]
        candidate_durable = semantic["quality"]["durable_rate"]["candidate"]
        if candidate_durable < baseline_durable:
            semantic["guardrail_failures"].append("DURABLE_RATE_REGRESSED")
        for metric, code in (
            ("reopen_rate", "REOPEN_RATE_REGRESSED"),
            ("manual_recovery_rate", "MANUAL_RECOVERY_RATE_REGRESSED"),
            ("final_gate_regression_rate", "FINAL_GATE_STABILITY_REGRESSED"),
        ):
            if semantic["quality"][metric]["candidate"] > semantic["quality"][metric]["baseline"]:
                semantic["guardrail_failures"].append(code)
        semantic["operational_health"]["latency_ms"] = {
            "baseline": _distribution([float(run["cost"]["active_wall_time_ms"]) for run in baseline]),
            "candidate": _distribution([float(run["cost"]["active_wall_time_ms"]) for run in candidate]),
        }
        overhead = [float(run["cost"].get("measurement_overhead_ms") or 0) for run in candidate]
        overhead_distribution = _distribution(overhead)
        semantic["operational_health"]["overhead_budget"] = {
            "budget_ms": overhead_budget_ms,
            "candidate": overhead_distribution,
            "status": "degraded" if overhead_distribution["p90"] > overhead_budget_ms else "healthy",
        }
        semantic.update(
            status="REGRESSED" if semantic["guardrail_failures"] else "SUPPORTED",
            reason_code="QUALITY_GUARDRAIL_REGRESSED" if semantic["guardrail_failures"] else "COMPARISON_SUPPORTED",
        )
    semantic["report_fingerprint"] = stable_fingerprint(semantic, prefix="comparison_")
    return semantic
