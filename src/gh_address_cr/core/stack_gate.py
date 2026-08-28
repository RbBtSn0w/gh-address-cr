"""Read-only bottom-up final-gate coordination for a selected stack segment."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from gh_address_cr.core import command_templates, paths, protocol_codes
from gh_address_cr.core.gate import Gatekeeper, GateResult
from gh_address_cr.core.runtime_kernel.stack import StackContext, project_stack_segment, stack_context_for_member
from gh_address_cr.core.session import SessionError


class StackContextDiscoveryError(RuntimeError):
    """Opening or closing stack observation failed before a coherent decision."""


@dataclass(frozen=True)
class StackGateResult:
    repo: str
    selected_pr_number: str
    stack_context: StackContext
    covered_pr_numbers: tuple[str, ...]
    member_outcomes: tuple[dict[str, Any], ...]
    check_requirement: str | None = None
    reason_code: str | None = None
    first_blocked_pr_number: str | None = None
    first_blocked_item_kind: str | None = None

    @property
    def passed(self) -> bool:
        return self.reason_code is None

    @property
    def exit_code(self) -> int:
        return 0 if self.passed else 5

    @property
    def waiting_on(self) -> str | None:
        if self.reason_code == protocol_codes.STACK_MEMBER_BLOCKED:
            blocked_outcome = next(
                (
                    outcome
                    for outcome in self.member_outcomes
                    if outcome.get("pr_number") == self.first_blocked_pr_number
                ),
                None,
            )
            if blocked_outcome:
                nested_waiting_on = str(blocked_outcome.get("layer_waiting_on") or "").strip()
                if nested_waiting_on:
                    return nested_waiting_on
        if self.reason_code is None:
            return None
        return {
            protocol_codes.STACK_CONTEXT_UNAVAILABLE: "stack_context",
            protocol_codes.STACK_CONTEXT_INVALID: "stack_context",
            protocol_codes.STACK_CONTEXT_STALE: "stack_refresh",
            protocol_codes.STACK_MEMBER_SESSION_MISSING: "member_session",
            protocol_codes.STACK_MEMBER_SESSION_INVALID: "member_session",
            protocol_codes.STACK_MEMBER_DRAFT: "member_state",
            protocol_codes.STACK_MEMBER_CLOSED: "member_state",
            protocol_codes.STACK_MEMBER_QUEUED: "merge_queue",
            protocol_codes.STACK_MEMBER_BLOCKED: "member_gate",
        }.get(self.reason_code)

    def to_machine_summary(self) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for outcome in self.member_outcomes:
            for key, value in (outcome.get("counts") or {}).items():
                counts[str(key)] = counts.get(str(key), 0) + int(value)
        recovery_pr = self.first_blocked_pr_number or self.selected_pr_number
        blocked_outcome = next(
            (outcome for outcome in self.member_outcomes if outcome.get("pr_number") == self.first_blocked_pr_number),
            None,
        )
        layer_reason_code = blocked_outcome.get("layer_reason_code") if blocked_outcome else None
        recovery_command = command_templates.stack_member_recovery(
            self.repo,
            recovery_pr,
            self.reason_code,
            layer_reason_code=layer_reason_code,
        )
        recovery_action = (
            str(blocked_outcome.get("layer_next_action") or recovery_command) if blocked_outcome else recovery_command
        )
        stack_merge_readiness = "ready" if self.passed else "blocked"
        if self.stack_context.availability in {"unavailable", "invalid"}:
            stack_merge_readiness = "unknown"
        return {
            "schema_version": "stack_gate_result.v1",
            "status": "PASSED" if self.passed else "FAILED",
            "repo": self.repo,
            "pr_number": self.selected_pr_number,
            "gate_scope": "final",
            "completion_scope": "stack_segment",
            "check_requirement": self.check_requirement,
            "stack_merge_readiness": stack_merge_readiness,
            "stack_context": self.stack_context.to_dict(),
            "stack_gate": {
                "selected_pr_number": self.selected_pr_number,
                "check_requirement": self.check_requirement,
                "covered_pr_numbers": list(self.covered_pr_numbers),
                "first_blocked_pr_number": self.first_blocked_pr_number,
                "member_outcomes": list(self.member_outcomes),
            },
            "reason_code": self.reason_code,
            "waiting_on": self.waiting_on,
            "failure_codes": [self.reason_code] if self.reason_code else [],
            "counts": counts,
            "exit_code": self.exit_code,
            "next_action": ("The selected stack segment is ready." if self.passed else recovery_action),
            "commands": {
                "final_gate_stack": command_templates.final_gate_stack(self.repo, self.selected_pr_number),
                "member_recovery": recovery_command,
            },
        }


def evaluate_stack_gate(
    repo: str,
    selected_pr_number: str,
    context: StackContext,
    *,
    session_exists: Callable[[str], bool],
    evaluate_member: Callable[[str], GateResult],
    closing_context: StackContext | Callable[[], StackContext],
    check_requirement: str | None = None,
) -> StackGateResult:
    if context.availability in {"unavailable", "invalid"}:
        return StackGateResult(
            repo,
            str(selected_pr_number),
            context,
            (),
            (),
            check_requirement=check_requirement,
            reason_code=context.diagnostic_code,
        )

    segment = project_stack_segment(context)
    covered = tuple(member.pr_number for member in segment.included_members)
    outcomes: list[dict[str, Any]] = []
    reason: str | None = None
    first_blocked: str | None = None
    first_blocked_item_kind: str | None = None
    for member in segment.included_members:
        member_reason = _member_preflight_reason(member, session_exists)
        layer: GateResult | None = None
        if member_reason is None:
            try:
                layer = evaluate_member(member.pr_number)
            except SessionError:
                member_reason = protocol_codes.STACK_MEMBER_SESSION_INVALID
            else:
                if not layer.passed:
                    member_reason = protocol_codes.STACK_MEMBER_BLOCKED
        outcome = {
            "pr_number": member.pr_number,
            "position": member.position,
            "status": "PASSED" if member_reason is None else "FAILED",
            "reason_code": member_reason,
            "layer_reason_code": layer.reason_code if layer is not None else None,
            "layer_waiting_on": layer.waiting_on if layer is not None else None,
            "counts": dict(layer.counts) if layer is not None else {},
            "layer_next_action": layer.to_machine_summary()["next_action"] if layer is not None else None,
        }
        outcomes.append(outcome)
        if reason is None and member_reason is not None:
            reason = member_reason
            first_blocked = member.pr_number
            first_blocked_item_kind = _layer_blocking_item_kind(layer)

    final_context = closing_context() if callable(closing_context) else closing_context
    if (
        final_context.availability != context.availability
        or final_context.selected_pr_number != context.selected_pr_number
        or final_context.topology_fingerprint != context.topology_fingerprint
    ):
        reason = protocol_codes.STACK_CONTEXT_STALE
        first_blocked = None
        first_blocked_item_kind = None

    return StackGateResult(
        repo,
        str(selected_pr_number),
        final_context if reason == protocol_codes.STACK_CONTEXT_STALE else context,
        covered,
        tuple(outcomes),
        check_requirement=check_requirement,
        reason_code=reason,
        first_blocked_pr_number=first_blocked,
        first_blocked_item_kind=first_blocked_item_kind,
    )


def _layer_blocking_item_kind(layer: GateResult | None) -> str | None:
    if layer is None:
        return None
    if layer.reason_code is None:
        return None
    expected_signal_types = {
        "FINAL_GATE_MISSING_VALIDATION_EVIDENCE": {"missing_required_evidence"},
        "FINAL_GATE_STALE_REVISION_EVIDENCE": {"stale_revision_evidence"},
        "FINAL_GATE_UNBOUND_REVISION_EVIDENCE": {"unbound_revision_evidence"},
    }.get(layer.reason_code)
    if expected_signal_types is None:
        return None
    signal = next(
        (
            row
            for row in (layer.logic_validation_signals or [])
            if row.get("gate_effect") == "blocking" and row.get("signal_type") in expected_signal_types
        ),
        None,
    )
    if signal is None:
        return None
    return str(signal.get("item_kind") or "").strip() or None


def run_stack_gate(
    repo: str,
    pr_number: str,
    *,
    github_client: Any,
    snapshot_path: str | Path | None = None,
    require_checks: bool = False,
    require_required_checks: bool = False,
) -> StackGateResult:
    try:
        opening = github_client.get_stack_context(repo, str(pr_number))
    except Exception as exc:
        raise StackContextDiscoveryError("Opening stack context could not be read.") from exc
    _emit_stack_event("gh_address_cr.stack.discovered", opening)
    check_requirement = "required" if require_required_checks else ("all" if require_checks else None)

    def evaluate_member(member_pr: str) -> GateResult:
        return Gatekeeper(github_client=github_client).run(
            repo,
            member_pr,
            snapshot_path=snapshot_path if member_pr == str(pr_number) else None,
            require_checks=require_checks,
            require_required_checks=require_required_checks,
            observed_stack_context=stack_context_for_member(opening, member_pr),
            require_existing_session=True,
        )

    def closing_context() -> StackContext:
        try:
            return github_client.get_stack_context(repo, str(pr_number))
        except Exception as exc:
            raise StackContextDiscoveryError("Closing stack context could not be read.") from exc

    result = evaluate_stack_gate(
        repo,
        str(pr_number),
        opening,
        session_exists=lambda member_pr: paths.session_file(repo, member_pr).is_file(),
        evaluate_member=evaluate_member,
        closing_context=closing_context,
        check_requirement=check_requirement,
    )
    _emit_stack_event(
        "gh_address_cr.stack.gate.evaluated",
        result.stack_context,
        outcome="passed" if result.passed else "blocked",
        reason_code=result.reason_code or "PASSED",
    )
    return result


def _member_preflight_reason(member: Any, session_exists: Callable[[str], bool]) -> str | None:
    if member.state == "CLOSED":
        return protocol_codes.STACK_MEMBER_CLOSED
    if member.is_draft:
        return protocol_codes.STACK_MEMBER_DRAFT
    if member.merge_queue_state:
        return protocol_codes.STACK_MEMBER_QUEUED
    if not session_exists(member.pr_number):
        return protocol_codes.STACK_MEMBER_SESSION_MISSING
    return None


def _emit_stack_event(
    name: str,
    context: StackContext,
    *,
    outcome: str | None = None,
    reason_code: str | None = None,
) -> None:
    try:
        from gh_address_cr.core.telemetry_safety import stack_telemetry_attributes
        from gh_address_cr.otel_tracing import add_current_span_event

        attributes = stack_telemetry_attributes(context)
        if outcome:
            attributes["gh_address_cr.stack.outcome"] = outcome
        if reason_code:
            attributes["gh_address_cr.stack.reason_code"] = reason_code
        add_current_span_event(name, attributes)
    except Exception:
        return
