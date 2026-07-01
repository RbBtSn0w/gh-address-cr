from __future__ import annotations

import json
import os
import sys

from gh_address_cr import __version__
from gh_address_cr.cli import main as cli_main
from gh_address_cr.core.otel_semconv import (
    GEN_AI_OPERATION_NAME,
    GEN_AI_TOOL_CALL_ARGUMENTS,
    GEN_AI_TOOL_NAME,
    PROCESS_COMMAND_ARGS,
    PROCESS_EXECUTABLE_NAME,
    PROCESS_PARENT_PID,
    PROCESS_PID,
)
from gh_address_cr.core.telemetry_safety import (
    derive_tool_name,
    detect_agent_session,
    safe_command_args,
)
from gh_address_cr.telemetry import (
    initialize_telemetry,
    resolve_parent_context,
    run_traced,
    shutdown_telemetry,
)


def main(argv: list[str] | None = None) -> int:
    """Run the CLI under one process-level span and always flush telemetry."""
    # Resolve the parent context from TRACEPARENT environment.
    # Note: TRACEPARENT path is dormant (R-002) in v1, while Tier 2
    # agent session correlation is the active correlation path (R-009).
    parent_context = resolve_parent_context(os.environ)

    tracer = initialize_telemetry()

    sanitized_args = safe_command_args(
        [sys.argv[0]] + (argv if argv is not None else sys.argv[1:])
    )

    attributes = {
        "service.version": __version__,
        "cli.entrypoint": "gh-address-cr",
        PROCESS_EXECUTABLE_NAME: os.path.basename(sys.argv[0]) or "gh-address-cr",
        PROCESS_PID: os.getpid(),
        PROCESS_COMMAND_ARGS: sanitized_args,
        GEN_AI_OPERATION_NAME: "execute_tool",
        GEN_AI_TOOL_NAME: derive_tool_name(argv if argv is not None else sys.argv[1:]),
        GEN_AI_TOOL_CALL_ARGUMENTS: json.dumps(sanitized_args),
    }

    try:
        attributes[PROCESS_PARENT_PID] = os.getppid()
    except Exception:
        pass

    attributes.update(detect_agent_session(os.environ))

    try:
        return run_traced(
            tracer,
            "gh-address-cr.cli",
            lambda: cli_main(argv),
            attributes=attributes,
            context=parent_context,
        )
    finally:
        shutdown_telemetry()

if __name__ == "__main__":
    raise SystemExit(main())
