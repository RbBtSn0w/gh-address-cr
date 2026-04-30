from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from gh_address_cr import __version__, PROTOCOL_VERSION, SUPPORTED_PROTOCOL_VERSIONS, SUPPORTED_SKILL_CONTRACT_VERSIONS
from gh_address_cr.core import gate as core_gate
from gh_address_cr.core import paths as core_paths
from gh_address_cr.core import session as session_store
from gh_address_cr.core import workflow
from gh_address_cr.github.client import GitHubClient
from gh_address_cr.github.errors import GitHubError
from gh_address_cr.intake.findings import (
    FindingsFormatError,
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

HIGH_LEVEL_COMMANDS = {"review", "threads", "findings", "adapter", "submit-action"}
NATIVE_HIGH_LEVEL_COMMANDS = {"review", "threads", "findings", "adapter"}
OUTPUT_FLAGS = {"--machine", "--human"}
HIGH_LEVEL_GH_COMMANDS = {"review", "threads", "adapter"}
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


def normalize_output_args(args: argparse.Namespace) -> bool:
    inline_flags = inline_output_flags(args.command, args.args)
    requested_flags = set(inline_flags)
    if args.machine:
        requested_flags.add("--machine")
    if args.human:
        requested_flags.add("--human")
    if requested_flags == {"--machine", "--human"}:
        print("--machine and --human are mutually exclusive.", file=sys.stderr)
        return False
    if args.command not in HIGH_LEVEL_COMMANDS and requested_flags:
        print(
            f"--machine and --human are only supported for {', '.join(sorted(HIGH_LEVEL_COMMANDS))}.", file=sys.stderr
        )
        return False
    args.machine = "--machine" in requested_flags
    args.human = "--human" in requested_flags
    if args.command != "adapter":
        args.args = [arg for arg in args.args if arg not in OUTPUT_FLAGS]
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
            "usage: cli.py review <owner/repo> <pr_number> [--input <path>|-] [--human|--machine]\n\n"
            "High-level PR review entrypoint.\n\n"
            "Use when you want the full PR review workflow to run automatically.\n"
            "This command waits for external review findings when they are absent,\n"
            "then tells you to re-run the same review command once handoff artifacts are filled.\n"
            "You may still provide findings JSON explicitly via --input <path> or --input -.\n"
            "Default output is a structured JSON summary. Use --human for narrative text.\n"
            "--machine remains a compatibility alias for the default machine summary.\n"
        )
    if command == "threads":
        return (
            "usage: cli.py threads <owner/repo> <pr_number> [--human|--machine]\n\n"
            "High-level GitHub review-thread entrypoint.\n\n"
            "Use when only GitHub review threads need processing.\n"
            "Default output is a structured JSON summary. Use --human for narrative text.\n"
            "--machine remains a compatibility alias for the default machine summary.\n"
        )
    if command == "findings":
        return (
            "usage: cli.py findings <owner/repo> <pr_number> --input <path>|- [--source <producer_id>] [--sync] [--human|--machine]\n\n"
            "High-level local findings entrypoint.\n\n"
            "Use when findings already exist as JSON or are piped in through stdin.\n"
            "Missing --input fails immediately instead of waiting on stdin.\n"
            "`--sync` requires --source so auto-closing stays scoped to one producer.\n"
            "Default output is a structured JSON summary. Use --human for narrative text.\n"
            "--machine remains a compatibility alias for the default machine summary.\n"
        )
    if command == "adapter":
        return (
            "usage: cli.py [--human|--machine] adapter <owner/repo> <pr_number> <adapter_cmd...>\n\n"
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
            "usage: cli.py submit-action <loop_request_path> --resolution {fix,clarify,defer} --note <text> ... [resume_cmd...]\n\n"
            "High-level manual action entrypoint.\n\n"
            "Use when the loop stops in WAITING_FOR_FIX and asks for a manual resolution.\n"
            "This command writes the chosen action to a payload and then optionally resumes the loop.\n"
            "If resume_cmd is omitted, it prints instructions for resuming.\n"
        )
    return ""


def persist_machine_summary(repo: str, pr_number: str, payload: dict) -> None:
    path = last_machine_summary_file(repo, pr_number)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def external_review_command(repo: str, pr_number: str) -> str:
    return f"python3 scripts/cli.py review {repo} {pr_number}"


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


def canonical_findings_payload(findings: list[dict]) -> str:
    return json.dumps(findings, sort_keys=True, separators=(",", ":"))


def last_consumed_handoff_sha256(repo: str, pr_number: str) -> str | None:
    session = load_session_payload(repo, pr_number)
    handoff = session.get("handoff") if isinstance(session, dict) else None
    if not isinstance(handoff, dict):
        return None
    value = handoff.get("last_consumed_sha256")
    return value if isinstance(value, str) and value else None


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
            f"Provide findings JSON with `python3 scripts/cli.py {command} {repo} {pr_number} --input <path>|-`."
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
        next_action = f"Address the finding by running: `python3 {sys.argv[0]} submit-action {artifact_path} --resolution <fix|clarify|defer> --note <note> ... -- python3 {sys.argv[0]} {command} {repo} {pr_number}`"
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
) -> dict:
    return {
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
    }


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
        )
        if persist:
            persist_machine_summary(repo, pr_number, summary)
        sys.stdout.write(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(message, file=sys.stderr)
    return exit_code


def _gh_auth_fixture_is_unimplemented(result: subprocess.CompletedProcess[str]) -> bool:
    combined = "\n".join(part for part in [result.stdout, result.stderr] if part)
    return "unhandled gh args" in combined and "auth" in combined and "status" in combined


def preflight_github_cli(args: argparse.Namespace, repo: str, pr_number: str) -> int | None:
    if shutil.which("gh") is None:
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
        )

    result = subprocess.run(["gh", "auth", "status"], text=True, capture_output=True)
    if result.returncode != 0 and not _gh_auth_fixture_is_unimplemented(result):
        return output_preflight_error(
            args,
            repo,
            pr_number,
            "GitHub CLI `gh` is not authenticated. Run `gh auth status` and fix authentication before rerunning.",
            reason_code="GH_AUTH_FAILED",
            waiting_on="github_auth",
            next_action="Authenticate GitHub CLI with `gh auth login`, then rerun the command.",
            exit_code=PR_IO_PREFLIGHT_EXIT,
            persist=False,
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
            next_action=f"Provide an adapter command after `python3 scripts/cli.py adapter {repo} {pr_number}`.",
        )

    if args.command in HIGH_LEVEL_GH_COMMANDS:
        gh_preflight = preflight_github_cli(args, repo, pr_number)
        if gh_preflight is not None:
            return gh_preflight

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
                args.review_continue_without_input = True
                return None
            args.args = [*args.args, "--input", normalized_input]
            if handoff_sha256:
                args.args.extend(["--handoff-sha256", handoff_sha256])
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
            next_action=f"`{args.command}` does not generate findings. Provide findings JSON with `python3 scripts/cli.py {args.command} {repo} {pr_number} --input <path>|-`.",
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
    session.setdefault("handoff", {"last_consumed_sha256": None})
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
    if handoff_sha256:
        handoff = session.setdefault("handoff", {})
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
        "resume_command": f"python3 scripts/cli.py {command} {repo} {pr_number}",
    }
    request_path.write_text(json.dumps(request, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return request_path


def _first_blocking_item(session: dict) -> dict | None:
    for item in session.get("items", {}).values():
        if isinstance(item, dict) and item.get("blocking"):
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
    }
    if command == "threads":
        summary["threads"] = _native_thread_rows(session)
    return summary


def _native_thread_rows(session: dict) -> list[dict]:
    items = session.get("items") if isinstance(session.get("items"), dict) else {}
    rows = []
    for item_id, item in sorted(items.items()):
        if not isinstance(item, dict) or item.get("item_kind") != "github_thread":
            continue
        status = str(item.get("status") or "")
        state = str(item.get("state") or "")
        thread_id = item.get("thread_id") or item.get("origin_ref") or str(item_id).removeprefix("github-thread:")
        reply_evidence = item.get("reply_evidence") if isinstance(item.get("reply_evidence"), dict) else None
        rows.append(
            {
                "item_id": str(item.get("item_id") or item_id),
                "thread_id": thread_id,
                "path": item.get("path"),
                "line": item.get("line"),
                "body": item.get("body"),
                "url": item.get("url"),
                "state": state or None,
                "status": status or None,
                "is_resolved": status.upper() == "CLOSED" or state.lower() in {"closed", "resolved"},
                "is_outdated": bool(item.get("is_outdated") or item.get("isOutdated") or status.upper() == "STALE"),
                "reply_evidence": reply_evidence,
                "accepted_response_present": isinstance(item.get("accepted_response"), dict),
            }
        )
    return rows


def _parse_native_high_level_args(command: str, args: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog=f"gh-address-cr {command}", add_help=False)
    parser.add_argument("repo")
    parser.add_argument("pr_number")
    parser.add_argument("adapter_cmd", nargs="*")
    parser.add_argument("--input")
    parser.add_argument("--source")
    parser.add_argument("--sync", action="store_true")
    parser.add_argument("--handoff-sha256")
    parser.add_argument("--scan-id")
    parser.add_argument("--audit-id")
    parser.add_argument("--snapshot")
    parser.add_argument("--max-iterations", type=int, default=1)
    parsed, unknown = parser.parse_known_args(args)
    if unknown:
        parsed.adapter_cmd.extend(unknown)
    if parsed.adapter_cmd and parsed.adapter_cmd[0] == "--":
        parsed.adapter_cmd = parsed.adapter_cmd[1:]
    return parsed


def _run_adapter_command(argv: list[str]) -> tuple[str | None, str | None]:
    if not argv:
        return None, "adapter requires <adapter_cmd...> after <owner/repo> <pr_number>."
    result = subprocess.run(argv, text=True, capture_output=True)
    if result.returncode != 0:
        return None, result.stderr or f"Adapter command failed with exit code {result.returncode}."
    return result.stdout, None


def handle_native_high_level(command: str, passthrough_args: list[str], *, human: bool) -> int:
    parsed = _parse_native_high_level_args(command, passthrough_args)
    repo = parsed.repo
    pr_number = str(parsed.pr_number)
    run_id = parsed.audit_id or f"native-{_utc_now()}"
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
        if command in {"review", "threads", "adapter"}:
            client = GitHubClient()
            remote_threads = client.list_threads(repo, pr_number)
            session = core_gate.session_with_remote_threads(session, remote_threads)
        _recalc_native_metrics(session)
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
            waiting_on="github",
            next_action=str(exc),
            exit_code=5,
            session=session,
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
                f"`python3 scripts/cli.py submit-action {request_path} --resolution <fix|clarify|defer> "
                f"--note <note> -- python3 scripts/cli.py {command} {repo} {pr_number}`"
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
        )
        _emit_native_summary(summary, human=human)
        return 5

    _set_loop_state(session, run_id=run_id, status="PASSED", iteration=1, max_iterations=parsed.max_iterations)
    _recalc_native_metrics(session)
    session_store.save_session(repo, pr_number, session)
    summary = _native_summary(
        command=command,
        repo=repo,
        pr_number=pr_number,
        status="PASSED",
        reason_code="PASSED",
        waiting_on=None,
        next_action="No action required.",
        exit_code=0,
        session=session,
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
            "clarify",
            "defer",
            "reject",
            "verify",
            "publish",
            "gate",
        ],
        "input_formats": [
            "action_request.v1",
            "finding.v1",
            "github_thread.v1",
        ],
        "output_formats": [
            "action_response.v1",
            "evidence_record.v1",
            "gate_report.v1",
        ],
        "constraints": {
            "max_parallel_claims": 2,
        },
        "public_commands": sorted(["review", "threads", "findings", "adapter", "submit-action", "final-gate"]),
    }


def handle_agent_command(args: argparse.Namespace) -> int:
    if args.repo in {None, "-h", "--help"}:
        sys.stdout.write(
            "usage: gh-address-cr agent {manifest,classify,next,submit,publish,leases,reclaim,orchestrate} ...\n\n"
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
    if args.repo == "publish":
        return handle_agent_publish(args.pr_number, args.args)
    if args.repo == "leases":
        return handle_agent_leases(args.pr_number, args.args)
    if args.repo == "reclaim":
        return handle_agent_reclaim(args.pr_number, args.args)
    if args.repo == "orchestrate":
        return handle_agent_orchestrate(args.pr_number, args.args)
    print(
        "Unknown agent command. Supported commands: manifest, classify, next, submit, publish, leases, reclaim, orchestrate.",
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
    parser.add_argument("--now")
    parsed = parser.parse_args(_prepend_optional(repo, passthrough))
    try:
        now_dt = None
        if parsed.now:
            now_dt = datetime.fromisoformat(parsed.now.replace("Z", "+00:00"))
        payload = workflow.submit_action_response(parsed.repo, parsed.pr_number, response_path=parsed.input, now=now_dt)
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
    parser.add_argument("repo")
    parser.add_argument("pr_number")
    parsed = parser.parse_args(_prepend_optional(repo, _prepend_optional(pr_number, passthrough)))
    try:
        result = core_gate.Gatekeeper().run(
            parsed.repo,
            parsed.pr_number,
            snapshot_path=parsed.snapshot or None,
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
    print()
    if result.passed:
        print("== Gate Result ==")
        print("Verified: 0 Unresolved Threads found")
        print("Verified: 0 Pending Reviews found")
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
        "command",
        metavar="{review,threads,findings,adapter,review-to-findings,submit-feedback,submit-action}",
        help=(
            "High-level commands:\n"
            "  cli.py review owner/repo 123 [--human]\n"
            "  cli.py threads owner/repo 123 [--human]\n"
            "  cli.py findings owner/repo 123 --input findings.json [--human]\n"
            "  cli.py --human adapter owner/repo 123 python3 tools/review_adapter.py\n"
            "Notes:\n"
            "  review waits for external review findings when they are absent.\n"
            "  High-level commands are the agent-safe public surface.\n"
            "  For `adapter`, flags after <adapter_cmd...> are passed through to the adapter command.\n"
            "Utility commands:\n"
            "  cli.py review-to-findings owner/repo 123 --input finding-blocks.md\n"
            "  cli.py submit-feedback --category workflow-gap --title ... --summary ... --expected ... --actual ...\n"
            "  review-to-findings accepts fixed finding blocks only, not arbitrary Markdown.\n"
            "Runtime commands:\n"
            "  gh-address-cr agent manifest\n"
            "  gh-address-cr final-gate owner/repo 123\n"
        ),
    )
    parser.add_argument("repo", nargs="?", help="Owner/repo name.")
    parser.add_argument("pr_number", nargs="?", help="Pull request number.")
    parser.add_argument("args", nargs=argparse.REMAINDER, help="Arguments passed through to the selected subcommand.")
    return parser.parse_args(argv)


def run_script(script_name: str, passthrough_args: list[str]) -> subprocess.CompletedProcess[str]:
    target = SCRIPT_DIR / script_name
    if not target.is_file():
        return subprocess.CompletedProcess(
            [sys.executable, str(target), *passthrough_args],
            127,
            "",
            f"Required gh-address-cr runtime script is missing: {target}\n",
        )
    env = os.environ.copy()
    src_root = str(Path(__file__).resolve().parents[1])
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = src_root if not existing_pythonpath else f"{src_root}{os.pathsep}{existing_pythonpath}"
    return subprocess.run([sys.executable, str(target), *passthrough_args], text=True, capture_output=True, env=env)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.command == "agent":
        return handle_agent_command(args)

    if args.command == "superpowers":
        return handle_superpowers_command(args)

    if args.command == "final-gate":
        if args.machine or args.human:
            print(
                f"--machine and --human are only supported for {', '.join(sorted(HIGH_LEVEL_COMMANDS))}.",
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
        passthrough = []
        if args.repo:
            passthrough.append(args.repo)
        if args.pr_number:
            passthrough.append(args.pr_number)
        passthrough.extend(args.args)
        result = run_script("submit_action.py", [*cmd, *passthrough])
        if result.stdout:
            sys.stdout.write(result.stdout)
        if result.stderr:
            sys.stderr.write(result.stderr)
        return result.returncode

    if args.command not in COMMAND_TO_SCRIPT and args.command not in NATIVE_HIGH_LEVEL_COMMANDS:
        supported_commands = ", ".join(sorted([*COMMAND_TO_SCRIPT, *NATIVE_HIGH_LEVEL_COMMANDS, "agent"]))
        print(f"Unknown command. Supported commands: {supported_commands}.", file=sys.stderr)
        return 2
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
        return handle_native_high_level(args.command, args.args, human=args.human)
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
