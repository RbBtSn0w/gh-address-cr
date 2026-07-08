from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from gh_address_cr.core.otel_semconv import (
    ERROR_TYPE,
    GH_ADDRESS_CR_SUBPROCESS_SPAN_NAME,
    PROCESS_COMMAND_ARGS,
    PROCESS_EXECUTABLE_NAME,
    PROCESS_EXIT_CODE,
    PROCESS_PID,
)
from gh_address_cr.core.telemetry_safety import (
    classify_workflow_span_layer,
    command_label,
    safe_command_args,
    workflow_step_span_attributes,
)
from gh_address_cr.github.transient_failures import is_transient_github_failure_text

# Bounded reap after killing a timed-out subprocess so the cleanup path can
# never itself hang the CLI (e.g. a process wedged in uninterruptible sleep
# that does not act on SIGKILL promptly). Unlike stdlib subprocess.run, which
# reaps unbounded, a user-facing CLI must not deadlock in its own timeout path.
_KILL_REAP_TIMEOUT_SECONDS = 5.0


def is_transient_gh_failure(
    stderr: str | None = None, stdout: str | None = None, returncode: int | None = None
) -> bool:
    _ = returncode
    return is_transient_github_failure_text(stderr, stdout)


def telemetry_debug_enabled() -> bool:
    return (os.environ.get("GH_ADDRESS_CR_DEBUG_TELEMETRY") or "").strip().lower() in {"1", "true", "yes"}


def timeout_stream_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value


def runtime_subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    runtime_root = str(Path(__file__).resolve().parents[2])
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = runtime_root if not existing else f"{runtime_root}{os.pathsep}{existing}"
    return env


def run_cmd(
    cmd: list[str],
    *,
    stdin: str | None = None,
    retries: int = 3,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    from opentelemetry.trace import SpanKind, Status, StatusCode

    from gh_address_cr.core.telemetry import SessionTelemetry
    from gh_address_cr.otel_tracing import add_current_span_event, set_current_span_attributes, start_child_span

    attempts = max(1, retries)
    start_time = time.time()
    result: subprocess.CompletedProcess[str] | None = None
    tool_name = command_label(cmd) or "subprocess"
    safe_args = safe_command_args(list(cmd))
    layer = classify_workflow_span_layer(
        has_independent_duration=True,
        has_independent_count=True,
        has_error_boundary=True,
        externally_visible=True,
    )
    add_current_span_event(
        "gh_address_cr.subprocess.start",
        {
            "gh_address_cr.command.name": tool_name,
            "gh_address_cr.subprocess.command_label": tool_name,
            "gh_address_cr.subprocess.command_args": safe_args,
            "gh_address_cr.subprocess.retries": attempts,
        },
    )
    with start_child_span(
        GH_ADDRESS_CR_SUBPROCESS_SPAN_NAME,
        kind=SpanKind.CLIENT,
        attributes={
            **workflow_step_span_attributes(step_name="subprocess", step_kind=layer),
            "gh_address_cr.command.name": tool_name,
            "gh_address_cr.subprocess.command_label": tool_name,
            "gh_address_cr.subprocess.retries": attempts,
            PROCESS_EXECUTABLE_NAME: os.path.basename(cmd[0]) if cmd else "subprocess",
            PROCESS_COMMAND_ARGS: safe_args,
        },
    ) as span:
        for attempt in range(attempts):
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE if stdin is not None else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=runtime_subprocess_env(),
            )
            set_current_span_attributes({PROCESS_PID: process.pid})
            try:
                stdout, stderr = process.communicate(input=stdin, timeout=timeout)
                result = subprocess.CompletedProcess(
                    args=cmd, returncode=process.returncode, stdout=stdout, stderr=stderr
                )
                if (
                    result.returncode != 0
                    and cmd
                    and cmd[0] == "gh"
                    and attempt < attempts - 1
                    and is_transient_gh_failure(result.stderr, result.stdout, result.returncode)
                ):
                    time.sleep(2**attempt)
                    continue
                break
            except subprocess.TimeoutExpired as exc:
                # kill() can race the process exiting and raise OSError
                # (ProcessLookupError on POSIX, PermissionError on Windows);
                # swallow it so a timeout still yields a 124 result, never a crash.
                try:
                    process.kill()
                except OSError:
                    pass
                # Bounded reap: never let post-kill draining hang the CLI.
                try:
                    process.communicate(timeout=_KILL_REAP_TIMEOUT_SECONDS)
                except (subprocess.TimeoutExpired, OSError):
                    pass
                result = subprocess.CompletedProcess(
                    args=cmd,
                    returncode=124,
                    stdout=timeout_stream_text(exc.stdout),
                    stderr=timeout_stream_text(exc.stderr) + f"\nCommand timed out after {timeout} seconds.",
                )
                if cmd and cmd[0] == "gh" and attempt < attempts - 1:
                    time.sleep(2**attempt)
                    continue
                break
        if result is None:
            result = subprocess.CompletedProcess(
                args=cmd,
                returncode=1,
                stdout="",
                stderr="Command failed before producing a result.",
            )
        end_time = time.time()
        exit_code = result.returncode
        span_attributes: dict[str, str | int | float] = {
            "gh_address_cr.subprocess.attempts_used": attempt + 1,
            "gh_address_cr.subprocess.duration_ms": round((end_time - start_time) * 1000, 3),
            PROCESS_EXIT_CODE: exit_code,
        }
        # Caller-span convention (CLI spans semconv): a non-zero exit from an
        # external tool is a genuine error, so record error.type AND set the
        # span status to ERROR. Set both once, from the final exit code, so a
        # transient timeout that later succeeds on retry leaves neither behind.
        if exit_code != 0:
            span_attributes[ERROR_TYPE] = "timeout" if exit_code == 124 else str(exit_code)
        set_current_span_attributes(span_attributes)
        if exit_code != 0:
            span.set_status(Status(StatusCode.ERROR))
    end_time = time.time()
    exit_code = result.returncode
    add_current_span_event(
        "gh_address_cr.subprocess.end",
        {
            "gh_address_cr.command.name": tool_name,
            "gh_address_cr.subprocess.command_label": tool_name,
            "gh_address_cr.subprocess.command_args": safe_args,
            "gh_address_cr.subprocess.attempts_used": attempt + 1,
            "gh_address_cr.subprocess.exit_code": exit_code,
        },
    )

    try:
        SessionTelemetry.get_instance().record(
            command=tool_name,
            start_time=start_time,
            end_time=end_time,
            exit_code=exit_code,
        )
    except Exception as telemetry_exc:
        if telemetry_debug_enabled():
            sys.stderr.write(f"Telemetry recording failed: {telemetry_exc}\n")

    return result
