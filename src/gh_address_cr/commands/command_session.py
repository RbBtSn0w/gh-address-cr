from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
import time
from pathlib import Path


def handle_command_session(passthrough: list[str]) -> int:
    """Run a batch of CLI operations in-process and return a combined JSON summary.

    Each operation's ``argv`` is dispatched through ``cli.main`` in the current
    process (not a child process), so operations share interpreter state — module
    globals, singletons (e.g. ``SessionTelemetry``), and cwd persist across them.
    ``stdout``/``stderr`` are captured via ``redirect_stdout``/``redirect_stderr``,
    which only intercept Python-level writes; output from any subprocess a command
    spawns (e.g. ``gh``) goes to the inherited file descriptors and is NOT captured
    here. Callers needing isolated, fully-captured execution should invoke the CLI
    as separate processes instead.
    """
    from gh_address_cr.cli import main
    from gh_address_cr.core.telemetry_safety import _safe_diagnostic_text, command_label
    from gh_address_cr.telemetry import add_current_span_event, set_current_span_attributes

    parser = argparse.ArgumentParser(prog="gh-address-cr command-session")
    parser.add_argument("--input", required=True)
    parsed = parser.parse_args(passthrough)
    try:
        raw = sys.stdin.read() if parsed.input == "-" else Path(parsed.input).read_text(encoding="utf-8")
        payload = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        summary = {
            "status": "FAILED",
            "reason_code": "COMMAND_SESSION_INPUT_INVALID",
            "waiting_on": "command_session_input",
            "next_action": "Provide JSON with an operations array.",
            "results": [],
            "exit_code": 2,
            "diagnostics": [str(exc)],
        }
        sys.stdout.write(json.dumps(summary, indent=2, sort_keys=True) + "\n")
        return 2
    operations = payload.get("operations") if isinstance(payload, dict) else None
    if not isinstance(operations, list):
        summary = {
            "status": "FAILED",
            "reason_code": "COMMAND_SESSION_INPUT_INVALID",
            "waiting_on": "command_session_input",
            "next_action": "Provide JSON with an operations array.",
            "results": [],
            "exit_code": 2,
        }
        sys.stdout.write(json.dumps(summary, indent=2, sort_keys=True) + "\n")
        return 2

    results = []
    set_current_span_attributes({"gh_address_cr.command_session.operation_count": len(operations)})
    for index, operation in enumerate(operations):
        operation_id = (
            str(operation.get("id") or f"op-{index + 1}") if isinstance(operation, dict) else f"op-{index + 1}"
        )
        argv = operation.get("argv") if isinstance(operation, dict) else None
        if not isinstance(argv, list) or not all(isinstance(arg, str) for arg in argv):
            results.append(
                {
                    "id": operation_id,
                    "status": "FAILED",
                    "reason_code": "COMMAND_SESSION_OPERATION_INVALID",
                    "exit_code": 2,
                    "stdout": "",
                    "stderr": "operation argv must be a string array",
                }
            )
            continue
        op_started_at = time.monotonic()
        op_command = command_label(argv) or "command"
        safe_operation_id = _safe_diagnostic_text(operation_id)
        add_current_span_event(
            "gh_address_cr.command_session.operation.start",
            {
                "gh_address_cr.command_session.operation_id": safe_operation_id,
                "gh_address_cr.command_session.operation_index": index + 1,
                "gh_address_cr.command.name": op_command,
            },
        )
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                exit_code = main(list(argv))
            except SystemExit as exc:
                exit_code = exc.code if isinstance(exc.code, int) else 2
            except Exception as exc:
                stderr.write(f"Unhandled exception: {exc}\n")
                exit_code = 2
        add_current_span_event(
            "gh_address_cr.command_session.operation.end",
            {
                "gh_address_cr.command_session.operation_id": safe_operation_id,
                "gh_address_cr.command_session.operation_index": index + 1,
                "gh_address_cr.command.name": op_command,
                "gh_address_cr.command_session.operation_exit_code": exit_code,
                "gh_address_cr.command_session.operation_duration_ms": round((time.monotonic() - op_started_at) * 1000, 3),
            },
        )
        results.append(
            {
                "id": operation_id,
                "status": "SUCCESS" if exit_code == 0 else "FAILED",
                "reason_code": "COMMAND_SESSION_STEP_OK" if exit_code == 0 else "COMMAND_SESSION_STEP_FAILED",
                "exit_code": exit_code,
                "stdout": stdout.getvalue(),
                "stderr": stderr.getvalue(),
            }
        )
    failed_operations = sum(1 for result in results if result["exit_code"] != 0)
    set_current_span_attributes({"gh_address_cr.command_session.failed_operations": failed_operations})
    add_current_span_event(
        "gh_address_cr.command_session.summary",
        {
            "gh_address_cr.command_session.operation_count": len(results),
            "gh_address_cr.command_session.failed_operations": failed_operations,
        },
    )
    session_exit = 0 if all(result["exit_code"] == 0 for result in results) else 2
    summary = {
        "status": "SUCCESS" if session_exit == 0 else "PARTIAL",
        "reason_code": "COMMAND_SESSION_COMPLETE" if session_exit == 0 else "COMMAND_SESSION_PARTIAL",
        "results": results,
        "exit_code": session_exit,
    }
    sys.stdout.write(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    return session_exit
