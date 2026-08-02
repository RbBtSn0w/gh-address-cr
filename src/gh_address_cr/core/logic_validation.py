from __future__ import annotations

from typing import Any, Mapping

from gh_address_cr.core.github_thread_state import GITHUB_THREAD_TERMINAL_STATES
from gh_address_cr.core.models import LogicValidationSignal
from gh_address_cr.core.runtime_kernel.stack import StackContext, stack_context_from_serialized
from gh_address_cr.core.validation_evidence import revision_evidence_status, validation_evidence_has_success

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
    stack_context = _current_stack_context(session)
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
                    item_kind,
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
                    item_kind,
                    "missing_required_evidence",
                    "high",
                    "Terminal work item is missing validation evidence.",
                    "Record validation evidence or reopen the item before final-gate.",
                    "blocking",
                )
            )
            continue

        if stack_context is not None and _requires_validation_evidence(item, item_kind, state):
            evidence_status = revision_evidence_status(_revision_binding(item), stack_context)
            if evidence_status != "current":
                signal_type = f"{evidence_status}_revision_evidence"
                signals.append(
                    _signal(
                        item_id,
                        item_kind,
                        signal_type,
                        "high",
                        "Validation evidence does not prove the current stacked-member revision.",
                        "Refresh the stack and rerun validation for this PR layer.",
                        "blocking",
                    )
                )
                continue

        if _is_low_confidence(item):
            signals.append(
                _signal(
                    item_id,
                    item_kind,
                    "low_confidence_advisory",
                    "low",
                    "Item carries a low-confidence logic validation marker.",
                    "Review the rationale if more evidence is available; this advisory does not block completion.",
                    "advisory",
                )
            )
    return signals


def _current_stack_context(session: Mapping[str, Any]) -> StackContext | None:
    metadata = session.get("metadata")
    observed = metadata.get("pull_request_context") if isinstance(metadata, Mapping) else None
    payload = observed.get("stack_context") if isinstance(observed, Mapping) else None
    if not isinstance(payload, Mapping) or payload.get("availability") != "present":
        return None
    return stack_context_from_serialized(
        payload,
        repo=str(session.get("repo") or ""),
        pr_number=str(session.get("pr_number") or ""),
    )


def _revision_binding(item: Mapping[str, Any]) -> Any:
    accepted = item.get("accepted_response")
    if isinstance(accepted, Mapping) and isinstance(accepted.get("revision_binding"), Mapping):
        return accepted["revision_binding"]
    return item.get("revision_binding")


def _has_state_contradiction(item: Mapping[str, Any]) -> bool:
    claim = str(item.get("completion_claim") or item.get("claim") or "")
    state = str(item.get("state") or "")
    if claim not in {"ready_to_publish", "fixed", "handled"}:
        return False
    terminal_states = (
        TERMINAL_GITHUB_STATES if str(item.get("item_kind") or "") == "github_thread" else TERMINAL_LOCAL_STATES
    )
    if state in terminal_states or state == "handled":
        return False
    return True


def _has_validation_evidence(item: Mapping[str, Any]) -> bool:
    for key in ("validation_evidence", "validation_commands", "validation_results"):
        if validation_evidence_has_success(item.get(key)):
            return True
    accepted_response = item.get("accepted_response")
    if isinstance(accepted_response, Mapping):
        for key in ("validation_evidence", "validation_commands", "validation_results"):
            if validation_evidence_has_success(accepted_response.get(key)):
                return True
    evidence = item.get("evidence")
    if isinstance(evidence, Mapping):
        return validation_evidence_has_success(evidence.get("validation")) or validation_evidence_has_success(
            evidence.get("validation_evidence")
        )
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
    for source in (item.get("accepted_response"), item):
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
    item_kind: str,
    signal_type: str,
    confidence: str,
    explanation: str,
    recommended_action: str,
    gate_effect: str,
) -> LogicValidationSignal:
    return LogicValidationSignal(
        signal_id=f"logic:{signal_type}:{item_id}",
        item_id=item_id,
        item_kind=item_kind,
        signal_type=signal_type,
        confidence=confidence,
        explanation=explanation,
        recommended_action=recommended_action,
        gate_effect=gate_effect,
    )
