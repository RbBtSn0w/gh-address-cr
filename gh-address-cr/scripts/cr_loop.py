#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import shlex
import subprocess
import sys
import uuid
from pathlib import Path

import session_engine as engine
from python_common import findings_file, loop_artifact_file, reply_file, validation_file


SCRIPT_DIR = Path(__file__).resolve().parent
RUN_ONCE = SCRIPT_DIR / "run_once.py"
RUN_LOCAL_REVIEW = SCRIPT_DIR / "run_local_review.py"
INGEST_FINDINGS = SCRIPT_DIR / "ingest_findings.py"
FINAL_GATE = SCRIPT_DIR / "final_gate.py"
POST_REPLY = SCRIPT_DIR / "post_reply.py"
RESOLVE_THREAD = SCRIPT_DIR / "resolve_thread.py"
CODE_REVIEW_ADAPTER = SCRIPT_DIR / "code_review_adapter.py"

VALID_MODES = {"remote", "local", "mixed", "ingest"}
VALID_PRODUCERS = {"code-review", "json", "adapter"}
NEEDS_HUMAN_EXIT = 4
BLOCKED_EXIT = 5


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
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
    parser.add_argument("--input", default=None, help="Findings JSON file. Use '-' to read from stdin.")
    parser.add_argument("--max-iterations", type=int, default=10)
    parser.add_argument("--loop-threshold", type=int, default=engine.LOOP_WARNING_THRESHOLD)
    parser.add_argument("--fixer-cmd", help="Optional external fixer command that returns a JSON action payload.")
    parser.add_argument("--validation-cmd", action="append", default=[], help="Extra validation command(s).")
    return getattr(parser, "parse_intermixed_args", parser.parse_args)(argv)


def parse_dispatch(mode: str, parts: list[str]) -> tuple[str | None, str, str, list[str]]:
    if mode == "remote":
        if len(parts) != 2:
            raise SystemExit("remote expects: <owner/repo> <pr_number>")
        return None, parts[0], parts[1], []
    if mode == "ingest":
        if len(parts) == 2:
            return "json", parts[0], parts[1], []
        if len(parts) >= 3:
            return parts[0], parts[1], parts[2], parts[3:]
        raise SystemExit("ingest expects: [producer] <owner/repo> <pr_number>")
    if len(parts) < 3:
        raise SystemExit(f"{mode} expects: <producer> <owner/repo> <pr_number> [adapter_cmd...]")
    return parts[0], parts[1], parts[2], parts[3:]


def run_cmd(cmd: list[str], *, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, input=stdin, text=True, capture_output=True)


def emit(result: subprocess.CompletedProcess[str]) -> None:
    if result.stdout:
        sys.stdout.write(result.stdout)
    if result.stderr:
        sys.stderr.write(result.stderr)


def severity_rank(item: dict) -> tuple[int, str]:
    severity = item.get("severity") or "P9"
    mapping = {"P1": 1, "P2": 2, "P3": 3}
    return mapping.get(severity, 9), severity


def select_next_item(session: dict) -> dict | None:
    candidates = [
        item
        for item in session["items"].values()
        if item.get("blocking") and not item.get("needs_human")
    ]
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda item: (
            0 if item["item_kind"] == "github_thread" else 1,
            severity_rank(item)[0],
            item.get("path") or "",
            item.get("line") or 0,
        ),
    )[0]


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
):
    session = engine.load_session(repo, pr_number)
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
    engine.save_session(session)


def record_auto_attempt(repo: str, pr_number: str, item_id: str, *, action: str | None, failure: str | None):
    session = engine.load_session(repo, pr_number)
    item = engine.ensure_item(session, item_id)
    item["auto_attempt_count"] = item.get("auto_attempt_count", 0) + 1
    item["last_auto_action"] = action
    item["last_auto_failure"] = failure
    item["updated_at"] = engine.utc_now()
    item["history"].append(engine.history_event("auto-attempt", failure or action or "auto-attempt", actor="cr-loop"))
    engine.save_session(session)


def mark_needs_human(repo: str, pr_number: str, item_id: str, reason: str, *, run_id: str, iteration: int, max_iterations: int):
    session = engine.load_session(repo, pr_number)
    item = engine.ensure_item(session, item_id)
    item["needs_human"] = True
    item["last_auto_failure"] = reason
    item["resolution_note"] = reason
    item["blocking"] = True
    item["updated_at"] = engine.utc_now()
    item["history"].append(engine.history_event("needs-human", reason, actor="cr-loop"))
    engine.save_session(session)
    update_loop_state(
        repo,
        pr_number,
        run_id=run_id,
        status="NEEDS_HUMAN",
        iteration=iteration,
        max_iterations=max_iterations,
        current_item_id=item_id,
        last_error=reason,
    )


def detect_needs_human(repo: str, pr_number: str, *, run_id: str, iteration: int, max_iterations: int, loop_threshold: int) -> tuple[bool, str]:
    session = engine.load_session(repo, pr_number)
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
            )
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
            )
            return True, item["item_id"]
    return False, ""


def run_gate(mode: str, repo: str, pr_number: str, audit_id: str) -> subprocess.CompletedProcess[str]:
    if mode == "local":
        return run_cmd([sys.executable, str(SCRIPT_DIR / "session_engine.py"), "gate", repo, pr_number])
    cmd = [sys.executable, str(FINAL_GATE), "--no-auto-clean"]
    if audit_id:
        cmd.extend(["--audit-id", audit_id])
    cmd.extend([repo, pr_number])
    return run_cmd(cmd)


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
            "If the item is a GitHub thread, also produce reply_markdown.",
            "Write any generated reply markdown inside the PR artifacts directory, not the project workspace.",
        ],
        **payload,
    }
    request_path.write_text(json.dumps(request, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return request_path


def run_validation(commands: list[str]) -> tuple[bool, str]:
    for command in commands:
        result = subprocess.run(command, shell=True, text=True, capture_output=True)
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


def release_item_for_retry(repo: str, pr_number: str, item_id: str, reason: str):
    session = engine.load_session(repo, pr_number)
    item = engine.ensure_item(session, item_id)
    if item["status"] == "CLAIMED":
        item["status"] = "OPEN"
    engine.clear_claim(item)
    item["blocking"] = True
    item["last_auto_failure"] = reason
    item["updated_at"] = engine.utc_now()
    item["history"].append(engine.history_event("auto-retry", reason, actor="cr-loop"))
    engine.save_session(session)


def handle_item(args: argparse.Namespace, repo: str, pr_number: str, item: dict, *, run_id: str, iteration: int) -> tuple[str, str]:
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
            repo,
            pr_number,
            run_id=run_id,
            status="BLOCKED",
            iteration=iteration,
            max_iterations=args.max_iterations,
            current_item_id=item["item_id"],
            last_error=f"Internal fixer action required: {request_path}",
        )
        return "internal_required", str(request_path)
    action, error = run_fixer(args.fixer_cmd, payload)
    if action is None:
        record_auto_attempt(repo, pr_number, item["item_id"], action=None, failure=error)
        mark_needs_human(repo, pr_number, item["item_id"], error, run_id=run_id, iteration=iteration, max_iterations=args.max_iterations)
        return "needs_human", error

    resolution = action.get("resolution")
    note = (action.get("note") or "").strip()
    if resolution not in {"fix", "clarify", "defer"}:
        error = f"Unsupported resolution: {resolution}"
        record_auto_attempt(repo, pr_number, item["item_id"], action=resolution, failure=error)
        mark_needs_human(repo, pr_number, item["item_id"], error, run_id=run_id, iteration=iteration, max_iterations=args.max_iterations)
        return "needs_human", error
    if not note:
        error = "Fixer action requires a non-empty note."
        record_auto_attempt(repo, pr_number, item["item_id"], action=resolution, failure=error)
        mark_needs_human(repo, pr_number, item["item_id"], error, run_id=run_id, iteration=iteration, max_iterations=args.max_iterations)
        return "needs_human", error

    record_auto_attempt(repo, pr_number, item["item_id"], action=resolution, failure=None)

    validation_commands = list(action.get("validation_commands") or []) + list(args.validation_cmd or [])
    if resolution == "fix" and validation_commands:
        ok, validation_error = run_validation(validation_commands)
        write_validation_record(
            repo,
            pr_number,
            run_id=run_id,
            iteration=iteration,
            item_id=item["item_id"],
            commands=validation_commands,
            ok=ok,
            error=validation_error,
        )
        if not ok:
            session = engine.load_session(repo, pr_number)
            current = engine.ensure_item(session, item["item_id"])
            if current.get("auto_attempt_count", 0) >= 2:
                mark_needs_human(
                    repo,
                    pr_number,
                    item["item_id"],
                    validation_error,
                    run_id=run_id,
                    iteration=iteration,
                    max_iterations=args.max_iterations,
                )
                return "needs_human", validation_error
            release_item_for_retry(repo, pr_number, item["item_id"], validation_error)
            return "retry", validation_error

    if item["item_kind"] == "github_thread":
        reply_markdown = action.get("reply_markdown")
        if not reply_markdown:
            error = "GitHub thread actions require reply_markdown."
            record_auto_attempt(repo, pr_number, item["item_id"], action=resolution, failure=error)
            mark_needs_human(repo, pr_number, item["item_id"], error, run_id=run_id, iteration=iteration, max_iterations=args.max_iterations)
            return "needs_human", error
        thread_id = item["origin_ref"]
        reply_path = reply_file(repo, pr_number, f"reply-{run_id}-iter{iteration}-{thread_id}.md")
        reply_already_posted = bool(item.get("reply_posted"))
        if not reply_already_posted:
            reply_path.write_text(reply_markdown, encoding="utf-8")
        try:
            if not reply_already_posted:
                result = run_cmd([sys.executable, str(POST_REPLY), "--repo", repo, "--pr", pr_number, "--audit-id", run_id, thread_id, str(reply_path)])
                emit(result)
                if result.returncode != 0:
                    record_auto_attempt(repo, pr_number, item["item_id"], action=resolution, failure=result.stderr or "post_reply failed")
                    mark_needs_human(repo, pr_number, item["item_id"], result.stderr or "post_reply failed", run_id=run_id, iteration=iteration, max_iterations=args.max_iterations)
                    return "needs_human", result.stderr or "post_reply failed"
                session = engine.load_session(repo, pr_number)
                current = engine.ensure_item(session, item["item_id"])
                current["reply_posted"] = True
                current["reply_url"] = _extract_reply_url(result.stdout)
                current["last_auto_action"] = f"reply:{resolution}"
                engine.save_session(session)
            result = run_cmd([sys.executable, str(RESOLVE_THREAD), "--repo", repo, "--pr", pr_number, "--audit-id", run_id, thread_id])
            emit(result)
            if result.returncode != 0:
                record_auto_attempt(repo, pr_number, item["item_id"], action=resolution, failure=result.stderr or "resolve_thread failed")
                update_loop_state(repo, pr_number, run_id=run_id, status="BLOCKED", iteration=iteration, max_iterations=args.max_iterations, current_item_id=item["item_id"], last_error=result.stderr or "resolve_thread failed")
                return "blocked", result.stderr or "resolve_thread failed"
        finally:
            if reply_path.exists():
                reply_path.unlink()
    else:
        result = run_cmd(
            [
                sys.executable,
                str(SCRIPT_DIR / "session_engine.py"),
                "resolve-local-item",
                repo,
                pr_number,
                item["item_id"],
                resolution,
                "--note",
                note,
                "--actor",
                "cr-loop",
            ]
        )
        emit(result)
        if result.returncode != 0:
            record_auto_attempt(repo, pr_number, item["item_id"], action=resolution, failure=result.stderr or "resolve-local-item failed")
            mark_needs_human(repo, pr_number, item["item_id"], result.stderr or "resolve-local-item failed", run_id=run_id, iteration=iteration, max_iterations=args.max_iterations)
            return "needs_human", result.stderr or "resolve-local-item failed"

    session = engine.load_session(repo, pr_number)
    current = engine.ensure_item(session, item["item_id"])
    current["last_auto_action"] = resolution
    current["last_auto_failure"] = None
    current["needs_human"] = False
    engine.save_session(session)
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

        needs_human, item_id = detect_needs_human(repo, pr_number, run_id=run_id, iteration=iteration, max_iterations=args.max_iterations, loop_threshold=args.loop_threshold)
        if needs_human:
            print(f"cr-loop NEEDS_HUMAN item={item_id}")
            return NEEDS_HUMAN_EXIT

        session = engine.load_session(repo, pr_number)
        next_item = select_next_item(session)
        if next_item is None:
            gate = run_gate(args.mode, repo, pr_number, run_id)
            emit(gate)
            if gate.returncode == 0:
                update_loop_state(repo, pr_number, run_id=run_id, status="PASSED", iteration=iteration, max_iterations=args.max_iterations)
                print("cr-loop PASSED")
                return 0
            update_loop_state(repo, pr_number, run_id=run_id, status="FAILED", iteration=iteration, max_iterations=args.max_iterations, last_error="Gate failed without selectable items.")
            print("cr-loop FAILED", file=sys.stderr)
            return 1

        if args.fixer_cmd:
            claim = run_cmd(
                [sys.executable, str(SCRIPT_DIR / "session_engine.py"), "claim", repo, pr_number, next_item["item_id"], "--agent", "cr-loop"]
            )
            emit(claim)
            if claim.returncode != 0:
                update_loop_state(repo, pr_number, run_id=run_id, status="BLOCKED", iteration=iteration, max_iterations=args.max_iterations, current_item_id=next_item["item_id"], last_error=claim.stderr or "claim failed")
                print("cr-loop BLOCKED", file=sys.stderr)
                return BLOCKED_EXIT

        update_loop_state(repo, pr_number, run_id=run_id, status="ACTIVE", iteration=iteration, max_iterations=args.max_iterations, current_item_id=next_item["item_id"])
        status, error = handle_item(args, repo, pr_number, next_item, run_id=run_id, iteration=iteration)
        if status != "done":
            session = engine.load_session(repo, pr_number)
            current = engine.ensure_item(session, next_item["item_id"])
            if status == "retry":
                continue
            if status == "internal_required":
                print("cr-loop PAUSED: Interaction Required")
                print("------------------------------------")
                print(f"Issue: {next_item['item_id']}")
                print(f"Task Description: {next_item.get('title') or next_item.get('body') or '-'}")
                print(f"Artifact to Address: {error}")
                print("Next Step: Address the finding and run the command again.")
                print(f"cr-loop INTERNAL_FIXER_REQUIRED item={next_item['item_id']} artifact={error}")
                return BLOCKED_EXIT
            if status == "needs_human" or current.get("needs_human"):
                print(f"cr-loop NEEDS_HUMAN item={next_item['item_id']}")
                return NEEDS_HUMAN_EXIT
            update_loop_state(repo, pr_number, run_id=run_id, status="BLOCKED", iteration=iteration, max_iterations=args.max_iterations, current_item_id=next_item["item_id"], last_error=error)
            print("cr-loop BLOCKED", file=sys.stderr)
            return BLOCKED_EXIT

        gate = run_gate(args.mode, repo, pr_number, run_id)
        emit(gate)
        if gate.returncode == 0:
            update_loop_state(repo, pr_number, run_id=run_id, status="PASSED", iteration=iteration, max_iterations=args.max_iterations)
            print("cr-loop PASSED")
            return 0

        needs_human, item_id = detect_needs_human(repo, pr_number, run_id=run_id, iteration=iteration, max_iterations=args.max_iterations, loop_threshold=args.loop_threshold)
        if needs_human:
            print(f"cr-loop NEEDS_HUMAN item={item_id}")
            return NEEDS_HUMAN_EXIT

    update_loop_state(repo, pr_number, run_id=run_id, status="FAILED", iteration=args.max_iterations, max_iterations=args.max_iterations, last_error="Max iterations reached.")
    print("cr-loop FAILED: max iterations reached", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
