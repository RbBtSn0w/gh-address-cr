from __future__ import annotations

from typing import Any

from gh_address_cr.agent.roles import TERMINAL_RESOLUTIONS


def required_evidence_for(item: dict[str, Any], role: str) -> list[str]:
    evidence = item.get("classification_evidence")
    classification = evidence.get("classification") if isinstance(evidence, dict) else None
    if classification in TERMINAL_RESOLUTIONS and classification != "fix":
        return ["note", "reply_markdown"]
    if role == "fixer":
        fields = ["note", "files", "validation_commands"]
        if item.get("item_kind") == "github_thread":
            fields.append("fix_reply")
        return fields
    return ["note", "reply_markdown"]
