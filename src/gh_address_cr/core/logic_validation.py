from __future__ import annotations

from typing import Any, Mapping

from gh_address_cr.core.models import LogicValidationSignal


TERMINAL_LOCAL_STATES = {"fixed", "closed", "verified", "published"}
TERMINAL_GITHUB_STATES = {"fixed", "closed", "verified", "published", "resolved"}


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

        if _requires_validation_evidence(item_kind, state) and not _has_validation_evidence(item):
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
    if state in {"closed", "fixed", "handled", "published", "verified"}:
        return False
    return True


def _has_validation_evidence(item: Mapping[str, Any]) -> bool:
    evidence = item.get("validation_evidence") or item.get("validation_commands")
    return bool(evidence)


def _requires_validation_evidence(item_kind: str, state: str) -> bool:
    if item_kind == "local_finding":
        return state in TERMINAL_LOCAL_STATES
    if item_kind == "github_thread":
        return state in TERMINAL_GITHUB_STATES
    return False


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
