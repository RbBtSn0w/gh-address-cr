from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib
import io
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from gh_address_cr import (
    MAX_PARALLEL_CLAIMS,
    PROTOCOL_VERSION,
    SUPPORTED_PROTOCOL_VERSIONS,
    SUPPORTED_SKILL_CONTRACT_VERSIONS,
    __version__,
)
from gh_address_cr.core import gate as core_gate
from gh_address_cr.core.github_thread_state import (
    is_claimable_github_thread,
    is_resolved_github_thread,
    is_stale_or_outdated_github_thread,
)
from gh_address_cr.core.handoff import (
    ensure_handoff_state as _ensure_handoff_state,
    record_producer_result,
)
from gh_address_cr.core import paths as core_paths
from gh_address_cr.core import session as session_store
from gh_address_cr.core import workflow
from gh_address_cr.github.diagnostics import classify_github_failure, github_waiting_on
from gh_address_cr.github.client import GitHubClient
from gh_address_cr.github.errors import GitHubError
from gh_address_cr.intake.findings import (
    EMPTY_FINDINGS_INPUT_MESSAGE,
    FindingsFormatError,
    canonical_findings_payload,
    normalize_finding as native_normalize_finding,
    normalize_findings_payload,
    parse_finding_blocks as native_parse_finding_blocks,
    parse_records as native_parse_records,
    with_local_item_fields,
)


SCRIPT_DIR = Path(__file__).resolve().parent / "legacy_scripts"

COMMAND_TO_SCRIPT = {
    "cr-loop": "cr_loop.py",
    "control-plane": "control_plane.py",
    "code-review-adapter": "code_review_adapter.py",
    "review-to-findings": "review_to_findings.py",
    "prepare-code-review": "prepare_code_review.py",
    "run-once": "run_once.py",
    "final-gate": "final_gate.py",
    "list-threads": "list_threads.py",
    "post-reply": "post_reply.py",
    "resolve-thread": "resolve_thread.py",
    "run-local-review": "run_local_review.py",
    "ingest-findings": "ingest_findings.py",
    "publish-finding": "publish_finding.py",
    "mark-handled": "mark_handled.py",
    "audit-report": "audit_report.py",
    "generate-reply": "generate_reply.py",
    "batch-resolve": "batch_resolve.py",
    "clean-state": "clean_state.py",
    "session-engine": "session_engine.py",
    "submit-feedback": "submit_feedback.py",
    "submit-action": "submit_action.py",
}

HIGH_LEVEL_COMMANDS = {"address", "review", "threads", "findings", "adapter", "submit-action", "version"}
NATIVE_HIGH_LEVEL_COMMANDS = {"address", "review", "threads", "findings", "adapter", "version"}
OUTPUT_FLAGS = {"--machine", "--human"}
LEAN_FLAGS = {"--lean", "--summary"}
HIGH_LEVEL_GH_COMMANDS = {"address", "review", "threads", "adapter"}
INPUT_REQUIRED_COMMANDS = {"findings"}
WAITING_FOR_EXTERNAL_REVIEW_EXIT = 6
PR_IO_PREFLIGHT_EXIT = 5
PR_URL_RE = re.compile(r"^https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/pull/(?P<pr_number>\d+)(?:[/?#].*)?$")


def _legacy_module(name: str):
    raise RuntimeError(f"Legacy module imports are not supported by the native CLI path: {name}")


def _normalize_finding(record: dict) -> dict:
    return native_normalize_finding(record)


def _parse_records(raw: str) -> list[dict]:
    return native_parse_records(raw)


def _parse_findings(raw: str) -> list[dict]:
    return native_parse_finding_blocks(raw)


def normalize_repo(repo: str) -> str:
    return repo.replace("/", "__")


def default_state_dir_without_create() -> Path:
    override = os.environ.get("GH_ADDRESS_CR_STATE_DIR")
    if override:
        return Path(override)

    home = os.environ.get("HOME")
    if platform.system() == "Darwin":
        base = os.environ.get("XDG_CACHE_HOME") or (f"{home}/Library/Caches" if home else None)
    else:
        base = os.environ.get("XDG_CACHE_HOME") or (f"{home}/.cache" if home else None)
    if not base:
        return Path(".gh-address-cr-state")
    return Path(base) / "gh-address-cr"


def workspace_path_without_create(repo: str, pr_number: str) -> Path:
    return default_state_dir_without_create() / normalize_repo(repo) / f"pr-{pr_number}"


def workspace_root(repo: str, pr_number: str) -> Path:
    return session_store.workspace_dir(repo, pr_number)


def producer_request_file(repo: str, pr_number: str) -> Path:
    return workspace_root(repo, pr_number) / "producer-request.md"


def incoming_findings_json_file(repo: str, pr_number: str) -> Path:
    return workspace_root(repo, pr_number) / "incoming-findings.json"


def incoming_findings_markdown_file(repo: str, pr_number: str) -> Path:
    return workspace_root(repo, pr_number) / "incoming-findings.md"


def normalized_handoff_findings_file(repo: str, pr_number: str) -> Path:
    return workspace_root(repo, pr_number) / "incoming-findings.normalized.json"


def last_machine_summary_file(repo: str, pr_number: str) -> Path:
    return workspace_root(repo, pr_number) / "last-machine-summary.json"


def inline_output_flags(command: str, passthrough_args: list[str]) -> set[str]:
    if command == "adapter":
        return set()
    return {arg for arg in passthrough_args if arg in OUTPUT_FLAGS}


def inline_lean_flags(command: str, passthrough_args: list[str]) -> set[str]:
    if command not in {"address", "review", "threads"}:
        return set()
    return {arg for arg in passthrough_args if arg in LEAN_FLAGS}


def normalize_output_args(args: argparse.Namespace) -> bool:
    inline_flags = inline_output_flags(args.command, args.args)
    inline_lean = inline_lean_flags(args.command, args.args)
    requested_flags = set(inline_flags)
    if args.machine:
        requested_flags.add("--machine")
    if args.human:
        requested_flags.add("--human")
    requested_lean = bool(inline_lean or getattr(args, "lean", False) or getattr(args, "summary", False))
    if requested_flags == {"--machine", "--human"}:
        print("--machine and --human are mutually exclusive.", file=sys.stderr)
        return False
    if requested_lean and "--human" in requested_flags:
        print("--lean/--summary and --human are mutually exclusive.", file=sys.stderr)
        return False
    if args.command not in HIGH_LEVEL_COMMANDS and requested_flags:
        print(
            f"--machine and --human are only supported for {', '.join(sorted(HIGH_LEVEL_COMMANDS))}.", file=sys.stderr
        )
        return False
    if args.command not in {"address", "review", "threads"} and requested_lean:
        print("--lean/--summary is only supported for address, review, and threads.", file=sys.stderr)
        return False
    args.machine = "--machine" in requested_flags
    args.human = "--human" in requested_flags
    args.lean = requested_lean
    if args.command != "adapter":
        stripped_flags = set(OUTPUT_FLAGS)
        if args.command in {"address", "review", "threads"}:
            stripped_flags.update(LEAN_FLAGS)
        args.args = [arg for arg in args.args if arg not in stripped_flags]
    return True


def rewrite_alias_args(
    command: str,
    passthrough_args: list[str],
    *,
    review_continue_without_input: bool = False,
) -> list[str]:
    if command == "review":
        if review_continue_without_input:
            return ["remote", *passthrough_args]
        return ["mixed", "json", *passthrough_args]
    if command == "threads":
        return ["remote", *passthrough_args]
    if command == "findings":
        return ["local", "json", *passthrough_args]
    if command == "adapter":
        if len(passthrough_args) >= 3:
            return ["mixed", "adapter", *passthrough_args[:2], "--", *passthrough_args[2:]]
        return ["mixed", "adapter", *passthrough_args]
    return passthrough_args


def alias_help(command: str) -> str:
    if command == "review":
        return (
            "usage: gh-address-cr review [--auto-simple] <owner/repo> <pr_number> [--input <path>|-] [--human|--machine|--lean|--summary]\n\n"
            "High-level PR review entrypoint.\n\n"
            "Use when you want the full PR review workflow to run automatically.\n"
            "This command waits for external review findings when they are absent,\n"
            "then tells you to re-run the same review command once handoff artifacts are filled.\n"
            "You may still provide findings JSON explicitly via --input <path> or --input -.\n"
            "Use --auto-simple for a lightweight GitHub thread-only path that does not wait for external review findings.\n"
            "Use --lean or --summary to omit verbose thread body/url/reply_evidence fields.\n"
            "Default output is a structured JSON summary. Use --human for narrative text.\n"
            "--machine remains a compatibility alias for the default machine summary.\n"
        )
    if command == "address":
        return (
            "usage: gh-address-cr address <owner/repo> <pr_number> [--human|--machine|--lean|--summary]\n\n"
            "Lightweight GitHub thread-only entrypoint.\n\n"
            "Use for simple PRs where only GitHub review threads need addressing.\n"
            "This command does not wait for external review findings and does not ingest local findings.\n"
            "Use --lean or --summary to omit verbose thread body/url/reply_evidence fields.\n"
            "Default output is a structured JSON summary. Use --human for narrative text.\n"
            "--machine remains a compatibility alias for the default machine summary.\n"
        )
    if command == "threads":
        return (
            "usage: gh-address-cr threads <owner/repo> <pr_number> [--human|--machine|--lean|--summary]\n\n"
            "High-level GitHub review-thread entrypoint.\n\n"
            "Use when only GitHub review threads need processing.\n"
            "Use --lean or --summary to omit verbose thread body/url/reply_evidence fields.\n"
            "Default output is a structured JSON summary. Use --human for narrative text.\n"
            "--machine remains a compatibility alias for the default machine summary.\n"
        )
    if command == "findings":
        return (
            "usage: gh-address-cr findings <owner/repo> <pr_number> --input <path>|- [--source <producer_id>] [--sync] [--human|--machine]\n\n"
            "High-level local findings entrypoint.\n\n"
            "Use when findings already exist as JSON or are piped in through stdin.\n"
            "Missing --input fails immediately instead of waiting on stdin.\n"
            "`--sync` requires --source so auto-closing stays scoped to one producer.\n"
            "Default output is a structured JSON summary. Use --human for narrative text.\n"
            "--machine remains a compatibility alias for the default machine summary.\n"
        )
    if command == "adapter":
        return (
            "usage: gh-address-cr [--human|--machine] adapter <owner/repo> <pr_number> <adapter_cmd...>\n\n"
            "High-level adapter entrypoint.\n\n"
            "Use when an adapter command prints findings JSON and then runs PR orchestration,\n"
            "including GitHub thread handling.\n"
            "Arguments after <adapter_cmd...> are passed through to the adapter command unchanged.\n"
            "Use global --human/--machine before `adapter` to change wrapper output mode.\n"
            "Default output is a structured JSON summary. Use --human for narrative text.\n"
            "--machine remains a compatibility alias for the default machine summary.\n"
        )

    if command == "submit-action":
        return (
            "usage: gh-address-cr submit-action <loop_request_path> --resolution {fix,clarify,defer} --note <text> ... [resume_cmd...]\n\n"
            "High-level manual action entrypoint.\n\n"
            "Use when the loop stops in WAITING_FOR_FIX and asks for a manual resolution.\n"
            "This command writes the chosen action to a payload and then optionally resumes the loop.\n"
            "If resume_cmd is omitted, it prints instructions for resuming.\n"
        )
    if command == "doctor":
        return (
            "usage: gh-address-cr doctor [<owner/repo> [<pr_number>]] [--human|--machine]\n\n"
            "Runtime diagnostics entrypoint.\n\n"
            "Checks GitHub CLI availability/authentication, optional repository access, and writable state directories.\n"
            "Default output is a structured JSON summary with stable checks, reason_code, and diagnostics fields.\n"
            "--machine remains a compatibility alias for the default machine summary.\n"
        )
    return ""


def persist_machine_summary(repo: str, pr_number: str, payload: dict) -> None:
    path = last_machine_summary_file(repo, pr_number)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def external_review_command(repo: str, pr_number: str) -> str:
    return f"gh-address-cr review {repo} {pr_number}"


def _write_if_missing(path: Path, content: str = "") -> None:
    if not path.exists():
        path.write_text(content, encoding="utf-8")


def ensure_external_review_handoff(repo: str, pr_number: str) -> Path:
    workspace = workspace_root(repo, pr_number)
    workspace.mkdir(parents=True, exist_ok=True)
    request_path = producer_request_file(repo, pr_number)
    incoming_json = incoming_findings_json_file(repo, pr_number)
    incoming_md = incoming_findings_markdown_file(repo, pr_number)
    request_path.write_text(
        (
            "# External Review Producer Handoff\n\n"
            f"Use any external review producer to review `{repo}` PR `{pr_number}`.\n\n"
            "Accepted handoff formats:\n\n"
            f"1. Preferred: write findings JSON to `{incoming_json}`\n"
            f"2. Fallback: write fixed `finding` blocks to `{incoming_md}`\n\n"
            "Required finding fields:\n\n"
            "- `title`\n"
            "- `body`\n"
            "- `path`\n"
            "- `line`\n\n"
            "Do not write a Markdown-only narrative review report.\n"
            "After writing one of the accepted handoff files, rerun:\n\n"
            f"```bash\n{external_review_command(repo, pr_number)}\n```\n"
        ),
        encoding="utf-8",
    )
    _write_if_missing(incoming_json)
    _write_if_missing(incoming_md)
    return request_path


def last_consumed_handoff_sha256(repo: str, pr_number: str) -> str | None:
    session = load_session_payload(repo, pr_number)
    handoff = session.get("handoff") if isinstance(session, dict) else None
    if not isinstance(handoff, dict):
        return None
    value = handoff.get("last_consumed_sha256")
    return value if isinstance(value, str) and value else None


def has_submitted_producer_result(repo: str, pr_number: str) -> bool:
    session = load_session_payload(repo, pr_number)
    handoff = session.get("handoff") if isinstance(session, dict) else None
    if not isinstance(handoff, dict):
        return False
    producer_results = handoff.get("producer_results")
    if not isinstance(producer_results, dict):
        return False
    return any(
        isinstance(result, dict) and result.get("status") == "submitted"
        for result in producer_results.values()
    )


def normalize_review_handoff(repo: str, pr_number: str) -> tuple[str | None, str | None, str | None]:
    incoming_json = incoming_findings_json_file(repo, pr_number)
    incoming_md = incoming_findings_markdown_file(repo, pr_number)
    raw_json = incoming_json.read_text(encoding="utf-8") if incoming_json.exists() else ""
    raw_md = incoming_md.read_text(encoding="utf-8") if incoming_md.exists() else ""
    findings: list[dict] | None = None

    if raw_json.strip():
        try:
            findings = [_normalize_finding(record) for record in _parse_records(raw_json)]
        except SystemExit as exc:
            return None, None, str(exc) or "Invalid findings JSON."
        except Exception as exc:
            return None, None, str(exc) or "Invalid findings JSON."
    elif raw_md.strip():
        try:
            findings = _parse_findings(raw_md)
        except SystemExit as exc:
            return None, None, str(exc) or "Invalid finding blocks."
        except Exception as exc:
            return None, None, str(exc) or "Invalid finding blocks."

    if findings is None:
        return None, None, None

    normalized_path = normalized_handoff_findings_file(repo, pr_number)
    normalized_path.write_text(json.dumps(findings, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return (
        str(normalized_path),
        hashlib.sha256(canonical_findings_payload(findings).encode("utf-8")).hexdigest(),
        None,
    )


def load_session_payload(repo: str, pr_number: str) -> dict:
    path = workspace_root(repo, pr_number) / "session.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def extract_artifact_path(last_error: str) -> str | None:
    prefix = "Internal fixer action required:"
    if prefix in last_error:
        candidate = last_error.split(prefix, 1)[1].strip()
        if candidate:
            return candidate
    match = re.search(r"(\/\S+\.json)", last_error)
    if match:
        return match.group(1)
    return None


def build_machine_summary(command: str, repo: str, pr_number: str, result: subprocess.CompletedProcess[str]) -> dict:
    session = load_session_payload(repo, pr_number)
    loop_state = session.get("loop_state") if isinstance(session, dict) else {}
    if not isinstance(loop_state, dict):
        loop_state = {}
    metrics = session.get("metrics") if isinstance(session, dict) else {}
    if not isinstance(metrics, dict):
        metrics = {}
    items = session.get("items") if isinstance(session, dict) else {}
    if not isinstance(items, dict):
        items = {}

    status = loop_state.get("status") or "FAILED"
    if result.returncode == 0 and status == "IDLE":
        status = "PASSED"
    elif result.returncode == 0 and status not in {"PASSED", "FAILED", "NEEDS_HUMAN", "BLOCKED"}:
        status = "PASSED"
    elif result.returncode == 4:
        status = "NEEDS_HUMAN"
    elif result.returncode == 5:
        status = "BLOCKED"
    elif result.returncode != 0 and status == "IDLE":
        status = "FAILED"

    item_id = loop_state.get("current_item_id")
    item = items.get(item_id, {}) if item_id else {}
    item_kind = item.get("item_kind") if isinstance(item, dict) else None
    artifact_path = extract_artifact_path(str(loop_state.get("last_error") or "")) or str(
        workspace_root(repo, pr_number)
    )
    stderr_text = result.stderr or ""
    last_error = str(loop_state.get("last_error") or "")
    combined_error = "\n".join(part for part in [last_error, stderr_text] if part)

    reason_code = "COMMAND_FAILED"
    waiting_on = None
    next_action = "Inspect stderr and fix the failing command or input."
    if status == "PASSED":
        reason_code = "PASSED"
        next_action = "No action required."
    elif "requires findings JSON" in combined_error or "requires findings input" in combined_error:
        reason_code = "MISSING_FINDINGS_INPUT"
        waiting_on = "findings_input"
        next_action = (
            f"`{command}` does not generate findings. "
            f"Provide findings JSON with `gh-address-cr {command} {repo} {pr_number} --input <path>|-`."
        )
    elif "Missing GitHub CLI" in combined_error or "gh executable" in combined_error:
        reason_code = "GH_NOT_FOUND"
        waiting_on = "github_cli"
        next_action = "Install GitHub CLI and ensure `gh` is available on PATH, then rerun the command."
    elif status == "NEEDS_HUMAN":
        reason_code = "NEEDS_HUMAN_REVIEW"
        waiting_on = "human_review"
        next_action = f"Inspect {artifact_path} and resolve manually."
    elif status == "BLOCKED" and (
        "Internal fixer action required:" in combined_error or "Interaction Required" in combined_error
    ):
        reason_code = "WAITING_FOR_FIX"
        waiting_on = "human_fix"
        next_action = f"Address the finding by running: `gh-address-cr submit-action {artifact_path} --resolution <fix|clarify|defer> --note <note> ... -- gh-address-cr {command} {repo} {pr_number}`"
    elif status == "BLOCKED":
        reason_code = "BLOCKED"
        waiting_on = "manual_intervention"
        next_action = f"Inspect {artifact_path} and rerun {command} after fixing the blocking issue."
    elif "Gate FAILED" in combined_error:
        reason_code = "BLOCKING_ITEMS_REMAIN"
        waiting_on = "unresolved_items"
        next_action = "Continue processing unresolved items until the final gate passes."

    return {
        "status": status,
        "repo": repo,
        "pr_number": pr_number,
        "item_id": item_id,
        "item_kind": item_kind,
        "counts": {
            "blocking_items_count": metrics.get("blocking_items_count", 0),
            "open_local_findings_count": metrics.get("open_local_findings_count", 0),
            "unresolved_github_threads_count": metrics.get("unresolved_github_threads_count", 0),
            "needs_human_items_count": metrics.get("needs_human_items_count", 0),
        },
        "artifact_path": artifact_path,
        "reason_code": reason_code,
        "waiting_on": waiting_on,
        "next_action": next_action,
        "exit_code": result.returncode,
        "commands": _summary_commands(repo, pr_number),
    }


def build_preflight_summary(
    command: str,
    repo: str,
    pr_number: str,
    *,
    status: str = "FAILED",
    exit_code: int,
    reason_code: str,
    waiting_on: str | None,
    next_action: str,
    artifact_path: str | None = None,
    diagnostics: dict | None = None,
) -> dict:
    summary = {
        "status": status,
        "repo": repo,
        "pr_number": pr_number,
        "item_id": None,
        "item_kind": None,
        "counts": {
            "blocking_items_count": None,
            "open_local_findings_count": None,
            "unresolved_github_threads_count": None,
            "needs_human_items_count": None,
        },
        "artifact_path": artifact_path or str(workspace_path_without_create(repo, pr_number)),
        "reason_code": reason_code,
        "waiting_on": waiting_on,
        "next_action": next_action,
        "exit_code": exit_code,
        "commands": _summary_commands(repo, pr_number),
    }
    if diagnostics:
        summary["diagnostics"] = diagnostics
    return summary


def has_option(args: list[str], flag: str) -> bool:
    return flag in args


def parse_pr_url(value: str) -> tuple[str, str] | None:
    match = PR_URL_RE.match(value)
    if not match:
        return None
    return f"{match.group('owner')}/{match.group('repo')}", match.group("pr_number")


def normalize_high_level_target_args(args: argparse.Namespace) -> None:
    if args.command not in HIGH_LEVEL_COMMANDS or not args.args:
        return
    parsed = parse_pr_url(args.args[0])
    if parsed is None:
        return
    repo, pr_number = parsed
    args.args = [repo, pr_number, *args.args[1:]]


def normalize_leading_high_level_options(args: argparse.Namespace) -> None:
    if args.command == "review" and args.args and args.args[0] == "--auto-simple":
        args.args = [*args.args[1:], "--auto-simple"]


def output_preflight_error(
    args: argparse.Namespace,
    repo: str,
    pr_number: str,
    message: str,
    *,
    status: str = "FAILED",
    reason_code: str,
    waiting_on: str | None,
    next_action: str,
    artifact_path: str | None = None,
    exit_code: int = 2,
    persist: bool = True,
    diagnostics: dict | None = None,
) -> int:
    if not args.human:
        summary = build_preflight_summary(
            args.command,
            repo,
            pr_number,
            status=status,
            exit_code=exit_code,
            reason_code=reason_code,
            waiting_on=waiting_on,
            next_action=next_action,
            artifact_path=artifact_path,
            diagnostics=diagnostics,
        )
        if persist:
            persist_machine_summary(repo, pr_number, summary)
        sys.stdout.write(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(message, file=sys.stderr)
    return exit_code


def _gh_auth_fixture_is_unimplemented(result: subprocess.CompletedProcess[str]) -> bool:
    combined = "\n".join(part for part in [result.stdout, result.stderr] if part)
    return "unhandled gh args" in combined and "auth" in combined and "status" in combined


def _preflight_gh_failure_response(diagnostics: dict) -> tuple[str, str, str, str]:
    category = diagnostics.get("stderr_category")
    if category == "network":
        return (
            "GH_NETWORK_FAILED",
            "github_network",
            "Fix GitHub network connectivity or sandbox network access, then rerun the command.",
            "GitHub CLI `gh` could not reach GitHub. Inspect `gh auth status` stderr and network/sandbox access before rerunning.",
        )
    if category in {"environment", "sandbox"}:
        return (
            "GH_ENVIRONMENT_FAILED",
            "github_environment",
            "Fix the local sandbox or permission issue for GitHub CLI, then rerun the command.",
            "GitHub CLI `gh` failed due to a local environment or sandbox permission issue.",
        )
    if category == "rate_limit":
        return (
            "GH_RATE_LIMITED",
            "github_rate_limit",
            "Wait for GitHub rate limits to recover or use a token with sufficient quota, then rerun the command.",
            "GitHub CLI `gh` is authenticated, but GitHub reported rate limiting.",
        )
    return (
        "GH_AUTH_FAILED",
        "github_auth",
        "Authenticate GitHub CLI with `gh auth login`, then rerun the command.",
        "GitHub CLI `gh` is not authenticated. Run `gh auth status` and fix authentication before rerunning.",
    )


def _doctor_check(name: str, passed: bool, *, detail: str | None = None, diagnostics: dict | None = None) -> dict:
    row = {
        "name": name,
        "status": "passed" if passed else "failed",
    }
    if detail:
        row["detail"] = detail
    if diagnostics:
        row["diagnostics"] = diagnostics
    return row


def _run_doctor_gh_check(name: str, command: list[str]) -> dict:
    result = subprocess.run(command, text=True, capture_output=True)
    if result.returncode == 0:
        detail = result.stdout.strip()
        return _doctor_check(name, True, detail=detail or None)
    diagnostics = classify_github_failure(result.stderr, result.stdout, result.returncode, command)
    return _doctor_check(name, False, detail=result.stderr.strip() or result.stdout.strip() or None, diagnostics=diagnostics)


def _doctor_writable_dir_check(name: str, path: Path) -> dict:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".gh-address-cr-doctor-write-test"
        probe.write_text("ok\n", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        diagnostics = classify_github_failure(str(exc), "", None, [name, str(path)])
        return _doctor_check(name, False, detail=str(path), diagnostics=diagnostics)
    return _doctor_check(name, True, detail=str(path))


def handle_doctor_command(args: argparse.Namespace) -> int:
    repo = args.repo
    pr_number = args.pr_number
    checks: list[dict] = []

    gh_path = shutil.which("gh")
    checks.append(_doctor_check("gh_available", bool(gh_path), detail=gh_path or "GitHub CLI `gh` not found on PATH."))
    if gh_path:
        checks.append(_run_doctor_gh_check("gh_auth", ["gh", "auth", "status"]))
        checks.append(_run_doctor_gh_check("gh_viewer", ["gh", "api", "user"]))
        if repo:
            checks.append(_run_doctor_gh_check("repo_access", ["gh", "repo", "view", repo, "--json", "nameWithOwner"]))
    elif repo:
        checks.append(
            _doctor_check(
                "repo_access",
                False,
                detail="Repository access check requires GitHub CLI `gh`.",
            )
        )

    try:
        checks.append(_doctor_writable_dir_check("state_dir", session_store.state_dir()))
    except session_store.SessionError as exc:
        checks.append(_doctor_check("state_dir", False, detail=str(exc)))
    if repo and pr_number:
        try:
            checks.append(_doctor_writable_dir_check("workspace_dir", session_store.workspace_dir(repo, pr_number)))
        except session_store.SessionError as exc:
            checks.append(_doctor_check("workspace_dir", False, detail=str(exc)))

    failed = [check for check in checks if check["status"] != "passed"]
    summary = {
        "status": "FAILED" if failed else "PASSED",
        "reason_code": "DOCTOR_FAILED" if failed else "DOCTOR_PASSED",
        "repo": repo,
        "pr_number": str(pr_number) if pr_number else None,
        "checks": checks,
        "next_action": "Fix failed doctor checks, then rerun the original command." if failed else "Rerun the blocked gh-address-cr command.",
        "exit_code": 5 if failed else 0,
    }
    sys.stdout.write(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    return int(summary["exit_code"])


def preflight_github_cli(args: argparse.Namespace, repo: str, pr_number: str) -> int | None:
    if shutil.which("gh") is None:
        diagnostics = classify_github_failure(
            "Missing GitHub CLI `gh` on PATH.",
            "",
            None,
            ["gh"],
        )
        return output_preflight_error(
            args,
            repo,
            pr_number,
            "Missing GitHub CLI `gh` on PATH. Install it or add it to PATH before running this command.",
            reason_code="GH_NOT_FOUND",
            waiting_on="github_cli",
            next_action="Install GitHub CLI and ensure `gh` is available on PATH, then rerun the command.",
            exit_code=PR_IO_PREFLIGHT_EXIT,
            persist=False,
            diagnostics=diagnostics,
        )

    auth_command = ["gh", "auth", "status"]
    result = subprocess.run(auth_command, text=True, capture_output=True)
    if result.returncode != 0 and not _gh_auth_fixture_is_unimplemented(result):
        diagnostics = classify_github_failure(result.stderr, result.stdout, result.returncode, auth_command)
        reason_code, waiting_on, next_action, message = _preflight_gh_failure_response(diagnostics)
        return output_preflight_error(
            args,
            repo,
            pr_number,
            message,
            reason_code=reason_code,
            waiting_on=waiting_on,
            next_action=next_action,
            exit_code=PR_IO_PREFLIGHT_EXIT,
            persist=False,
            diagnostics=diagnostics,
        )
    return None


def preflight_high_level(args: argparse.Namespace) -> int | None:
    repo = args.args[0]
    pr_number = args.args[1]

    if args.command == "adapter" and len(args.args) < 3:
        return output_preflight_error(
            args,
            repo,
            pr_number,
            "adapter requires <adapter_cmd...> after <owner/repo> <pr_number>.",
            reason_code="MISSING_ADAPTER_COMMAND",
            waiting_on="adapter_command",
            next_action=f"Provide an adapter command after `gh-address-cr adapter {repo} {pr_number}`.",
        )

    if args.command in HIGH_LEVEL_GH_COMMANDS:
        gh_preflight = preflight_github_cli(args, repo, pr_number)
        if gh_preflight is not None:
            return gh_preflight

    if args.command == "review" and has_option(args.args, "--auto-simple"):
        return None

    if args.command == "review" and not has_option(args.args, "--input"):
        normalized_input, handoff_sha256, error = normalize_review_handoff(repo, pr_number)
        if error:
            return output_preflight_error(
                args,
                repo,
                pr_number,
                f"Invalid external review producer output: {error} Use findings JSON or fixed `finding` blocks.",
                reason_code="INVALID_PRODUCER_OUTPUT",
                waiting_on="external_review_output",
                next_action=(
                    "Write valid findings JSON to `incoming-findings.json` or fixed `finding` blocks "
                    "to `incoming-findings.md`, then rerun the same review command."
                ),
            )
        if normalized_input:
            if handoff_sha256 and handoff_sha256 == last_consumed_handoff_sha256(repo, pr_number):
                return None
            args.args = [*args.args, "--input", normalized_input]
            if handoff_sha256:
                args.args.extend(["--handoff-sha256", handoff_sha256])
            return None
        if has_submitted_producer_result(repo, pr_number):
            return None
        request_path = ensure_external_review_handoff(repo, pr_number)
        return output_preflight_error(
            args,
            repo,
            pr_number,
            (
                "No external review findings are available yet from an external review producer. "
                f"Write findings JSON or fixed `finding` blocks using {request_path}, then rerun the same review command."
            ),
            status="WAITING_FOR_EXTERNAL_REVIEW",
            reason_code="WAITING_FOR_EXTERNAL_REVIEW",
            waiting_on="external_review",
            next_action=(
                "Provide findings JSON in `incoming-findings.json` or fixed `finding` blocks "
                "in `incoming-findings.md`, then rerun the same review command."
            ),
            artifact_path=str(request_path),
            exit_code=WAITING_FOR_EXTERNAL_REVIEW_EXIT,
        )

    if args.command in INPUT_REQUIRED_COMMANDS and not has_option(args.args, "--input"):
        return output_preflight_error(
            args,
            repo,
            pr_number,
            f"{args.command} requires findings JSON. This command does not generate findings. Pass --input <path> or --input - and provide findings through stdin.",
            reason_code="MISSING_FINDINGS_INPUT",
            waiting_on="findings_input",
            next_action=f"`{args.command}` does not generate findings. Provide findings JSON with `gh-address-cr {args.command} {repo} {pr_number} --input <path>|-`.",
        )
    return None


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _load_or_create_session(repo: str, pr_number: str) -> dict:
    manager = session_store.SessionManager(repo, str(pr_number))
    try:
        session = manager.load()
    except session_store.SessionError:
        session = manager.create(status="ACTIVE")
    _ensure_native_session_fields(session)
    return session


def _ensure_native_session_fields(session: dict) -> None:
    now = _utc_now()
    session.setdefault("schema_version", 1)
    session.setdefault("created_at", now)
    session.setdefault("updated_at", now)
    session.setdefault("current_scan_id", None)
    session.setdefault("items", {})
    session.setdefault("leases", {})
    session.setdefault("history", [])
    _ensure_handoff_state(session)
    session.setdefault(
        "loop_state",
        {
            "run_id": None,
            "status": "IDLE",
            "iteration": 0,
            "max_iterations": 0,
            "current_item_id": None,
            "last_error": "",
            "last_started_at": None,
            "last_completed_at": None,
        },
    )
    session.setdefault("metrics", {})


def _set_loop_state(
    session: dict,
    *,
    run_id: str,
    status: str,
    iteration: int,
    max_iterations: int,
    current_item_id: str | None = None,
    last_error: str = "",
) -> None:
    loop_state = session.setdefault("loop_state", {})
    loop_state.update(
        {
            "run_id": run_id,
            "status": status,
            "iteration": iteration,
            "max_iterations": max_iterations,
            "current_item_id": current_item_id,
            "last_error": last_error,
            "last_started_at": loop_state.get("last_started_at") or _utc_now(),
            "last_completed_at": _utc_now() if status in {"PASSED", "FAILED", "BLOCKED", "NEEDS_HUMAN"} else None,
        }
    )


def _recalc_native_metrics(session: dict) -> None:
    items = [item for item in session.get("items", {}).values() if isinstance(item, dict)]
    session["metrics"] = {
        "blocking_items_count": sum(1 for item in items if item.get("blocking")),
        "open_local_findings_count": sum(
            1 for item in items if item.get("item_kind") == "local_finding" and item.get("blocking")
        ),
        "unresolved_github_threads_count": sum(
            1
            for item in items
            if item.get("item_kind") == "github_thread"
            and str(item.get("status") or "").upper() not in {"CLOSED", "DROPPED"}
        ),
        "needs_human_items_count": sum(1 for item in items if item.get("needs_human")),
    }


def _read_findings_input(input_path: str | None) -> str:
    if input_path == "-":
        return sys.stdin.read()
    if not input_path:
        return ""
    return Path(input_path).read_text(encoding="utf-8")


def _ingest_native_findings(
    session: dict,
    *,
    raw: str,
    source: str,
    sync: bool = False,
    scan_id: str | None = None,
    handoff_sha256: str | None = None,
) -> list[dict]:
    if not raw.strip():
        raise FindingsFormatError(EMPTY_FINDINGS_INPUT_MESSAGE)
    format_source = "adapter" if source == "adapter" else "json"
    findings = []
    for finding in normalize_findings_payload(format_source, raw):
        if source != format_source:
            base = {key: value for key, value in finding.items() if key not in {"item_id", "item_kind", "source"}}
            finding = with_local_item_fields(source, base)
        findings.append(finding)
    items = session.setdefault("items", {})
    incoming_ids: set[str] = set()
    now = _utc_now()
    if scan_id:
        session["current_scan_id"] = scan_id
    for finding in findings:
        item_id = str(finding["item_id"])
        incoming_ids.add(item_id)
        existing = items.get(item_id)
        item = dict(existing) if isinstance(existing, dict) else {}
        item.update(finding)
        item.setdefault("created_at", now)
        item["updated_at"] = now
        item["status"] = "OPEN"
        item["state"] = "open"
        item["blocking"] = True
        item["handled"] = False
        item["needs_human"] = False
        item.setdefault("history", [])
        item.setdefault("reply_posted", False)
        item.setdefault("reply_url", None)
        item.setdefault("validation_commands", [])
        items[item_id] = item
    if sync:
        for item_id, item in list(items.items()):
            if not isinstance(item, dict) or item.get("item_kind") != "local_finding":
                continue
            if item.get("source") == source and item_id not in incoming_ids:
                item["status"] = "CLOSED"
                item["state"] = "closed"
                item["blocking"] = False
                item["handled"] = True
                item["handled_at"] = now
                item["updated_at"] = now
    handoff = _ensure_handoff_state(session)
    record_producer_result(
        session,
        source=source,
        findings=findings,
        sync_enabled=bool(sync),
        submitted_at=now,
        payload_sha256=handoff_sha256 or None,
    )
    if handoff_sha256:
        handoff["last_consumed_sha256"] = handoff_sha256
    return findings


def _write_native_action_request(repo: str, pr_number: str, item: dict, *, command: str, run_id: str) -> Path:
    request_path = workspace_root(repo, pr_number) / f"loop-request-native-{run_id}-{uuid4().hex}.json"
    request = {
        "mode": "native-runtime-fixer",
        "repo": repo,
        "pr_number": str(pr_number),
        "run_id": run_id,
        "item": item,
        "instructions": [
            "Inspect the selected item and decide one resolution: fix, clarify, defer, or reject.",
            "Submit structured evidence with `gh-address-cr agent submit` or rerun the originating command after recording the fix.",
        ],
        "resume_command": f"gh-address-cr {command} {repo} {pr_number}",
    }
    request_path.write_text(json.dumps(request, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return request_path


def _first_blocking_item(session: dict) -> dict | None:
    for item in session.get("items", {}).values():
        if isinstance(item, dict) and item.get("blocking"):
            return item
    return None


def _first_local_item(session: dict) -> dict | None:
    for item in session.get("items", {}).values():
        if isinstance(item, dict) and item.get("item_kind") == "local_finding":
            return item
    return None


def _native_summary(
    *,
    command: str,
    repo: str,
    pr_number: str,
    status: str,
    reason_code: str,
    waiting_on: str | None,
    next_action: str,
    exit_code: int,
    session: dict,
    artifact_path: str | None = None,
    item: dict | None = None,
    include_threads: bool = False,
    diagnostics: dict | None = None,
    lean: bool = False,
) -> dict:
    metrics = session.get("metrics") if isinstance(session.get("metrics"), dict) else {}
    summary = {
        "status": status,
        "repo": repo,
        "pr_number": str(pr_number),
        "item_id": item.get("item_id") if item else None,
        "item_kind": item.get("item_kind") if item else None,
        "counts": {
            "blocking_items_count": metrics.get("blocking_items_count", 0),
            "open_local_findings_count": metrics.get("open_local_findings_count", 0),
            "unresolved_github_threads_count": metrics.get("unresolved_github_threads_count", 0),
            "needs_human_items_count": metrics.get("needs_human_items_count", 0),
        },
        "artifact_path": artifact_path or str(workspace_root(repo, pr_number)),
        "reason_code": reason_code,
        "waiting_on": waiting_on,
        "next_action": next_action,
        "exit_code": exit_code,
        "commands": _summary_commands(repo, pr_number),
    }
    if diagnostics:
        summary["diagnostics"] = diagnostics
    if command == "threads" or include_threads:
        summary["threads"] = _native_thread_rows(session, lean=lean)
    return summary


def _summary_commands(repo: str, pr_number: str) -> dict[str, str]:
    return {
        "address": f"gh-address-cr address {repo} {pr_number} --lean",
        "review_auto_simple": f"gh-address-cr review --auto-simple {repo} {pr_number} --lean",
        "threads": f"gh-address-cr threads {repo} {pr_number} --lean",
        "classify": f"gh-address-cr agent classify {repo} {pr_number} <item_id> --classification fix --note <note>",
        "next": f"gh-address-cr agent next {repo} {pr_number} --role fixer --agent-id <agent_id>",
        "submit": f"gh-address-cr agent submit {repo} {pr_number} --input response.json",
        "submit_batch": f"gh-address-cr agent submit-batch {repo} {pr_number} --input batch-response.json",
        "fix_all": (
            f"gh-address-cr agent fix-all {repo} {pr_number} "
            "--commit <sha> --files <paths> --validation <cmd=passed>"
        ),
        "resolve_stale": (
            f"gh-address-cr agent resolve-stale {repo} {pr_number} "
            "--commit <sha> --files <paths> --validation <cmd=passed> --match-files"
        ),
        "publish": f"gh-address-cr agent publish {repo} {pr_number}",
        "final_gate": f"gh-address-cr final-gate {repo} {pr_number}",
    }


def _native_thread_rows(session: dict, *, lean: bool = False) -> list[dict]:
    items = session.get("items") if isinstance(session.get("items"), dict) else {}
    rows = []
    for item_id, item in sorted(items.items()):
        if not isinstance(item, dict) or item.get("item_kind") != "github_thread":
            continue
        status = str(item.get("status") or "")
        state = str(item.get("state") or "")
        thread_id = item.get("thread_id") or item.get("origin_ref") or str(item_id).removeprefix("github-thread:")
        reply_evidence = item.get("reply_evidence") if isinstance(item.get("reply_evidence"), dict) else None
        base = {
            "item_id": str(item.get("item_id") or item_id),
            "thread_id": thread_id,
            "path": item.get("path"),
            "line": item.get("line"),
            "state": state or None,
            "status": status or None,
            "is_resolved": is_resolved_github_thread(item),
            "is_outdated": is_stale_or_outdated_github_thread(item),
            "accepted_response_present": isinstance(item.get("accepted_response"), dict),
        }
        if lean:
            base["claimable"] = is_claimable_github_thread(item)
            base["reply_evidence_present"] = bool(reply_evidence)
            rows.append(base)
            continue
        base.update(
            {
                "body": item.get("body"),
                "url": item.get("url"),
                "item_kind": "github_thread",
                "reply_evidence": reply_evidence,
            }
        )
        rows.append(base)
    return rows


def _blocking_local_items(session: dict) -> list[dict]:
    items = session.get("items") if isinstance(session.get("items"), dict) else {}
    return [
        item
        for item in items.values()
        if isinstance(item, dict) and item.get("item_kind") == "local_finding" and bool(item.get("blocking"))
    ]


def _auto_simple_local_gate_failed(result: core_gate.GateResult) -> bool:
    return any(
        code
        in {
            core_gate.FINAL_GATE_BLOCKING_LOCAL_ITEMS,
            core_gate.FINAL_GATE_MISSING_VALIDATION_EVIDENCE,
        }
        for code in result.failure_codes
    )


def _write_simple_address_request(repo: str, pr_number: str, session: dict, *, command: str, run_id: str) -> Path:
    request_path = workspace_root(repo, pr_number) / f"simple-address-request-{run_id}-{uuid4().hex}.json"
    threads = _native_thread_rows(session)
    claimable_item_ids = _claimable_github_thread_item_ids(threads)
    request = {
        "mode": "simple-address",
        "repo": repo,
        "pr_number": str(pr_number),
        "run_id": run_id,
        "source_command": command,
        "threads": threads,
        "claimable_item_ids": claimable_item_ids,
        "batch_response_skeleton": _batch_response_skeleton(claimable_item_ids),
        "instructions": [
            "Use per-thread ActionResponse evidence, or agent submit-batch when one commit/files/validation set addresses multiple threads.",
            "For each actionable GitHub thread, run agent classify and agent next to acquire leases before submitting evidence.",
            "When common commit, file, and validation evidence applies, submit one BatchActionResponse with per-thread summary/why entries.",
            "After accepted evidence is present, run agent publish.",
        ],
        "commands": _summary_commands(repo, pr_number),
    }
    request_path.write_text(json.dumps(request, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return request_path


def _claimable_github_thread_item_ids(threads: list[dict]) -> list[str]:
    return [
        str(row["item_id"])
        for row in threads
        if row.get("item_id") and is_claimable_github_thread(row)
    ]


def _batch_response_skeleton(item_ids: list[str]) -> dict:
    return {
        "schema_version": "1.0",
        "agent_id": "<agent_id>",
        "resolution": "fix",
        "common": {
            "files": ["<file_path>"],
            "validation_commands": [{"command": "<test_command>", "result": "<passed|failed + key signal>"}],
            "fix_reply": {
                "commit_hash": "<commit_hash>",
                "test_command": "<test_command>",
                "test_result": "<passed|failed + key signal>",
            },
        },
        "items": [
            {
                "item_id": item_id,
                "request_id": "<request_id from agent next>",
                "lease_id": "<lease_id from agent next>",
                "summary": "<per-thread fix summary>",
                "why": "<why this fixes this review thread>",
            }
            for item_id in item_ids
        ],
    }


def _parse_native_high_level_args(command: str, args: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog=f"gh-address-cr {command}", add_help=False)
    parser.add_argument("repo")
    parser.add_argument("pr_number")
    if command == "adapter":
        parser.add_argument("adapter_cmd", nargs=argparse.REMAINDER)
        parsed = parser.parse_args(args)
        if parsed.adapter_cmd and parsed.adapter_cmd[0] == "--":
            parsed.adapter_cmd = parsed.adapter_cmd[1:]
        parsed.input = None
        parsed.source = None
        parsed.sync = False
        parsed.handoff_sha256 = None
        parsed.scan_id = None
        parsed.audit_id = None
        parsed.snapshot = None
        parsed.max_iterations = 1
        parsed.lean = False
        parsed.summary = False
        parsed.auto_simple = False
        return parsed
    parser.add_argument("adapter_cmd", nargs="*")
    if command == "review":
        parser.add_argument("--auto-simple", action="store_true")
    parser.add_argument("--input")
    parser.add_argument("--source")
    parser.add_argument("--sync", action="store_true")
    parser.add_argument("--handoff-sha256")
    parser.add_argument("--scan-id")
    parser.add_argument("--audit-id")
    parser.add_argument("--snapshot")
    parser.add_argument("--max-iterations", type=int, default=1)
    parser.add_argument("--lean", action="store_true")
    parser.add_argument("--summary", action="store_true")
    parsed, unknown = parser.parse_known_args(args)
    if unknown:
        parsed.adapter_cmd.extend(unknown)
    if parsed.adapter_cmd and parsed.adapter_cmd[0] == "--":
        parsed.adapter_cmd = parsed.adapter_cmd[1:]
    if not hasattr(parsed, "auto_simple"):
        parsed.auto_simple = False
    return parsed


def _run_adapter_command(argv: list[str]) -> tuple[str | None, str | None]:
    if not argv:
        return None, "adapter requires <adapter_cmd...> after <owner/repo> <pr_number>."
    result = subprocess.run(argv, text=True, capture_output=True)
    if result.returncode != 0:
        return None, result.stderr or f"Adapter command failed with exit code {result.returncode}."
    return result.stdout, None


def handle_native_high_level(command: str, passthrough_args: list[str], *, human: bool, lean: bool = False) -> int:
    parsed = _parse_native_high_level_args(command, passthrough_args)
    repo = parsed.repo
    pr_number = str(parsed.pr_number)
    lean = bool(lean or parsed.lean or parsed.summary)
    run_id = parsed.audit_id or f"native-{_utc_now()}"
    auto_simple = command == "address" or (command == "review" and bool(parsed.auto_simple))
    session = _load_or_create_session(repo, pr_number)
    _set_loop_state(session, run_id=run_id, status="ACTIVE", iteration=1, max_iterations=parsed.max_iterations)

    try:
        if parsed.sync and not parsed.source:
            raise FindingsFormatError(
                "`--sync` requires an explicit --source so missing findings stay scoped to one producer."
            )
        if command in {"review", "findings"} and parsed.input:
            raw = _read_findings_input(parsed.input)
            _ingest_native_findings(
                session,
                raw=raw,
                source=parsed.source or "json",
                sync=parsed.sync,
                scan_id=parsed.scan_id,
                handoff_sha256=parsed.handoff_sha256,
            )
        elif command == "adapter":
            raw, error = _run_adapter_command(parsed.adapter_cmd)
            if error:
                raise FindingsFormatError(error)
            _ingest_native_findings(
                session,
                raw=raw or "",
                source=parsed.source or "adapter",
                sync=parsed.sync,
                scan_id=parsed.scan_id,
            )

        remote_threads: list[dict] = []
        if command in {"address", "review", "threads", "adapter"}:
            client = GitHubClient()
            remote_threads = client.list_threads(repo, pr_number)
            session = core_gate.session_with_remote_threads(session, remote_threads)
        _recalc_native_metrics(session)
        if auto_simple and _blocking_local_items(session):
            next_action = (
                "Auto-simple only handles GitHub review threads. Run normal review/findings/adapter workflow "
                "to handle local findings, then rerun this command."
            )
            item = _blocking_local_items(session)[0]
            _set_loop_state(
                session,
                run_id=run_id,
                status="BLOCKED",
                iteration=1,
                max_iterations=parsed.max_iterations,
                current_item_id=item.get("item_id"),
                last_error=next_action,
            )
            _recalc_native_metrics(session)
            session_store.save_session(repo, pr_number, session)
            summary = _native_summary(
                command=command,
                repo=repo,
                pr_number=pr_number,
                status="BLOCKED",
                reason_code="AUTO_SIMPLE_NOT_ELIGIBLE",
                waiting_on="local_findings",
                next_action=next_action,
                exit_code=5,
                session=session,
                item=item,
                include_threads=True,
                lean=lean,
            )
            _emit_native_summary(summary, human=human)
            return 5
        result = core_gate.evaluate_final_gate(session, remote_threads=remote_threads)
    except (FindingsFormatError, OSError) as exc:
        _set_loop_state(
            session,
            run_id=run_id,
            status="BLOCKED",
            iteration=1,
            max_iterations=parsed.max_iterations,
            last_error=str(exc),
        )
        _recalc_native_metrics(session)
        session_store.save_session(repo, pr_number, session)
        summary = _native_summary(
            command=command,
            repo=repo,
            pr_number=pr_number,
            status="BLOCKED",
            reason_code="INVALID_FINDINGS_INPUT",
            waiting_on="findings_input",
            next_action=str(exc),
            exit_code=2,
            session=session,
            lean=lean,
        )
        _emit_native_summary(summary, human=human)
        return 2
    except GitHubError as exc:
        _set_loop_state(
            session,
            run_id=run_id,
            status="BLOCKED",
            iteration=1,
            max_iterations=parsed.max_iterations,
            last_error=str(exc),
        )
        _recalc_native_metrics(session)
        session_store.save_session(repo, pr_number, session)
        summary = _native_summary(
            command=command,
            repo=repo,
            pr_number=pr_number,
            status="BLOCKED",
            reason_code=exc.reason_code,
            waiting_on=github_waiting_on(exc.diagnostics),
            next_action=str(exc),
            exit_code=5,
            session=session,
            diagnostics=exc.diagnostics,
            lean=lean,
        )
        _emit_native_summary(summary, human=human)
        return 5

    if auto_simple and not result.passed:
        if _auto_simple_local_gate_failed(result):
            next_action = (
                "Auto-simple only handles GitHub review threads. Run normal review/findings/adapter workflow "
                "to handle local findings, then rerun this command."
            )
            item = _first_local_item(session) or _first_blocking_item(session)
            _set_loop_state(
                session,
                run_id=run_id,
                status="BLOCKED",
                iteration=1,
                max_iterations=parsed.max_iterations,
                current_item_id=item.get("item_id") if item else None,
                last_error=next_action,
            )
            _recalc_native_metrics(session)
            session_store.save_session(repo, pr_number, session)
            summary = _native_summary(
                command=command,
                repo=repo,
                pr_number=pr_number,
                status="BLOCKED",
                reason_code="AUTO_SIMPLE_NOT_ELIGIBLE",
                waiting_on="local_findings",
                next_action=next_action,
                exit_code=5,
                session=session,
                item=item,
                include_threads=True,
                lean=lean,
            )
            _emit_native_summary(summary, human=human)
            return 5
        item = _first_blocking_item(session)
        request_path = _write_simple_address_request(repo, pr_number, session, command=command, run_id=run_id)
        next_action = (
            "Address GitHub review threads with per-thread agent evidence, then run "
            f"`gh-address-cr agent publish {repo} {pr_number}` and rerun this command."
        )
        _set_loop_state(
            session,
            run_id=run_id,
            status="BLOCKED",
            iteration=1,
            max_iterations=parsed.max_iterations,
            current_item_id=item.get("item_id") if item else None,
            last_error=next_action,
        )
        _recalc_native_metrics(session)
        session_store.save_session(repo, pr_number, session)
        summary = _native_summary(
            command=command,
            repo=repo,
            pr_number=pr_number,
            status="BLOCKED",
            reason_code="WAITING_FOR_SIMPLE_ADDRESS",
            waiting_on="agent_fix",
            next_action=next_action,
            exit_code=5,
            session=session,
            artifact_path=str(request_path),
            item=item,
            include_threads=True,
            lean=lean,
        )
        _emit_native_summary(summary, human=human)
        return 5

    if not result.passed:
        item = _first_blocking_item(session)
        artifact_path = None
        reason_code = "BLOCKING_ITEMS_REMAIN"
        waiting_on = "unresolved_items"
        next_action = result.to_machine_summary()["next_action"]
        if item and item.get("item_kind") == "local_finding":
            request_path = _write_native_action_request(repo, pr_number, item, command=command, run_id=run_id)
            artifact_path = str(request_path)
            reason_code = "WAITING_FOR_FIX"
            waiting_on = "human_fix"
            next_action = (
                "Address the finding by running: "
                f"`gh-address-cr submit-action {request_path} --resolution <fix|clarify|defer> "
                f"--note <note> -- gh-address-cr {command} {repo} {pr_number}`"
            )
        _set_loop_state(
            session,
            run_id=run_id,
            status="BLOCKED",
            iteration=1,
            max_iterations=parsed.max_iterations,
            current_item_id=item.get("item_id") if item else None,
            last_error=next_action,
        )
        _recalc_native_metrics(session)
        session_store.save_session(repo, pr_number, session)
        summary = _native_summary(
            command=command,
            repo=repo,
            pr_number=pr_number,
            status="BLOCKED",
            reason_code=reason_code,
            waiting_on=waiting_on,
            next_action=next_action,
            exit_code=5,
            session=session,
            artifact_path=artifact_path,
            item=item,
            lean=lean,
        )
        _emit_native_summary(summary, human=human)
        return 5

    _set_loop_state(session, run_id=run_id, status="PASSED", iteration=1, max_iterations=parsed.max_iterations)
    _recalc_native_metrics(session)
    session_store.save_session(repo, pr_number, session)
    next_action = "No action required."
    if command == "findings":
        next_action = (
            f"Run `gh-address-cr review {repo} {pr_number}` to continue PR orchestration, "
            "including GitHub thread handling and final-gate checks."
        )
    summary = _native_summary(
        command=command,
        repo=repo,
        pr_number=pr_number,
        status="PASSED",
        reason_code="PASSED",
        waiting_on=None,
        next_action=next_action,
        exit_code=0,
        session=session,
        include_threads=auto_simple,
        lean=lean,
    )
    _emit_native_summary(summary, human=human)
    return 0


def _emit_native_summary(summary: dict, *, human: bool) -> None:
    persist_machine_summary(str(summary["repo"]), str(summary["pr_number"]), summary)
    if human:
        status = summary["status"]
        if status == "PASSED":
            print("cr-loop PASSED")
        elif status == "BLOCKED":
            print("cr-loop BLOCKED")
            print(summary["next_action"])
        else:
            print(f"cr-loop {status}")
        return
    sys.stdout.write(json.dumps(summary, indent=2, sort_keys=True) + "\n")


def build_agent_manifest() -> dict:
    return {
        "status": "MANIFEST_READY",
        "schema_version": PROTOCOL_VERSION,
        "runtime_package": "gh-address-cr",
        "runtime_version": __version__,
        "agent_id": "gh-address-cr-runtime",
        "protocol_versions": list(SUPPORTED_PROTOCOL_VERSIONS),
        "supported_protocol_versions": list(SUPPORTED_PROTOCOL_VERSIONS),
        "supported_skill_contract_versions": list(SUPPORTED_SKILL_CONTRACT_VERSIONS),
        "roles": [
            "coordinator",
            "review_producer",
            "triage",
            "fixer",
            "verifier",
            "publisher",
            "gatekeeper",
        ],
        "actions": [
            "review",
            "produce_findings",
            "triage",
            "classify",
            "fix",
            "fix_all",
            "evidence",
            "clarify",
            "defer",
            "reject",
            "verify",
            "publish",
            "gate",
            "resolve_stale",
        ],
        "input_formats": [
            "action_request.v1",
            "finding.v1",
            "github_thread.v1",
            "evidence_profile.v1",
        ],
        "output_formats": [
            "action_response.v1",
            "batch_action_response.v1",
            "evidence_record.v1",
            "evidence_profile.v1",
            "gate_report.v1",
        ],
        "constraints": {
            "max_parallel_claims": MAX_PARALLEL_CLAIMS,
        },
        "public_commands": sorted(
            ["active-pr", "address", "review", "threads", "findings", "adapter", "doctor", "submit-action", "final-gate"]
        ),
    }


def handle_agent_command(args: argparse.Namespace) -> int:
    if args.repo in {None, "-h", "--help"}:
        sys.stdout.write(
            "usage: gh-address-cr agent {manifest,classify,next,submit,submit-batch,fix,fix-all,resolve-stale,evidence,publish,leases,reclaim,orchestrate} ...\n\n"
            "Agent protocol utilities.\n"
        )
        return 0
    if args.repo == "manifest" and not args.pr_number and not args.args:
        sys.stdout.write(json.dumps(build_agent_manifest(), indent=2, sort_keys=True) + "\n")
        return 0
    if args.repo == "classify":
        return handle_agent_classify(args.pr_number, args.args)
    if args.repo == "next":
        return handle_agent_next(args.pr_number, args.args)
    if args.repo == "submit":
        return handle_agent_submit(args.pr_number, args.args)
    if args.repo == "submit-batch":
        return handle_agent_submit_batch(args.pr_number, args.args)
    if args.repo == "fix":
        return handle_agent_fix(args.pr_number, args.args)
    if args.repo == "fix-all":
        return handle_agent_fix_all(args.pr_number, args.args)
    if args.repo == "resolve-stale":
        return handle_agent_resolve_stale(args.pr_number, args.args)
    if args.repo == "evidence":
        return handle_agent_evidence(args.pr_number, args.args)
    if args.repo == "publish":
        return handle_agent_publish(args.pr_number, args.args)
    if args.repo == "leases":
        return handle_agent_leases(args.pr_number, args.args)
    if args.repo == "reclaim":
        return handle_agent_reclaim(args.pr_number, args.args)
    if args.repo == "orchestrate":
        return handle_agent_orchestrate(args.pr_number, args.args)
    print(
        "Unknown agent command. Supported commands: manifest, classify, next, submit, submit-batch, fix, fix-all, resolve-stale, evidence, publish, leases, reclaim, orchestrate.",
        file=sys.stderr,
    )
    return 2


def handle_agent_classify(repo: str | None, passthrough: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="gh-address-cr agent classify")
    parser.add_argument("repo")
    parser.add_argument("pr_number")
    parser.add_argument("item_id")
    parser.add_argument("--classification", required=True, choices=["fix", "clarify", "defer", "reject"])
    parser.add_argument("--agent-id", default="agent")
    parser.add_argument("--note", required=True)
    parsed = parser.parse_args(_prepend_optional(repo, passthrough))
    try:
        payload = workflow.record_classification(
            parsed.repo,
            parsed.pr_number,
            item_id=parsed.item_id,
            classification=parsed.classification,
            agent_id=parsed.agent_id,
            note=parsed.note,
        )
    except workflow.WorkflowError as exc:
        return output_workflow_error(exc, repo=parsed.repo, pr_number=parsed.pr_number)
    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return 0


def handle_agent_next(repo: str | None, passthrough: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="gh-address-cr agent next")
    parser.add_argument("repo")
    parser.add_argument("pr_number")
    parser.add_argument("--role", required=True)
    parser.add_argument("--agent-id", default="agent")
    parser.add_argument("--item-id")
    parser.add_argument("--now")
    parsed = parser.parse_args(_prepend_optional(repo, passthrough))
    try:
        now_dt = None
        if parsed.now:
            now_dt = datetime.fromisoformat(parsed.now.replace("Z", "+00:00"))
        payload = workflow.issue_action_request(
            parsed.repo,
            parsed.pr_number,
            role=parsed.role,
            agent_id=parsed.agent_id,
            item_id=parsed.item_id,
            now=now_dt,
        )
    except workflow.WorkflowError as exc:
        return output_workflow_error(exc, repo=parsed.repo, pr_number=parsed.pr_number)
    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return 0


def handle_agent_submit(repo: str | None, passthrough: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="gh-address-cr agent submit")
    parser.add_argument("repo")
    parser.add_argument("pr_number")
    parser.add_argument("--input", required=True)
    parser.add_argument("--publish", action="store_true", help="Publish accepted GitHub-thread fix evidence immediately.")
    parser.add_argument("--now")
    parsed = parser.parse_args(_prepend_optional(repo, passthrough))
    try:
        now_dt = None
        if parsed.now:
            now_dt = datetime.fromisoformat(parsed.now.replace("Z", "+00:00"))
        payload = workflow.submit_action_response(
            parsed.repo,
            parsed.pr_number,
            response_path=parsed.input,
            now=now_dt,
            publish=parsed.publish,
        )
    except workflow.WorkflowError as exc:
        return output_workflow_error(exc, repo=parsed.repo, pr_number=parsed.pr_number)
    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return 0


def handle_agent_submit_batch(repo: str | None, passthrough: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="gh-address-cr agent submit-batch",
        description="Submit a BatchActionResponse with common fix evidence for multiple GitHub review threads.",
    )
    parser.add_argument("repo")
    parser.add_argument("pr_number")
    parser.add_argument("--input", required=True, help="Path to a BatchActionResponse JSON file.")
    parser.add_argument("--now")
    parsed = parser.parse_args(_prepend_optional(repo, passthrough))
    try:
        now_dt = None
        if parsed.now:
            now_dt = datetime.fromisoformat(parsed.now.replace("Z", "+00:00"))
        payload = workflow.submit_batch_action_response(
            parsed.repo,
            parsed.pr_number,
            batch_path=parsed.input,
            now=now_dt,
        )
    except workflow.WorkflowError as exc:
        return output_workflow_error(exc, repo=parsed.repo, pr_number=parsed.pr_number)
    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return 0


def _parse_agent_files(files: str | None, extra_files: list[str] | None = None) -> list[str]:
    values: list[str] = []
    if files:
        values.extend(part.strip() for part in files.split(",") if part.strip())
    for item in extra_files or []:
        values.extend(part.strip() for part in item.split(",") if part.strip())
    return values


def _parse_agent_validation(values: list[str] | None) -> list[dict[str, str]]:
    commands: list[dict[str, str]] = []
    for raw in values or []:
        command, result = _split_agent_validation_record(raw.strip())
        if command and result:
            commands.append({"command": command, "result": result})
    return commands


def _split_agent_validation_record(raw: str) -> tuple[str, str]:
    command, separator, result = raw.rpartition("=")
    if not separator or not _looks_like_agent_validation_result(result):
        return raw.strip(), "passed"
    return command.strip(), result.strip()


def _looks_like_agent_validation_result(value: str) -> bool:
    normalized = value.strip().lower()
    if not normalized or any(char.isspace() for char in normalized):
        return False
    return normalized in {"pass", "passed", "success", "succeeded", "ok", "fail", "failed", "error", "skipped"}


def _changed_files_for_commit(
    commit_hash: str,
    *,
    rejected_status: str = "FAST_FIX_ALL_REJECTED",
    command_name: str = "agent fix-all",
) -> list[str]:
    commit = commit_hash.strip()
    if not commit:
        return []
    if commit.startswith("-"):
        raise workflow.WorkflowError(
            status=rejected_status,
            reason_code="INVALID_COMMIT_HASH",
            waiting_on="git_commit",
            exit_code=2,
            message=f"{command_name} requires a commit-ish that does not start with '-'.",
        )
    commands = [
        ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", commit],
        ["git", "show", "--format=", "--name-only", commit],
    ]
    last_error = ""
    for command in commands:
        result = subprocess.run(command, text=True, capture_output=True)
        if result.returncode != 0:
            last_error = result.stderr.strip() or result.stdout.strip()
            continue
        files = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if files:
            return files
    raise workflow.WorkflowError(
        status=rejected_status,
        reason_code="COMMIT_FILES_UNAVAILABLE",
        waiting_on="git_commit",
        exit_code=2,
        message=last_error or f"Could not determine changed files for commit {commit}. Pass --files explicitly.",
    )


def handle_agent_fix(repo: str | None, passthrough: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="gh-address-cr agent fix",
        description="Classify, claim, submit, and optionally publish one GitHub review-thread fix.",
    )
    parser.add_argument("repo")
    parser.add_argument("pr_number")
    parser.add_argument("item_id")
    parser.add_argument("--agent-id", default="agent")
    parser.add_argument("--commit", required=True)
    parser.add_argument("--files")
    parser.add_argument("--file", action="append", default=[])
    parser.add_argument("--summary", required=True)
    parser.add_argument("--why", required=True)
    parser.add_argument("--validation", "--validation-cmd", dest="validation", action="append", default=[])
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--now")
    parsed = parser.parse_args(_prepend_optional(repo, passthrough))
    try:
        now_dt = None
        if parsed.now:
            now_dt = datetime.fromisoformat(parsed.now.replace("Z", "+00:00"))
        payload = workflow.fast_fix_item(
            parsed.repo,
            parsed.pr_number,
            item_id=parsed.item_id,
            agent_id=parsed.agent_id,
            commit_hash=parsed.commit,
            files=_parse_agent_files(parsed.files, parsed.file),
            validation_commands=_parse_agent_validation(parsed.validation),
            summary=parsed.summary,
            why=parsed.why,
            publish=parsed.publish,
            now=now_dt,
        )
    except workflow.WorkflowError as exc:
        return output_workflow_error(exc, repo=parsed.repo, pr_number=parsed.pr_number)
    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return 0


def handle_agent_fix_all(repo: str | None, passthrough: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="gh-address-cr agent fix-all",
        description="Classify, claim, and submit shared fix evidence for matching GitHub review threads.",
    )
    parser.add_argument("repo")
    parser.add_argument("pr_number")
    parser.add_argument("--agent-id", default="agent")
    parser.add_argument("--commit", required=True)
    parser.add_argument("--files")
    parser.add_argument("--file", action="append", default=[])
    parser.add_argument("--validation", "--validation-cmd", dest="validation", action="append", default=[])
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--include-stale", action="store_true")
    parser.add_argument("--now")
    parsed = parser.parse_args(_prepend_optional(repo, passthrough))
    try:
        now_dt = None
        if parsed.now:
            now_dt = datetime.fromisoformat(parsed.now.replace("Z", "+00:00"))
        files = _parse_agent_files(parsed.files, parsed.file)
        if not files:
            files = _changed_files_for_commit(parsed.commit)
        payload = workflow.fast_fix_matching_threads(
            parsed.repo,
            parsed.pr_number,
            agent_id=parsed.agent_id,
            commit_hash=parsed.commit,
            files=files,
            validation_commands=_parse_agent_validation(parsed.validation),
            include_stale=parsed.include_stale,
            publish=parsed.publish,
            now=now_dt,
        )
    except workflow.WorkflowError as exc:
        return output_workflow_error(exc, repo=parsed.repo, pr_number=parsed.pr_number)
    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return 0


def handle_agent_resolve_stale(repo: str | None, passthrough: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="gh-address-cr agent resolve-stale",
        description="Submit runtime-mediated evidence for stale GitHub review threads matching changed files.",
    )
    parser.add_argument("repo")
    parser.add_argument("pr_number")
    parser.add_argument("--agent-id", default="agent")
    parser.add_argument("--commit", required=True)
    parser.add_argument("--files")
    parser.add_argument("--file", action="append", default=[])
    parser.add_argument("--validation", "--validation-cmd", dest="validation", action="append", default=[])
    parser.add_argument("--match-files", action="store_true")
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--now")
    parsed = parser.parse_args(_prepend_optional(repo, passthrough))
    try:
        if not parsed.match_files:
            raise workflow.WorkflowError(
                status="STALE_RESOLUTION_REJECTED",
                reason_code="MISSING_MATCH_FILES",
                waiting_on="stale_resolution_input",
                exit_code=2,
                message="agent resolve-stale requires --match-files so stale synchronization stays file-scoped.",
            )
        now_dt = None
        if parsed.now:
            now_dt = datetime.fromisoformat(parsed.now.replace("Z", "+00:00"))
        files = _parse_agent_files(parsed.files, parsed.file)
        if not files:
            files = _changed_files_for_commit(
                parsed.commit,
                rejected_status="STALE_RESOLUTION_REJECTED",
                command_name="agent resolve-stale",
            )
        payload = workflow.fast_fix_matching_threads(
            parsed.repo,
            parsed.pr_number,
            agent_id=parsed.agent_id,
            commit_hash=parsed.commit,
            files=files,
            validation_commands=_parse_agent_validation(parsed.validation),
            include_stale=True,
            stale_only=True,
            publish=parsed.publish,
            now=now_dt,
        )
    except workflow.WorkflowError as exc:
        return output_workflow_error(exc, repo=parsed.repo, pr_number=parsed.pr_number)
    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return 0


def handle_agent_evidence(repo: str | None, passthrough: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="gh-address-cr agent evidence")
    parser.add_argument("subcommand", choices=["add", "list"])
    parser.add_argument("repo")
    parser.add_argument("pr_number")
    parser.add_argument("--name")
    parser.add_argument("--agent-id", default="agent")
    parser.add_argument("--commit")
    parser.add_argument("--files")
    parser.add_argument("--file", action="append", default=[])
    parser.add_argument("--validation", "--validation-cmd", dest="validation", action="append", default=[])
    parser.add_argument("--summary")
    parser.add_argument("--why")
    parser.add_argument("--test-command")
    parser.add_argument("--test-result")
    parser.add_argument("--now")
    parsed = parser.parse_args(_prepend_optional(repo, passthrough))
    try:
        if parsed.subcommand == "list":
            payload = workflow.list_evidence_profiles(parsed.repo, parsed.pr_number)
        else:
            if not parsed.name:
                raise workflow.WorkflowError(
                    status="EVIDENCE_PROFILE_REJECTED",
                    reason_code="MISSING_EVIDENCE_PROFILE_NAME",
                    waiting_on="evidence_profile",
                    exit_code=2,
                    message="agent evidence add requires --name.",
                )
            now_dt = None
            if parsed.now:
                now_dt = datetime.fromisoformat(parsed.now.replace("Z", "+00:00"))
            payload = workflow.record_evidence_profile(
                parsed.repo,
                parsed.pr_number,
                name=parsed.name,
                agent_id=parsed.agent_id,
                commit_hash=parsed.commit or "",
                files=_parse_agent_files(parsed.files, parsed.file),
                validation_commands=_parse_agent_validation(parsed.validation),
                summary=parsed.summary,
                why=parsed.why,
                test_command=parsed.test_command,
                test_result=parsed.test_result,
                now=now_dt,
            )
    except workflow.WorkflowError as exc:
        return output_workflow_error(exc, repo=parsed.repo, pr_number=parsed.pr_number)
    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return 0


def handle_agent_publish(repo: str | None, passthrough: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="gh-address-cr agent publish")
    parser.add_argument("repo")
    parser.add_argument("pr_number")
    parser.add_argument("--agent-id", default="gh-address-cr-publisher")
    parser.add_argument("--now")
    parsed = parser.parse_args(_prepend_optional(repo, passthrough))
    try:
        now_dt = None
        if parsed.now:
            now_dt = datetime.fromisoformat(parsed.now.replace("Z", "+00:00"))
        payload = workflow.publish_github_thread_responses(
            parsed.repo,
            parsed.pr_number,
            agent_id=parsed.agent_id,
            now=now_dt,
        )
    except workflow.WorkflowError as exc:
        return output_workflow_error(exc, repo=parsed.repo, pr_number=parsed.pr_number)
    except Exception as exc:
        return output_generic_agent_error(parsed.repo, parsed.pr_number, "PUBLISH_ERROR", str(exc))
    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return 0


def handle_agent_leases(repo: str | None, passthrough: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="gh-address-cr agent leases")
    parser.add_argument("repo")
    parser.add_argument("pr_number")
    parsed = parser.parse_args(_prepend_optional(repo, passthrough))
    try:
        payload = workflow.list_leases(parsed.repo, parsed.pr_number)
    except workflow.WorkflowError as exc:
        return output_workflow_error(exc, repo=parsed.repo, pr_number=parsed.pr_number)
    except Exception as exc:
        return output_generic_agent_error(parsed.repo, parsed.pr_number, "SESSION_ERROR", str(exc))
    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return 0


def handle_agent_reclaim(repo: str | None, passthrough: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="gh-address-cr agent reclaim")
    parser.add_argument("repo")
    parser.add_argument("pr_number")
    parser.add_argument("--now")
    parsed = parser.parse_args(_prepend_optional(repo, passthrough))
    now = datetime.fromisoformat(parsed.now.replace("Z", "+00:00")) if parsed.now else None
    try:
        payload = workflow.reclaim_leases(parsed.repo, parsed.pr_number, now=now)
    except workflow.WorkflowError as exc:
        return output_workflow_error(exc, repo=parsed.repo, pr_number=parsed.pr_number)
    except Exception as exc:
        return output_generic_agent_error(parsed.repo, parsed.pr_number, "SESSION_ERROR", str(exc))
    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return 0


def handle_agent_orchestrate(repo: str | None, passthrough: list[str]) -> int:
    from gh_address_cr.orchestrator import harness

    return harness.handle_agent_orchestrate(repo, passthrough)


def handle_superpowers_command(args: argparse.Namespace) -> int:
    if args.repo != "check":
        print(f"Unknown superpowers subcommand: {args.repo}. Did you mean 'check'?", file=sys.stderr)
        return 2

    # Simple scanner for superpowers bridge verification
    required_skills = [
        "verification-before-completion",
        "test-driven-development",
        "systematic-debugging",
        "receiving-code-review",
        "finishing-a-development-branch",
    ]
    optional_skills = [
        "fail-fast-loud",
        "dispatching-parallel-agents",
        "code-review",
    ]

    global_root = Path.home() / ".agents" / "skills"

    lines = [
        "# Superpowers Bridge Report",
        "",
        "This report verifies the presence of required and optional skills for the gh-address-cr control plane.",
        "",
        "## Required Skills",
        "",
    ]

    for skill in required_skills:
        global_path = global_root / skill
        status = "✅ Found" if global_path.is_dir() else "❌ Missing"
        lines.append(f"- **{skill}**: {status} (at {global_path})")

    lines.extend(["", "## Optional Skills", ""])
    for skill in optional_skills:
        global_path = global_root / skill
        status = "✅ Found" if global_path.is_dir() else "⚪ Missing"
        lines.append(f"- **{skill}**: {status} (at {global_path})")

    content = "\n".join(lines) + "\n"
    Path("superpowers-bridge-report.md").write_text(content, encoding="utf-8")
    sys.stdout.write(content)
    return 0


def handle_final_gate(repo: str | None, pr_number: str | None, passthrough: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="gh-address-cr final-gate")
    auto_group = parser.add_mutually_exclusive_group()
    auto_group.add_argument("--auto-clean", dest="auto_clean", action="store_true")
    auto_group.add_argument("--no-auto-clean", dest="auto_clean", action="store_false")
    parser.set_defaults(auto_clean=True)
    parser.add_argument("--audit-id", default="default")
    parser.add_argument("--snapshot", default="")
    checks_group = parser.add_mutually_exclusive_group()
    checks_group.add_argument("--require-checks", action="store_true", help="Require all PR checks to be green.")
    checks_group.add_argument(
        "--require-required-checks",
        action="store_true",
        help="Require required PR checks to be green.",
    )
    parser.add_argument("repo")
    parser.add_argument("pr_number")
    parsed = parser.parse_args(_prepend_optional(repo, _prepend_optional(pr_number, passthrough)))
    try:
        result = core_gate.Gatekeeper().run(
            parsed.repo,
            parsed.pr_number,
            snapshot_path=parsed.snapshot or None,
            require_checks=parsed.require_checks,
            require_required_checks=parsed.require_required_checks,
        )
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Final gate failed to evaluate: {exc}", file=sys.stderr)
        return 5

    _write_native_final_gate_artifacts(parsed.repo, parsed.pr_number, parsed.audit_id, result)
    _emit_final_gate_result(result)
    if not result.passed:
        print(f"\nGate FAILED: {_final_gate_failure_message(result)}. Do not send completion summary.", file=sys.stderr)
        return result.exit_code

    if parsed.auto_clean:
        _archive_and_clean_workspace(parsed.repo, parsed.pr_number, parsed.audit_id)
    return 0


def _emit_final_gate_result(result: core_gate.GateResult) -> None:
    print("== Final Freshness Check ==")
    print(f"Unresolved thread count: {result.counts['unresolved_remote_threads_count']}")
    print(f"Pending review count: {result.counts['pending_current_login_review_count']}")
    if result.check_requirement:
        print(
            "PR checks: "
            f"{result.counts['pr_checks_failed_count']} failed, "
            f"{result.counts['pr_checks_pending_count']} pending "
            f"({result.check_requirement})"
        )
    print()
    if result.passed:
        print("== Gate Result ==")
        print("Verified: 0 Unresolved Threads found")
        print("Verified: 0 Pending Reviews found")
        if result.check_requirement:
            print("Verified: 0 Non-green PR Checks found")
        print(f"Session blocking items: {result.counts['blocking_items_count']}")
    else:
        print("== Gate Result ==")
        print(f"Gate FAILED: {_final_gate_failure_message(result)}")
    print()
    print("== Machine Gate Diagnostics ==")
    for key in core_gate.COUNT_KEYS:
        print(f"{key}={result.counts[key]}")
    print(f"reason_code={result.reason_code or 'PASSED'}")
    print(f"exit_code={result.exit_code}")


def _write_native_final_gate_artifacts(
    repo: str,
    pr_number: str,
    audit_id: str,
    result: core_gate.GateResult,
) -> None:
    workspace = session_store.workspace_dir(repo, pr_number)
    timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    run_id = audit_id or "final-gate"
    summary_path = workspace / core_paths.audit_summary_file(repo, pr_number).name
    audit_path = workspace / core_paths.audit_log_file(repo, pr_number).name
    trace_path = workspace / "trace.jsonl"
    status = "ok" if result.passed else "failed"
    summary_lines = [
        "# Audit Summary",
        "",
        f"- repo: {repo}",
        f"- pr: {pr_number}",
        f"- run_id: {run_id}",
        f"- final_gate_status: {status}",
        f"- reason_code: {result.reason_code or 'PASSED'}",
        f"- check_requirement: {result.check_requirement or 'none'}",
    ]
    summary_lines.extend(f"- {key}: {result.counts[key]}" for key in core_gate.COUNT_KEYS)
    if result.failure_codes:
        summary_lines.extend(["", "## Failure Codes", *[f"- {code}" for code in result.failure_codes]])
    summary_path.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    summary_sha256 = hashlib.sha256(summary_path.read_bytes()).hexdigest()
    audit_entry = {
        "ts": timestamp,
        "run_id": run_id,
        "audit_id": run_id,
        "repo": repo,
        "pr": str(pr_number),
        "action": "final-gate",
        "status": status,
        "message": "Evaluated native final gate",
        "details": {
            "counts": dict(result.counts),
            "failure_codes": list(result.failure_codes),
            "check_requirement": result.check_requirement,
            "summary_file": str(summary_path),
            "summary_sha256": summary_sha256,
        },
    }
    trace_entry = {
        "ts": timestamp,
        "run_id": run_id,
        "repo": repo,
        "pr": str(pr_number),
        "event": "final_gate",
        "status": status,
        "reason_code": result.reason_code or "PASSED",
        "counts": dict(result.counts),
        "check_requirement": result.check_requirement,
    }
    for path, entry in ((audit_path, audit_entry), (trace_path, trace_entry)):
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")


def _final_gate_failure_message(result: core_gate.GateResult) -> str:
    reasons: list[str] = []
    if result.counts["unresolved_remote_threads_count"]:
        reasons.append(f"{result.counts['unresolved_remote_threads_count']} unresolved thread(s)")
    if result.counts["blocking_local_items_count"]:
        reasons.append(f"{result.counts['blocking_local_items_count']} blocking item(s)")
    if result.counts["github_threads_missing_reply_count"]:
        reasons.append(f"{result.counts['github_threads_missing_reply_count']} GitHub thread(s) missing reply evidence")
    if result.counts["pending_current_login_review_count"]:
        reasons.append(f"{result.counts['pending_current_login_review_count']} pending review(s)")
    if result.counts["missing_validation_evidence_count"]:
        reasons.append(
            f"{result.counts['missing_validation_evidence_count']} local item(s) missing validation evidence"
        )
    if result.counts["pr_checks_not_green_count"]:
        reasons.append(f"{result.counts['pr_checks_not_green_count']} non-green PR check(s)")
    return " and ".join(reasons) or "gate checks reported failure"


def _archive_and_clean_workspace(repo: str, pr_number: str, audit_id: str) -> None:
    workspace = session_store.workspace_dir(repo, pr_number)
    if not workspace.exists():
        return
    archive_root = core_paths.state_dir() / "archive" / core_paths.normalize_repo(repo) / f"pr-{pr_number}"
    archive_root.mkdir(parents=True, exist_ok=True)
    base_name = audit_id or "final-gate"
    archive_target = archive_root / base_name
    suffix = 1
    while archive_target.exists():
        archive_target = archive_root / f"{base_name}-{suffix}"
        suffix += 1
    shutil.copytree(workspace, archive_target)
    shutil.rmtree(workspace, ignore_errors=True)
    print(f"Archived PR workspace: {archive_target}")
    print(f"Auto-cleaned PR workspace: {workspace}")


def _prepend_optional(value: str | None, args: list[str]) -> list[str]:
    return [*([value] if value else []), *args]


def output_workflow_error(exc: workflow.WorkflowError, *, repo: str, pr_number: str) -> int:
    sys.stdout.write(json.dumps(exc.to_summary(repo=repo, pr_number=pr_number), indent=2, sort_keys=True) + "\n")
    print(str(exc), file=sys.stderr)
    return exc.exit_code


def output_generic_agent_error(repo: str, pr_number: str, reason_code: str, message: str) -> int:
    payload = {
        "status": "FAILED",
        "repo": repo,
        "pr_number": pr_number,
        "reason_code": reason_code,
        "waiting_on": "session",
        "next_action": message,
        "exit_code": 5,
    }
    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(message, file=sys.stderr)
    return 5


def _root_passthrough_args(args: argparse.Namespace) -> list[str]:
    return [*([args.repo] if args.repo else []), *([args.pr_number] if args.pr_number else []), *args.args]


def _emit_active_pr_payload(payload: dict, *, stderr: str | None = None) -> int:
    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    if stderr:
        print(stderr, file=sys.stderr)
    return int(payload["exit_code"])


def _git_output(command: list[str]) -> str:
    result = subprocess.run(command, text=True, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f"{' '.join(command)} failed.")
    return result.stdout.strip()


def _derive_current_branch() -> str:
    branch = _git_output(["git", "branch", "--show-current"])
    if not branch:
        raise RuntimeError("Current git branch is detached or empty. Pass --head explicitly.")
    return branch


def _derive_current_repo() -> str:
    remote_url = _git_output(["git", "config", "--get", "remote.origin.url"])
    normalized = remote_url.strip().rstrip("/").removesuffix(".git")
    patterns = (
        r"^git@github\.com:(?P<repo>[^/]+/[^/]+)$",
        r"^ssh://git@github\.com/(?P<repo>[^/]+/[^/]+)$",
        r"^https?://github\.com/(?P<repo>[^/]+/[^/]+)$",
    )
    for pattern in patterns:
        match = re.match(pattern, normalized)
        if match:
            return match.group("repo")
    raise RuntimeError(f"Could not derive owner/repo from remote.origin.url: {remote_url}")


def handle_active_pr_command(passthrough: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="gh-address-cr active-pr")
    parser.add_argument("--repo")
    parser.add_argument("--head")
    parsed = parser.parse_args(passthrough)
    try:
        repo = parsed.repo or _derive_current_repo()
        head = parsed.head or _derive_current_branch()
    except RuntimeError as exc:
        return _emit_active_pr_payload(
            {
                "status": "ACTIVE_PR_LOOKUP_FAILED",
                "repo": parsed.repo,
                "head": parsed.head,
                "reason_code": "ACTIVE_PR_TARGET_REQUIRED",
                "waiting_on": "active_pr_target",
                "next_action": f"{exc} Pass --repo <owner/repo> and --head <branch> explicitly.",
                "exit_code": 2,
            },
            stderr=str(exc),
        )

    command = [
        "gh",
        "pr",
        "list",
        "--repo",
        repo,
        "--state",
        "open",
        "--head",
        head,
        "--json",
        "number,url,headRefName,state",
    ]
    if shutil.which("gh") is None:
        return _emit_active_pr_payload(
            {
                "status": "ACTIVE_PR_LOOKUP_FAILED",
                "repo": repo,
                "head": head,
                "reason_code": "GH_NOT_FOUND",
                "waiting_on": "github_cli",
                "next_action": "Install GitHub CLI and ensure `gh` is available on PATH, then rerun active-pr.",
                "exit_code": PR_IO_PREFLIGHT_EXIT,
            },
            stderr="Missing GitHub CLI `gh` on PATH.",
        )
    result = subprocess.run(command, text=True, capture_output=True)
    if result.returncode != 0:
        diagnostics = classify_github_failure(result.stderr, result.stdout, result.returncode, command)
        return _emit_active_pr_payload(
            {
                "status": "ACTIVE_PR_LOOKUP_FAILED",
                "repo": repo,
                "head": head,
                "reason_code": "ACTIVE_PR_QUERY_FAILED",
                "waiting_on": github_waiting_on(diagnostics),
                "next_action": "Fix the GitHub CLI query failure, then rerun `gh-address-cr active-pr`.",
                "exit_code": PR_IO_PREFLIGHT_EXIT,
                "diagnostics": diagnostics,
            },
            stderr=result.stderr.strip() or result.stdout.strip() or "GitHub active PR lookup failed.",
        )
    try:
        pull_requests = json.loads(result.stdout or "[]")
    except json.JSONDecodeError as exc:
        return _emit_active_pr_payload(
            {
                "status": "ACTIVE_PR_LOOKUP_FAILED",
                "repo": repo,
                "head": head,
                "reason_code": "ACTIVE_PR_INVALID_JSON",
                "waiting_on": "github_cli",
                "next_action": "Inspect `gh pr list` output; it must be a JSON array.",
                "exit_code": PR_IO_PREFLIGHT_EXIT,
            },
            stderr=f"GitHub active PR lookup returned invalid JSON: {exc}",
        )
    if not isinstance(pull_requests, list):
        pull_requests = []

    if not pull_requests:
        return _emit_active_pr_payload(
            {
                "status": "NO_ACTIVE_PR",
                "repo": repo,
                "head": head,
                "reason_code": "NO_ACTIVE_PR",
                "waiting_on": "open_pr",
                "next_action": f"Open a PR or run `gh pr list --repo {repo} --state open --head {head}` to inspect candidates.",
                "pull_requests": [],
                "exit_code": 4,
            }
        )
    if len(pull_requests) > 1:
        return _emit_active_pr_payload(
            {
                "status": "AMBIGUOUS_ACTIVE_PR",
                "repo": repo,
                "head": head,
                "reason_code": "AMBIGUOUS_ACTIVE_PR",
                "waiting_on": "open_pr",
                "next_action": "Multiple OPEN PRs match this branch. Pass the intended PR number to review/address.",
                "pull_requests": pull_requests,
                "exit_code": 5,
            },
            stderr="Multiple OPEN PRs matched the active branch.",
        )

    pr = pull_requests[0] if isinstance(pull_requests[0], dict) else {}
    pr_number = str(pr.get("number") or "").strip()
    if not pr_number or not pr_number.isdigit():
        return _emit_active_pr_payload(
            {
                "status": "ACTIVE_PR_LOOKUP_FAILED",
                "repo": repo,
                "head": head,
                "reason_code": "ACTIVE_PR_INVALID_RESPONSE",
                "waiting_on": "github_cli",
                "next_action": f"Inspect `gh pr list --repo {repo} --state open --head {head}` output; each row must include a PR number.",
                "pull_requests": pull_requests,
                "exit_code": PR_IO_PREFLIGHT_EXIT,
            },
            stderr="GitHub active PR lookup returned a row without a valid PR number.",
        )
    return _emit_active_pr_payload(
        {
            "status": "ACTIVE_PR_FOUND",
            "repo": repo,
            "head": head,
            "pr_number": pr_number,
            "url": pr.get("url"),
            "state": pr.get("state"),
            "reason_code": "ACTIVE_PR_FOUND",
            "waiting_on": None,
            "next_action": f"Run `gh-address-cr address {repo} {pr_number} --lean`.",
            "exit_code": 0,
        }
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="gh-address-cr",
        description="Unified Python CLI for gh-address-cr.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--machine",
        action="store_true",
        help="Compatibility alias for the default structured JSON summary.",
    )
    parser.add_argument(
        "--human",
        action="store_true",
        help="Emit human-oriented text instead of the default machine summary.",
    )
    parser.add_argument(
        "--version",
        "-v",
        action="version",
        version=f"gh-address-cr {__version__}",
    )
    parser.add_argument(
        "command",
        metavar="{active-pr,address,review,threads,findings,adapter,doctor,review-to-findings,submit-feedback,submit-action,version}",
        help=(
            "High-level commands:\n"
            "  gh-address-cr active-pr [--repo owner/repo] [--head branch]\n"
            "  gh-address-cr address owner/repo 123 [--human|--lean|--summary]\n"
            "  gh-address-cr review owner/repo 123 [--human]\n"
            "  gh-address-cr review --auto-simple owner/repo 123 [--human|--lean|--summary]\n"
            "  gh-address-cr threads owner/repo 123 [--human|--lean|--summary]\n"
            "  gh-address-cr doctor [owner/repo] [123]\n"
            "  gh-address-cr version\n"
            "  gh-address-cr findings owner/repo 123 --input findings.json [--human]\n"
            "  gh-address-cr --human adapter owner/repo 123 python3 tools/review_adapter.py\n"
            "Notes:\n"
            "  review waits for external review findings when they are absent.\n"
            "  High-level commands are the agent-safe public surface.\n"
            "  For `adapter`, flags after <adapter_cmd...> are passed through to the adapter command.\n"
            "Utility commands:\n"
            "  gh-address-cr review-to-findings owner/repo 123 --input finding-blocks.md\n"
            "  gh-address-cr submit-feedback --category workflow-gap --title ... --summary ... --expected ... --actual ...\n"
            "  review-to-findings accepts fixed finding blocks only, not arbitrary Markdown.\n"
            "Runtime commands:\n"
            "  gh-address-cr agent manifest\n"
            "  gh-address-cr agent fix-all owner/repo 123 --commit <sha> --files <paths> --validation <cmd=passed>\n"
            "  gh-address-cr agent resolve-stale owner/repo 123 --commit <sha> --files <paths> --validation <cmd=passed> --match-files\n"
            "  gh-address-cr agent submit-batch owner/repo 123 --input batch-response.json\n"
            "  gh-address-cr final-gate owner/repo 123\n"
        ),
    )
    parser.add_argument("repo", nargs="?", help="Owner/repo name.")
    parser.add_argument("pr_number", nargs="?", help="Pull request number.")
    parser.add_argument("args", nargs=argparse.REMAINDER, help="Arguments passed through to the selected subcommand.")
    return parser.parse_args(argv)


def run_script(script_name: str, passthrough_args: list[str]) -> subprocess.CompletedProcess[str]:
    target = SCRIPT_DIR / script_name
    command = [sys.executable, str(target), *passthrough_args]
    if not target.is_file():
        return subprocess.CompletedProcess(
            command,
            127,
            "",
            f"Required gh-address-cr runtime script is missing: {target}\n",
        )
    module_name = f"gh_address_cr.legacy_scripts.{Path(script_name).stem}"
    stdout = io.StringIO()
    stderr = io.StringIO()
    previous_argv = sys.argv
    previous_sys_path = list(sys.path)
    previous_pythonpath = os.environ.get("PYTHONPATH")
    try:
        script_dir = str(SCRIPT_DIR)
        sys.path.insert(0, script_dir)
        runtime_import_root = str(Path(__file__).resolve().parents[1])
        pythonpath_parts = [part for part in (previous_pythonpath or "").split(os.pathsep) if part]
        if runtime_import_root not in pythonpath_parts:
            os.environ["PYTHONPATH"] = os.pathsep.join([runtime_import_root, *pythonpath_parts])
        module = importlib.import_module(module_name)
        script_main = getattr(module, "main", None)
        if not callable(script_main):
            return subprocess.CompletedProcess(
                command,
                127,
                "",
                f"Required gh-address-cr runtime script does not expose main(): {module_name}\n",
            )
        sys.argv = [str(target), *passthrough_args]
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                code = script_main()
            except SystemExit as exc:
                code = exc.code
    except Exception:
        traceback.print_exc(file=stderr)
        return subprocess.CompletedProcess(command, 1, stdout.getvalue(), stderr.getvalue())
    finally:
        sys.argv = previous_argv
        sys.path[:] = previous_sys_path
        if previous_pythonpath is None:
            os.environ.pop("PYTHONPATH", None)
        else:
            os.environ["PYTHONPATH"] = previous_pythonpath
    if code is None:
        returncode = 0
    elif isinstance(code, int):
        returncode = code
    else:
        stderr.write(f"{code}\n")
        returncode = 1
    return subprocess.CompletedProcess(command, returncode, stdout.getvalue(), stderr.getvalue())


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.command == "version":
        sys.stdout.write(f"gh-address-cr {__version__}\n")
        return 0

    if args.command == "agent":
        return handle_agent_command(args)

    if args.command == "active-pr":
        return handle_active_pr_command(_root_passthrough_args(args))

    if args.command == "doctor":
        if args.pr_number is None and (args.repo in {"-h", "--help"} or args.args[:1] in (["-h"], ["--help"])):
            print(alias_help(args.command), end="")
            return 0
        return handle_doctor_command(args)

    if args.command == "superpowers":
        return handle_superpowers_command(args)

    if args.command == "final-gate":
        if args.machine or args.human or getattr(args, "lean", False) or getattr(args, "summary", False):
            print(
                f"--machine and --human are only supported for {', '.join(sorted(HIGH_LEVEL_COMMANDS))}. "
                "--lean and --summary are only supported for address, review, and threads.",
                file=sys.stderr,
            )
            return 2
        return handle_final_gate(args.repo, args.pr_number, args.args)

    if args.command == "adapter" and args.repo == "check-runtime" and args.pr_number is None and not args.args:
        sys.stdout.write(json.dumps(workflow.runtime_compatibility(), indent=2, sort_keys=True) + "\n")
        return 0

    full_args = list(args.args)
    if args.pr_number:
        full_args = [args.pr_number, *full_args]
    if args.repo:
        full_args = [args.repo, *full_args]
    args.args = full_args

    if args.command == "submit-action":
        if args.args and args.args[0] in {"-h", "--help"}:
            print(alias_help(args.command), end="")
            return 0
        cmd = []
        if args.machine:
            cmd.append("--machine")
        if args.human:
            cmd.append("--human")
        passthrough = list(args.args)
        result = run_script("submit_action.py", [*cmd, *passthrough])
        if result.stdout:
            sys.stdout.write(result.stdout)
        if result.stderr:
            sys.stderr.write(result.stderr)
        return result.returncode

    if args.command not in COMMAND_TO_SCRIPT and args.command not in NATIVE_HIGH_LEVEL_COMMANDS:
        supported_commands = ", ".join(
            sorted([*COMMAND_TO_SCRIPT, *NATIVE_HIGH_LEVEL_COMMANDS, "active-pr", "agent", "doctor"])
        )
        print(f"Unknown command. Supported commands: {supported_commands}.", file=sys.stderr)
        return 2
    normalize_leading_high_level_options(args)
    if not normalize_output_args(args):
        return 2
    normalize_high_level_target_args(args)
    if args.command in HIGH_LEVEL_COMMANDS and args.args and args.args[0] in {"-h", "--help"}:
        print(alias_help(args.command), end="")
        return 0
    if args.command in HIGH_LEVEL_COMMANDS and len(args.args) < 2:
        print("High-level commands require <owner/repo> <pr_number> or <PR_URL>.", file=sys.stderr)
        return 2
    if args.command in HIGH_LEVEL_COMMANDS:
        preflight_rc = preflight_high_level(args)
        if preflight_rc is not None:
            return preflight_rc
    if args.command in NATIVE_HIGH_LEVEL_COMMANDS:
        return handle_native_high_level(args.command, args.args, human=args.human, lean=getattr(args, "lean", False))
    rewritten_args = rewrite_alias_args(
        args.command,
        args.args,
        review_continue_without_input=bool(getattr(args, "review_continue_without_input", False)),
    )
    result = run_script(COMMAND_TO_SCRIPT[args.command], rewritten_args)
    if args.command in HIGH_LEVEL_COMMANDS and not args.human:
        summary = build_machine_summary(args.command, args.args[0], args.args[1], result)
        persist_machine_summary(args.args[0], args.args[1], summary)
        sys.stdout.write(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    else:
        if result.stdout:
            sys.stdout.write(result.stdout)
        if result.stderr:
            error_text = result.stderr
            if args.command in HIGH_LEVEL_COMMANDS and "Unsupported producer:" in error_text:
                error_text += (
                    "\nproducer expects a category (`code-review`, `json`, `adapter`), not the upstream tool name.\n"
                )
            sys.stderr.write(error_text)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
