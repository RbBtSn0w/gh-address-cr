"""Pure final-gate facts, projection, and policy decisions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from gh_address_cr.core import protocol_codes
from gh_address_cr.core.github_thread_state import (
    GITHUB_THREAD_TERMINAL_STATES,
    is_resolved_github_thread,
    is_terminal_github_thread,
)
from gh_address_cr.core.validation_evidence import validation_evidence_has_success

JsonDict = dict[str, Any]

RUNTIME_FACT_SCHEMA_VERSION = "1.0"
REVIEW_THREAD_OBSERVED = "review_thread_observed"
LOCAL_ITEM_OBSERVED = "local_item_observed"
PENDING_REVIEW_OBSERVED = "pending_review_observed"
CHECK_RUN_OBSERVED = "check_run_observed"
LOGIC_VALIDATION_OBSERVED = "logic_validation_observed"
SUPPORTED_FACT_KINDS = frozenset(
    {
        REVIEW_THREAD_OBSERVED,
        LOCAL_ITEM_OBSERVED,
        PENDING_REVIEW_OBSERVED,
        CHECK_RUN_OBSERVED,
        LOGIC_VALIDATION_OBSERVED,
    }
)

FINAL_GATE_UNRESOLVED_REMOTE_THREADS = "FINAL_GATE_UNRESOLVED_REMOTE_THREADS"
FINAL_GATE_MISSING_REPLY_EVIDENCE = "FINAL_GATE_MISSING_REPLY_EVIDENCE"
FINAL_GATE_PENDING_CURRENT_LOGIN_REVIEW = "FINAL_GATE_PENDING_CURRENT_LOGIN_REVIEW"
FINAL_GATE_BLOCKING_GITHUB_ITEMS = "FINAL_GATE_BLOCKING_GITHUB_ITEMS"
FINAL_GATE_BLOCKING_LOCAL_ITEMS = "FINAL_GATE_BLOCKING_LOCAL_ITEMS"
FINAL_GATE_MISSING_VALIDATION_EVIDENCE = "FINAL_GATE_MISSING_VALIDATION_EVIDENCE"
FINAL_GATE_PR_CHECKS_NOT_GREEN = "FINAL_GATE_PR_CHECKS_NOT_GREEN"
FINAL_GATE_LOGIC_VALIDATION_BLOCKING = "FINAL_GATE_LOGIC_VALIDATION_BLOCKING"

GITHUB_TERMINAL_STATES = GITHUB_THREAD_TERMINAL_STATES
LOCAL_TERMINAL_STATES = {
    "closed",
    "fixed",
    "clarified",
    "deferred",
    "rejected",
    "verified",
    "published",
}

COUNT_KEYS = (
    "unresolved_github_threads_count",
    "pending_review_count",
    "blocking_items_count",
    "blocking_github_items_count",
    "github_threads_missing_reply_count",
    "missing_validation_evidence_count",
    "blocking_local_items_count",
    "pending_current_login_review_count",
    "unresolved_remote_threads_count",
    "pr_checks_count",
    "pr_checks_failed_count",
    "pr_checks_pending_count",
    "pr_checks_not_green_count",
    "logic_validation_blocking_count",
    "logic_validation_advisory_count",
)

FAILURE_ORDER = (
    (FINAL_GATE_UNRESOLVED_REMOTE_THREADS, "unresolved_remote_threads_count", "remote_threads"),
    (FINAL_GATE_MISSING_REPLY_EVIDENCE, "github_threads_missing_reply_count", "reply_evidence"),
    (FINAL_GATE_PENDING_CURRENT_LOGIN_REVIEW, "pending_current_login_review_count", "pending_review"),
    (FINAL_GATE_BLOCKING_GITHUB_ITEMS, "blocking_github_items_count", "github_items"),
    (FINAL_GATE_BLOCKING_LOCAL_ITEMS, "blocking_local_items_count", "local_items"),
    (FINAL_GATE_MISSING_VALIDATION_EVIDENCE, "missing_validation_evidence_count", "validation_evidence"),
    (FINAL_GATE_LOGIC_VALIDATION_BLOCKING, "logic_validation_blocking_count", "logic_validation"),
    (FINAL_GATE_PR_CHECKS_NOT_GREEN, "pr_checks_not_green_count", "checks"),
)

ADAPTER_OBSERVED_AT = "1970-01-01T00:00:00Z"


@dataclass(frozen=True)
class RuntimeFact:
    schema_version: str
    fact_kind: str
    fact_id: str
    observed_at: str
    sequence: int
    payload: JsonDict

    @classmethod
    def from_dict(cls, payload: JsonDict | "RuntimeFact") -> "RuntimeFact":
        if isinstance(payload, RuntimeFact):
            return payload
        schema_version = _require_string(payload, "schema_version")
        if schema_version != RUNTIME_FACT_SCHEMA_VERSION:
            raise ValueError(f"unsupported runtime fact schema_version: {schema_version}")
        fact_kind = _require_string(payload, "fact_kind")
        if fact_kind not in SUPPORTED_FACT_KINDS:
            raise ValueError(f"unsupported runtime fact kind: {fact_kind}")
        fact_id = _require_string(payload, "fact_id")
        observed_at = _require_string(payload, "observed_at")
        _parse_observed_at(observed_at)
        sequence = _optional_int(payload, "sequence")
        fact_payload = payload.get("payload", {})
        if not isinstance(fact_payload, dict):
            raise ValueError("payload must be a JSON object")
        return cls(
            schema_version=schema_version,
            fact_kind=fact_kind,
            fact_id=fact_id,
            observed_at=observed_at,
            sequence=sequence,
            payload=dict(fact_payload),
        )

    def sort_key(self) -> tuple[datetime, int, str]:
        return (_parse_observed_at(self.observed_at), self.sequence, self.fact_id)


@dataclass(frozen=True)
class FinalGateProjection:
    counts: dict[str, int]
    unresolved_remote_threads: tuple[JsonDict, ...] = ()
    missing_reply_items: tuple[JsonDict, ...] = ()
    historical_reply_items: tuple[JsonDict, ...] = ()
    blocking_github_items: tuple[JsonDict, ...] = ()
    blocking_local_items: tuple[JsonDict, ...] = ()
    missing_validation_items: tuple[JsonDict, ...] = ()
    pending_current_login_reviews: tuple[JsonDict, ...] = ()
    failed_checks: tuple[JsonDict, ...] = ()
    pending_checks: tuple[JsonDict, ...] = ()
    logic_validation_signals: tuple[JsonDict, ...] = ()
    blocking_logic_validation_signals: tuple[JsonDict, ...] = ()
    advisory_logic_validation_signals: tuple[JsonDict, ...] = ()


@dataclass(frozen=True)
class FinalGatePolicyDecision:
    failure_codes: tuple[str, ...]
    reason_code: str | None
    waiting_on: str | None


def build_final_gate_facts(
    session: Mapping[str, Any],
    *,
    remote_threads: Iterable[Mapping[str, Any]] = (),
    pending_reviews: Iterable[Mapping[str, Any]] = (),
    current_login: str | None = None,
    check_runs: Iterable[Mapping[str, Any]] = (),
    check_requirement: str | None = None,
    logic_validation_signals: Iterable[Mapping[str, Any]] = (),
) -> tuple[RuntimeFact, ...]:
    """Adapt current final-gate inputs into replayable kernel facts."""

    facts: list[RuntimeFact] = []
    sequence = 0

    def append_fact(fact_kind: str, fact_id: str, payload: Mapping[str, Any]) -> None:
        nonlocal sequence
        facts.append(
            RuntimeFact.from_dict(
                {
                    "schema_version": RUNTIME_FACT_SCHEMA_VERSION,
                    "fact_kind": fact_kind,
                    "fact_id": fact_id,
                    "observed_at": ADAPTER_OBSERVED_AT,
                    "sequence": sequence,
                    "payload": dict(payload),
                }
            )
        )
        sequence += 1

    for item in _session_items(session):
        item_kind = _item_kind(item)
        item_id = _item_id(item) or f"session-item-{sequence}"
        payload = dict(item)
        payload["source_scope"] = "session_item"
        if current_login:
            payload.setdefault("current_login", current_login)
        if item_kind == "github_thread":
            append_fact(REVIEW_THREAD_OBSERVED, f"session-github-item:{item_id}", payload)
        elif item_kind == "local_finding":
            append_fact(LOCAL_ITEM_OBSERVED, f"session-local-item:{item_id}", payload)

    for index, thread in enumerate(remote_threads):
        payload = dict(thread)
        thread_id = thread_identifier(payload) or f"remote-row-{index}"
        payload["thread_id"] = thread_id
        payload["item_id"] = f"github-thread:{thread_id}"
        payload["source_scope"] = "remote_thread"
        append_fact(REVIEW_THREAD_OBSERVED, f"remote-thread:{thread_id}:{index}", payload)

    for index, review in enumerate(pending_reviews):
        payload = dict(review)
        if current_login:
            payload.setdefault("current_login", current_login)
        review_id = payload.get("id") or payload.get("node_id") or f"pending-review-{index}"
        append_fact(PENDING_REVIEW_OBSERVED, f"pending-review:{review_id}:{index}", payload)

    for index, check in enumerate(check_runs):
        payload = dict(check)
        if check_requirement:
            payload.setdefault("check_requirement", check_requirement)
        check_id = payload.get("id") or payload.get("name") or payload.get("context") or f"check-run-{index}"
        append_fact(CHECK_RUN_OBSERVED, f"check-run:{check_id}:{index}", payload)

    for index, signal in enumerate(logic_validation_signals):
        payload = dict(signal)
        signal_id = payload.get("signal_type") or payload.get("item_id") or f"logic-signal-{index}"
        append_fact(LOGIC_VALIDATION_OBSERVED, f"logic-validation:{signal_id}:{index}", payload)

    return tuple(facts)


def project_final_gate(
    facts: Iterable[dict[str, Any] | RuntimeFact],
    *,
    current_login: str | None = None,
    check_requirement: str | None = None,
) -> FinalGateProjection:
    parsed_facts = sort_runtime_facts(tuple(facts))
    github_items: list[JsonDict] = []
    local_items: list[JsonDict] = []
    remote_thread_rows: list[JsonDict] = []
    pending_review_rows: list[JsonDict] = []
    check_rows: list[JsonDict] = []
    logic_validation_signals: list[JsonDict] = []

    for fact in parsed_facts:
        payload = dict(fact.payload)
        if fact.fact_kind == REVIEW_THREAD_OBSERVED:
            if payload.get("source_scope") == "remote_thread":
                remote_thread_rows.append(payload)
            elif _item_kind(payload) == "github_thread":
                github_items.append(payload)
        elif fact.fact_kind == LOCAL_ITEM_OBSERVED:
            local_items.append(payload)
        elif fact.fact_kind == PENDING_REVIEW_OBSERVED:
            pending_review_rows.append(payload)
        elif fact.fact_kind == CHECK_RUN_OBSERVED:
            check_rows.append(payload)
            check_requirement = check_requirement or _string_or_none(payload.get("check_requirement"))
        elif fact.fact_kind == LOGIC_VALIDATION_OBSERVED:
            logic_validation_signals.append(payload)

    items: list[JsonDict] = [*github_items, *local_items]
    remote_by_id = {thread_id: thread for thread in remote_thread_rows if (thread_id := thread_identifier(thread))}
    unresolved_remote_threads = tuple(thread for thread in remote_thread_rows if not thread_is_resolved(thread))
    pending_current_login_reviews = tuple(
        review for review in pending_review_rows if _is_current_login_pending_review(review, current_login)
    )
    failed_checks = tuple(check for check in check_rows if _check_bucket(check) in {"fail", "cancel", "unknown"})
    pending_checks = tuple(check for check in check_rows if _check_bucket(check) == "pending")
    blocking_local_items = tuple(item for item in local_items if _is_local_blocking(item))
    blocking_github_items = tuple(item for item in github_items if _is_blocking_item(item))
    blocking_items = tuple(item for item in items if _is_blocking_item(item))
    reply_evidence_details = tuple(
        _reply_evidence_detail(item, remote_by_id)
        for item in github_items
        if _github_thread_requires_reply_evidence(item, remote_by_id) and not _has_reply_evidence(item, current_login)
    )
    missing_reply_items = tuple(
        detail for detail in reply_evidence_details if detail.get("recoverability") != "non_blocking"
    )
    historical_reply_items = tuple(
        detail for detail in reply_evidence_details if detail.get("recoverability") == "non_blocking"
    )
    missing_validation_items = tuple(
        item for item in local_items if _is_terminal_local_item(item) and not _has_validation_evidence(item)
    )
    blocking_logic_validation_signals = tuple(
        signal for signal in logic_validation_signals if signal.get("gate_effect") == "blocking"
    )
    advisory_logic_validation_signals = tuple(
        signal for signal in logic_validation_signals if signal.get("gate_effect") == "advisory"
    )

    counts = {
        "unresolved_github_threads_count": len(unresolved_remote_threads),
        "pending_review_count": len(pending_current_login_reviews),
        "blocking_items_count": len(blocking_items),
        "blocking_github_items_count": len(blocking_github_items),
        "github_threads_missing_reply_count": len(missing_reply_items),
        "missing_validation_evidence_count": len(missing_validation_items),
        "blocking_local_items_count": len(blocking_local_items),
        "pending_current_login_review_count": len(pending_current_login_reviews),
        "unresolved_remote_threads_count": len(unresolved_remote_threads),
        "pr_checks_count": len(check_rows),
        "pr_checks_failed_count": len(failed_checks),
        "pr_checks_pending_count": len(pending_checks),
        "pr_checks_not_green_count": len(failed_checks) + len(pending_checks) if check_requirement else 0,
        "logic_validation_blocking_count": len(blocking_logic_validation_signals),
        "logic_validation_advisory_count": len(advisory_logic_validation_signals),
    }
    return FinalGateProjection(
        counts={key: counts[key] for key in COUNT_KEYS},
        unresolved_remote_threads=unresolved_remote_threads,
        missing_reply_items=missing_reply_items,
        historical_reply_items=historical_reply_items,
        blocking_github_items=blocking_github_items,
        blocking_local_items=blocking_local_items,
        missing_validation_items=missing_validation_items,
        pending_current_login_reviews=pending_current_login_reviews,
        failed_checks=failed_checks,
        pending_checks=pending_checks,
        logic_validation_signals=tuple(logic_validation_signals),
        blocking_logic_validation_signals=blocking_logic_validation_signals,
        advisory_logic_validation_signals=advisory_logic_validation_signals,
    )


def evaluate_final_gate_policy(projection: FinalGateProjection) -> FinalGatePolicyDecision:
    failure_codes = tuple(code for code, count_key, _ in FAILURE_ORDER if projection.counts[count_key] > 0)
    reason_code = failure_codes[0] if failure_codes else None
    waiting_on = None
    if reason_code:
        waiting_on = next(
            (candidate_waiting_on for code, _, candidate_waiting_on in FAILURE_ORDER if code == reason_code),
            "final_gate",
        )
    return FinalGatePolicyDecision(
        failure_codes=failure_codes,
        reason_code=reason_code,
        waiting_on=waiting_on,
    )


def _session_items(session: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw_items = session.get("items") or {}
    if isinstance(raw_items, Mapping):
        return [item for item in raw_items.values() if isinstance(item, Mapping)]
    return [item for item in raw_items if isinstance(item, Mapping)]


def _item_id(item: Mapping[str, Any]) -> str | None:
    value = item.get("item_id")
    return str(value) if value else None


def _item_kind(item: Mapping[str, Any]) -> str:
    return str(item.get("item_kind") or item.get("kind") or "").lower()


def _state(item: Mapping[str, Any]) -> str:
    return str(item.get("state") or item.get("status") or "").lower()


def thread_identifier(row: Mapping[str, Any]) -> str | None:
    for key in ("thread_id", "remote_thread_id", "github_thread_id", "id", "node_id"):
        value = row.get(key)
        if value:
            return str(value)
    item_id = row.get("item_id")
    if isinstance(item_id, str) and item_id.startswith("github-thread:"):
        return item_id.split(":", 1)[1]
    return None


def thread_is_resolved(thread: Mapping[str, Any]) -> bool:
    return is_resolved_github_thread(thread)


def _github_thread_requires_reply_evidence(
    item: Mapping[str, Any],
    remote_by_id: Mapping[str, Mapping[str, Any]],
) -> bool:
    thread_id = thread_identifier(item)
    if thread_id and thread_id in remote_by_id:
        return thread_is_resolved(remote_by_id[thread_id])
    return is_terminal_github_thread(item)


def _reply_evidence_detail(
    item: Mapping[str, Any],
    remote_by_id: Mapping[str, Mapping[str, Any]],
) -> JsonDict:
    thread_id = thread_identifier(item)
    remote_thread = remote_by_id.get(thread_id or "")
    if _is_non_blocking_historical_reply_gap(item, remote_thread):
        return {
            "item_id": _item_id(item),
            "thread_id": thread_id,
            "state": _state(item),
            "reason_code": protocol_codes.CLOSED_HISTORICAL_ITEM,
            "recoverability": "non_blocking",
        }
    return {
        "item_id": _item_id(item),
        "thread_id": thread_id,
        "state": _state(item),
        "reason_code": FINAL_GATE_MISSING_REPLY_EVIDENCE,
        "recoverability": "reconcile",
    }


def _is_non_blocking_historical_reply_gap(
    item: Mapping[str, Any],
    remote_thread: Mapping[str, Any] | None,
) -> bool:
    if not bool(item.get("historical_remote_only")):
        return False
    if remote_thread is not None and not thread_is_resolved(remote_thread):
        return False
    return not _has_runtime_reply_expectation(item)


def _has_runtime_reply_expectation(item: Mapping[str, Any]) -> bool:
    if item.get("reply_posted") or has_content(item.get("reply_url")):
        return True
    if isinstance(item.get("reply_evidence"), Mapping):
        return True
    if isinstance(item.get("accepted_response"), Mapping):
        return True
    if has_content(item.get("publish_resolution")):
        return True
    if isinstance(item.get("classification_evidence"), Mapping):
        return True
    if has_content(item.get("decision")):
        return True
    return False


def _has_reply_evidence(item: Mapping[str, Any], current_login: str | None) -> bool:
    evidence = item.get("reply_evidence")
    if isinstance(evidence, Mapping):
        reply_url = evidence.get("reply_url") or evidence.get("url") or evidence.get("external_url")
        author_login = evidence.get("author_login") or evidence.get("login")
        if not author_login and isinstance(evidence.get("author"), Mapping):
            author_login = evidence["author"].get("login")
        return bool(reply_url) and _login_matches(author_login, current_login)

    reply_url = item.get("reply_url") or item.get("reply_evidence_url")
    reply_posted = item.get("reply_posted", True)
    author_login = item.get("reply_author_login")
    return bool(reply_url) and bool(reply_posted) and _login_matches(author_login, current_login)


def _login_matches(author_login: Any, current_login: str | None) -> bool:
    if not current_login or not author_login:
        return True
    return str(author_login) == current_login


def _is_current_login_pending_review(review: Mapping[str, Any], current_login: str | None) -> bool:
    if str(review.get("state") or "").upper() != "PENDING":
        return False
    if not current_login:
        return True
    return _review_login(review) == current_login


def _review_login(review: Mapping[str, Any]) -> str | None:
    if review.get("author_login"):
        return str(review["author_login"])
    if isinstance(review.get("user"), Mapping) and review["user"].get("login"):
        return str(review["user"]["login"])
    if isinstance(review.get("author"), Mapping) and review["author"].get("login"):
        return str(review["author"]["login"])
    if review.get("login"):
        return str(review["login"])
    return None


def _check_bucket(check: Mapping[str, Any]) -> str:
    bucket = str(check.get("bucket") or "").strip().lower()
    if bucket in {"pass", "pending", "fail", "skipping", "cancel"}:
        return bucket
    state = str(check.get("state") or "").strip().lower()
    if state in {"success", "passed", "completed"}:
        return "pass"
    if state in {"queued", "pending", "in_progress", "requested", "waiting"}:
        return "pending"
    if state in {"failure", "failed", "error", "timed_out", "action_required"}:
        return "fail"
    if state in {"cancelled", "canceled", "neutral"}:
        return "cancel"
    if state in {"skipped", "skipping"}:
        return "skipping"
    return "unknown"


def _is_local_blocking(item: Mapping[str, Any]) -> bool:
    if "blocking" in item:
        return bool(item["blocking"])
    return _state(item) not in LOCAL_TERMINAL_STATES


def _is_blocking_item(item: Mapping[str, Any]) -> bool:
    if _item_kind(item) == "local_finding":
        return _is_local_blocking(item)
    return bool(item.get("blocking"))


def _is_terminal_local_item(item: Mapping[str, Any]) -> bool:
    return _state(item) in LOCAL_TERMINAL_STATES


def _has_validation_evidence(item: Mapping[str, Any]) -> bool:
    for key in ("validation_evidence", "validation_commands", "validation_results"):
        if validation_evidence_has_success(item.get(key)):
            return True
    evidence = item.get("evidence")
    if isinstance(evidence, Mapping):
        return validation_evidence_has_success(evidence.get("validation")) or validation_evidence_has_success(
            evidence.get("validation_evidence")
        )
    if has_content(item.get("resolution_note")) and str(item.get("decision") or "").lower() in {
        "accept",
        "manual",
        "sync",
    }:
        return True
    return False


def has_content(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, Mapping):
        return bool(value)
    if isinstance(value, Iterable):
        return any(True for _ in value)
    return bool(value)


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _require_string(payload: Mapping[str, Any], field_name: str) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str) or value.strip() == "":
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _optional_int(payload: Mapping[str, Any], field_name: str, default: int = 0) -> int:
    value = payload.get(field_name, default)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer")
    return value


def _parse_observed_at(value: str) -> datetime:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        raise ValueError(f"observed_at must be an RFC3339 timestamp with timezone: {value}") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"observed_at must include a timezone offset: {value}")
    return parsed.astimezone(timezone.utc)


def sort_runtime_facts(
    facts: Iterable[dict[str, Any] | RuntimeFact],
) -> tuple[RuntimeFact, ...]:
    parsed_facts = tuple(RuntimeFact.from_dict(fact) for fact in facts)
    seen_keys = set()
    for fact in parsed_facts:
        sort_key = fact.sort_key()
        if sort_key in seen_keys:
            raise ValueError(f"duplicate runtime fact ordering key: {fact.fact_id}")
        seen_keys.add(sort_key)
    return tuple(sorted(parsed_facts, key=lambda fact: fact.sort_key()))
