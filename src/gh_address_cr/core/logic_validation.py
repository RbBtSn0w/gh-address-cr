from __future__ import annotations

from typing import Any, Mapping

from gh_address_cr.core.github_thread_state import GITHUB_THREAD_TERMINAL_STATES
from gh_address_cr.core.models import LogicValidationSignal


TERMINAL_LOCAL_STATES = {"closed", "fixed", "clarified", "deferred", "rejected", "verified", "published"}
TERMINAL_GITHUB_STATES = GITHUB_THREAD_TERMINAL_STATES
NON_MUTATING_GITHUB_RESOLUTIONS = {"clarify", "defer", "reject"}
MUTATING_GITHUB_RESOLUTIONS = {"fix", "fixed"}


def generate_logic_validation_signals(session: Mapping[str, Any]) -> list[LogicValidationSignal]:
    items = session.get("items") or {}
    if isinstance(items, Mapping):
        iterable = items.values()
    else:
        iterable = items

    signals: list[LogicValidationSignal] = []
    for item in iterable:
        if not isinstance(item, Mapping):
            continue
        item_id = str(item.get("item_id") or "")
        if not item_id:
            continue
        state = str(item.get("state") or "")
        item_kind = str(item.get("item_kind") or "")

        if _has_state_contradiction(item):
            signals.append(
                _signal(
                    item_id,
                    "state_contradiction",
                    "high",
                    "Item claims publish readiness while runtime state is not terminal.",
                    "Refresh runtime state and submit the missing evidence before final-gate.",
                    "blocking",
                )
            )
            continue

        if _requires_validation_evidence(item, item_kind, state) and not _has_validation_evidence(item):
            signals.append(
                _signal(
                    item_id,
                    "missing_required_evidence",
                    "high",
                    "Terminal work item is missing validation evidence.",
                    "Record validation evidence or reopen the item before final-gate.",
                    "blocking",
                )
            )
            continue

        if _is_low_confidence(item):
            signals.append(
                _signal(
                    item_id,
                    "low_confidence_advisory",
                    "low",
                    "Item carries a low-confidence logic validation marker.",
                    "Review the rationale if more evidence is available; this advisory does not block completion.",
                    "advisory",
                )
            )
    return signals


def _has_state_contradiction(item: Mapping[str, Any]) -> bool:
    claim = str(item.get("completion_claim") or item.get("claim") or "")
    state = str(item.get("state") or "")
    if claim not in {"ready_to_publish", "fixed", "handled"}:
        return False
    terminal_states = TERMINAL_GITHUB_STATES if str(item.get("item_kind") or "") == "github_thread" else TERMINAL_LOCAL_STATES
    if state in terminal_states or state == "handled":
        return False
    return True


def _has_validation_evidence(item: Mapping[str, Any]) -> bool:
    for key in ("validation_evidence", "validation_commands", "validation_results"):
        if _has_content(item.get(key)):
            return True
    accepted_response = item.get("accepted_response")
    if isinstance(accepted_response, Mapping):
        for key in ("validation_evidence", "validation_commands", "validation_results"):
            if _has_content(accepted_response.get(key)):
                return True
    evidence = item.get("evidence")
    if isinstance(evidence, Mapping):
        return _has_content(evidence.get("validation")) or _has_content(evidence.get("validation_evidence"))
    if _has_content(item.get("resolution_note")) and str(item.get("decision") or "").lower() in {
        "accept",
        "manual",
        "sync",
    }:
        return True
    return False


def _has_content(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, Mapping):
        return any(_has_content(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_has_content(item) for item in value)
    return bool(value)


def _requires_validation_evidence(item: Mapping[str, Any], item_kind: str, state: str) -> bool:
    if item_kind == "local_finding":
        return state in TERMINAL_LOCAL_STATES
    if item_kind == "github_thread":
        resolution = _github_resolution(item)
        if resolution in NON_MUTATING_GITHUB_RESOLUTIONS or state in {"clarified", "deferred", "rejected"}:
            return False
        if resolution in MUTATING_GITHUB_RESOLUTIONS or isinstance(item.get("accepted_response"), Mapping):
            return state in TERMINAL_GITHUB_STATES
        return False
    return False


def _github_resolution(item: Mapping[str, Any]) -> str:
    for source in (item, item.get("accepted_response")):
        if not isinstance(source, Mapping):
            continue
        for key in ("resolution", "decision", "action"):
            value = source.get(key)
            if _has_content(value):
                return str(value).strip().lower()
    classification_evidence = item.get("classification_evidence")
    if isinstance(classification_evidence, Mapping):
        value = classification_evidence.get("classification")
        if _has_content(value):
            return str(value).strip().lower()
    return ""


def _is_low_confidence(item: Mapping[str, Any]) -> bool:
    confidence = str(item.get("logic_confidence") or item.get("confidence") or "").lower()
    return confidence in {"low", "advisory"}


def _signal(
    item_id: str,
    signal_type: str,
    confidence: str,
    explanation: str,
    recommended_action: str,
    gate_effect: str,
) -> LogicValidationSignal:
    return LogicValidationSignal(
        signal_id=f"logic:{signal_type}:{item_id}",
        item_id=item_id,
        signal_type=signal_type,
        confidence=confidence,
        explanation=explanation,
        recommended_action=recommended_action,
        gate_effect=gate_effect,
    )
