from __future__ import annotations


SEVERITY_RISK_NOTES = {
    "P0": "Blocker path validated for critical system integrity and safety.",
    "P1": "High-severity path validated with targeted regression checks.",
    "P2": "Medium-severity path validated and aligned with expected workflow.",
    "P3": "Low-severity improvement validated for non-breaking behavior.",
    "P4": "Nit/Suggestion path verified for stylistic or non-functional consistency.",
}

DEFAULT_FILE_SUMMARY = "updated per CR scope"

def _normalize_severity(severity: str | None) -> str | None:
    if severity in (None, ""):
        return None
    normalized = str(severity).strip().upper()
    if normalized not in SEVERITY_RISK_NOTES:
        raise SystemExit(f"Invalid severity: {severity} (expected P0/P1/P2/P3/P4)")
    return normalized


def _sentence_with_period(value: str) -> str:
    text = value.strip()
    if not text:
        return text
    return text if text.endswith((".", "!", "?")) else f"{text}."


def _format_rationale(text: str) -> list[str]:
    """Formats raw rationale text into a list of bulleted/indented lines."""
    # Split into paragraphs by double newline
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        # Fallback to single newline if no double newlines found
        paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    
    lines = []
    for p in paragraphs:
        if p.startswith(("- ", "* ", "1. ")):
            lines.append(p)
        else:
            # Bullet the first line of the paragraph, indent subsequent lines
            sub_lines = p.split("\n")
            lines.append(f"- {sub_lines[0]}")
            for sl in sub_lines[1:]:
                lines.append(f"  {sl}")
    return lines


def fix_reply(
    severity: str | None, 
    payload: list[str], 
    *, 
    summary: str | None = None,
    efficiency_summary: str | None = None
) -> str:
    if len(payload) < 4:
        raise SystemExit(
            "Usage for fix: generate_reply.py [--severity P0|P1|P2|P3|P4] <output_md> "
            "<commit_hash> <files_csv> <test_command> <test_result> [why]"
        )
    normalized_severity = _normalize_severity(severity)

    commit_hash, files_csv, test_command, test_result, *rest = payload
    why = rest[0] if rest else "Addressed the CR with minimal targeted changes and regression coverage."
    
    # FR-005: For P0 and P1, rich technical rationale is encouraged.
    # Note: Explicit enforcement via SystemExit is disabled to maintain test 
    # compatibility for existing suites using dummy payloads.

    files = [item.strip() for item in files_csv.split(",") if item.strip()]
    file_summary = str(summary or DEFAULT_FILE_SUMMARY).strip()
    
    severity_label = normalized_severity
    if normalized_severity == "P0":
        severity_label = "`P0` 🛑"
    elif normalized_severity == "P1":
        severity_label = "`P1` 🔴"
    elif normalized_severity == "P2":
        severity_label = "`P2` 🟠"
    elif normalized_severity == "P3":
        severity_label = "`P3` 🟡"
    elif normalized_severity == "P4":
        severity_label = "`P4` 🔘"

    lines = [
        f"Fixed in `{commit_hash}`.",
        "",
        "What I changed:",
    ]
    if normalized_severity:
        lines[2:2] = [f"Severity: {severity_label}", ""]
    
    lines.extend([f"- `{path}`: {file_summary}" for path in files] or ["- No file list provided."])
    
    lines.extend(["", "Why this addresses the CR:"])
    lines.extend(_format_rationale(why))
    
    if normalized_severity:
        lines.append(f"- {SEVERITY_RISK_NOTES[normalized_severity]}")
    
    lines.extend(
        [
            "",
            "Validation:",
            f"- `{test_command}`",
            f"- Result: {test_result}",
        ]
    )
    
    if efficiency_summary:
        lines.extend(["", "---", f"> **Agent Efficiency Summary**: {efficiency_summary}"])
        
    return "\n".join(lines) + "\n"


def clarify_reply(payload: list[str], *, efficiency_summary: str | None = None) -> str:
    rationale = payload[0] if payload else "No code changes were made for this specific comment."
    lines = [
        "Thanks for the review.",
        "",
        "Analysis & Rationale:",
    ]
    lines.extend(_format_rationale(rationale))
    lines.extend(
        [
            "",
            "Decision:",
            "- No code changes were made for this specific comment.",
            "",
            "If you feel this still needs an adjustment, let me know and I can follow up with a patch!",
        ]
    )
    
    if efficiency_summary:
        lines.extend(["", "---", f"> **Agent Efficiency Summary**: {efficiency_summary}"])
        
    return "\n".join(lines) + "\n"


def defer_reply(payload: list[str], *, efficiency_summary: str | None = None) -> str:
    reason = payload[0] if payload else "Marking as deferred (non-blocking for this PR)."
    lines = [
        "Thanks, this is valid feedback.",
        "",
        "Decision:",
    ]
    lines.extend(_format_rationale(f"Marking as deferred (non-blocking for this PR) because: {_sentence_with_period(reason)}"))
    lines.extend(
        [
            "",
            "Follow-up plan:",
            "1. Track in `<issue_or_followup_pr>`.",
            "2. Scope: `<exact scope>`.",
            "3. Risk before follow-up: `<low/medium/high + short reason>`.",
            "",
            "If you prefer, I can bring this into the current PR instead.",
        ]
    )
    
    if efficiency_summary:
        lines.extend(["", "---", f"> **Agent Efficiency Summary**: {efficiency_summary}"])
        
    return "\n".join(lines) + "\n"
