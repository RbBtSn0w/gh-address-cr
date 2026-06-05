"""Projection logic for deriving current review state from runtime facts."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from gh_address_cr.core.github_thread_state import (
    is_resolved_github_thread,
    is_stale_or_outdated_github_thread,
    normalized_thread_state,
)
from gh_address_cr.core.runtime_kernel.events import (
    COMMAND_EXECUTED,
    REPORTING_OBSERVED,
    REVIEW_THREAD_OBSERVED,
    CommandExecutionFact,
    ReviewThreadFact,
    RuntimeFact,
    sort_runtime_facts,
)
from gh_address_cr.core.runtime_kernel.identity import planned_command_id, planned_command_payload


JsonDict = dict[str, Any]

REQUIRED_THREAD_COMMANDS = ("reply_thread", "resolve_thread")
DURABLE_EVIDENCE_COMMANDS = frozenset(REQUIRED_THREAD_COMMANDS)


@dataclass(frozen=True)
class ReviewWorkItem:
    item_id: str
    thread_id: str
    source_fact_id: str
    source_observed_at: str
    state: str
    source_status: str
    is_resolved: bool
    is_outdated: bool
    reply_evidence_present: bool
    required_commands: tuple[str, ...] = ()
    completion_evidence: tuple[JsonDict, ...] = ()
    failed_commands: tuple[JsonDict, ...] = ()
    history: tuple[JsonDict, ...] = ()
    path: str | None = None
    line: int | None = None
    url: str | None = None
    body: str | None = None

    def to_dict(self) -> JsonDict:
        payload: JsonDict = {
            "item_id": self.item_id,
            "thread_id": self.thread_id,
            "source_fact_id": self.source_fact_id,
            "source_observed_at": self.source_observed_at,
            "state": self.state,
            "source_status": self.source_status,
            "is_resolved": self.is_resolved,
            "is_outdated": self.is_outdated,
            "reply_evidence_present": self.reply_evidence_present,
            "required_commands": list(self.required_commands),
            "completion_evidence": [dict(record) for record in self.completion_evidence],
            "failed_commands": [dict(record) for record in self.failed_commands],
            "history": [dict(record) for record in self.history],
        }
        if self.path is not None:
            payload["path"] = self.path
        if self.line is not None:
            payload["line"] = self.line
        if self.url is not None:
            payload["url"] = self.url
        if self.body is not None:
            payload["body"] = self.body
        return payload


@dataclass(frozen=True)
class ReviewProjection:
    work_items: tuple[ReviewWorkItem, ...] = ()
    active_item_ids: tuple[str, ...] = ()
    terminal_item_ids: tuple[str, ...] = ()
    stale_item_ids: tuple[str, ...] = ()
    reopened_item_ids: tuple[str, ...] = ()
    waiting_item_ids: tuple[str, ...] = ()
    evidence_pending_item_ids: tuple[str, ...] = ()
    final_gate_blocker_ids: tuple[str, ...] = ()
    diagnostics: tuple[JsonDict, ...] = ()

    def to_dict(self) -> JsonDict:
        return {
            "work_items": [item.to_dict() for item in self.work_items],
            "active_item_ids": list(self.active_item_ids),
            "terminal_item_ids": list(self.terminal_item_ids),
            "stale_item_ids": list(self.stale_item_ids),
            "reopened_item_ids": list(self.reopened_item_ids),
            "waiting_item_ids": list(self.waiting_item_ids),
            "evidence_pending_item_ids": list(self.evidence_pending_item_ids),
            "final_gate_blocker_ids": list(self.final_gate_blocker_ids),
            "diagnostics": [dict(record) for record in self.diagnostics],
        }


def _history_record(thread_fact: ReviewThreadFact) -> JsonDict:
    row = thread_fact.row()
    return {
        "fact_id": thread_fact.fact.fact_id,
        "observed_at": thread_fact.fact.observed_at,
        "sequence": thread_fact.fact.sequence,
        "state": normalized_thread_state(row),
        "status": thread_fact.payload.get("status"),
        "is_resolved": is_resolved_github_thread(row),
        "is_outdated": is_stale_or_outdated_github_thread(row),
    }


def _execution_records(executions: tuple[CommandExecutionFact, ...]) -> tuple[JsonDict, ...]:
    records: list[JsonDict] = []
    for execution in sorted(executions, key=lambda execution: execution.command_id):
        if not execution.succeeded:
            continue
        record = {
            "command_id": execution.command_id,
            "command_kind": execution.command_kind,
            "status": execution.status,
            **({"result_url": execution.result_url} if execution.result_url else {}),
        }
        satisfies_command_kind = _satisfies_command_kind(execution)
        if satisfies_command_kind != execution.command_kind:
            record["satisfies_command_kind"] = satisfies_command_kind
        records.append(record)
    return tuple(records)


def _failed_execution_records(executions: tuple[CommandExecutionFact, ...]) -> tuple[JsonDict, ...]:
    return tuple(
        {
            "command_id": execution.command_id,
            "command_kind": execution.command_kind,
            "status": execution.status,
            **({"result_url": execution.result_url} if execution.result_url else {}),
        }
        for execution in sorted(executions, key=lambda execution: execution.command_id)
        if not execution.succeeded
    )


def _satisfies_command_kind(execution: CommandExecutionFact) -> str:
    if execution.command_kind == "retry_command":
        return str(execution.payload.get("retry_command_kind") or "")
    return execution.command_kind


def _successful_command_kinds(executions: tuple[CommandExecutionFact, ...]) -> frozenset[str]:
    return frozenset(_satisfies_command_kind(execution) for execution in executions if execution.succeeded)


def _has_durable_completion_evidence(execution: CommandExecutionFact) -> bool:
    if not execution.succeeded:
        return False
    if _satisfies_command_kind(execution) in DURABLE_EVIDENCE_COMMANDS:
        return isinstance(execution.result_url, str) and execution.result_url.strip() != ""
    return True


def _completion_evidence_executions(executions: tuple[CommandExecutionFact, ...]) -> tuple[CommandExecutionFact, ...]:
    return tuple(execution for execution in executions if _has_durable_completion_evidence(execution))


def _expected_command_id(command_kind: str, latest: ReviewThreadFact) -> str:
    payload = planned_command_payload(
        item_id=latest.item_id,
        thread_id=latest.thread_id,
        source_fact_id=latest.fact.fact_id,
        source_observed_at=latest.fact.observed_at,
    )
    return planned_command_id(
        command_kind=command_kind,
        reason_code="REVIEW_THREAD_ACTION_REQUIRED",
        item_id=latest.item_id,
        payload=payload,
    )


def _expected_retry_command_id(execution: CommandExecutionFact, latest: ReviewThreadFact) -> str | None:
    retry_command_kind = execution.payload.get("retry_command_kind")
    if retry_command_kind not in REQUIRED_THREAD_COMMANDS:
        return None
    failed_command_id = execution.payload.get("failed_command_id")
    if failed_command_id != _expected_command_id(str(retry_command_kind), latest):
        return None
    payload = planned_command_payload(
        item_id=latest.item_id,
        thread_id=latest.thread_id,
        source_fact_id=latest.fact.fact_id,
        source_observed_at=latest.fact.observed_at,
    )
    payload.update(
        {
            "failed_command_id": failed_command_id,
            "retry_command_kind": retry_command_kind,
        }
    )
    return planned_command_id(
        command_kind="retry_command",
        reason_code="SIDE_EFFECT_RETRY_REQUIRED",
        item_id=latest.item_id,
        payload=payload,
    )


def _expected_current_generation_command_id(execution: CommandExecutionFact, latest: ReviewThreadFact) -> str | None:
    if execution.command_kind == "retry_command":
        return _expected_retry_command_id(execution, latest)
    return _expected_command_id(execution.command_kind, latest)


def _matches_current_generation(execution: CommandExecutionFact, latest: ReviewThreadFact) -> bool:
    expected_command_id = _expected_current_generation_command_id(execution, latest)
    return (
        expected_command_id is not None
        and execution.payload.get("source_fact_id") == latest.fact.fact_id
        and execution.payload.get("source_observed_at") == latest.fact.observed_at
        and execution.command_id == expected_command_id
    )


def _matching_generation_executions(
    executions: tuple[CommandExecutionFact, ...],
    thread_fact: ReviewThreadFact,
) -> tuple[CommandExecutionFact, ...]:
    return tuple(execution for execution in executions if _matches_current_generation(execution, thread_fact))


def _current_generation_executions(
    executions: tuple[CommandExecutionFact, ...],
    latest: ReviewThreadFact,
) -> tuple[CommandExecutionFact, ...]:
    return _matching_generation_executions(executions, latest)


def _generation_completed(thread_fact: ReviewThreadFact, executions: tuple[CommandExecutionFact, ...]) -> bool:
    successful_commands = _successful_command_kinds(
        _completion_evidence_executions(_matching_generation_executions(executions, thread_fact))
    )
    return all(command in successful_commands for command in REQUIRED_THREAD_COMMANDS)


def _project_item(thread_facts: tuple[ReviewThreadFact, ...], executions: tuple[CommandExecutionFact, ...]) -> ReviewWorkItem:
    latest = thread_facts[-1]
    latest_row = latest.row()
    latest_payload = latest.payload
    history = tuple(_history_record(fact) for fact in thread_facts)
    current_executions = _current_generation_executions(executions, latest)
    completion_executions = _completion_evidence_executions(current_executions)
    successful_commands = _successful_command_kinds(completion_executions)
    completion_evidence = _execution_records(completion_executions)
    failed_commands = _failed_execution_records(current_executions)
    has_reply = latest_payload.get("reply_evidence_present") is True or "reply_thread" in successful_commands
    has_resolve = is_resolved_github_thread(latest_row) or "resolve_thread" in successful_commands
    all_commands_succeeded = all(command in successful_commands for command in REQUIRED_THREAD_COMMANDS)
    had_terminal_history = any(record["is_resolved"] for record in history[:-1]) or any(
        _generation_completed(thread_fact, executions) for thread_fact in thread_facts[:-1]
    )
    latest_resolved = is_resolved_github_thread(latest_row)
    latest_stale = is_stale_or_outdated_github_thread(latest_row)
    external_wait = latest_payload.get("external_wait") is True

    if all_commands_succeeded or (latest_resolved and has_reply):
        state = "terminal"
    elif latest_resolved and not has_reply:
        state = "evidence_pending"
    elif external_wait:
        state = "waiting"
    elif had_terminal_history and not latest_resolved:
        state = "reopened"
    elif latest_stale:
        state = "stale"
    else:
        state = "active"

    required_commands: tuple[str, ...]
    if state == "terminal":
        required_commands = ()
    else:
        missing = []
        if not has_reply:
            missing.append("reply_thread")
        if not has_resolve:
            missing.append("resolve_thread")
        required_commands = tuple(missing)

    return ReviewWorkItem(
        item_id=latest.item_id,
        thread_id=latest.thread_id,
        source_fact_id=latest.fact.fact_id,
        source_observed_at=latest.fact.observed_at,
        state=state,
        source_status=str(latest_payload.get("status") or normalized_thread_state(latest_row) or "").upper(),
        is_resolved=state == "terminal" or latest_resolved,
        is_outdated=latest_stale,
        reply_evidence_present=has_reply,
        required_commands=required_commands,
        completion_evidence=completion_evidence,
        failed_commands=failed_commands,
        history=history,
        path=latest_payload.get("path"),
        line=latest_payload.get("line"),
        url=latest_payload.get("url"),
        body=latest_payload.get("body"),
    )


def project_review_threads(facts: list[JsonDict | RuntimeFact] | tuple[JsonDict | RuntimeFact, ...]) -> ReviewProjection:
    sorted_facts = sort_runtime_facts(tuple(facts))
    thread_facts_by_item: dict[str, list[ReviewThreadFact]] = defaultdict(list)
    executions_by_item: dict[str, list[CommandExecutionFact]] = defaultdict(list)
    diagnostics: list[JsonDict] = []

    for fact in sorted_facts:
        if fact.fact_kind == REVIEW_THREAD_OBSERVED:
            thread_fact = ReviewThreadFact.from_runtime_fact(fact)
            thread_facts_by_item[thread_fact.item_id].append(thread_fact)
        elif fact.fact_kind == COMMAND_EXECUTED:
            execution = CommandExecutionFact.from_runtime_fact(fact)
            if execution.item_id:
                executions_by_item[str(execution.item_id)].append(execution)
            else:
                diagnostics.append(
                    {
                        "severity": "advisory",
                        "reason_code": "KERNEL_COMMAND_EXECUTION_UNSCOPED",
                        "fact_id": fact.fact_id,
                    }
                )
        elif fact.fact_kind == REPORTING_OBSERVED:
            diagnostics.append(
                {
                    "severity": "diagnostic",
                    "reason_code": "REPORTING_OBSERVED",
                    "fact_id": fact.fact_id,
                    "write_status": fact.payload.get("write_status"),
                }
            )

    work_items = tuple(
        _project_item(tuple(thread_facts_by_item[item_id]), tuple(executions_by_item.get(item_id, ())))
        for item_id in sorted(thread_facts_by_item)
    )

    active_item_ids = tuple(item.item_id for item in work_items if item.state in {"active", "stale", "reopened"})
    terminal_item_ids = tuple(item.item_id for item in work_items if item.state == "terminal")
    stale_item_ids = tuple(item.item_id for item in work_items if item.state == "stale")
    reopened_item_ids = tuple(item.item_id for item in work_items if item.state == "reopened")
    waiting_item_ids = tuple(item.item_id for item in work_items if item.state == "waiting")
    evidence_pending_item_ids = tuple(item.item_id for item in work_items if item.state == "evidence_pending")
    final_gate_blocker_ids = tuple(
        item.item_id for item in work_items if item.state in {"active", "stale", "reopened", "waiting", "evidence_pending"}
    )

    return ReviewProjection(
        work_items=work_items,
        active_item_ids=active_item_ids,
        terminal_item_ids=terminal_item_ids,
        stale_item_ids=stale_item_ids,
        reopened_item_ids=reopened_item_ids,
        waiting_item_ids=waiting_item_ids,
        evidence_pending_item_ids=evidence_pending_item_ids,
        final_gate_blocker_ids=final_gate_blocker_ids,
        diagnostics=tuple(diagnostics),
    )
