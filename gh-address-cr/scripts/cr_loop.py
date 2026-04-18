#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import shlex
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from generate_reply import fix_reply as render_fix_reply
import session_engine as engine
from python_common import findings_file, loop_artifact_file, reply_file, run_cmd as common_run_cmd, snapshot_file, trace_event, validation_file, parse_dispatch, shield_adapter_passthrough, VALID_MODES, VALID_PRODUCERS


SCRIPT_DIR = Path(__file__).resolve().parent
RUN_ONCE = SCRIPT_DIR / "run_once.py"
RUN_LOCAL_REVIEW = SCRIPT_DIR / "run_local_review.py"
INGEST_FINDINGS = SCRIPT_DIR / "ingest_findings.py"
FINAL_GATE = SCRIPT_DIR / "final_gate.py"
POST_REPLY = SCRIPT_DIR / "post_reply.py"
RESOLVE_THREAD = SCRIPT_DIR / "resolve_thread.py"
CODE_REVIEW_ADAPTER = SCRIPT_DIR / "code_review_adapter.py"


NEEDS_HUMAN_EXIT = 4
BLOCKED_EXIT = 5


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    argv = shield_adapter_passthrough(argv)
    parser = argparse.ArgumentParser(
        description="Run a multi-iteration CR loop for gh-address-cr.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("mode", choices=sorted(VALID_MODES))
    parser.add_argument("parts", nargs="*", help="Mode-dependent positional args.")
    parser.add_argument("--audit-id", default="")
    parser.add_argument("--scan-id", default="")
    parser.add_argument("--source", default="")
    parser.add_argument("--sync", action="store_true", help="Close missing local findings from the same source.")
    parser.add_argument("--handoff-sha256", default="")
    parser.add_argument("--input", default=None, help="Findings JSON file. Use '-' to read from stdin.")
    parser.add_argument("--max-iterations", type=int, default=10)
    parser.add_argument("--loop-threshold", type=int, default=engine.LOOP_WARNING_THRESHOLD)
    parser.add_argument("--fixer-cmd", help="Optional external fixer command that returns a JSON action payload.")
    parser.add_argument("--validation-cmd", action="append", default=[], help="Extra validation command(s).")
    return getattr(parser, "parse_intermixed_args", parser.parse_args)(argv)


# parse_dispatch is now imported from python_common


def run_cmd(cmd: list[str], *, stdin: str | None = None, retries: int = 3) -> subprocess.CompletedProcess[str]:
    return common_run_cmd(cmd, input_text=stdin, retries=retries)


def emit(result: subprocess.CompletedProcess[str]) -> None:
    if result.stdout:
        sys.stdout.write(result.stdout)
    if result.stderr:
        sys.stderr.write(result.stderr)


def severity_rank(item: dict) -> tuple[int, str]:
    severity = item.get("severity") or "P9"
    mapping = {"P1": 1, "P2": 2, "P3": 3}
    return mapping.get(severity, 9), severity


def has_active_claim(item: dict) -> bool:
    claimed_by = item.get("claimed_by")
    lease_expires_at = item.get("lease_expires_at")
    if not claimed_by or not lease_expires_at:
        return False
    try:
        expires = datetime.fromisoformat(lease_expires_at)
    except ValueError:
        return bool(claimed_by)
    return expires > datetime.now(timezone.utc)


def select_ready_batch(session: dict) -> list[dict]:
    candidates = [
        item
        for item in session["items"].values()
        if item.get("blocking") and not item.get("needs_human") and not has_active_claim(item)
    ]
    return sorted(
        candidates,
        key=lambda item: (
            0 if item["item_kind"] == "github_thread" else 1,
            severity_rank(item)[0],
            item.get("path") or "",
            item.get("line") or 0,
        ),
    )


def _resolve_session(repo: str, pr_number: str, session: dict | None) -> tuple[dict, bool]:
    if session is not None:
        return session, False
    return engine.load_session(repo, pr_number), True


def _save_if_needed(session: dict, *, loaded_here: bool, persist: bool) -> None:
    if loaded_here or persist:
        engine.save_session(session)


def update_loop_state(
    repo: str,
    pr_number: str,
    *,
    run_id: str,
    status: str,
    iteration: int,
    max_iterations: int,
    current_item_id: str | None = None,
    last_error: str = "",
    session: dict | None = None,
    persist: bool = True,
):
    session, loaded_here = _resolve_session(repo, pr_number, session)
    engine.ensure_loop_state(session)
    loop = session["loop_state"]
    loop["run_id"] = run_id
    loop["status"] = status
    loop["iteration"] = iteration
    loop["max_iterations"] = max_iterations
    loop["current_item_id"] = current_item_id
    loop["last_error"] = last_error
    if status == "ACTIVE" and not loop.get("last_started_at"):
        loop["last_started_at"] = engine.utc_now()
    if status in {"PASSED", "FAILED", "NEEDS_HUMAN", "BLOCKED"}:
        loop["last_completed_at"] = engine.utc_now()
    _save_if_needed(session, loaded_here=loaded_here, persist=persist)
    trace_event(
        "cr-loop-state",
        status.lower(),
        repo,
        pr_number,
        run_id=run_id,
        audit_id=run_id,
        message=f"cr-loop status -> {status}",
        details={
            "iteration": iteration,
            "max_iterations": max_iterations,
            "current_item_id": current_item_id,
            "last_error": last_error,
        },
    )


def record_auto_attempt(
    repo: str,
    pr_number: str,
    item_id: str,
    *,
    action: str | None,
    failure: str | None,
    session: dict | None = None,
    persist: bool = True,
):
    session, loaded_here = _resolve_session(repo, pr_number, session)
    item = engine.ensure_item(session, item_id)
    item["auto_attempt_count"] = item.get("auto_attempt_count", 0) + 1
    item["last_auto_action"] = action
    item["last_auto_failure"] = failure
    item["updated_at"] = engine.utc_now()
    item["history"].append(engine.history_event("auto-attempt", failure or action or "auto-attempt", actor="cr-loop"))
    _save_if_needed(session, loaded_here=loaded_here, persist=persist)
    trace_event(
        "cr-loop-auto-attempt",
        "failed" if failure else "ok",
        repo,
        pr_number,
        run_id=session.get("loop_state", {}).get("run_id"),
        audit_id=session.get("loop_state", {}).get("run_id"),
        message=f"Auto attempt for {item_id}",
        details={
            "item_id": item_id,
            "action": action,
            "failure": failure,
            "auto_attempt_count": item["auto_attempt_count"],
        },
    )


def mark_needs_human(
    repo: str,
    pr_number: str,
    item_id: str,
    reason: str,
    *,
    run_id: str,
    iteration: int,
    max_iterations: int,
    session: dict | None = None,
    persist: bool = True,
):
    session, loaded_here = _resolve_session(repo, pr_number, session)
    item = engine.ensure_item(session, item_id)
    item["needs_human"] = True
    item["last_auto_failure"] = reason
    item["resolution_note"] = reason
    item["blocking"] = True
    item["updated_at"] = engine.utc_now()
    item["history"].append(engine.history_event("needs-human", reason, actor="cr-loop"))
    update_loop_state(
        repo,
        pr_number,
        run_id=run_id,
        status="NEEDS_HUMAN",
        iteration=iteration,
        max_iterations=max_iterations,
        current_item_id=item_id,
        last_error=reason,
        session=session,
        persist=False,
    )
    _save_if_needed(session, loaded_here=loaded_here, persist=persist)


def detect_needs_human(
    repo: str,
    pr_number: str,
    *,
    run_id: str,
    iteration: int,
    max_iterations: int,
    loop_threshold: int,
    session: dict | None = None,
    persist: bool = True,
) -> tuple[bool, str]:
    session, loaded_here = _resolve_session(repo, pr_number, session)
    for item in session["items"].values():
        if item.get("needs_human"):
            update_loop_state(
                repo,
                pr_number,
                run_id=run_id,
                status="NEEDS_HUMAN",
                iteration=iteration,
                max_iterations=max_iterations,
                current_item_id=item["item_id"],
                last_error=item.get("last_auto_failure") or "Item requires human review.",
                session=session,
                persist=False,
            )
            _save_if_needed(session, loaded_here=loaded_here, persist=persist)
            return True, item["item_id"]
        if (
            item.get("item_kind") == "local_finding"
            and item.get("blocking")
            and max(item.get("repeat_count", 0), item.get("reopen_count", 0)) >= loop_threshold
        ):
            mark_needs_human(
                repo,
                pr_number,
                item["item_id"],
                f"Loop threshold exceeded for {item['item_id']}.",
                run_id=run_id,
                iteration=iteration,
                max_iterations=max_iterations,
                session=session,
                persist=False,
            )
            _save_if_needed(session, loaded_here=loaded_here, persist=persist)
            return True, item["item_id"]
    return False, ""


def run_gate(mode: str, repo: str, pr_number: str, audit_id: str, *, snapshot: str = "") -> subprocess.CompletedProcess[str]:
    if mode == "local":
        return run_cmd([sys.executable, str(SCRIPT_DIR / "session_engine.py"), "gate", repo, pr_number])
    cmd = [sys.executable, str(FINAL_GATE), "--no-auto-clean"]
    if audit_id:
        cmd.extend(["--audit-id", audit_id])
    if snapshot:
        cmd.extend(["--snapshot", snapshot])
    cmd.extend([repo, pr_number])
    return run_cmd(cmd)


def current_snapshot_path(mode: str, repo: str, pr_number: str) -> str:
    if mode not in {"remote", "mixed"}:
        return ""
    path = snapshot_file(repo, pr_number)
    if not path.exists():
        return ""
    return str(path)


def run_intake(args: argparse.Namespace, producer: str | None, repo: str, pr_number: str, extra: list[str], iteration: int, stdin_payload: str | None) -> subprocess.CompletedProcess[str]:
    if iteration == 1:
        run_cmd([sys.executable, str(SCRIPT_DIR / "session_engine.py"), "init", repo, pr_number])

    if args.mode in {"remote", "mixed"}:
        result = run_cmd(
            [sys.executable, str(RUN_ONCE), *(["--audit-id", args.audit_id] if args.audit_id else []), repo, pr_number]
        )
        if result.returncode != 0:
            return result

    if args.mode in {"local", "mixed", "ingest"}:
        if producer == "adapter":
            cmd = [sys.executable, str(RUN_LOCAL_REVIEW)]
            if args.scan_id:
                cmd.extend(["--scan-id", args.scan_id])
            if args.source or producer:
                cmd.extend(["--source", args.source or f"local-agent:{producer}"])
            if args.sync:
                cmd.append("--sync")
            cmd.extend([repo, pr_number, *extra])
            return run_cmd(cmd)
        if producer == "json":
            if iteration > 1:
                return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            cmd = [sys.executable, str(INGEST_FINDINGS)]
            if args.scan_id:
                cmd.extend(["--scan-id", args.scan_id])
            if args.source or producer:
                cmd.extend(["--source", args.source or f"local-agent:{producer}"])
            if args.sync:
                cmd.append("--sync")
            if args.handoff_sha256:
                cmd.extend(["--handoff-sha256", args.handoff_sha256])
            if args.input is not None:
                cmd.extend(["--input", args.input])
            cmd.extend([repo, pr_number])
            return run_cmd(cmd, stdin=stdin_payload)
        if producer == "code-review":
            if iteration > 1:
                return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            input_arg = args.input
            persisted_input_path: Path | None = None
            try:
                if stdin_payload is not None:
                    persisted_input_path = findings_file(repo, pr_number, f"findings-stdin-code-review-{uuid.uuid4().hex}.json")
                    persisted_input_path.write_text(stdin_payload, encoding="utf-8")
                    input_arg = str(persisted_input_path)
                cmd = [sys.executable, str(RUN_LOCAL_REVIEW)]
                if args.scan_id:
                    cmd.extend(["--scan-id", args.scan_id])
                cmd.extend(["--source", args.source or "local-agent:code-review"])
                if args.sync:
                    cmd.append("--sync")
                cmd.extend([repo, pr_number, sys.executable, str(CODE_REVIEW_ADAPTER), "--input", input_arg or "-"])
                return run_cmd(cmd)
            finally:
                if persisted_input_path and persisted_input_path.exists():
                    persisted_input_path.unlink()
    return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")


def run_fixer(fixer_cmd: str, payload: dict) -> tuple[dict | None, str]:
    result = subprocess.run(shlex.split(fixer_cmd), input=json.dumps(payload), text=True, capture_output=True)
    if result.returncode != 0:
        return None, result.stderr or "Fixer command failed."
    try:
        action = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        return None, f"Invalid fixer JSON: {exc}"
    return action, ""


def _extract_reply_url(stdout: str) -> str | None:
    if not stdout:
        return None
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return None
    return (
        payload.get("data", {})
        .get("addPullRequestReviewThreadReply", {})
        .get("comment", {})
        .get("url")
    )


def write_internal_fixer_request(repo: str, pr_number: str, *, run_id: str, iteration: int, payload: dict) -> Path:
    safe_item_id = payload["item"]["item_id"].replace("/", "_").replace(":", "_")
    request_path = loop_artifact_file(repo, pr_number, f"loop-request-{run_id}-iter{iteration}-{safe_item_id}.json")
    request = {
        "mode": "internal-fixer",
        "repo": repo,
        "pr_number": pr_number,
        "run_id": run_id,
        "iteration": iteration,
        "instructions": [
            "Review the selected item using the current PR context.",
            "Decide one resolution: fix, clarify, or defer.",
            "Produce note text for terminal handling.",
            "If the item is a GitHub thread and resolution=fix, return fix_reply instead of handwritten reply_markdown.",
            "fix_reply must include commit_hash and files, and should include why; test_command/test_result may be omitted when validation_commands are provided.",
            "If the item is a GitHub thread and resolution=clarify or defer, produce reply_markdown.",
            "Write any generated reply markdown inside the PR artifacts directory, not the project workspace.",
        ],
        **payload,
    }
    request_path.write_text(json.dumps(request, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return request_path


def normalize_validation_commands(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        command = value.strip()
        return [command] if command else []
    if isinstance(value, (list, tuple)):
        commands = []
        for entry in value:
            command = str(entry or "").strip()
            if command:
                commands.append(command)
        return commands
    command = str(value).strip()
    return [command] if command else []


def normalize_fix_reply_severity(value: object) -> str:
    severity = str(value or "").strip().upper()
    return severity if severity in {"P1", "P2", "P3"} else "P2"


def build_github_fix_reply(action: dict, item: dict, validation_commands: object) -> tuple[str | None, str]:
    fix_reply = action.get("fix_reply")
    if not isinstance(fix_reply, dict):
        return None, "GitHub fix actions require fix_reply. Raw reply_markdown is not allowed for fix."

    commit_hash = str(fix_reply.get("commit_hash") or "").strip()
    if not commit_hash:
        return None, "GitHub fix actions require fix_reply.commit_hash."

    files_value = fix_reply.get("files")
    if isinstance(files_value, str):
        files = [part.strip() for part in files_value.split(",") if part.strip()]
    elif isinstance(files_value, list):
        files = [str(part).strip() for part in files_value if str(part).strip()]
    else:
        files = []
    if not files:
        return None, "GitHub fix actions require fix_reply.files."

    normalized_validation_commands = normalize_validation_commands(validation_commands)
    severity = normalize_fix_reply_severity(fix_reply.get("severity") or item.get("severity") or "P2")
    why = str(fix_reply.get("why") or "Addressed the CR with minimal targeted changes and regression coverage.").strip()
    test_command = str(fix_reply.get("test_command") or " && ".join(normalized_validation_commands)).strip()
    derived_test_result = "passed" if normalized_validation_commands else ""
    test_result = str(fix_reply.get("test_result") or derived_test_result).strip()
    if not test_command:
        return None, "GitHub fix actions require fix_reply.test_command or validation_commands."
    if not test_result:
        return None, "GitHub fix actions require fix_reply.test_result or a derivable validation result."

    try:
        reply_markdown = render_fix_reply(
            severity,
            [commit_hash, ",".join(files), test_command, test_result, why],
        )
    except SystemExit as exc:
        return None, str(exc) or "Invalid fix_reply payload."
    return reply_markdown, ""


def run_validation(commands: list[str]) -> tuple[bool, str]:
    for command in commands:
        try:
            argv = shlex.split(command)
        except ValueError as exc:
            return False, f"Invalid validation command: {command}\n{exc}"
        if not argv:
            return False, "Invalid validation command: command is empty."
        result = subprocess.run(argv, text=True, capture_output=True)
        if result.returncode != 0:
            output = (result.stdout or "") + (result.stderr or "")
            return False, f"Validation failed: {command}\n{output}".strip()
    return True, ""


def write_validation_record(
    repo: str,
    pr_number: str,
    *,
    run_id: str,
    iteration: int,
    item_id: str,
    commands: list[str],
    ok: bool,
    error: str,
) -> None:
    safe_item_id = item_id.replace("/", "_").replace(":", "_")
    record_path = validation_file(repo, pr_number, f"validation-{run_id}-iter{iteration}-{safe_item_id}.json")
    record_path.write_text(
        json.dumps(
            {
                "item_id": item_id,
                "run_id": run_id,
                "iteration": iteration,
                "commands": commands,
                "ok": ok,
                "error": error,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def release_item_for_retry(
    repo: str,
    pr_number: str,
    item_id: str,
    reason: str,
    *,
    session: dict | None = None,
    persist: bool = True,
):
    session, loaded_here = _resolve_session(repo, pr_number, session)
    item = engine.ensure_item(session, item_id)
    if item["status"] == "CLAIMED":
        item["status"] = "OPEN"
    engine.clear_claim(item)
    item["blocking"] = True
    item["last_auto_failure"] = reason
    item["updated_at"] = engine.utc_now()
    item["history"].append(engine.history_event("auto-retry", reason, actor="cr-loop"))
    _save_if_needed(session, loaded_here=loaded_here, persist=persist)


def handle_batch(args: argparse.Namespace, repo: str, pr_number: str, batch_items: list[dict], *, run_id: str, iteration: int) -> tuple[str, str]:
    github_actions = []
    local_updates = []
    has_needs_human = False
    first_error = ""

    def mark_batch_error(error_msg: str):
        nonlocal has_needs_human, first_error
        has_needs_human = True
        if not first_error:
            first_error = error_msg

    for item in batch_items:
        payload = {
            "repo": repo,
            "pr_number": pr_number,
            "iteration": iteration,
            "item": item,
            "loop_state": {"run_id": run_id, "max_iterations": args.max_iterations},
            "default_validation_commands": args.validation_cmd,
        }
        if not args.fixer_cmd:
            request_path = write_internal_fixer_request(repo, pr_number, run_id=run_id, iteration=iteration, payload=payload)
            update_loop_state(
                repo, pr_number, run_id=run_id, status="BLOCKED", iteration=iteration,
                max_iterations=args.max_iterations, current_item_id=item["item_id"],
                last_error=f"Internal fixer action required: {request_path}"
            )
            return "internal_required", str(request_path)

        action, error = run_fixer(args.fixer_cmd, payload)
        if action is None:
            item_session = engine.load_session(repo, pr_number)
            record_auto_attempt(repo, pr_number, item["item_id"], action=None, failure=error, session=item_session, persist=False)
            mark_needs_human(
                repo,
                pr_number,
                item["item_id"],
                error,
                run_id=run_id,
                iteration=iteration,
                max_iterations=args.max_iterations,
                session=item_session,
                persist=True,
            )
            mark_batch_error(error)
            continue

        resolution = action.get("resolution")
        note = (action.get("note") or "").strip()
        if resolution not in {"fix", "clarify", "defer"} or not note:
            error = error or f"Unsupported resolution or missing note: {resolution}"
            item_session = engine.load_session(repo, pr_number)
            record_auto_attempt(
                repo,
                pr_number,
                item["item_id"],
                action=resolution,
                failure=error,
                session=item_session,
                persist=False,
            )
            mark_needs_human(
                repo,
                pr_number,
                item["item_id"],
                error,
                run_id=run_id,
                iteration=iteration,
                max_iterations=args.max_iterations,
                session=item_session,
                persist=True,
            )
            mark_batch_error(error)
            continue

        item_session = engine.load_session(repo, pr_number)
        record_auto_attempt(
            repo,
            pr_number,
            item["item_id"],
            action=resolution,
            failure=None,
            session=item_session,
            persist=True,
        )

        validation_commands = normalize_validation_commands(action.get("validation_commands")) + normalize_validation_commands(args.validation_cmd)
        if resolution == "fix" and validation_commands:
            ok, validation_error = run_validation(validation_commands)
            write_validation_record(repo, pr_number, run_id=run_id, iteration=iteration, item_id=item["item_id"], commands=validation_commands, ok=ok, error=validation_error)
            if not ok:
                current = engine.ensure_item(item_session, item["item_id"])
                if current.get("auto_attempt_count", 0) >= 2:
                    mark_needs_human(
                        repo,
                        pr_number,
                        item["item_id"],
                        validation_error,
                        run_id=run_id,
                        iteration=iteration,
                        max_iterations=args.max_iterations,
                        session=item_session,
                        persist=True,
                    )
                    mark_batch_error(validation_error)
                    continue
                release_item_for_retry(
                    repo,
                    pr_number,
                    item["item_id"],
                    validation_error,
                    session=item_session,
                    persist=True,
                )
                continue  # Skip this item for now, retry next wave

        if item["item_kind"] == "github_thread":
            if resolution == "fix":
                reply_markdown, error = build_github_fix_reply(action, item, validation_commands)
            else:
                reply_markdown = action.get("reply_markdown")
                error = ""
            if not reply_markdown:
                error = error or "GitHub thread actions require reply_markdown."
                record_auto_attempt(
                    repo,
                    pr_number,
                    item["item_id"],
                    action=resolution,
                    failure=error,
                    session=item_session,
                    persist=False,
                )
                mark_needs_human(
                    repo,
                    pr_number,
                    item["item_id"],
                    error,
                    run_id=run_id,
                    iteration=iteration,
                    max_iterations=args.max_iterations,
                    session=item_session,
                    persist=True,
                )
                mark_batch_error(error)
                continue

            thread_id = item["origin_ref"]
            reply_path = reply_file(repo, pr_number, f"reply-{run_id}-iter{iteration}-{thread_id}.md")
            reply_already_posted = bool(item.get("reply_posted"))
            if not reply_already_posted:
                reply_path.write_text(reply_markdown, encoding="utf-8")

            github_actions.append({
                "item_id": item["item_id"],
                "thread_id": thread_id,
                "reply_body": reply_markdown if not reply_already_posted else None,
                "resolve": True,
                "resolution": resolution,
                "note": note,
            })
        else:
            local_updates.append({
                "item_id": item["item_id"],
                "resolution": resolution,
                "note": note,
            })

    if github_actions:
        payload_str = json.dumps(github_actions)
        cmd = [sys.executable, str(SCRIPT_DIR / "batch_github_execute.py"), "--repo", repo, "--pr", pr_number, "--audit-id", run_id]
        result = run_cmd(cmd, stdin=payload_str)
        emit(result)
        if result.returncode != 0 and not result.stdout.strip():
            return "blocked", result.stderr or "batch GitHub helper failed"

        try:
            github_results = json.loads(result.stdout) if result.stdout.strip() else {}
        except json.JSONDecodeError:
            github_results = {}

        session_updates = []
        for action in github_actions:
            item_id = action["item_id"]
            res = github_results.get(item_id, {})
            result_status = res.get("status")
            if result_status != "succeeded":
                failure = res.get("error") or f"GitHub action ended with status={result_status or 'unknown'}"
                item_session = engine.load_session(repo, pr_number)
                record_auto_attempt(
                    repo,
                    pr_number,
                    item_id,
                    action=action["resolution"],
                    failure=failure,
                    session=item_session,
                    persist=False,
                )
                release_item_for_retry(
                    repo,
                    pr_number,
                    item_id,
                    failure,
                    session=item_session,
                    persist=True,
                )
                if action["reply_body"] and res.get("reply_url"):
                    session_updates.append({
                        "item_id": item_id,
                        "reply_posted": True,
                        "reply_url": res["reply_url"]
                    })
            else:
                update = {
                    "item_id": item_id,
                    "status": "CLOSED",
                    "handled": True,
                    "note": action["note"],
                    "last_auto_action": action["resolution"],
                    "last_auto_failure": None,
                    "needs_human": False,
                    "clear_claim": True
                }
                if action["reply_body"]:
                    update["reply_posted"] = True
                    update["reply_url"] = res.get("reply_url")
                session_updates.append(update)

        if session_updates:
            run_cmd(
                [sys.executable, str(SCRIPT_DIR / "session_engine.py"), "update-items-batch", repo, pr_number],
                stdin=json.dumps(session_updates)
            )


    for update in local_updates:
        result = run_cmd(
            [
                sys.executable,
                str(SCRIPT_DIR / "session_engine.py"),
                "resolve-local-item",
                repo,
                pr_number,
                update["item_id"],
                update["resolution"],
                "--note",
                update["note"],
                "--actor",
                "cr-loop",
            ]
        )
        emit(result)
        if result.returncode != 0:
            item_session = engine.load_session(repo, pr_number)
            failure = result.stderr or "resolve-local-item failed"
            record_auto_attempt(
                repo,
                pr_number,
                update["item_id"],
                action=update["resolution"],
                failure=failure,
                session=item_session,
                persist=False,
            )
            mark_needs_human(
                repo,
                pr_number,
                update["item_id"],
                failure,
                run_id=run_id,
                iteration=iteration,
                max_iterations=args.max_iterations,
                session=item_session,
                persist=True,
            )
            return "needs_human", result.stderr or "resolve-local-item failed"

        run_cmd(
            [sys.executable, str(SCRIPT_DIR / "session_engine.py"), "update-items-batch", repo, pr_number],
            stdin=json.dumps([{
                "item_id": update["item_id"],
                "last_auto_action": update["resolution"],
                "last_auto_failure": None,
                "needs_human": False
            }])
        )

    if has_needs_human:
        return "needs_human", first_error
    return "done", ""

def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    producer, repo, pr_number, extra = parse_dispatch(args.mode, args.parts)
    if producer is not None and producer not in VALID_PRODUCERS:
        print(
            f"Unsupported producer: {producer}\n"
            "producer expects a category (`code-review`, `json`, `adapter`), not the upstream tool name.",
            file=sys.stderr,
        )
        return 2
    if args.mode == "remote" and producer is not None:
        print("remote mode does not accept a producer.", file=sys.stderr)
        return 2
    if args.mode == "ingest" and producer != "json":
        print("ingest mode only supports producer=json.", file=sys.stderr)
        return 2
    if args.sync and not args.source:
        print("`--sync` requires an explicit --source so missing findings are scoped to one producer.", file=sys.stderr)
        return 2

    stdin_payload = None
    if args.mode in {"local", "mixed", "ingest"} and producer != "adapter":
        if extra:
            print(f"producer={producer} does not accept an adapter command.", file=sys.stderr)
            return 2
        if args.input == "-":
            stdin_payload = sys.stdin.read()
            if not stdin_payload.strip():
                print(f"producer={producer} requires findings JSON via --input or stdin.", file=sys.stderr)
                return 2
        elif args.input is None:
            stdin_payload = sys.stdin.read()
            if not stdin_payload.strip():
                print(f"producer={producer} requires findings JSON via --input or stdin.", file=sys.stderr)
                return 2

    run_id = args.audit_id or f"cr-loop-{engine.utc_now()}"
    run_cmd([sys.executable, str(SCRIPT_DIR / "session_engine.py"), "init", repo, pr_number])
    update_loop_state(repo, pr_number, run_id=run_id, status="ACTIVE", iteration=0, max_iterations=args.max_iterations)

    for iteration in range(1, args.max_iterations + 1):
        update_loop_state(repo, pr_number, run_id=run_id, status="ACTIVE", iteration=iteration, max_iterations=args.max_iterations)

        intake = run_intake(args, producer, repo, pr_number, extra, iteration, stdin_payload)
        emit(intake)
        if intake.returncode != 0:
            update_loop_state(repo, pr_number, run_id=run_id, status="BLOCKED", iteration=iteration, max_iterations=args.max_iterations, last_error=intake.stderr or "intake failed")
            print("cr-loop BLOCKED", file=sys.stderr)
            return BLOCKED_EXIT

        session = engine.load_session(repo, pr_number)
        needs_human, item_id = detect_needs_human(
            repo,
            pr_number,
            run_id=run_id,
            iteration=iteration,
            max_iterations=args.max_iterations,
            loop_threshold=args.loop_threshold,
            session=session,
        )
        if needs_human:
            print(f"cr-loop NEEDS_HUMAN item={item_id}")
            return NEEDS_HUMAN_EXIT

        batch_items = select_ready_batch(session)
        if not batch_items:
            gate = run_gate(args.mode, repo, pr_number, run_id, snapshot=current_snapshot_path(args.mode, repo, pr_number))
            emit(gate)
            if gate.returncode == 0:
                update_loop_state(repo, pr_number, run_id=run_id, status="PASSED", iteration=iteration, max_iterations=args.max_iterations)
                print("cr-loop PASSED")
                return 0
            update_loop_state(repo, pr_number, run_id=run_id, status="FAILED", iteration=iteration, max_iterations=args.max_iterations, last_error="Gate failed without selectable items.")
            print("cr-loop FAILED", file=sys.stderr)
            return 1

        if args.fixer_cmd:
            for item in batch_items:
                claim = run_cmd(
                    [sys.executable, str(SCRIPT_DIR / "session_engine.py"), "claim", repo, pr_number, item["item_id"], "--agent", "cr-loop"]
                )
                emit(claim)
                if claim.returncode != 0:
                    update_loop_state(repo, pr_number, run_id=run_id, status="BLOCKED", iteration=iteration, max_iterations=args.max_iterations, current_item_id=item["item_id"], last_error=claim.stderr or "claim failed")
                    print("cr-loop BLOCKED", file=sys.stderr)
                    return BLOCKED_EXIT

        update_loop_state(repo, pr_number, run_id=run_id, status="ACTIVE", iteration=iteration, max_iterations=args.max_iterations, current_item_id=batch_items[0]["item_id"])
        status, error = handle_batch(args, repo, pr_number, batch_items, run_id=run_id, iteration=iteration)
        if status != "done":
            if status == "internal_required":
                print("cr-loop PAUSED: Interaction Required")
                print("------------------------------------")
                print(f"Artifact to Address: {error}")
                print("Next Step: Address the finding and run the command again.")
                print(f"cr-loop INTERNAL_FIXER_REQUIRED artifact={error}")
                return BLOCKED_EXIT
            if status == "needs_human":
                print("cr-loop NEEDS_HUMAN")
                return NEEDS_HUMAN_EXIT
            update_loop_state(repo, pr_number, run_id=run_id, status="BLOCKED", iteration=iteration, max_iterations=args.max_iterations, current_item_id=batch_items[0]["item_id"], last_error=error)
            print("cr-loop BLOCKED", file=sys.stderr)
            return BLOCKED_EXIT

        gate_snapshot = ""
        if all(item["item_kind"] != "github_thread" for item in batch_items):
            gate_snapshot = current_snapshot_path(args.mode, repo, pr_number)
        gate = run_gate(args.mode, repo, pr_number, run_id, snapshot=gate_snapshot)
        emit(gate)
        if gate.returncode == 0:
            update_loop_state(repo, pr_number, run_id=run_id, status="PASSED", iteration=iteration, max_iterations=args.max_iterations)
            print("cr-loop PASSED")
            return 0

        session = engine.load_session(repo, pr_number)
        needs_human, item_id = detect_needs_human(
            repo,
            pr_number,
            run_id=run_id,
            iteration=iteration,
            max_iterations=args.max_iterations,
            loop_threshold=args.loop_threshold,
            session=session,
        )
        if needs_human:
            print(f"cr-loop NEEDS_HUMAN item={item_id}")
            return NEEDS_HUMAN_EXIT

    update_loop_state(repo, pr_number, run_id=run_id, status="FAILED", iteration=args.max_iterations, max_iterations=args.max_iterations, last_error="Max iterations reached.")
    print("cr-loop FAILED: max iterations reached", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
