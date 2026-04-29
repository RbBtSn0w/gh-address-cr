from __future__ import annotations


SEVERITY_RISK_NOTES = {
    "P1": "High-severity path validated with targeted regression checks.",
    "P2": "Medium-severity path validated and behavior aligned with expected workflow.",
    "P3": "Low-severity improvement validated for non-breaking behavior.",
}


def fix_reply(severity: str, payload: list[str]) -> str:
    if len(payload) < 4:
        raise SystemExit(
            "Usage for fix: generate_reply.py [--severity P1|P2|P3] <output_md> "
            "<commit_hash> <files_csv> <test_command> <test_result> [why]"
        )
    normalized_severity = severity.upper()
    if normalized_severity not in SEVERITY_RISK_NOTES:
        raise SystemExit(f"Invalid severity: {severity} (expected P1/P2/P3)")

    commit_hash, files_csv, test_command, test_result, *rest = payload
    why = rest[0] if rest else "Addressed the CR with minimal targeted changes and regression coverage."
    files = [item.strip() for item in files_csv.split(",") if item.strip()]
    lines = [
        f"Fixed in `{commit_hash}`.",
        "",
        f"Severity: `{normalized_severity}`",
        "",
        "What I changed:",
    ]
    lines.extend([f"- `{path}`: updated per CR scope" for path in files] or ["- No file list provided."])
    lines.extend(
        [
            "",
            "Why this addresses the CR:",
            f"- {why}",
            f"- {SEVERITY_RISK_NOTES[normalized_severity]}",
            "",
            "Validation:",
            f"- `{test_command}`",
            f"- Result: {test_result}",
            "",
            "If anything still looks off, I can follow up with a focused patch.",
        ]
    )
    return "\n".join(lines) + "\n"
