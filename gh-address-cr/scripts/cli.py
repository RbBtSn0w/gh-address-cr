#!/usr/bin/env python3
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from ingest_findings import normalize_finding, parse_records
from review_to_findings import parse_findings
from python_common import incoming_findings_json_file, incoming_findings_markdown_file, normalized_handoff_findings_file
from python_common import last_machine_summary_file, producer_request_file, workspace_dir


SCRIPT_DIR = Path(__file__).resolve().parent
COMMAND_TO_SCRIPT = {
    "review": "cr_loop.py",
    "threads": "cr_loop.py",
    "findings": "cr_loop.py",
    "adapter": "cr_loop.py",
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
OUTPUT_FLAGS = {"--machine", "--human"}
HIGH_LEVEL_GH_COMMANDS = {"review", "threads", "adapter"}
INPUT_REQUIRED_COMMANDS = {"findings"}
WAITING_FOR_EXTERNAL_REVIEW_EXIT = 6
PR_URL_RE = re.compile(
    r"^https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/pull/(?P<pr_number>\d+)(?:[/?#].*)?$"
)


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
        print(f"--machine and --human are only supported for {', '.join(sorted(HIGH_LEVEL_COMMANDS))}.", file=sys.stderr)
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


def workspace_root(repo: str, pr_number: str) -> Path:
    return workspace_dir(repo, pr_number)


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
            f"# External Review Producer Handoff\n\n"
            f"Use any external review producer to review `{repo}` PR `{pr_number}`.\n\n"
            f"Accepted handoff formats:\n\n"
            f"1. Preferred: write findings JSON to `{incoming_json}`\n"
            f"2. Fallback: write fixed `finding` blocks to `{incoming_md}`\n\n"
            f"Required finding fields:\n\n"
            f"- `title`\n"
            f"- `body`\n"
            f"- `path`\n"
            f"- `line`\n\n"
            f"Do not write a Markdown-only narrative review report.\n"
            f"After writing one of the accepted handoff files, rerun:\n\n"
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
            findings = [normalize_finding(record) for record in parse_records(raw_json)]
        except SystemExit as exc:
            return None, None, str(exc) or "Invalid findings JSON."
        except Exception as exc:
            return None, None, str(exc) or "Invalid findings JSON."
    elif raw_md.strip():
        try:
            findings = parse_findings(raw_md)
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
    artifact_path = extract_artifact_path(str(loop_state.get("last_error") or "")) or str(workspace_root(repo, pr_number))
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
        reason_code = "MISSING_GH_CLI"
        waiting_on = "github_cli"
        next_action = "Install GitHub CLI and ensure `gh` is available on PATH, then rerun the command."
    elif status == "NEEDS_HUMAN":
        reason_code = "NEEDS_HUMAN_REVIEW"
        waiting_on = "human_review"
        next_action = f"Inspect {artifact_path} and resolve manually."
    elif status == "BLOCKED" and ("Internal fixer action required:" in combined_error or "Interaction Required" in combined_error):
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
        "artifact_path": artifact_path or str(workspace_root(repo, pr_number)),
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
        persist_machine_summary(repo, pr_number, summary)
        sys.stdout.write(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(message, file=sys.stderr)
    return exit_code


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

    if args.command in HIGH_LEVEL_GH_COMMANDS and shutil.which("gh") is None:
        return output_preflight_error(
            args,
            repo,
            pr_number,
            "Missing GitHub CLI `gh` on PATH. Install it or add it to PATH before running this command.",
            reason_code="MISSING_GH_CLI",
            waiting_on="github_cli",
            next_action="Install GitHub CLI and ensure `gh` is available on PATH, then rerun the command.",
        )

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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
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
        ),
    )
    parser.add_argument("repo", nargs="?", help="Owner/repo name.")
    parser.add_argument("pr_number", nargs="?", help="Pull request number.")
    parser.add_argument("args", nargs=argparse.REMAINDER, help="Arguments passed through to the selected subcommand.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "submit-action":
        if args.args and args.args[0] in {"-h", "--help"}:
            print(alias_help(args.command), end="")
            return 0
        script_path = SCRIPT_DIR / "submit_action.py"
        cmd = [sys.executable, str(script_path)]
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
        return subprocess.run(cmd + passthrough).returncode

    if args.command not in COMMAND_TO_SCRIPT:
        supported_commands = ", ".join(sorted(COMMAND_TO_SCRIPT))
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
    target = SCRIPT_DIR / COMMAND_TO_SCRIPT[args.command]
    rewritten_args = rewrite_alias_args(
        args.command,
        args.args,
        review_continue_without_input=bool(getattr(args, "review_continue_without_input", False)),
    )
    result = subprocess.run([sys.executable, str(target), *rewritten_args], text=True, capture_output=True)
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
                error_text += "\nproducer expects a category (`code-review`, `json`, `adapter`), not the upstream tool name.\n"
            sys.stderr.write(error_text)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
