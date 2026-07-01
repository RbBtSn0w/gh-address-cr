from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from gh_address_cr import __version__
from gh_address_cr.core.evaluation.models import EvaluationObservationV1, EvidencePointer, RunManifestV1
from gh_address_cr.core.evaluation.projector import project_concern
from gh_address_cr.core.evaluation.timing import compute_workflow_cost
from gh_address_cr.core.io import write_json_atomic

MANIFEST_NAME = "run-manifest.v1.json"
ARCHIVE_ARTIFACTS = (
    "session.json",
    "evidence.jsonl",
    "audit.jsonl",
    "trace.jsonl",
    "efficiency-report.json",
    "audit_summary.md",
)


def normalize_evidence_pointers(artifact: str, records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for record in records:
        pointer = EvidencePointer.from_dict(
            {
                "artifact": artifact,
                "record_id": record.get("record_id"),
                "event_type": record.get("event_type"),
                "observed_at": record.get("observed_at"),
                "source": record.get("source"),
            }
        ).to_dict()
        unique[pointer["fingerprint"]] = pointer
    return [unique[key] for key in sorted(unique)]


def capture_observation_inputs(client: Any, repo: str, pr_number: str, run_id: str) -> list[EvaluationObservationV1]:
    return [
        EvaluationObservationV1.from_dict(payload)
        for payload in client.evaluation_observations(repo, pr_number, run_id)
    ]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _complexity(run_dir: Path) -> dict[str, Any]:
    try:
        session = json.loads((run_dir / "session.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        session = {}
    items = session.get("items") if isinstance(session, Mapping) else {}
    rows = list(items.values()) if isinstance(items, Mapping) else list(items) if isinstance(items, Sequence) and not isinstance(items, (str, bytes)) else []
    mix = {key: 0 for key in ("fix", "clarify", "defer", "reject")}
    for row in rows:
        if isinstance(row, Mapping) and row.get("classification") in mix:
            mix[str(row["classification"])] += 1
    return {"review_item_count": len(rows), "changed_file_count": None, "diff_line_count": None, "classification_mix": mix}


def finalize_run_manifest(
    run_dir: Path,
    *,
    repo: str,
    pr_number: str,
    run_id: str,
    final_gate_passed: bool,
    final_gate_counts: Mapping[str, int],
    telemetry_sources: list[str] | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    run_dir = Path(run_dir)
    artifacts = [
        {"path": name, "sha256": _sha256(run_dir / name)}
        for name in ARCHIVE_ARTIFACTS
        if (run_dir / name).is_file()
    ]
    manifest = RunManifestV1.from_dict(
        {
            "schema_version": "run-manifest.v1",
            "run_id": run_id,
            "session_id": f"{repo}#{pr_number}",
            "repo": repo,
            "pr_number": str(pr_number),
            "runtime_version": __version__,
            "runtime_commit": None,
            "skill_version": None,
            "head_sha": None,
            "started_at": None,
            "final_gate_observed_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "final_gate_status": "PASSED" if final_gate_passed else "FAILED",
            "final_gate_counts": dict(final_gate_counts),
            "workflow_variant": "review",
            "telemetry_sources": telemetry_sources or [],
            "producer_attribution": sorted({"runtime", *(telemetry_sources or [])}),
            "complexity": _complexity(run_dir),
            "artifacts": artifacts,
            "diagnostics": [],
        }
    ).to_dict()
    manifest["evaluation_capture_overhead_ms"] = round((time.perf_counter() - started) * 1000, 3)
    write_json_atomic(run_dir / MANIFEST_NAME, manifest)
    return manifest


def load_archive(run_dir: Path) -> dict[str, Any]:
    run_dir = Path(run_dir)
    try:
        raw = json.loads((run_dir / MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"archive manifest invalid: {exc}") from exc
    manifest = RunManifestV1.from_dict(raw).to_dict()
    for artifact in manifest["artifacts"]:
        path = run_dir / artifact["path"]
        if not path.is_file() or (artifact.get("sha256") and _sha256(path) != artifact["sha256"]):
            raise ValueError(f"archive integrity failed: {artifact['path']}")
    return {"manifest": manifest, "run_dir": str(run_dir)}


def _trace_fallback(run_dir: Path) -> tuple[dict[str, Any], int | None, int]:
    try:
        records = [
            json.loads(line)
            for line in (run_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        rows = [row for row in records if isinstance(row, Mapping)]
    except (OSError, UnicodeError, ValueError):
        return {}, None, 0
    cost = compute_workflow_cost(rows)
    token_total = sum(
        int((row.get("metadata") or {}).get("token_total_count") or row.get("token_total_count") or 0)
        for row in rows
        if isinstance(row.get("metadata") or {}, Mapping)
    )
    return cost, token_total or None, len(rows)


def _resolve_cost_metrics(
    run_dir: Path, efficiency: Mapping[str, Any], host_metrics: Mapping[str, Any]
) -> tuple[int | None, int | None, dict[str, Any], int]:
    token_total = host_metrics.get("token_total_count")
    active_time = efficiency.get("total_observed_duration_ms")
    fallback_cost: dict[str, Any] = {}
    fallback_invocations = 0
    if active_time is None or token_total is None:
        fallback_cost, fallback_tokens, fallback_invocations = _trace_fallback(run_dir)
        token_total = fallback_tokens if token_total is None else token_total
        active_time = fallback_cost.get("active_wall_time_ms") if active_time is None else active_time
    return token_total, active_time, fallback_cost, fallback_invocations


def project_archive(run_dir: Path, observations: Sequence[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    loaded = load_archive(run_dir)
    manifest = loaded["manifest"]
    try:
        session = json.loads((Path(run_dir) / "session.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"archive session invalid: {exc}") from exc
    raw_items = session.get("items") or {}
    items = [dict(item) for item in (raw_items.values() if isinstance(raw_items, Mapping) else raw_items) if isinstance(item, Mapping)]
    evidence_by_item: dict[str, list[dict[str, Any]]] = {}
    evidence_path = Path(run_dir) / "evidence.jsonl"
    if evidence_path.exists():
        try:
            records = [json.loads(line) for line in evidence_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        except (OSError, ValueError) as exc:
            raise ValueError(f"archive evidence invalid: {exc}") from exc
        for record in records:
            if isinstance(record, dict) and record.get("item_id"):
                evidence_by_item.setdefault(str(record["item_id"]), []).append(record)
    for item in items:
        item_id = str(item.get("item_id") or "")
        evidence = evidence_by_item.get(item_id, [])
        by_type = {str(record.get("event_type")): record for record in evidence}
        item["classification_verified"] = bool(item.get("classification_evidence") or by_type.get("classification_recorded"))
        item.setdefault("classification_evidence", by_type.get("classification_recorded"))
        if not item.get("reply_evidence") and by_type.get("reply_posted"):
            item["reply_evidence"] = by_type["reply_posted"]
        item["resolve_required"] = item.get("item_kind") == "github_thread"
        item["publish_required"] = item.get("item_kind") == "github_thread"
        if item.get("thread_resolved") or by_type.get("thread_resolved"):
            item["resolve_evidence"] = by_type.get("thread_resolved") or {"source": "runtime"}
        if by_type.get("response_published"):
            item["publish_evidence"] = by_type["response_published"]
        item["final_gate_passed"] = manifest["final_gate_status"] == "PASSED"
    observations_by_item: dict[str, list[Mapping[str, Any]]] = {}
    for observation in observations or []:
        for key in {str(observation.get("item_id") or ""), str(observation.get("related_item_id") or "")} - {""}:
            observations_by_item.setdefault(key, []).append(observation)
    concerns = [
        project_concern(
            manifest["run_id"],
            item,
            observations_by_item.get(str(item.get("item_id") or ""), []),
        )
        for item in items
        if isinstance(item, Mapping)
    ]
    verified = sum(row["provisional_state"] == "verified" for row in concerns)
    durable = sum(row["durable_state"] == "verified" for row in concerns)
    negative = sum(row["durable_state"] == "negative" for row in concerns)
    manual_recovery = sum(row.get("outcome_kind") == "manual_recovery" for row in (observations or []))
    final_gate_regressions = sum(row.get("outcome_kind") == "final_gate_regression" for row in (observations or []))
    count = len(concerns)
    try:
        efficiency = json.loads((Path(run_dir) / "efficiency-report.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        efficiency = {}
    host_metrics = efficiency.get("host_metrics") or {}
    token_total, active_time, fallback_cost, fallback_invocations = _resolve_cost_metrics(
        Path(run_dir), efficiency, host_metrics
    )
    coverage = {
        "workflow": {"status": "complete" if count else "unavailable", "deficits": [] if count else ["WORKFLOW_EVIDENCE_MISSING"]},
        "timing": {"status": "complete" if active_time is not None else "unavailable", "deficits": [] if active_time is not None else ["TIMING_INTERVALS_MISSING"]},
        "token": {"status": "complete" if token_total is not None else "unavailable", "deficits": [] if token_total is not None else ["TOKEN_EVIDENCE_MISSING"]},
        "outcome": {
            "status": "complete" if concerns and observations else ("partial" if concerns else "unavailable"),
            "deficits": [] if concerns and observations else (["DURABLE_OBSERVATION_MISSING"] if concerns else ["OUTCOME_CORRELATION_MISSING"]),
        },
    }
    semantic = {
        "run_id": manifest["run_id"],
        "repo": manifest["repo"],
        "pr_number": manifest["pr_number"],
        "runtime_version": manifest["runtime_version"],
        "cohort_key": manifest["complexity"]["bucket_key"],
        "coverage": coverage,
        "quality": {
            "provisional_rate": verified / count if count else 0.0,
            "durable_rate": durable / count if count else 0.0,
            "reopen_rate": negative / count if count else 0.0,
            "manual_recovery_rate": manual_recovery / count if count else 0.0,
            "final_gate_regression_rate": final_gate_regressions / count if count else 0.0,
        },
        "cost": {
            "total_tokens": token_total,
            "active_wall_time_ms": active_time,
            "summed_resource_time_ms": efficiency.get("total_observed_duration_ms", fallback_cost.get("summed_resource_time_ms")),
            "invocation_count": efficiency.get("total_invocations", efficiency.get("total_events", fallback_invocations or None)),
            "github_api_round_trip_count": host_metrics.get("github_api_round_trip_count"),
            "tool_call_count": host_metrics.get("tool_call_count"),
            "retry_count": host_metrics.get("retry_count"),
            "actionable_rejection_count": host_metrics.get("actionable_rejection_count"),
            "measurement_overhead_ms": manifest.get("evaluation_capture_overhead_ms", 0.0),
        },
        "concerns": concerns,
        "observations": list(observations or []),
        "manifest": manifest,
    }
    from gh_address_cr.core.evaluation.models import stable_fingerprint

    semantic["projection_fingerprint"] = stable_fingerprint(semantic, prefix="run_")
    return semantic
