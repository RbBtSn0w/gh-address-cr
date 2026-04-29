#!/usr/bin/env python3
from __future__ import annotations
import argparse
from pathlib import Path


SEVERITY_RISK_NOTES = {
    "P1": "High-severity path validated with targeted regression checks.",
    "P2": "Medium-severity path validated and behavior aligned with expected workflow.",
    "P3": "Low-severity improvement validated for non-breaking behavior.",
}


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a Markdown reply template for a CR item.")
    parser.add_argument("--severity", default="P2", help="P1, P2, or P3 for fix mode.")
    parser.add_argument("--mode", default="fix", choices=["fix", "clarify", "defer"])
    parser.add_argument("output_md")
    parser.add_argument("args", nargs="*")
    return parser.parse_args()


def fix_reply(severity: str, payload: list[str]) -> str:
    if len(payload) < 4:
        raise SystemExit(
            "Usage for fix: generate_reply.py [--severity P1|P2|P3] <output_md> <commit_hash> <files_csv> <test_command> <test_result> [why]"
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
    rationale = payload[0] if payload else "Marking as deferred (non-blocking for this PR)."
    return "\n".join(
        [
            "Thanks, this is valid feedback.",
            "",
            "Decision:",
            f"- Marking as deferred (non-blocking for this PR) because: {rationale}",
            "",
            "Follow-up plan:",
            "1. Track in follow-up issue/PR.",
            "2. Risk before follow-up: Low.",
            "",
            "If you prefer, I can bring this into the current PR instead.",
            "",
        ]
    )


def main() -> int:
    args = parse_args()
    output_path = Path(args.output_md)
    if args.mode == "fix":
        content = fix_reply(args.severity, args.args)
    elif args.mode == "clarify":
        content = clarify_reply(args.args)
    else:
        content = defer_reply(args.args)

    write_text(output_path, content)
    print(f"Wrote reply template ({args.mode} mode): {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
