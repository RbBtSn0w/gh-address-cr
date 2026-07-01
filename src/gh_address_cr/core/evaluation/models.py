from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping


def stable_fingerprint(value: object, *, prefix: str = "") -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"{prefix}{digest}"


def _non_negative(value: object, field_name: str) -> int:
    result = int(str(value or 0))
    if result < 0:
        raise ValueError(f"{field_name} must be non-negative")
    return result


def _bucket(value: int | None, boundaries: tuple[tuple[int, str], ...], unknown: str = "unknown") -> str:
    if value is None:
        return unknown
    for maximum, label in boundaries:
        if value <= maximum:
            return label
    return boundaries[-1][1]


@dataclass(frozen=True)
class ComplexityProfile:
    review_item_count: int
    changed_file_count: int | None = None
    diff_line_count: int | None = None
    classification_mix: dict[str, int] = field(default_factory=dict)
    language_toolchain: tuple[str, ...] = ()
    required_check_duration_ms: int | None = None
    bucket_key: str = ""

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ComplexityProfile":
        review_items = _non_negative(payload.get("review_item_count"), "review_item_count")
        changed_files = payload.get("changed_file_count")
        diff_lines = payload.get("diff_line_count")
        changed_files = None if changed_files is None else _non_negative(changed_files, "changed_file_count")
        diff_lines = None if diff_lines is None else _non_negative(diff_lines, "diff_line_count")
        raw_mix = payload.get("classification_mix") or {}
        if not isinstance(raw_mix, Mapping):
            raise ValueError("classification_mix must be an object")
        mix = {key: _non_negative(raw_mix.get(key), f"classification_mix.{key}") for key in ("fix", "clarify", "defer", "reject")}
        non_zero = [key for key, count in mix.items() if count]
        mix_bucket = "unknown" if not non_zero else ("fix-only" if non_zero == ["fix"] else ("non-fix-only" if "fix" not in non_zero else "mixed"))
        items_bucket = "1" if review_items <= 1 else ("2-5" if review_items <= 5 else "6+")
        files_bucket = _bucket(changed_files, ((3, "1-3"), (10, "4-10"), (2**63, "11+")))
        diff_bucket = _bucket(diff_lines, ((100, "1-100"), (500, "101-500"), (2**63, "501+")))
        bucket_key = f"items:{items_bucket}|files:{files_bucket}|diff:{diff_bucket}|mix:{mix_bucket}"
        toolchains = tuple(sorted(str(item) for item in (payload.get("language_toolchain") or [])))
        duration = payload.get("required_check_duration_ms")
        if toolchains:
            bucket_key += "|toolchain:" + "+".join(toolchains)
        if duration is not None:
            duration_value = _non_negative(duration, "required_check_duration_ms")
            bucket_key += "|checks:" + ("0-60s" if duration_value <= 60_000 else "60s+")
        return cls(
            review_item_count=review_items,
            changed_file_count=changed_files,
            diff_line_count=diff_lines,
            classification_mix=mix,
            language_toolchain=toolchains,
            required_check_duration_ms=None if duration is None else _non_negative(duration, "required_check_duration_ms"),
            bucket_key=bucket_key,
        )

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["language_toolchain"] = list(self.language_toolchain)
        return result


@dataclass(frozen=True)
class RunManifestV1:
    run_id: str
    session_id: str
    repo: str
    pr_number: str
    runtime_version: str
    final_gate_status: str
    final_gate_counts: dict[str, int]
    workflow_variant: str
    telemetry_sources: tuple[str, ...]
    complexity: ComplexityProfile
    artifacts: tuple[dict[str, Any], ...]
    schema_version: str = "run-manifest.v1"
    runtime_commit: str | None = None
    skill_version: str | None = None
    head_sha: str | None = None
    started_at: str | None = None
    final_gate_observed_at: str | None = None
    diagnostics: tuple[str, ...] = ()
    evaluation_capture_overhead_ms: float | None = None
    producer_attribution: tuple[str, ...] = ("runtime",)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RunManifestV1":
        if payload.get("schema_version") != "run-manifest.v1":
            raise ValueError("unsupported run manifest schema")
        required = ("run_id", "session_id", "repo", "pr_number", "runtime_version", "final_gate_status")
        for name in required:
            if not str(payload.get(name) or "").strip():
                raise ValueError(f"{name} is required")
        if "/" not in str(payload["repo"]):
            raise ValueError("repo must be owner/repo")
        artifacts: list[dict[str, Any]] = []
        for raw in payload.get("artifacts") or []:
            row = dict(raw)
            path = Path(str(row.get("path") or ""))
            if not str(path) or path.is_absolute() or ".." in path.parts:
                raise ValueError("artifact paths must be relative and remain inside the run directory")
            if path.name == "run-manifest.v1.json":
                raise ValueError("manifest must not list itself")
            artifacts.append(row)
        return cls(
            run_id=str(payload["run_id"]),
            session_id=str(payload["session_id"]),
            repo=str(payload["repo"]),
            pr_number=str(payload["pr_number"]),
            runtime_version=str(payload["runtime_version"]),
            runtime_commit=payload.get("runtime_commit"),
            skill_version=payload.get("skill_version"),
            head_sha=payload.get("head_sha"),
            started_at=payload.get("started_at"),
            final_gate_observed_at=payload.get("final_gate_observed_at"),
            final_gate_status=str(payload["final_gate_status"]),
            final_gate_counts={str(key): int(value) for key, value in dict(payload.get("final_gate_counts") or {}).items()},
            workflow_variant=str(payload.get("workflow_variant") or "unknown"),
            telemetry_sources=tuple(sorted(str(item) for item in (payload.get("telemetry_sources") or []))),
            complexity=ComplexityProfile.from_dict(payload.get("complexity") or {}),
            artifacts=tuple(artifacts),
            diagnostics=tuple(str(item) for item in (payload.get("diagnostics") or [])),
            evaluation_capture_overhead_ms=(
                None
                if payload.get("evaluation_capture_overhead_ms") is None
                else max(0.0, float(payload["evaluation_capture_overhead_ms"]))
            ),
            producer_attribution=tuple(sorted(str(item) for item in (payload.get("producer_attribution") or ["runtime"]))),
        )

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["telemetry_sources"] = list(self.telemetry_sources)
        result["artifacts"] = [dict(item) for item in self.artifacts]
        result["diagnostics"] = list(self.diagnostics)
        result["producer_attribution"] = list(self.producer_attribution)
        result["complexity"] = self.complexity.to_dict()
        return result


@dataclass(frozen=True)
class EvidencePointer:
    artifact: str
    record_id: str | None
    event_type: str
    observed_at: str | None
    source: str
    fingerprint: str = ""

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "EvidencePointer":
        artifact = Path(str(payload.get("artifact") or ""))
        if not str(artifact) or artifact.is_absolute() or ".." in artifact.parts:
            raise ValueError("evidence artifact must be relative")
        values = {
            "artifact": str(artifact),
            "record_id": payload.get("record_id"),
            "event_type": str(payload.get("event_type") or "unknown"),
            "observed_at": payload.get("observed_at"),
            "source": str(payload.get("source") or "unknown"),
        }
        return cls(
            artifact=str(values["artifact"]),
            record_id=None if values["record_id"] is None else str(values["record_id"]),
            event_type=str(values["event_type"]),
            observed_at=None if values["observed_at"] is None else str(values["observed_at"]),
            source=str(values["source"]),
            fingerprint=stable_fingerprint(values, prefix="evidence_"),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EvaluationObservationV1:
    repo: str
    pr_number: str
    run_id: str
    observed_at: str
    observed_head_sha: str
    review_round_id: str
    review_state: str
    reviewer_relation: str
    outcome_kind: str
    correlation_method: str
    source: str = "github"
    item_id: str | None = None
    observed_thread_id: str | None = None
    related_item_id: str | None = None
    finding_fingerprint: str | None = None
    source_url: str | None = None
    observation_id: str = ""
    schema_version: str = "evaluation-observation.v1"

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "EvaluationObservationV1":
        from gh_address_cr.core.telemetry_safety import _validate_safe_metadata_value

        _validate_safe_metadata_value(dict(payload), key_path="evaluation_observation")
        if payload.get("schema_version", "evaluation-observation.v1") != "evaluation-observation.v1":
            raise ValueError("unsupported evaluation observation schema")
        if payload.get("username") or payload.get("reviewer_login"):
            raise ValueError("unsafe reviewer identity")
        observed_at = str(payload.get("observed_at") or "")
        datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
        values = {key: payload.get(key) for key in (
            "repo", "pr_number", "run_id", "observed_at", "observed_head_sha", "review_round_id",
            "review_state", "reviewer_relation", "outcome_kind", "correlation_method", "source", "item_id",
            "observed_thread_id", "related_item_id", "finding_fingerprint", "source_url",
        )}
        for key in ("repo", "pr_number", "run_id", "observed_at", "observed_head_sha", "review_round_id", "review_state", "reviewer_relation", "outcome_kind", "correlation_method"):
            if not values.get(key):
                raise ValueError(f"{key} is required")
        if values["reviewer_relation"] not in {"original_concern_author", "other_reviewer", "unknown"}:
            raise ValueError("unsupported reviewer_relation")
        if values["outcome_kind"] not in {"no_reopen", "reopened", "equivalent_recurrence", "manual_recovery", "final_gate_regression"}:
            raise ValueError("unsupported outcome_kind")
        if values["correlation_method"] not in {"thread_id", "related_item_id", "finding_fingerprint"}:
            raise ValueError("unsupported correlation_method")
        values["source"] = values["source"] or "github"
        normalized = {key: (None if value is None else str(value)) for key, value in values.items()}
        fingerprint = str(payload.get("observation_id") or stable_fingerprint(normalized, prefix="observation_"))
        return cls(
            repo=str(normalized["repo"]),
            pr_number=str(normalized["pr_number"]),
            run_id=str(normalized["run_id"]),
            observed_at=str(normalized["observed_at"]),
            observed_head_sha=str(normalized["observed_head_sha"]),
            review_round_id=str(normalized["review_round_id"]),
            review_state=str(normalized["review_state"]),
            reviewer_relation=str(normalized["reviewer_relation"]),
            outcome_kind=str(normalized["outcome_kind"]),
            correlation_method=str(normalized["correlation_method"]),
            source=str(normalized["source"]),
            item_id=normalized["item_id"],
            observed_thread_id=normalized["observed_thread_id"],
            related_item_id=normalized["related_item_id"],
            finding_fingerprint=normalized["finding_fingerprint"],
            source_url=normalized["source_url"],
            observation_id=fingerprint,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
