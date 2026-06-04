from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

TRANSIENT_GH_FAILURE_MARKERS = (
    "502",
    "503",
    "temporary failure",
    "timeout",
    "timed out",
    "connection reset",
    "graphql error",
    "graphql failed",
)


def is_transient_gh_failure(
    stderr: str | None = None, stdout: str | None = None, returncode: int | None = None
) -> bool:
    _ = returncode
    text = f"{stderr or ''}\n{stdout or ''}".lower()
    return any(marker in text for marker in TRANSIENT_GH_FAILURE_MARKERS)


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
    import time

    from gh_address_cr.core.telemetry import SessionTelemetry, command_label

    attempts = max(1, retries)
    start_time = time.time()
    result: subprocess.CompletedProcess[str] | None = None
    for attempt in range(attempts):
        try:
            result = subprocess.run(
                cmd,
                input=stdin,
                text=True,
                capture_output=True,
                env=runtime_subprocess_env(),
                timeout=timeout,
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

    try:
        SessionTelemetry.get_instance().record(
            command=command_label(cmd),
            start_time=start_time,
            end_time=end_time,
            exit_code=exit_code,
        )
    except Exception as telemetry_exc:
        if telemetry_debug_enabled():
            sys.stderr.write(f"Telemetry recording failed: {telemetry_exc}\n")

    return result
