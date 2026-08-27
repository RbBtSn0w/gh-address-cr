from __future__ import annotations

SEVERITY_SIGNAL_LABELS = {
    "P0": "`P0`",
    "P1": "`P1`",
    "P2": "`P2`",
    "P3": "`P3`",
    "P4": "`P4`",
}

VALID_REVIEW_PRIORITIES = {"high", "medium", "low"}


def _normalize_severity(severity: str | None) -> str | None:
    if severity in (None, ""):
        return None
    normalized = str(severity).strip().upper()
    if normalized not in SEVERITY_SIGNAL_LABELS:
        raise SystemExit(f"Invalid severity: {severity} (expected P0/P1/P2/P3/P4)")
    return normalized


def _sentence_with_period(value: str) -> str:
    text = value.strip()
    if not text:
        return text
    return text if text.endswith((".", "!", "?")) else f"{text}."


def _normalize_review_priority(priority: str | None) -> str | None:
    if priority in (None, ""):
        return None
    normalized = str(priority).strip().lower()
    if normalized not in VALID_REVIEW_PRIORITIES:
        raise SystemExit(f"Invalid reviewer priority: {priority} (expected high/medium/low)")
    return normalized


def _review_priority_label(priority: str) -> str:
    return f"{priority.title()} Priority"


def _review_signal_label(severity: str | None, review_priority: str | None) -> str | None:
    if severity is not None:
        return SEVERITY_SIGNAL_LABELS.get(severity, "`unknown`")
    if review_priority:
        return f"`{_review_priority_label(review_priority)}`"
    return None


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
    review_priority: str | None = None,
    review_priority_note: str | None = None,
) -> str:
    if len(payload) < 4:
        raise SystemExit(
            "Usage for fix reply: gh-address-cr agent submit <repo> <pr> --input <action-response.json> "
            "or gh-address-cr submit-action <action-request.json> --resolution fix "
            "<commit_hash> <files_csv> <test_command> <test_result> [why]"
        )
    normalized_severity = _normalize_severity(severity)
    normalized_review_priority = _normalize_review_priority(review_priority)

    commit_hash, files_csv, test_command, test_result, *rest = payload
    why = rest[0] if rest else "Addressed the CR with minimal targeted changes and regression coverage."

    # FR-005: For P0 and P1, rich technical rationale is encouraged.
    # Explicit enforcement via SystemExit stays disabled so dummy test payloads
    # can still exercise formatting paths.

    files = [item.strip() for item in files_csv.split(",") if item.strip()]
    file_summary = str(summary).strip() if summary else None

    review_signal = _review_signal_label(normalized_severity, normalized_review_priority)

    display_commit = _display_commit_hash(commit_hash)
    lines = [f"Addressed in `{display_commit}`.", ""]
    if review_signal:
        lines.extend([f"Review signal: {review_signal}", ""])

    lines.extend(
        [f"- `{path}`: {file_summary}" if file_summary else f"- `{path}`" for path in files]
        or ["- No file list provided."]
    )

    rationale_lines = _format_rationale(why)
    if len(rationale_lines) == 1 and rationale_lines[0].startswith("- "):
        lines.append(f"- Why: {rationale_lines[0][2:]}")
    else:
        lines.append("- Why:")
        lines.extend(f"  {line}" for line in rationale_lines)

    if not normalized_severity and normalized_review_priority:
        priority_note = str(review_priority_note or "").strip()
        if priority_note:
            lines.append(f"- Review note: {priority_note}")

    lines.append(f"- Validation: `{test_command}` {test_result}")

    return "\n".join(lines) + "\n"


def _display_commit_hash(commit_hash: str) -> str:
    normalized = commit_hash.strip()
    if len(normalized) > 12 and all(ch in "0123456789abcdefABCDEF" for ch in normalized):
        return normalized[:7]
    return normalized


def clarify_reply(payload: list[str]) -> str:
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

    return "\n".join(lines) + "\n"


def defer_reply(payload: list[str]) -> str:
    reason = payload[0] if payload else "Marking as deferred (non-blocking for this PR)."
    lines = [
        "Thanks, this is valid feedback.",
        "",
        "Decision:",
    ]
    lines.extend(
        _format_rationale(f"Marking as deferred (non-blocking for this PR) because: {_sentence_with_period(reason)}")
    )
    lines.extend(
        [
            "",
            "If you prefer, I can bring this into the current PR instead.",
        ]
    )

    return "\n".join(lines) + "\n"
