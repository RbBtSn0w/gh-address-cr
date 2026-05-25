from __future__ import annotations


SEVERITY_RISK_NOTES = {
    "P1": "High-severity path validated with targeted regression checks.",
    "P2": "Medium-severity path validated and aligned with expected workflow.",
    "P3": "Low-severity improvement validated for non-breaking behavior.",
}

DEFAULT_FILE_SUMMARY = "updated per CR scope"

def _normalize_severity(severity: str | None) -> str | None:
    if severity in (None, ""):
        return None
    normalized = str(severity).strip().upper()
    if normalized not in SEVERITY_RISK_NOTES:
        raise SystemExit(f"Invalid severity: {severity} (expected P1/P2/P3)")
    return normalized


def _sentence_with_period(value: str) -> str:
    text = value.strip()
    if not text:
        return text
    return text if text.endswith((".", "!", "?")) else f"{text}."


def fix_reply(severity: str | None, payload: list[str], *, summary: str | None = None) -> str:
    if len(payload) < 4:
        raise SystemExit(
            "Usage for fix: generate_reply.py [--severity P1|P2|P3] <output_md> "
            "<commit_hash> <files_csv> <test_command> <test_result> [why]"
        )
    normalized_severity = _normalize_severity(severity)

    commit_hash, files_csv, test_command, test_result, *rest = payload
    why = rest[0] if rest else "Addressed the CR with minimal targeted changes and regression coverage."
    files = [item.strip() for item in files_csv.split(",") if item.strip()]
    file_summary = str(summary or DEFAULT_FILE_SUMMARY).strip()
    lines = [
        f"Fixed in `{commit_hash}`.",
        "",
        "What I changed:",
    ]
    if normalized_severity:
        lines[2:2] = [f"Severity: `{normalized_severity}`", ""]
    lines.extend([f"- `{path}`: {file_summary}" for path in files] or ["- No file list provided."])
    why_lines = ["", "Why this addresses the CR:", f"- {why}"]
    if normalized_severity:
        why_lines.append(f"- {SEVERITY_RISK_NOTES[normalized_severity]}")
    lines.extend(
        why_lines
        + [
            "",
            "Validation:",
            f"- `{test_command}`",
            f"- Result: {test_result}",
        ]
    )
    return "\n".join(lines) + "\n"


def clarify_reply(payload: list[str]) -> str:
    rationale = payload[0] if payload else "No code changes were made for this specific comment."
    return "\n".join(
        [
            "Thanks for the review.",
            "",
            "Analysis & Rationale:",
            f"- {rationale}",
            "",
            "Decision:",
            "- No code changes were made for this specific comment.",
            "",
            "If you feel this still needs an adjustment, let me know and I can follow up with a patch!",
            "",
        ]
    )


def defer_reply(payload: list[str]) -> str:
    reason = payload[0] if payload else "Marking as deferred (non-blocking for this PR)."
    return "\n".join(
        [
            "Thanks, this is valid feedback.",
            "",
            "Decision:",
            f"- Marking as deferred (non-blocking for this PR) because: {_sentence_with_period(reason)}",
            "",
            "Follow-up plan:",
            "1. Track in `<issue_or_followup_pr>`.",
            "2. Scope: `<exact scope>`.",
            "3. Risk before follow-up: `<low/medium/high + short reason>`.",
            "",
            "If you prefer, I can bring this into the current PR instead.",
            "",
        ]
    )
