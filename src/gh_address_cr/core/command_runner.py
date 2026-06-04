from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


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

    _ = retries
    start_time = time.time()
    try:
        result = subprocess.run(
            cmd,
            input=stdin,
            text=True,
            capture_output=True,
            env=runtime_subprocess_env(),
            timeout=timeout,
        )
        end_time = time.time()
        exit_code = result.returncode
    except subprocess.TimeoutExpired as exc:
        end_time = time.time()
        exit_code = 124
        result = subprocess.CompletedProcess(
            args=cmd,
            returncode=exit_code,
            stdout=timeout_stream_text(exc.stdout),
            stderr=timeout_stream_text(exc.stderr) + f"\nCommand timed out after {timeout} seconds.",
        )

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
