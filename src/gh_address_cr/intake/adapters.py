from __future__ import annotations

import json
from typing import Any

from gh_address_cr.github.threads import normalize_threads
from gh_address_cr.intake.findings import FindingsFormatError, normalize_findings_payload


class AdapterError(ValueError):
    pass


def normalize_adapter_payload(source: str, raw: str) -> list[dict[str, Any]]:
    if source in {"github", "github-threads"}:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise AdapterError(f"Invalid GitHub thread JSON: {exc}") from exc
        return normalize_threads(payload)
    try:
        return normalize_findings_payload(source, raw)
    except FindingsFormatError as exc:
        raise AdapterError(str(exc)) from exc


def normalize_github_thread_fixture(payload: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        return normalize_threads(payload["input"])
    except (KeyError, TypeError, ValueError, FindingsFormatError) as exc:
        raise AdapterError(f"Invalid GitHub thread fixture: {exc}") from exc
