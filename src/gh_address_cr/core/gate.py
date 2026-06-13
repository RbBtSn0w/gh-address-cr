"""Final-gate aggregation for PR-scoped review sessions."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from gh_address_cr.core import command_templates
from gh_address_cr.core.github_thread_state import (
    GITHUB_THREAD_TERMINAL_STATES,
    is_stale_or_outdated_github_thread,
)
from gh_address_cr.core.logic_validation import generate_logic_validation_signals
from gh_address_cr.core.runtime_kernel.final_gate import (
    COUNT_KEYS,
    FAILURE_ORDER,
    FINAL_GATE_BLOCKING_GITHUB_ITEMS,
    FINAL_GATE_BLOCKING_LOCAL_ITEMS,
    FINAL_GATE_LOGIC_VALIDATION_BLOCKING,
    FINAL_GATE_MISSING_REPLY_EVIDENCE,
    FINAL_GATE_MISSING_VALIDATION_EVIDENCE,
    FINAL_GATE_PENDING_CURRENT_LOGIN_REVIEW,
    FINAL_GATE_PR_CHECKS_NOT_GREEN,
    FINAL_GATE_UNRESOLVED_REMOTE_THREADS,
    build_final_gate_facts,
    evaluate_final_gate_policy,
    has_content,
    project_final_gate,
    thread_identifier,
    thread_is_resolved,
)
from gh_address_cr.core.session import SessionError, SessionManager
from gh_address_cr.core.severity import (
    apply_severity_evidence,
    extract_review_priority_evidence,
    extract_severity_evidence,
    first_scene_item_severity,
    review_priority_evidence,
    severity_evidence,
)
from gh_address_cr.github.client import GitHubClient

PASS_EXIT_CODE = 0
FAIL_EXIT_CODE = 5

GITHUB_TERMINAL_STATES = GITHUB_THREAD_TERMINAL_STATES


@dataclass(frozen=True)
class GateResult:
    repo: str
    pr_number: str
    counts: dict[str, int]
    failure_codes: list[str]
    check_requirement: str | None = None
    logic_validation_signals: list[dict[str, Any]] | None = None

    @property
    def passed(self) -> bool:
        return not self.failure_codes

    @property
    def reason_code(self) -> str | None:
        return self.failure_codes[0] if self.failure_codes else None

    @property
    def waiting_on(self) -> str | None:
        if not self.reason_code:
            return None
        for code, _, waiting_on in FAILURE_ORDER:
            if code == self.reason_code:
                return waiting_on
        return "final_gate"

    @property
    def exit_code(self) -> int:
        return PASS_EXIT_CODE if self.passed else FAIL_EXIT_CODE

    def to_machine_summary(self) -> dict[str, Any]:
        return {
            "status": "PASSED" if self.passed else "FAILED",
            "repo": self.repo,
            "pr_number": self.pr_number,
            "item_id": None,
            "item_kind": None,
            "counts": dict(self.counts),
            "artifact_path": None,
            "reason_code": self.reason_code,
            "waiting_on": self.waiting_on,
            "next_action": _next_action(self.reason_code, repo=self.repo, pr_number=self.pr_number, passed=self.passed),
            "exit_code": self.exit_code,
            # Authoritative completion proof (pending reviews + checks evaluated),
            # distinct from the inline pre-gate emitted by review/address/threads.
            "gate_scope": "final",
            "failure_codes": list(self.failure_codes),
            "check_requirement": self.check_requirement,
            "commands": _final_gate_commands(self.repo, self.pr_number),
            "logic_validation_signals": list(self.logic_validation_signals or []),
        }


class Gatekeeper:
    def __init__(self, *, github_client: Any | None = None):
        self.github_client = github_client or GitHubClient()

    def run(
        self,
        repo: str,
        pr_number: str,
        *,
        snapshot_path: str | Path | None = None,
        require_checks: bool = False,
        require_required_checks: bool = False,
    ) -> GateResult:
        manager = SessionManager(repo, str(pr_number))
        try:
            session = manager.load()
        except SessionError:
            session = manager.create(status="WAITING_FOR_GATE")
        current_login = self.github_client.viewer_login()
        remote_threads = (
            _load_thread_snapshot(snapshot_path)
            if snapshot_path
            else self.github_client.list_threads(repo, str(pr_number))
        )
        pending_reviews = self.github_client.list_pending_reviews(repo, str(pr_number), current_login)
        check_runs = (
            self.github_client.list_pr_checks(repo, str(pr_number), required=require_required_checks)
            if require_checks or require_required_checks
            else []
        )
        merged_session = _session_with_remote_threads(session, remote_threads, current_login=current_login)
        result = evaluate_final_gate(
            merged_session,
            remote_threads=remote_threads,
            pending_reviews=pending_reviews,
            current_login=current_login,
            check_runs=check_runs,
            check_requirement="required" if require_required_checks else ("all" if require_checks else None),
        )
        metrics = dict(merged_session.get("metrics") or {})
        metrics.update(
            {
                "blocking_items_count": result.counts["blocking_items_count"],
                "unresolved_github_threads_count": result.counts["unresolved_github_threads_count"],
                "github_threads_missing_reply_count": result.counts["github_threads_missing_reply_count"],
                "pending_current_login_review_count": result.counts["pending_current_login_review_count"],
                "pr_checks_failed_count": result.counts["pr_checks_failed_count"],
                "pr_checks_pending_count": result.counts["pr_checks_pending_count"],
            }
        )
        merged_session["metrics"] = metrics
        manager.save(merged_session)
        return result


def evaluate_final_gate(
    session: Mapping[str, Any],
    *,
    remote_threads: Iterable[Mapping[str, Any]] = (),
    pending_reviews: Iterable[Mapping[str, Any]] = (),
    current_login: str | None = None,
    check_runs: Iterable[Mapping[str, Any]] = (),
    check_requirement: str | None = None,
) -> GateResult:
    logic_validation_signals = [signal.to_dict() for signal in generate_logic_validation_signals(session)]
    facts = build_final_gate_facts(
        session,
        remote_threads=remote_threads,
        pending_reviews=pending_reviews,
        current_login=current_login,
        check_runs=check_runs,
        check_requirement=check_requirement,
        logic_validation_signals=logic_validation_signals,
    )
    projection = project_final_gate(
        facts,
        current_login=current_login,
        check_requirement=check_requirement,
    )
    decision = evaluate_final_gate_policy(projection)

    return GateResult(
        repo=str(session.get("repo") or ""),
        pr_number=str(session.get("pr_number") or ""),
        counts={key: projection.counts[key] for key in COUNT_KEYS},
        failure_codes=list(decision.failure_codes),
        check_requirement=check_requirement,
        logic_validation_signals=logic_validation_signals,
    )


def _load_thread_snapshot(snapshot_path: str | Path | None) -> list[dict[str, Any]]:
    if not snapshot_path:
        return []
    path = Path(snapshot_path)
    if not path.exists():
        raise FileNotFoundError(f"Snapshot file not found: {path}")
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return []
    if raw.startswith("["):
        payload = json.loads(raw)
        if not isinstance(payload, list):
            raise ValueError(f"Snapshot file must contain a JSON array or JSONL rows: {path}")
        return [row for row in payload if isinstance(row, dict)]
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError(f"Snapshot row {line_number} must be a JSON object: {path}")
        rows.append(row)
    return rows


def session_with_remote_threads(
    session: Mapping[str, Any],
    remote_threads: Iterable[Mapping[str, Any]],
    *,
    current_login: str | None = None,
) -> dict[str, Any]:
    return _session_with_remote_threads(session, remote_threads, current_login=current_login)


def _session_with_remote_threads(
    session: Mapping[str, Any],
    remote_threads: Iterable[Mapping[str, Any]],
    *,
    current_login: str | None = None,
) -> dict[str, Any]:
    merged: dict[str, Any] = dict(session)
    raw_items = session.get("items") or {}
    items = dict(raw_items) if isinstance(raw_items, Mapping) else {}
    for thread in remote_threads:
        thread_id = thread_identifier(thread)
        if not thread_id:
            continue
        item_id = f"github-thread:{thread_id}"
        existing = items.get(item_id)
        item = dict(existing) if isinstance(existing, Mapping) else {}
        item.setdefault("item_id", item_id)
        item.setdefault("item_kind", "github_thread")
        item.setdefault("source", "github")
        item["thread_id"] = thread_id
        item["origin_ref"] = thread_id
        item["path"] = thread.get("path") or item.get("path")
        item["line"] = thread.get("line") or item.get("line")
        item["url"] = thread.get("url") or item.get("url")
        item["body"] = thread.get("body") or item.get("body")
        if thread.get("first_author_login"):
            item["first_author_login"] = thread.get("first_author_login")
        if thread.get("latest_author_login"):
            item["latest_author_login"] = thread.get("latest_author_login")
        first_body = thread.get("first_body")
        if first_body is None and thread.get("comment_source") == "first":
            first_body = thread.get("body")
        first_url = thread.get("first_url") or thread.get("url")
        raw_severity = thread.get("severity")
        detected_severity = severity_evidence(
            raw_severity,
            source="github_payload",
            raw_marker=str(raw_severity).strip() if raw_severity is not None else None,
            observed_from=thread.get("url") or first_url,
        )
        if detected_severity is None and first_body is not None:
            detected_severity = extract_severity_evidence(
                first_body,
                source="github_first_comment",
                observed_from=first_url,
            )
        if detected_severity:
            apply_severity_evidence(item, detected_severity)
        elif first_scene_item_severity(item):
            item["severity"] = first_scene_item_severity(item)
        else:
            apply_severity_evidence(item, None)
        priority_evidence = review_priority_evidence(
            thread.get("review_priority") or thread.get("priority"),
            source="github_payload",
            raw_marker=str(thread.get("review_priority") or thread.get("priority") or "").strip() or None,
            observed_from=thread.get("url") or first_url,
        )
        if priority_evidence is None and first_body is not None:
            priority_evidence = extract_review_priority_evidence(
                first_body, source="github_first_comment", observed_from=first_url
            )
        if priority_evidence:
            item["review_priority_evidence"] = priority_evidence
        elif first_body is not None:
            item.pop("review_priority_evidence", None)
        is_resolved = thread_is_resolved(thread)
        is_outdated = is_stale_or_outdated_github_thread(thread)
        item["is_outdated"] = is_outdated
        if is_resolved:
            item["state"] = (
                item.get("state") if str(item.get("state") or "").lower() in GITHUB_TERMINAL_STATES else "closed"
            )
            item["status"] = "CLOSED"
            item["blocking"] = False
            item["handled"] = True
        elif _has_publish_ready_evidence(item):
            item["state"] = "publish_ready"
            item["status"] = item.get("status") or "OPEN"
            item["blocking"] = True
        elif is_outdated:
            item["state"] = "stale"
            item["status"] = "STALE"
            item["blocking"] = True
        else:
            item["state"] = "open"
            item["status"] = "OPEN"
            item["blocking"] = True
        if thread.get("viewer_replied") and thread.get("viewer_reply_url"):
            item["reply_evidence"] = {
                "reply_url": thread["viewer_reply_url"],
                "author_login": thread.get("viewer_login") or item.get("reply_author_login") or current_login,
            }
            item["reply_url"] = thread["viewer_reply_url"]
            item["reply_posted"] = True
        items[item_id] = item
    merged["items"] = items
    return merged


def _has_publish_ready_evidence(item: Mapping[str, Any]) -> bool:
    if isinstance(item.get("accepted_response"), Mapping):
        return True
    return has_content(item.get("publish_resolution"))



def _final_gate_commands(repo: str, pr_number: str) -> dict[str, str]:
    if not repo or not pr_number:
        return {}
    return {
        "address": command_templates.address(repo, pr_number),
        "publish": command_templates.publish(repo, pr_number),
        "final_gate": command_templates.final_gate(repo, pr_number),
        "batch_next": command_templates.batch_next(repo, pr_number),
        "resolve": command_templates.resolve_single(repo, pr_number),
        "resolve_batch": command_templates.resolve_batch(repo, pr_number),
        "resolve_homogeneous": command_templates.resolve_homogeneous(repo, pr_number),
        "resolve_stale": command_templates.resolve_stale(repo, pr_number),
    }


def _next_action(reason_code: str | None, *, repo: str = "", pr_number: str = "", passed: bool = False) -> str:
    if reason_code is None:
        if passed:
            return "Completion may be claimed."
        return "Status unknown: pending check results."
    if repo and pr_number:
        final_gate = f"`gh-address-cr final-gate {repo} {pr_number}`"
        if reason_code == FINAL_GATE_UNRESOLVED_REMOTE_THREADS:
            return f"Run `gh-address-cr address {repo} {pr_number} --lean`, publish accepted evidence, then rerun {final_gate}."
        if reason_code == FINAL_GATE_MISSING_REPLY_EVIDENCE:
            return f"Run `gh-address-cr agent publish {repo} {pr_number}`, then rerun {final_gate}."
        if reason_code == FINAL_GATE_PENDING_CURRENT_LOGIN_REVIEW:
            return f"Submit or dismiss pending reviews for the current GitHub login, then rerun {final_gate}."
        if reason_code == FINAL_GATE_BLOCKING_GITHUB_ITEMS:
            return f"Run `gh-address-cr agent publish {repo} {pr_number}` or `gh-address-cr address {repo} {pr_number} --lean`, then rerun {final_gate}."
        if reason_code == FINAL_GATE_BLOCKING_LOCAL_ITEMS:
            return f"Run `gh-address-cr review {repo} {pr_number}` or close/defer local items, then rerun {final_gate}."
        if reason_code == FINAL_GATE_MISSING_VALIDATION_EVIDENCE:
            return f"Run `gh-address-cr agent evidence add {repo} {pr_number} ...`, then rerun {final_gate}."
        if reason_code == FINAL_GATE_PR_CHECKS_NOT_GREEN:
            return f"Wait for PR checks to pass or fix failing checks, then rerun {final_gate}."
    if reason_code == FINAL_GATE_UNRESOLVED_REMOTE_THREADS:
        return "Resolve all remote GitHub review threads, then rerun final-gate."
    if reason_code == FINAL_GATE_MISSING_REPLY_EVIDENCE:
        return "Record durable reply evidence for terminal GitHub threads, then rerun final-gate."
    if reason_code == FINAL_GATE_PENDING_CURRENT_LOGIN_REVIEW:
        return "Submit or dismiss pending reviews for the current GitHub login, then rerun final-gate."
    if reason_code == FINAL_GATE_BLOCKING_GITHUB_ITEMS:
        return "Publish or resolve blocking GitHub review-thread items, then rerun final-gate."
    if reason_code == FINAL_GATE_BLOCKING_LOCAL_ITEMS:
        return "Close or explicitly defer blocking local items, then rerun final-gate."
    if reason_code == FINAL_GATE_MISSING_VALIDATION_EVIDENCE:
        return "Record validation evidence for terminal local findings, then rerun final-gate."
    if reason_code == FINAL_GATE_PR_CHECKS_NOT_GREEN:
        return "Wait for PR checks to pass or fix failing checks, then rerun final-gate."
    if reason_code == FINAL_GATE_LOGIC_VALIDATION_BLOCKING:
        return "Inspect final-gate diagnostics, fix blockers, then rerun final-gate."
    return "Inspect final-gate diagnostics, fix blockers, then rerun final-gate."
