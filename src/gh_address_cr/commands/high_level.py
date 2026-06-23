"""High-level review command runtime service."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from gh_address_cr.core import command_templates
from gh_address_cr.core import gate as core_gate
from gh_address_cr.core import session as session_store
from gh_address_cr.core.github_thread_state import (
    is_claimable_github_thread,
    is_resolved_github_thread,
    is_stale_or_outdated_github_thread,
)
from gh_address_cr.core.handoff import (
    ensure_handoff_state as _ensure_handoff_state,
)
from gh_address_cr.core.handoff import (
    record_producer_result,
)
from gh_address_cr.core.io import write_json_atomic
from gh_address_cr.core.severity import apply_severity_evidence, severity_evidence
from gh_address_cr.github.client import GitHubClient
from gh_address_cr.github.diagnostics import github_waiting_on
from gh_address_cr.github.errors import GitHubError
from gh_address_cr.intake.findings import (
    EMPTY_FINDINGS_INPUT_MESSAGE,
    FindingsFormatError,
    normalize_findings_payload,
    with_local_item_fields,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _workspace_root(repo: str, pr_number: str) -> Path:
    return session_store.workspace_dir(repo, pr_number)


def _persist_machine_summary(repo: str, pr_number: str, payload: dict[str, Any]) -> None:
    path = _workspace_root(repo, pr_number) / "last-machine-summary.json"
    write_json_atomic(path, payload)


def _build_preflight_summary(
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
    diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
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
        "gate_scope": "inline",
        "commands": summary_commands(repo, pr_number),
    }
    if diagnostics:
        summary["diagnostics"] = diagnostics
    return summary


def _load_or_create_session(repo: str, pr_number: str) -> dict[str, Any]:
    manager = session_store.SessionManager(repo, str(pr_number))
    created = False
    try:
        session = manager.load()
    except session_store.SessionError:
        session = manager.create(status="ACTIVE")
        created = True
    _ensure_native_session_fields(session)
    if created:
        from gh_address_cr.core.telemetry import configure_context_safely

        configure_context_safely(repo, pr_number)
    return session


def _ensure_native_session_fields(session: dict[str, Any]) -> None:
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


def _recalc_native_metrics(session: dict[str, Any]) -> None:
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
        # Fail loud on an interactive TTY instead of blocking forever waiting for
        # EOF that will never arrive (#115). Piped-but-empty input still reaches
        # the explicit EMPTY_FINDINGS_INPUT_MESSAGE check downstream.
        if sys.stdin.isatty():
            raise FindingsFormatError(EMPTY_FINDINGS_INPUT_MESSAGE)
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
) -> list[dict[str, Any]]:
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
        normalized_finding = dict(finding)
        raw_severity = normalized_finding.pop("severity", None)
        item.update(normalized_finding)
        finding_severity = severity_evidence(
            raw_severity,
            source="producer_payload",
            raw_marker=str(raw_severity).strip() if raw_severity is not None else None,
            observed_from=source,
        )
        if finding_severity:
            apply_severity_evidence(item, finding_severity)
        elif raw_severity is not None:
            apply_severity_evidence(item, None)
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
    request_path = _workspace_root(repo, pr_number) / f"loop-request-native-{run_id}-{uuid4().hex}.json"
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
    write_json_atomic(request_path, request)
    return request_path


def _first_blocking_item(session: dict[str, Any]) -> dict[str, Any] | None:
    for item in session.get("items", {}).values():
        if isinstance(item, dict) and item.get("blocking"):
            return item
    return None


def _first_local_item(session: dict[str, Any]) -> dict[str, Any] | None:
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
    item: dict[str, Any] | None = None,
    include_threads: bool = False,
    diagnostics: dict[str, Any] | None = None,
    lean: bool = False,
) -> dict[str, Any]:
    raw_metrics = session.get("metrics")
    metrics: dict[str, Any] = raw_metrics if isinstance(raw_metrics, dict) else {}
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
        "artifact_path": artifact_path or str(_workspace_root(repo, pr_number)),
        "reason_code": reason_code,
        "waiting_on": waiting_on,
        "next_action": next_action,
        "exit_code": exit_code,
        # Inline pre-gate: not the authoritative completion proof. Only
        # `final-gate` (gate_scope=final) checks pending reviews and PR checks.
        "gate_scope": "inline",
        "commands": summary_commands(repo, pr_number),
    }
    if diagnostics:
        summary["diagnostics"] = diagnostics
    if command == "threads" or include_threads:
        summary["threads"] = _native_thread_rows(session, lean=lean)
    return summary


def summary_commands(repo: str, pr_number: str) -> dict[str, str]:
    return command_templates.common_summary_commands(repo, pr_number)


def _native_thread_rows(session: dict, *, lean: bool = False) -> list[dict[str, Any]]:
    raw_items = session.get("items")
    items: dict[str, Any] = raw_items if isinstance(raw_items, dict) else {}
    rows = []
    alias_index = 0
    for item_id, item in sorted(items.items()):
        if not isinstance(item, dict) or item.get("item_kind") != "github_thread":
            continue
        alias_index += 1
        status = str(item.get("status") or "")
        state = str(item.get("state") or "")
        thread_id = item.get("thread_id") or item.get("origin_ref") or str(item_id).removeprefix("github-thread:")
        reply_evidence = item.get("reply_evidence") if isinstance(item.get("reply_evidence"), dict) else None
        base = {
            "item_id": str(item.get("item_id") or item_id),
            # Stable short per-session handle (T1..Tn) so agents can pass an alias to
            # `agent resolve` instead of transcribing a long, confusable item_id (#135).
            "alias": f"T{alias_index}",
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


def _blocking_local_items(session: dict[str, Any]) -> list[dict[str, Any]]:
    raw_items = session.get("items")
    items: dict[str, Any] = raw_items if isinstance(raw_items, dict) else {}
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


def _emit_auto_simple_not_eligible(
    *,
    command: str,
    repo: str,
    pr_number: str,
    run_id: str,
    max_iterations: int,
    session: dict,
    item: dict[str, Any] | None,
    human: bool,
    lean: bool,
) -> int:
    """Single emission point for the auto-simple-meets-local-findings block (#121)."""
    next_action = (
        "Auto-simple only handles GitHub review threads. Run normal review/findings/adapter workflow "
        "to handle local findings, then rerun this command."
    )
    _set_loop_state(
        session,
        run_id=run_id,
        status="BLOCKED",
        iteration=1,
        max_iterations=max_iterations,
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


def _write_simple_address_request(repo: str, pr_number: str, session: dict, *, command: str, run_id: str) -> Path:
    request_path = _workspace_root(repo, pr_number) / f"simple-address-request-{run_id}-{uuid4().hex}.json"
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
            "Resolve each actionable GitHub thread with `agent resolve <item_id> ...`; classification is recorded internally, no separate classify step is required.",
            "When one set of files/validation evidence addresses multiple threads, run `agent next --batch` to write a BatchActionResponse skeleton, then `agent resolve --batch --input <file>` with per-thread summary/why entries.",
            "Use `agent resolve --homogeneous-reason <why>` only for a homogeneous repeated concern, and `agent resolve --stale --match-files` for STALE/outdated threads.",
            "To decline (not fix) a repeated concern across threads with one shared reply, use `agent resolve --reject|--clarify --homogeneous-reason <why> --match-files`.",
            "After accepted evidence is present, run `agent publish`.",
        ],
        "commands": summary_commands(repo, pr_number),
    }
    write_json_atomic(request_path, request)
    return request_path


def _claimable_github_thread_item_ids(threads: list[dict[str, Any]]) -> list[str]:
    return [str(row["item_id"]) for row in threads if row.get("item_id") and is_claimable_github_thread(row)]


def _batch_response_skeleton(item_ids: list[str]) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "agent_id": "<agent_id>",
        "resolution": "fix",
        "common": {
            "files": ["<file_path>"],
            "validation_commands": [{"command": "<test_command>", "result": "<passed|failed + key signal>"}],
            "fix_reply": {
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
    import time

    from gh_address_cr.core.telemetry import SessionTelemetry
    from gh_address_cr.core.telemetry_safety import (
        command_label,
    )
    from gh_address_cr.core.telemetry_safety import (
        split_inline_env_assignments as _split_inline_env_assignments,
    )

    start_time = time.time()
    result = None
    error: str | None = None
    exit_code = 1
    try:
        run_argv, inline_env = _split_inline_env_assignments(argv)
        if not run_argv:
            return None, "adapter requires an executable after inline environment assignments."
        run_env = None
        if inline_env:
            run_env = os.environ.copy()
            run_env.update(inline_env)
        result = subprocess.run(run_argv, text=True, capture_output=True, env=run_env)
        exit_code = result.returncode
    except Exception as exc:
        error = str(exc)
    finally:
        end_time = time.time()
        try:
            SessionTelemetry.get_instance().record(
                command=command_label(argv),
                start_time=start_time,
                end_time=end_time,
                exit_code=exit_code,
            )
        except Exception as exc:  # intentionally broad: telemetry must not break command execution
            from gh_address_cr.core.command_runner import telemetry_debug_enabled

            if telemetry_debug_enabled():
                sys.stderr.write(f"Telemetry record failed: {type(exc).__name__}: {exc}\n")

    if error is not None:
        return None, error
    if result is None:
        return None, "Adapter command failed before producing a result."
    if result.returncode != 0:
        return None, result.stderr or f"Adapter command failed with exit code {result.returncode}."
    return result.stdout, None


def _emit_native_summary(summary: dict, *, human: bool) -> None:
    _persist_machine_summary(str(summary["repo"]), str(summary["pr_number"]), summary)
    if human:
        status = summary["status"]
        if status == "PASSED":
            print("Review workflow PASSED")
        elif status == "BLOCKED":
            print("Review workflow BLOCKED")
            print(summary["next_action"])
        else:
            print(f"Review workflow {status}")
        return
    sys.stdout.write(json.dumps(summary, indent=2, sort_keys=True) + "\n")


class HighLevelReviewRuntime:
    def _run_preflight_checks(
        self, command: str, parsed: Any, repo: str, pr_number: str
    ) -> tuple[int | None, str | None]:
        if parsed.sync and not parsed.source:
            summary = _build_preflight_summary(
                command,
                repo,
                pr_number,
                status="BLOCKED",
                exit_code=2,
                reason_code="INVALID_FINDINGS_INPUT",
                waiting_on="findings_input",
                next_action="`--sync` requires an explicit --source so missing findings stay scoped to one producer.",
            )
            sys.stdout.write(json.dumps(summary, indent=2, sort_keys=True) + "\n")
            return 2, None
        if command in {"review", "findings"} and parsed.input:
            try:
                preloaded = _read_findings_input(parsed.input)
                if not preloaded.strip():
                    raise FindingsFormatError(EMPTY_FINDINGS_INPUT_MESSAGE)
                return None, preloaded
            except (FindingsFormatError, OSError) as exc:
                summary = _build_preflight_summary(
                    command,
                    repo,
                    pr_number,
                    status="BLOCKED",
                    exit_code=2,
                    reason_code="INVALID_FINDINGS_INPUT",
                    waiting_on="findings_input",
                    next_action=str(exc),
                )
                sys.stdout.write(json.dumps(summary, indent=2, sort_keys=True) + "\n")
                return 2, None
        return None, None

    def _ingest_and_load_threads(
        self,
        command: str,
        parsed: Any,
        session: dict[str, Any],
        preloaded_findings_input: str | None,
        repo: str,
        pr_number: str,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        if command in {"review", "findings"} and parsed.input:
            _ingest_native_findings(
                session,
                raw=preloaded_findings_input or "",
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

        remote_threads: list[dict[str, Any]] = []
        if command in {"address", "review", "threads", "adapter"}:
            client = GitHubClient()
            remote_threads = client.list_threads(repo, pr_number)
            session = core_gate.session_with_remote_threads(session, remote_threads)
        return session, remote_threads

    def _handle_format_error(
        self,
        exc: Exception,
        command: str,
        repo: str,
        pr_number: str,
        run_id: str,
        max_iterations: int,
        session: dict[str, Any],
        human: bool,
        lean: bool,
    ) -> int:
        _set_loop_state(
            session,
            run_id=run_id,
            status="BLOCKED",
            iteration=1,
            max_iterations=max_iterations,
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

    def _handle_github_error(
        self,
        exc: GitHubError,
        command: str,
        repo: str,
        pr_number: str,
        run_id: str,
        max_iterations: int,
        session: dict[str, Any],
        human: bool,
        lean: bool,
    ) -> int:
        _set_loop_state(
            session,
            run_id=run_id,
            status="BLOCKED",
            iteration=1,
            max_iterations=max_iterations,
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

    def handle(self, command: str, passthrough_args: list[str], *, human: bool, lean: bool = False) -> int:
        parsed = _parse_native_high_level_args(command, passthrough_args)
        repo = parsed.repo
        pr_number = str(parsed.pr_number)
        lean = bool(lean or parsed.lean or parsed.summary)
        run_id = parsed.audit_id or f"native-{_utc_now().replace(':', '-')}"
        auto_simple = command == "address" or (command == "review" and bool(parsed.auto_simple))

        exit_code, preloaded_findings_input = self._run_preflight_checks(command, parsed, repo, pr_number)
        if exit_code is not None:
            return exit_code

        session = _load_or_create_session(repo, pr_number)
        _set_loop_state(session, run_id=run_id, status="ACTIVE", iteration=1, max_iterations=parsed.max_iterations)

        try:
            session, remote_threads = self._ingest_and_load_threads(
                command, parsed, session, preloaded_findings_input, repo, pr_number
            )
            _recalc_native_metrics(session)
            if auto_simple and _blocking_local_items(session):
                return _emit_auto_simple_not_eligible(
                    command=command,
                    repo=repo,
                    pr_number=pr_number,
                    run_id=run_id,
                    max_iterations=parsed.max_iterations,
                    session=session,
                    item=_blocking_local_items(session)[0],
                    human=human,
                    lean=lean,
                )
            result = core_gate.evaluate_final_gate(session, remote_threads=remote_threads)
        except (FindingsFormatError, OSError) as exc:
            return self._handle_format_error(
                exc, command, repo, pr_number, run_id, parsed.max_iterations, session, human, lean
            )
        except GitHubError as exc:
            return self._handle_github_error(
                exc, command, repo, pr_number, run_id, parsed.max_iterations, session, human, lean
            )

        if auto_simple and not result.passed:
            if _auto_simple_local_gate_failed(result):
                return _emit_auto_simple_not_eligible(
                    command=command,
                    repo=repo,
                    pr_number=pr_number,
                    run_id=run_id,
                    max_iterations=parsed.max_iterations,
                    session=session,
                    item=_first_local_item(session) or _first_blocking_item(session),
                    human=human,
                    lean=lean,
                )
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
