from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

from gh_address_cr.core.evaluation.models import EvaluationObservationV1


def append_observations(path: Path, observations: Iterable[EvaluationObservationV1]) -> dict[str, int]:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: set[str] = set()
    if path.exists():
        try:
            records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            existing = {str(record["observation_id"]) for record in records}
        except (OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
            raise ValueError(f"observation ledger invalid: {exc}") from exc
    accepted = duplicate = 0
    with path.open("a", encoding="utf-8") as handle:
        for observation in observations:
            if observation.observation_id in existing:
                duplicate += 1
                continue
            handle.write(json.dumps(observation.to_dict(), sort_keys=True) + "\n")
            existing.add(observation.observation_id)
            accepted += 1
    return {"accepted_count": accepted, "duplicate_count": duplicate}


def load_observations(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def normalize_observation(payload: Mapping[str, Any]) -> EvaluationObservationV1:
    return EvaluationObservationV1.from_dict(payload)


def validate_observation(observation: EvaluationObservationV1, manifest: Mapping[str, Any]) -> None:
    identity = (observation.repo, observation.pr_number, observation.run_id)
    manifest_identity = (str(manifest.get("repo")), str(manifest.get("pr_number")), str(manifest.get("run_id")))
    if identity != manifest_identity:
        raise ValueError("observation identity does not match the archived run")
    boundary = manifest.get("final_gate_observed_at")
    if not boundary:
        raise ValueError("archived run has no supported later-observation boundary")
    observed_at = datetime.fromisoformat(observation.observed_at.replace("Z", "+00:00"))
    final_gate_at = datetime.fromisoformat(str(boundary).replace("Z", "+00:00"))
    if observed_at <= final_gate_at:
        raise ValueError("observation must be later than provisional final-gate evidence")
