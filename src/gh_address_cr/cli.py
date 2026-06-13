from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from gh_address_cr import __version__
from gh_address_cr.commands.active_pr import handle_active_pr_command
from gh_address_cr.commands.agent import handle_agent_command
from gh_address_cr.commands.command_session import handle_command_session
from gh_address_cr.commands.common import (
    emit_scope_resolution_error as _emit_scope_resolution_error,
)
from gh_address_cr.commands.common import (
    maybe_prepend_implicit_scope as _maybe_prepend_implicit_scope,
)
from gh_address_cr.commands.common import (
    root_passthrough_args as _root_passthrough_args,
)
from gh_address_cr.commands.doctor import handle_doctor_command
from gh_address_cr.commands.final_gate import handle_final_gate
from gh_address_cr.commands.high_level import (
    HighLevelReviewRuntime,
    summary_commands,
)
from gh_address_cr.commands.telemetry import handle_telemetry_command
from gh_address_cr.core import session as session_store
from gh_address_cr.core import workflow
from gh_address_cr.core.io import write_json_atomic
from gh_address_cr.github.diagnostics import classify_github_failure
from gh_address_cr.intake.findings import (
    canonical_findings_payload,
)
from gh_address_cr.intake.findings import (
    normalize_finding as native_normalize_finding,
)
from gh_address_cr.intake.findings import (
    parse_finding_blocks as native_parse_finding_blocks,
)
from gh_address_cr.intake.findings import (
    parse_records as native_parse_records,
)

HIGH_LEVEL_COMMANDS = {"address", "review", "threads", "findings", "adapter", "submit-action", "version", "final-gate"}
NATIVE_HIGH_LEVEL_COMMANDS = {"address", "review", "threads", "findings", "adapter", "version"}
UTILITY_COMMANDS = {"review-to-findings", "submit-feedback", "submit-action"}
PUBLIC_COMMANDS = {
    *NATIVE_HIGH_LEVEL_COMMANDS,
    *UTILITY_COMMANDS,
    "active-pr",
    "agent",
    "command-session",
    "doctor",
    "final-gate",
    "telemetry",
}
PR_SCOPED_IMPLICIT_COMMANDS = {"address", "review", "threads", "final-gate"}
UNSUPPORTED_LEGACY_COMMANDS = {
    "audit-report",
    "batch-resolve",
    "clean-state",
    "code-review-adapter",
    "control-plane",
    "cr-loop",
    "generate-reply",
    "ingest-findings",
    "list-threads",
    "mark-handled",
    "post-reply",
    "prepare-code-review",
    "publish-finding",
    "resolve-thread",
    "run-local-review",
    "run-once",
    "session-engine",
}
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
    write_json_atomic(path, payload)


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
    write_json_atomic(normalized_path, findings)
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
        "commands": summary_commands(repo, pr_number),
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
        "artifact_path": artifact_path or str(session_store.workspace_dir(repo, pr_number)),
        "reason_code": reason_code,
        "waiting_on": waiting_on,
        "next_action": next_action,
        "exit_code": exit_code,
        "commands": summary_commands(repo, pr_number),
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


def handle_native_high_level(command: str, passthrough_args: list[str], *, human: bool, lean: bool = False) -> int:
    return HighLevelReviewRuntime().handle(command, passthrough_args, human=human, lean=lean)





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
        metavar="{active-pr,address,review,threads,findings,adapter,doctor,telemetry,command-session,final-gate,review-to-findings,submit-feedback,submit-action,version}",
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
            "  gh-address-cr agent submit-batch owner/repo 123 --input batch-response.json\n"
            "  gh-address-cr agent fix-all owner/repo 123 --input batch-response.json\n"
            "  gh-address-cr agent fix-all owner/repo 123 --commit <sha> --files <paths> --validation <cmd=passed> --homogeneous-reason <why>\n"
            "  gh-address-cr agent resolve-stale owner/repo 123 --commit <sha> --files <paths> --validation <cmd=passed> --match-files\n"
            "  gh-address-cr final-gate owner/repo 123\n"
            "  gh-address-cr telemetry ingest owner/repo 123 --source generic-agent --format agent-jsonl --input telemetry.jsonl\n"
            "  gh-address-cr telemetry summary owner/repo 123 [--format json|markdown]\n"
            "  gh-address-cr command-session --input commands.json\n"
        ),
    )
    parser.add_argument("repo", nargs="?", help="Owner/repo name.")
    parser.add_argument("pr_number", nargs="?", help="Pull request number.")
    parser.add_argument("args", nargs=argparse.REMAINDER, help="Arguments passed through to the selected subcommand.")
    return parser.parse_args(argv)


def _dispatch_management_commands(args) -> int | None:
    """Handle commands that run before target-arg expansion. Returns None if unhandled."""
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

    if args.command == "final-gate":
        if getattr(args, "lean", False) or getattr(args, "summary", False):
            print(
                "--lean and --summary are only supported for address, review, and threads.",
                file=sys.stderr,
            )
            return 2
        passthrough = list(args.args)
        if args.human and "--human" not in passthrough:
            passthrough.append("--human")
        if args.machine and "--machine" not in passthrough:
            passthrough.append("--machine")
        return handle_final_gate(args.repo, args.pr_number, passthrough)

    if args.command == "telemetry":
        if args.machine or args.human or getattr(args, "lean", False) or getattr(args, "summary", False):
            print(
                "--machine, --human, --lean, and --summary are not supported for telemetry commands.",
                file=sys.stderr,
            )
            return 2
        return handle_telemetry_command(args.repo, args.pr_number, args.args)

    if args.command == "command-session":
        if args.machine or args.human:
            print("--machine and --human are not supported for command-session.", file=sys.stderr)
            return 2
        return handle_command_session(_root_passthrough_args(args))

    if args.command == "adapter" and args.repo == "check-runtime" and args.pr_number is None and not args.args:
        sys.stdout.write(json.dumps(workflow.runtime_compatibility(), indent=2, sort_keys=True) + "\n")
        return 0

    return None


def _expand_target_args(args) -> None:
    """Fold the leading repo/pr_number positionals back into args.args."""
    full_args = list(args.args)
    if args.pr_number:
        full_args = [args.pr_number, *full_args]
    if args.repo:
        full_args = [args.repo, *full_args]
    args.args = full_args


def _dispatch_passthrough_commands(args) -> int | None:
    """Handle commands that delegate to a sub-handler module. Returns None if unhandled."""
    if args.command == "submit-action":
        if args.args and args.args[0] in {"-h", "--help"}:
            print(alias_help(args.command), end="")
            return 0
        from gh_address_cr.commands import submit_action as submit_action_handler

        cmd: list[str] = []
        if args.machine:
            cmd.append("--machine")
        if args.human:
            cmd.append("--human")
        rc = submit_action_handler.main([*cmd, *args.args])
        return rc if rc is not None else 0

    if args.command == "review-to-findings":
        if args.machine or args.human:
            print(
                f"--machine and --human are only supported for {', '.join(sorted(HIGH_LEVEL_COMMANDS))}.",
                file=sys.stderr,
            )
            return 2
        from gh_address_cr.commands import review_to_findings as review_to_findings_handler

        rc = review_to_findings_handler.main(args.args)
        return rc if rc is not None else 0

    if args.command == "submit-feedback":
        if args.machine or args.human:
            print(
                f"--machine and --human are only supported for {', '.join(sorted(HIGH_LEVEL_COMMANDS))}.",
                file=sys.stderr,
            )
            return 2
        from gh_address_cr.commands import submit_feedback as submit_feedback_handler

        rc = submit_feedback_handler.main(args.args)
        return rc if rc is not None else 0

    return None


def _dispatch_high_level_commands(args) -> int:
    """Handle legacy, unknown, and native high-level commands. Always returns a code."""
    if args.command in UNSUPPORTED_LEGACY_COMMANDS:
        print(
            f"Unsupported legacy command: {args.command}. "
            "Use current workflows such as `gh-address-cr review <owner/repo> <pr_number>`, "
            "`gh-address-cr address <owner/repo> <pr_number>`, or `gh-address-cr agent ...`.",
            file=sys.stderr,
        )
        return 2

    if args.command not in NATIVE_HIGH_LEVEL_COMMANDS:
        supported_commands = ", ".join(sorted(PUBLIC_COMMANDS))
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
        args.args, scope_error = _maybe_prepend_implicit_scope(args.args)
        if scope_error is not None:
            return _emit_scope_resolution_error(scope_error)
    if args.command in HIGH_LEVEL_COMMANDS:
        preflight_rc = preflight_high_level(args)
        if preflight_rc is not None:
            return preflight_rc
    return handle_native_high_level(args.command, args.args, human=args.human, lean=getattr(args, "lean", False))


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    rc = _dispatch_management_commands(args)
    if rc is not None:
        return rc

    _expand_target_args(args)

    rc = _dispatch_passthrough_commands(args)
    if rc is not None:
        return rc

    return _dispatch_high_level_commands(args)


if __name__ == "__main__":
    raise SystemExit(main())
