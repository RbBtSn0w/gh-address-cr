#!/usr/bin/env python3
from __future__ import annotations
import argparse
import hashlib
import json
import re
import shlex
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote_plus

from python_common import (
    audit_event,
    audit_summary_file,
    gh_read_json,
    gh_write_cmd,
    github_pr_cache_file,
    last_machine_summary_file,
    session_file,
    sha256_of_file,
)


DEFAULT_TARGET_REPO = "RbBtSn0w/gh-address-cr-skill"
DEFAULT_COOLDOWN_HOURS = 24
DEFAULT_FEEDBACK_PR = "feedback"
DEFAULT_FEEDBACK_SEARCH_PAGE_SIZE = 10
FINGERPRINT_MARKER_PREFIX = "gh-address-cr-feedback-fingerprint:"
REPO_ROOT = Path(__file__).resolve().parents[2]
PR_URL_RE = re.compile(
    r"^https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/pull/(?P<pr_number>\d+)(?:[/?#].*)?$"
)
REPO_SLUG_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
VALID_CATEGORIES = (
    "workflow-gap",
    "tooling-bug",
    "docs-gap",
    "integration-gap",
    "other",
)
POSIX_ABSOLUTE_PATH_RE = re.compile(r"(?P<prefix>^|[\s([{\"'<=,`])(?P<path>/[^\s`\"')\]}>;,]+)")
WINDOWS_ABSOLUTE_PATH_RE = re.compile(r"(?P<prefix>^|[\s([{\"'<=,`])(?P<path>[A-Za-z]:\\[^\s`\"')\]}>;,]+)")
FILE_URI_RE = re.compile(r"(?P<prefix>^|[\s([{\"'<=,`])(?P<scheme>file://)(?P<path>/[^\s`\"')\]}>;,]+)")
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
TOKEN_PATTERNS = (
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._-]{16,}\b", re.IGNORECASE),
)
SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b((?:[A-Za-z0-9]+[_-])*token|secret|password|api[_-]?key)\b([=: ]+)([^\s,;&]+)"
)
PRIVATE_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(username|user|email|hostname|host|machine|machine_name|computer|computer_name)\b([=: ]+)([^\s,;&]+)"
)
VERSION_RE = re.compile(r"^## \[(?P<version>[^\]]+)\]", re.MULTILINE)
SENSITIVE_VALUE_FLAGS = {
    "--token",
    "--secret",
    "--password",
    "--api-key",
    "--api_key",
    "--email",
    "--user",
    "--username",
    "--host",
    "--hostname",
    "--machine",
    "--machine-name",
    "--computer",
    "--computer-name",
}


def normalize_title(value: str) -> str:
    title = value.strip()
    if not title:
        raise SystemExit("--title must not be empty.")
    if not title.startswith("[AI Feedback] "):
        title = f"[AI Feedback] {title}"
    return sanitize_text(title)


def normalize_text(value: str, *, field_name: str) -> str:
    text = value.strip()
    if not text:
        raise SystemExit(f"{field_name} must not be empty.")
    return text


def is_windows_absolute_path(value: str) -> bool:
    return bool(re.match(r"^[A-Za-z]:[\\/]", value))


def compact_absolute_path(value: str) -> str:
    if not value:
        return value
    if not (value.startswith("/") or is_windows_absolute_path(value)):
        return value
    normalized = value.replace("\\", "/")
    parts = [part for part in normalized.split("/") if part]
    if parts and re.match(r"^[A-Za-z]:$", parts[0]):
        parts = parts[1:]
    if len(parts) >= 2 and parts[0] in {"Users", "home"}:
        parts = parts[2:]
    elif len(parts) >= 3 and parts[:2] == ["var", "home"]:
        parts = parts[3:]
    elif len(parts) >= 4 and parts[0] == "mnt" and re.match(r"^[A-Za-z]$", parts[1]) and parts[2] in {"Users", "home"}:
        parts = parts[4:]
    elif len(parts) >= 5 and parts[0] == "mnt" and re.match(r"^[A-Za-z]$", parts[1]) and parts[2:4] == ["var", "home"]:
        parts = parts[5:]
    if not parts:
        return "..."
    return f".../{'/'.join(parts[-3:])}"


def redact_secret_token(value: str) -> str:
    redacted = value
    redacted = EMAIL_RE.sub("[redacted-email]", redacted)
    for pattern in TOKEN_PATTERNS:
        redacted = pattern.sub("[redacted-token]", redacted)
    redacted = SECRET_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}{match.group(2)}[redacted-token]", redacted)
    redacted = PRIVATE_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}{match.group(2)}[redacted]", redacted)
    return redacted


def sanitize_text(value: str) -> str:
    sanitized = redact_secret_token(value)
    sanitized = FILE_URI_RE.sub(
        lambda match: f"{match.group('prefix')}{match.group('scheme')}{compact_absolute_path(match.group('path'))}",
        sanitized,
    )
    sanitized = POSIX_ABSOLUTE_PATH_RE.sub(
        lambda match: f"{match.group('prefix')}{compact_absolute_path(match.group('path'))}",
        sanitized,
    )
    sanitized = WINDOWS_ABSOLUTE_PATH_RE.sub(
        lambda match: f"{match.group('prefix')}{compact_absolute_path(match.group('path'))}",
        sanitized,
    )
    return sanitized


def sanitize_token(token: str) -> str:
    return sanitize_text(token)


def sanitize_command(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        tokens = shlex.split(value)
    except ValueError:
        return sanitize_text(value)

    sanitized_tokens: list[str] = []
    expects_sensitive_value = False
    for token in tokens:
        lower_token = token.lower()
        if expects_sensitive_value:
            sanitized_tokens.append("[redacted]")
            expects_sensitive_value = False
            continue
        if lower_token in SENSITIVE_VALUE_FLAGS:
            sanitized_tokens.append(token)
            expects_sensitive_value = True
            continue
        if "=" in token:
            key, _ = token.split("=", 1)
            if key.lower() in SENSITIVE_VALUE_FLAGS:
                sanitized_tokens.append(f"{key}=[redacted]")
                continue
            sanitized_tokens.append(sanitize_text(token))
            continue
        sanitized_tokens.append(sanitize_token(token))
    return " ".join(sanitized_tokens)


def parse_pr_url(value: str) -> tuple[str, str] | None:
    match = PR_URL_RE.match(value)
    if not match:
        return None
    return f"{match.group('owner')}/{match.group('repo')}", match.group("pr_number")


def is_probable_repo_slug(value: str) -> bool:
    if not REPO_SLUG_RE.match(value):
        return False
    if value.startswith(("./", "../", "/")):
        return False
    if value.endswith((".py", ".sh", ".bash", ".zsh")):
        return False
    return True


def infer_review_context_from_command(value: str | None) -> tuple[str | None, str | None]:
    if not value:
        return None, None
    try:
        tokens = shlex.split(value)
    except ValueError:
        tokens = value.split()
    for token in tokens:
        parsed = parse_pr_url(token)
        if parsed is not None:
            return parsed
    for index, token in enumerate(tokens[:-1]):
        if not is_probable_repo_slug(token):
            continue
        pr_number = tokens[index + 1]
        if pr_number.isdigit():
            return token, pr_number
    return None, None


def infer_review_context(args: argparse.Namespace) -> None:
    for command in (args.source_command, args.failing_command):
        repo, pr_number = infer_review_context_from_command(command)
        if repo and not args.using_repo:
            args.using_repo = repo
        if pr_number and not args.using_pr:
            if not args.using_repo or not repo or args.using_repo == repo:
                args.using_pr = pr_number
        if args.using_repo and args.using_pr:
            return


def unique_preserving_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def load_json_file(path: Path, errors: list[str], *, label: str) -> dict:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        errors.append(f"{label} was not valid JSON: {exc}")
        return {}
    if not isinstance(payload, dict):
        errors.append(f"{label} did not contain a JSON object.")
        return {}
    return payload


def extract_artifact_path(last_error: str) -> str | None:
    prefix = "Internal fixer action required:"
    if prefix in last_error:
        candidate = last_error.split(prefix, 1)[1].strip()
        if candidate:
            return candidate
    match = re.search(r"((?<!:)(?<!/)/(?:\S+\.json)|[A-Za-z]:\\\S+\.json)", last_error)
    if match:
        return match.group(1)
    return None


def detect_skill_version() -> str | None:
    changelog = REPO_ROOT / "CHANGELOG.md"
    if not changelog.exists():
        return None
    match = VERSION_RE.search(changelog.read_text(encoding="utf-8"))
    if not match:
        return None
    return match.group("version")


def load_feedback_context(repo: str | None, pr_number: str | None) -> dict:
    context = {
        "errors": [],
        "artifacts": [],
        "head_sha": None,
        "current_item_id": None,
        "session_status": None,
        "loop_status": None,
        "blocking_items_count": None,
        "open_local_findings_count": None,
        "unresolved_github_threads_count": None,
        "needs_human_items_count": None,
        "audit_summary_sha256": None,
    }
    if not repo or not pr_number:
        return context

    summary_path = last_machine_summary_file(repo, pr_number)
    summary_payload = load_json_file(summary_path, context["errors"], label="last-machine-summary.json")
    context["machine_summary"] = summary_payload
    if summary_payload.get("artifact_path"):
        context["artifacts"].append(str(summary_payload["artifact_path"]))
    if summary_payload.get("item_id"):
        context["current_item_id"] = str(summary_payload["item_id"])

    session_path = session_file(repo, pr_number)
    session_payload = load_json_file(session_path, context["errors"], label="session.json")
    context["session"] = session_payload
    if session_payload:
        context["session_status"] = session_payload.get("status")
        metrics = session_payload.get("metrics")
        if isinstance(metrics, dict):
            context["blocking_items_count"] = metrics.get("blocking_items_count")
            context["open_local_findings_count"] = metrics.get("open_local_findings_count")
            context["unresolved_github_threads_count"] = metrics.get("unresolved_github_threads_count")
            context["needs_human_items_count"] = metrics.get("needs_human_items_count")
        loop_state = session_payload.get("loop_state")
        if isinstance(loop_state, dict):
            context["loop_status"] = loop_state.get("status")
            context["run_id"] = loop_state.get("run_id")
            if not context["current_item_id"]:
                context["current_item_id"] = loop_state.get("current_item_id")
            last_error = str(loop_state.get("last_error") or "")
            artifact_path = extract_artifact_path(last_error)
            if artifact_path:
                context["artifacts"].append(artifact_path)

    cache_path = github_pr_cache_file(repo, pr_number)
    cache_payload = load_json_file(cache_path, context["errors"], label="github_pr_cache.json")
    context["head_sha"] = cache_payload.get("head_sha")

    audit_path = audit_summary_file(repo, pr_number)
    if audit_path.exists():
        context["audit_summary_sha256"] = sha256_of_file(audit_path)
        context["artifacts"].append(str(audit_path))

    context["artifacts"] = unique_preserving_order(context["artifacts"])
    return context


def merge_context(args: argparse.Namespace, context: dict) -> None:
    machine_summary = context.get("machine_summary") if isinstance(context.get("machine_summary"), dict) else {}

    args.status = args.status or machine_summary.get("status") or context.get("loop_status")
    args.reason_code = args.reason_code or machine_summary.get("reason_code")
    args.waiting_on = args.waiting_on or machine_summary.get("waiting_on")
    args.exit_code = args.exit_code if args.exit_code is not None else machine_summary.get("exit_code")
    args.run_id = args.run_id or context.get("run_id")
    args.skill_version = args.skill_version or detect_skill_version()

    artifact_values = [*args.artifact, *context.get("artifacts", [])]
    args.artifact = unique_preserving_order(artifact_values)


def bullet_or_default(items: list[str], *, empty_value: str = "- Not provided.") -> list[str]:
    if not items:
        return [empty_value]
    return [f"- `{item}`" for item in items]


def technical_diagnostics(args: argparse.Namespace, context: dict) -> list[str]:
    values = []
    if args.failing_command:
        values.append(f"- Failing command: `{args.failing_command}`")
    if args.exit_code is not None:
        values.append(f"- Exit code: `{args.exit_code}`")
    if args.status:
        values.append(f"- Status: `{args.status}`")
    if args.reason_code:
        values.append(f"- Reason code: `{args.reason_code}`")
    if args.waiting_on:
        values.append(f"- Waiting on: `{args.waiting_on}`")
    if args.run_id:
        values.append(f"- Run ID: `{args.run_id}`")
    if args.skill_version:
        values.append(f"- Skill version: `{args.skill_version}`")
    if context.get("head_sha"):
        values.append(f"- Head SHA: `{context['head_sha']}`")
    if context.get("current_item_id"):
        values.append(f"- Current item ID: `{context['current_item_id']}`")
    if context.get("session_status"):
        values.append(f"- Session status: `{context['session_status']}`")
    if context.get("loop_status"):
        values.append(f"- Loop status: `{context['loop_status']}`")
    if context.get("blocking_items_count") is not None:
        values.append(f"- Session blocking items: `{context['blocking_items_count']}`")
    if context.get("open_local_findings_count") is not None:
        values.append(f"- Open local findings: `{context['open_local_findings_count']}`")
    if context.get("unresolved_github_threads_count") is not None:
        values.append(f"- Unresolved GitHub threads: `{context['unresolved_github_threads_count']}`")
    if context.get("needs_human_items_count") is not None:
        values.append(f"- Needs-human items: `{context['needs_human_items_count']}`")
    if context.get("audit_summary_sha256"):
        values.append(f"- Audit summary SHA256: `{context['audit_summary_sha256']}`")
    for error in context.get("errors", []):
        values.append(f"- Context load warning: {sanitize_text(error)}")
    return values or ["- Not provided."]


def build_fingerprint_payload(args: argparse.Namespace) -> dict:
    return {
        "category": args.category,
        "title": args.title,
        "summary": sanitize_text(args.summary),
        "expected": sanitize_text(args.expected),
        "actual": sanitize_text(args.actual),
        "source_command": args.source_command or "",
        "failing_command": args.failing_command or "",
    }


def compute_feedback_fingerprint(args: argparse.Namespace) -> str:
    payload = build_fingerprint_payload(args)
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def extract_feedback_fingerprint(body: str) -> str | None:
    marker = re.search(rf"{re.escape(FINGERPRINT_MARKER_PREFIX)}\s*([0-9a-f]{{64}})", body or "")
    if not marker:
        return None
    return marker.group(1)


def parse_github_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def search_existing_feedback_issues(target_repo: str, fingerprint: str) -> list[dict]:
    query = f"repo:{target_repo} is:issue {fingerprint} in:body"
    response = gh_read_json(["api", f"search/issues?q={quote_plus(query)}&per_page={DEFAULT_FEEDBACK_SEARCH_PAGE_SIZE}"])
    if not isinstance(response, dict):
        raise SystemExit("Expected a JSON object when searching existing feedback issues.")
    items = response.get("items")
    if not isinstance(items, list):
        raise SystemExit("Expected an `items` array when searching existing feedback issues.")
    return [issue for issue in items if isinstance(issue, dict) and "pull_request" not in issue]


def find_existing_feedback_issue(target_repo: str, fingerprint: str, cooldown_hours: int) -> tuple[str | None, dict | None]:
    now = datetime.now(timezone.utc)
    cooldown_cutoff = now - timedelta(hours=cooldown_hours)
    recent_closed_match: dict | None = None
    for issue in search_existing_feedback_issues(target_repo, fingerprint):
        issue_fingerprint = extract_feedback_fingerprint(str(issue.get("body") or ""))
        if issue_fingerprint != fingerprint:
            continue
        if issue.get("state") == "open":
            return "duplicate", issue
        closed_at = parse_github_time(issue.get("closed_at") or issue.get("updated_at"))
        if closed_at and closed_at >= cooldown_cutoff:
            recent_closed_match = issue
    if recent_closed_match is not None:
        return "cooldown", recent_closed_match
    return None, None


def build_issue_body(args: argparse.Namespace, context: dict, fingerprint: str) -> str:
    repo_context = f"`{sanitize_text(args.using_repo)}`" if args.using_repo else "Not provided."
    pr_context = f"`{sanitize_text(args.using_pr)}`" if args.using_pr else "Not provided."
    source_command = f"`{sanitize_text(args.source_command)}`" if args.source_command else "Not provided."

    lines = [
        "## Summary",
        "",
        sanitize_text(args.summary),
        "",
        "## Category",
        "",
        f"- {args.category}",
        "",
        "## Expected Workflow",
        "",
        sanitize_text(args.expected),
        "",
        "## Actual Behavior",
        "",
        sanitize_text(args.actual),
        "",
        "## Reproduction Context",
        "",
        f"- Agent: `{sanitize_text(args.agent)}`",
        f"- Skill command: {source_command}",
        f"- Repository under review: {repo_context}",
        f"- Pull request under review: {pr_context}",
        "",
        "## Technical Diagnostics",
        "",
        *technical_diagnostics(args, context),
        "",
        "## Artifacts",
        "",
        *bullet_or_default([sanitize_text(item) for item in args.artifact]),
        "",
        "## Additional Notes",
        "",
        sanitize_text(args.notes) if args.notes else "None.",
        "",
        f"<!-- {FINGERPRINT_MARKER_PREFIX} {fingerprint} -->",
        "",
    ]
    return "\n".join(lines)


def emit_result(payload: dict, exit_code: int, *, error_message: str | None = None) -> int:
    sys.stdout.write(json.dumps(payload))
    if error_message:
        print(error_message, file=sys.stderr)
    return exit_code


def format_lookup_error(exc: Exception) -> str:
    if isinstance(exc, subprocess.CalledProcessError):
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
    else:
        detail = str(exc).strip()
    if not detail:
        detail = exc.__class__.__name__
    return sanitize_text(f"feedback issue dedupe lookup failed: {detail}")


def sanitize_error_message(value: str | None, fallback: str) -> str:
    sanitized = sanitize_text(value or "").strip()
    if not sanitized:
        return fallback
    return sanitized[:2000]


def validate_created_issue_response(response: object) -> tuple[int | None, str | None, str | None]:
    if not isinstance(response, dict):
        return None, None, "feedback issue response did not contain a JSON object"

    invalid_fields: list[str] = []
    issue_number = response.get("number")
    if not isinstance(issue_number, int) or isinstance(issue_number, bool) or issue_number <= 0:
        invalid_fields.append("number")

    issue_url = response.get("html_url")
    if not isinstance(issue_url, str) or not issue_url.strip():
        invalid_fields.append("html_url")

    if invalid_fields:
        return None, None, f"feedback issue response missing valid {', '.join(invalid_fields)}"
    return issue_number, issue_url, None


def audit_scope(args: argparse.Namespace) -> tuple[str, str]:
    return args.using_repo or args.target_repo, args.using_pr or DEFAULT_FEEDBACK_PR


def write_feedback_audit(args: argparse.Namespace, status: str, message: str, details: dict) -> None:
    repo, pr_number = audit_scope(args)
    audit_event("submit_feedback", status, repo, pr_number, args.audit_id, message, details)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a structured AI-agent feedback issue for gh-address-cr-skill.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--target-repo", default=DEFAULT_TARGET_REPO, help="GitHub repository that receives skill feedback issues.")
    parser.add_argument("--agent", default="ai-agent")
    parser.add_argument("--audit-id", default="default")
    parser.add_argument("--cooldown-hours", type=int, default=DEFAULT_COOLDOWN_HOURS)
    parser.add_argument("--category", required=True, choices=VALID_CATEGORIES)
    parser.add_argument("--title", required=True)
    parser.add_argument("--summary", required=True)
    parser.add_argument("--expected", required=True)
    parser.add_argument("--actual", required=True)
    parser.add_argument("--source-command")
    parser.add_argument("--failing-command")
    parser.add_argument("--exit-code", type=int)
    parser.add_argument("--status")
    parser.add_argument("--reason-code")
    parser.add_argument("--waiting-on")
    parser.add_argument("--run-id")
    parser.add_argument("--skill-version")
    parser.add_argument("--using-repo", help="Repository under review for PR-scoped feedback.")
    parser.add_argument(
        "--using-pr",
        help="Pull request under review for PR-scoped feedback. If omitted, the script tries to infer both values from --source-command or --failing-command.",
    )
    parser.add_argument("--artifact", action="append", default=[])
    parser.add_argument("--notes")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.using_pr and not args.using_repo:
        parser.error("--using-pr requires --using-repo.")
    if args.cooldown_hours < 0:
        parser.error("--cooldown-hours must be >= 0.")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    args.title = normalize_title(args.title)
    args.summary = normalize_text(args.summary, field_name="--summary")
    args.expected = normalize_text(args.expected, field_name="--expected")
    args.actual = normalize_text(args.actual, field_name="--actual")
    args.source_command = sanitize_command(args.source_command)
    args.failing_command = sanitize_command(args.failing_command)
    infer_review_context(args)

    context = load_feedback_context(args.using_repo, args.using_pr)
    merge_context(args, context)
    fingerprint = compute_feedback_fingerprint(args)
    body = build_issue_body(args, context, fingerprint)

    payload = {
        "status": "failed",
        "target_repo": args.target_repo,
        "issue_number": None,
        "issue_url": None,
        "title": args.title,
        "body": body,
        "fingerprint": fingerprint,
        "error": None,
    }

    if args.dry_run:
        payload["status"] = "dry-run"
        write_feedback_audit(
            args,
            "dry-run",
            "Previewed feedback issue submission",
            {"target_repo": args.target_repo, "fingerprint": fingerprint},
        )
        return emit_result(payload, 0)

    try:
        dedupe_status, existing_issue = find_existing_feedback_issue(args.target_repo, fingerprint, args.cooldown_hours)
    except (json.JSONDecodeError, subprocess.CalledProcessError, SystemExit) as exc:
        payload["error"] = format_lookup_error(exc)
        write_feedback_audit(
            args,
            "failed",
            "Feedback issue dedupe lookup failed",
            {"target_repo": args.target_repo, "fingerprint": fingerprint, "error": payload["error"]},
        )
        return emit_result(payload, 1, error_message=payload["error"])

    if existing_issue is not None and dedupe_status is not None:
        payload["status"] = dedupe_status
        payload["issue_number"] = existing_issue.get("number")
        payload["issue_url"] = existing_issue.get("html_url")
        write_feedback_audit(
            args,
            dedupe_status,
            "Skipped feedback issue creation because a matching issue already exists",
            {
                "target_repo": args.target_repo,
                "fingerprint": fingerprint,
                "existing_issue_number": existing_issue.get("number"),
                "existing_issue_url": existing_issue.get("html_url"),
            },
        )
        return emit_result(payload, 0)

    request_payload = {"title": args.title, "body": body}
    try:
        result = gh_write_cmd(
            ["gh", "api", f"repos/{args.target_repo}/issues", "--method", "POST", "--input", "-"],
            input_text=json.dumps(request_payload),
            check=False,
        )
    except SystemExit as exc:
        payload["error"] = sanitize_error_message(str(exc), "submit feedback failed")
        write_feedback_audit(
            args,
            "failed",
            "Feedback issue submission failed",
            {"target_repo": args.target_repo, "fingerprint": fingerprint, "error": payload["error"]},
        )
        return emit_result(payload, 1, error_message=payload["error"])
    if result.returncode != 0:
        payload["error"] = sanitize_error_message(result.stderr or result.stdout, "submit feedback failed")
        write_feedback_audit(
            args,
            "failed",
            "Feedback issue submission failed",
            {"target_repo": args.target_repo, "fingerprint": fingerprint, "error": payload["error"]},
        )
        return emit_result(payload, 1, error_message=payload["error"])

    try:
        response = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        payload["error"] = "feedback issue response was not valid JSON"
        write_feedback_audit(
            args,
            "failed",
            "Feedback issue response was not valid JSON",
            {"target_repo": args.target_repo, "fingerprint": fingerprint, "error": payload["error"]},
        )
        return emit_result(payload, 1, error_message=payload["error"])

    issue_number, issue_url, response_error = validate_created_issue_response(response)
    if response_error:
        payload["error"] = response_error
        write_feedback_audit(
            args,
            "failed",
            "Feedback issue response missing required fields",
            {"target_repo": args.target_repo, "fingerprint": fingerprint, "error": payload["error"]},
        )
        return emit_result(payload, 1, error_message=payload["error"])

    payload["status"] = "succeeded"
    payload["issue_number"] = issue_number
    payload["issue_url"] = issue_url
    write_feedback_audit(
        args,
        "ok",
        "Created feedback issue",
        {
            "target_repo": args.target_repo,
            "fingerprint": fingerprint,
            "issue_number": issue_number,
            "issue_url": issue_url,
        },
    )
    return emit_result(payload, 0)


if __name__ == "__main__":
    raise SystemExit(main())
