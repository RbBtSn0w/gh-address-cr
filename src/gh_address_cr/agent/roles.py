from __future__ import annotations

from enum import Enum


class AgentRole(str, Enum):
    COORDINATOR = "coordinator"
    REVIEW_PRODUCER = "review_producer"
    TRIAGE = "triage"
    FIXER = "fixer"
    VERIFIER = "verifier"
    PUBLISHER = "publisher"
    GATEKEEPER = "gatekeeper"

    @classmethod
    def parse(cls, value: "AgentRole | str") -> "AgentRole":
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value))
        except ValueError as exc:
            raise ValueError(f"unsupported agent role: {value}") from exc


AI_AGENT_ROLES = frozenset(
    {
        AgentRole.REVIEW_PRODUCER,
        AgentRole.TRIAGE,
        AgentRole.FIXER,
        AgentRole.VERIFIER,
    }
)
DETERMINISTIC_ROLES = frozenset({AgentRole.COORDINATOR, AgentRole.PUBLISHER, AgentRole.GATEKEEPER})
TERMINAL_RESOLUTIONS = frozenset({"fix", "clarify", "defer", "reject"})
MUTATING_RESOLUTIONS = frozenset({"fix"})
GITHUB_SIDE_EFFECT_FORBIDDEN_ACTIONS = ("post_github_reply", "resolve_github_thread")


def parse_role(value: AgentRole | str) -> AgentRole:
    return AgentRole.parse(value)


def is_ai_agent_role(value: AgentRole | str) -> bool:
    return parse_role(value) in AI_AGENT_ROLES


def is_mutating_resolution(value: str) -> bool:
    return value in MUTATING_RESOLUTIONS
