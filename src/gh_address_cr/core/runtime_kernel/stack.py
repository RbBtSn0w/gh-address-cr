"""Pure GitHub stacked-PR facts, projections, and policy decisions."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Mapping

from gh_address_cr.core import protocol_codes

STACK_OBSERVATION_SCHEMA_VERSION = "stack_observation.v1"
STACK_CONTEXT_SCHEMA_VERSION = "stack_context.v1"
STACK_AVAILABILITIES = frozenset({"absent", "present", "unavailable", "invalid"})
PULL_REQUEST_STATES = frozenset({"OPEN", "CLOSED", "MERGED"})
REVISION_BINDING_SCHEMA_VERSION = "revision_binding.v1"
STACK_MANAGEMENT_ACTIONS = (
    "create_stack",
    "checkout_stack",
    "rebase_stack",
    "push_stack",
    "modify_stack",
    "unstack",
    "queue_stack",
    "merge_stack",
)

JsonDict = dict[str, Any]


@dataclass(frozen=True)
class PullRequestMemberFact:
    position: int
    pr_number: str
    state: str
    is_draft: bool
    base_ref_name: str
    head_ref_name: str
    head_oid: str
    merge_queue_state: str | None = None

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "PullRequestMemberFact":
        position = int(payload.get("position") or 0)
        pr_number = str(payload.get("pr_number") or "").strip()
        state = str(payload.get("state") or "").upper()
        base_ref_name = str(payload.get("base_ref_name") or "").strip()
        head_ref_name = str(payload.get("head_ref_name") or "").strip()
        head_oid = str(payload.get("head_oid") or "").strip()
        if position < 1:
            raise ValueError("invalid_position")
        if not pr_number.isdigit() or int(pr_number) < 1:
            raise ValueError("invalid_pr_number")
        if state not in PULL_REQUEST_STATES:
            raise ValueError("invalid_member_state")
        if not base_ref_name:
            raise ValueError("missing_base_ref")
        if not head_ref_name:
            raise ValueError("missing_head_ref")
        if not head_oid:
            raise ValueError("missing_head_oid")
        queue_state = payload.get("merge_queue_state")
        return cls(
            position=position,
            pr_number=pr_number,
            state=state,
            is_draft=bool(payload.get("is_draft")),
            base_ref_name=base_ref_name,
            head_ref_name=head_ref_name,
            head_oid=head_oid,
            merge_queue_state=str(queue_state).lower() if queue_state else None,
        )

    def to_dict(self) -> JsonDict:
        return {
            "position": self.position,
            "pr_number": self.pr_number,
            "state": self.state,
            "is_draft": self.is_draft,
            "base_ref_name": self.base_ref_name,
            "head_ref_name": self.head_ref_name,
            "head_oid": self.head_oid,
            "merge_queue_state": self.merge_queue_state,
        }


@dataclass(frozen=True)
class StackContext:
    availability: str
    repo: str
    selected_pr_number: str
    observed_at: str
    stack_node_id: str | None = None
    stack_number: int | None = None
    trunk_ref_name: str | None = None
    reported_size: int | None = None
    selected_position: int | None = None
    members: tuple[PullRequestMemberFact, ...] = ()
    selected_pr: PullRequestMemberFact | None = None
    topology_fingerprint: str | None = None
    diagnostic_code: str | None = None
    invalid_invariant: str | None = None

    @property
    def schema_version(self) -> str:
        return STACK_CONTEXT_SCHEMA_VERSION

    def to_dict(self) -> JsonDict:
        payload: JsonDict = {
            "schema_version": self.schema_version,
            "availability": self.availability,
            "observed_at": self.observed_at,
        }
        if self.topology_fingerprint:
            payload["topology_fingerprint"] = self.topology_fingerprint
        if self.selected_pr:
            payload["selected_pr"] = self.selected_pr.to_dict()
        if self.availability == "present":
            payload["stack"] = {
                "number": self.stack_number,
                "trunk_ref_name": self.trunk_ref_name,
                "size": self.reported_size,
                "selected_position": self.selected_position,
                "members": [member.to_dict() for member in self.members],
            }
        if self.diagnostic_code:
            payload["diagnostic"] = {
                "reason_code": self.diagnostic_code,
                **({"invariant": self.invalid_invariant} if self.invalid_invariant else {}),
            }
        return payload


@dataclass(frozen=True)
class StackSegmentProjection:
    merged_prefix: tuple[PullRequestMemberFact, ...]
    included_members: tuple[PullRequestMemberFact, ...]
    excluded_upper_members: tuple[PullRequestMemberFact, ...]


@dataclass(frozen=True)
class StackContextPolicyDecision:
    allowed: bool
    completion_scope: str
    covered_pr_numbers: tuple[str, ...] = ()
    reason_code: str | None = None
    waiting_on: str | None = None


def project_stack_context(payload: Mapping[str, Any]) -> StackContext:
    availability = str(payload.get("availability") or "invalid").lower()
    repo = str(payload.get("repo") or "").strip()
    selected_pr_number = str(payload.get("selected_pr_number") or "").strip()
    observed_at = str(payload.get("observed_at") or "").strip()
    if payload.get("schema_version") != STACK_OBSERVATION_SCHEMA_VERSION:
        return _invalid_context(repo, selected_pr_number, observed_at, "unsupported_schema")
    if availability not in STACK_AVAILABILITIES:
        return _invalid_context(repo, selected_pr_number, observed_at, "invalid_availability")
    if availability == "unavailable":
        return StackContext(
            availability="unavailable",
            repo=repo,
            selected_pr_number=selected_pr_number,
            observed_at=observed_at,
            diagnostic_code=protocol_codes.STACK_CONTEXT_UNAVAILABLE,
        )
    if availability == "invalid":
        return _invalid_context(
            repo,
            selected_pr_number,
            observed_at,
            str(payload.get("invalid_invariant") or "upstream_invalid"),
        )
    if availability == "absent":
        try:
            selected_pr = PullRequestMemberFact.from_dict(payload["selected_pr"])
        except (KeyError, TypeError, ValueError) as exc:
            return _invalid_context(repo, selected_pr_number, observed_at, str(exc))
        if selected_pr.pr_number != selected_pr_number:
            return _invalid_context(repo, selected_pr_number, observed_at, "selected_member_mismatch")
        return StackContext(
            availability="absent",
            repo=repo,
            selected_pr_number=selected_pr_number,
            observed_at=observed_at,
            selected_pr=selected_pr,
            topology_fingerprint=_fingerprint_absent(repo, selected_pr),
        )

    raw_members = payload.get("members")
    if not isinstance(raw_members, list):
        return _invalid_context(repo, selected_pr_number, observed_at, "members_not_array")
    reported_size = _optional_int(payload.get("reported_size"))
    if reported_size != len(raw_members):
        return _invalid_context(repo, selected_pr_number, observed_at, "reported_size_mismatch")
    try:
        members = tuple(sorted((PullRequestMemberFact.from_dict(row) for row in raw_members), key=lambda row: row.position))
    except (TypeError, ValueError) as exc:
        return _invalid_context(repo, selected_pr_number, observed_at, str(exc))
    invariant = _stack_invariant_failure(
        members,
        selected_pr_number=selected_pr_number,
        trunk_ref_name=str(payload.get("trunk_ref_name") or "").strip(),
    )
    if invariant:
        return _invalid_context(repo, selected_pr_number, observed_at, invariant)
    selected_pr = next(member for member in members if member.pr_number == selected_pr_number)
    stack_node_id = str(payload.get("stack_node_id") or "").strip()
    stack_number = _optional_int(payload.get("stack_number"))
    trunk_ref_name = str(payload.get("trunk_ref_name") or "").strip()
    if not stack_node_id:
        return _invalid_context(repo, selected_pr_number, observed_at, "missing_stack_node_id")
    if stack_number is None or stack_number < 1:
        return _invalid_context(repo, selected_pr_number, observed_at, "invalid_stack_number")
    context = StackContext(
        availability="present",
        repo=repo,
        selected_pr_number=selected_pr_number,
        observed_at=observed_at,
        stack_node_id=stack_node_id,
        stack_number=stack_number,
        trunk_ref_name=trunk_ref_name,
        reported_size=reported_size,
        selected_position=selected_pr.position,
        members=members,
        selected_pr=selected_pr,
    )
    return StackContext(**{**context.__dict__, "topology_fingerprint": _fingerprint_present(context)})


def unavailable_stack_context(repo: str, pr_number: str, *, observed_at: str | None = None) -> StackContext:
    """Return the bounded fail-open projection for a failed preview-only read."""
    timestamp = observed_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return project_stack_context(
        {
            "schema_version": STACK_OBSERVATION_SCHEMA_VERSION,
            "availability": "unavailable",
            "repo": repo,
            "selected_pr_number": str(pr_number),
            "observed_at": timestamp,
            "diagnostic_code": protocol_codes.STACK_CONTEXT_UNAVAILABLE,
            "members": [],
        }
    )


def stack_context_for_member(context: StackContext, pr_number: str) -> StackContext:
    """Select one member from an already coherent stack observation."""
    target = str(pr_number)
    if context.availability != "present":
        return context
    selected = next((member for member in context.members if member.pr_number == target), None)
    if selected is None:
        return _invalid_context(context.repo, target, context.observed_at, "selected_member_missing")
    return replace(
        context,
        selected_pr_number=target,
        selected_position=selected.position,
        selected_pr=selected,
    )


def project_stack_segment(context: StackContext) -> StackSegmentProjection:
    if context.availability == "absent" and context.selected_pr:
        return StackSegmentProjection((), (context.selected_pr,), ())
    if context.availability != "present" or context.selected_position is None:
        return StackSegmentProjection((), (), ())
    merged_prefix = tuple(member for member in context.members if member.state == "MERGED")
    active = tuple(member for member in context.members if member.state != "MERGED")
    included = tuple(member for member in active if member.position <= context.selected_position)
    excluded = tuple(member for member in active if member.position > context.selected_position)
    return StackSegmentProjection(merged_prefix, included, excluded)


def evaluate_stack_context_policy(
    context: StackContext,
    *,
    explicit_stack: bool,
) -> StackContextPolicyDecision:
    scope = "stack_segment" if explicit_stack else "pull_request"
    if context.availability in {"unavailable", "invalid"}:
        if not explicit_stack:
            return StackContextPolicyDecision(True, scope)
        return StackContextPolicyDecision(
            False,
            scope,
            reason_code=context.diagnostic_code,
            waiting_on="stack_context",
        )
    segment = project_stack_segment(context)
    covered = tuple(member.pr_number for member in segment.included_members)
    if not explicit_stack:
        covered = (context.selected_pr_number,) if context.selected_pr_number else ()
    return StackContextPolicyDecision(True, scope, covered_pr_numbers=covered)


def revision_binding_for_context(context: StackContext) -> JsonDict | None:
    """Return the runtime-owned revision identity for a selected PR observation."""
    selected = context.selected_pr
    if context.availability != "present" or selected is None or context.stack_number is None:
        return None
    return {
        "schema_version": REVISION_BINDING_SCHEMA_VERSION,
        "pr_number": selected.pr_number,
        "head_oid": selected.head_oid,
        "stack_number": context.stack_number,
        "stack_position": selected.position,
        "topology_fingerprint": context.topology_fingerprint,
        "captured_at": context.observed_at,
    }


def repository_context_for_stack(
    repo: str,
    pr_number: str,
    observed_context: Mapping[str, Any] | None,
) -> JsonDict:
    """Build additive ActionRequest context from a non-authoritative observation."""
    payload: JsonDict = {"repo": repo, "pr_number": str(pr_number)}
    if not isinstance(observed_context, Mapping):
        return payload
    if observed_context.get("schema_version") == STACK_CONTEXT_SCHEMA_VERSION:
        context_payload = dict(observed_context)
        context = stack_context_from_serialized(context_payload, repo=repo, pr_number=str(pr_number))
    else:
        context = project_stack_context(observed_context)
        context_payload = context.to_dict()
    payload["stack_context"] = context_payload
    binding = revision_binding_for_context(context)
    if binding is not None:
        payload["revision_binding"] = binding
    return payload


def compare_revision_binding(binding: Mapping[str, Any] | None, current: StackContext) -> str | None:
    """Return a stable rejection code when a request/evidence binding is no longer current."""
    if not isinstance(binding, Mapping):
        return protocol_codes.FINAL_GATE_UNBOUND_REVISION_EVIDENCE
    if str(binding.get("pr_number") or "") != current.selected_pr_number:
        return protocol_codes.STACK_ACTION_CONTEXT_MISMATCH
    if current.availability == "invalid":
        return protocol_codes.STACK_CONTEXT_INVALID
    if current.availability == "unavailable":
        return protocol_codes.STACK_CONTEXT_UNAVAILABLE
    if current.availability == "absent":
        return protocol_codes.STALE_REQUEST_CONTEXT
    expected = revision_binding_for_context(current)
    if expected is None:
        return protocol_codes.STACK_CONTEXT_UNAVAILABLE
    fields = ("schema_version", "pr_number", "head_oid", "stack_number", "stack_position", "topology_fingerprint")
    if any(binding.get(field) != expected.get(field) for field in fields):
        return protocol_codes.STALE_REQUEST_CONTEXT
    return None


def stack_context_from_serialized(payload: Mapping[str, Any], *, repo: str, pr_number: str) -> StackContext:
    availability = str(payload.get("availability") or "invalid")
    selected = payload.get("selected_pr")
    stack_payload = payload.get("stack")
    stack: Mapping[str, Any] = stack_payload if isinstance(stack_payload, Mapping) else {}
    observation: JsonDict = {
        "schema_version": STACK_OBSERVATION_SCHEMA_VERSION,
        "availability": availability,
        "repo": repo,
        "selected_pr_number": pr_number,
        "observed_at": str(payload.get("observed_at") or ""),
    }
    if availability == "present":
        observation.update(
            {
                "stack_node_id": "serialized-context",
                "stack_number": stack.get("number"),
                "trunk_ref_name": stack.get("trunk_ref_name"),
                "reported_size": stack.get("size"),
                "members": stack.get("members"),
            }
        )
    elif selected is not None:
        observation["selected_pr"] = selected
    context = project_stack_context(observation)
    if availability == "present" and payload.get("topology_fingerprint"):
        context = StackContext(**{**context.__dict__, "topology_fingerprint": payload["topology_fingerprint"]})
    return context


def _stack_invariant_failure(
    members: tuple[PullRequestMemberFact, ...],
    *,
    selected_pr_number: str,
    trunk_ref_name: str,
) -> str | None:
    if len(members) < 2:
        return "stack_requires_two_members"
    if [member.position for member in members] != list(range(1, len(members) + 1)):
        return "positions_not_contiguous"
    if len({member.pr_number for member in members}) != len(members):
        return "duplicate_member_pr_number"
    if sum(member.pr_number == selected_pr_number for member in members) != 1:
        return "selected_member_missing_or_duplicate"
    first_unmerged = next((index for index, member in enumerate(members) if member.state != "MERGED"), len(members))
    if any(member.state == "MERGED" for member in members[first_unmerged:]):
        return "merged_members_not_prefix"
    if first_unmerged < len(members):
        if members[first_unmerged].base_ref_name != trunk_ref_name:
            return "lowest_unmerged_base_mismatch"
        for lower, upper in zip(members[first_unmerged:], members[first_unmerged + 1 :], strict=False):
            if upper.base_ref_name != lower.head_ref_name:
                return "dependency_chain_mismatch"
    return None


def _invalid_context(repo: str, selected_pr_number: str, observed_at: str, invariant: str) -> StackContext:
    return StackContext(
        availability="invalid",
        repo=repo,
        selected_pr_number=selected_pr_number,
        observed_at=observed_at,
        diagnostic_code=protocol_codes.STACK_CONTEXT_INVALID,
        invalid_invariant=invariant,
    )


def _fingerprint_present(context: StackContext) -> str:
    return _hash_payload(
        {
            "repo": context.repo,
            "stack_node_id": context.stack_node_id,
            "stack_number": context.stack_number,
            "trunk_ref_name": context.trunk_ref_name,
            "reported_size": context.reported_size,
            "members": [member.to_dict() for member in context.members],
        }
    )


def _fingerprint_absent(repo: str, selected_pr: PullRequestMemberFact) -> str:
    return _hash_payload({"repo": repo, "selected_pr": selected_pr.to_dict()})


def _hash_payload(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _optional_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
