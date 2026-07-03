from __future__ import annotations

import json
import os
import sys
from collections.abc import Sequence

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
    sanitize_cli_argv,
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

    effective_argv = argv if argv is not None else sys.argv[1:]
    sanitized_args, vcs_attrs = sanitize_cli_argv([sys.argv[0]] + effective_argv, command_argv=effective_argv)
    command = derive_tool_name(effective_argv)

    attributes: dict[str, str | bool | int | float | Sequence[str]] = {
        "service.version": __version__,
        "cli.entrypoint": "gh-address-cr",
        "gh_address_cr.span.kind": "process",
        "gh_address_cr.command.name": command,
        PROCESS_EXECUTABLE_NAME: os.path.basename(sys.argv[0]) or "gh-address-cr",
        PROCESS_PID: os.getpid(),
        PROCESS_COMMAND_ARGS: sanitized_args,
        GEN_AI_OPERATION_NAME: "execute_tool",
        GEN_AI_TOOL_NAME: command,
        GEN_AI_TOOL_CALL_ARGUMENTS: json.dumps(sanitized_args),
    }

    try:
        attributes[PROCESS_PARENT_PID] = os.getppid()
    except Exception:
        pass

    attributes.update(detect_agent_session(os.environ))
    attributes.update(vcs_attrs)

    try:
        # The process span remains the invocation anchor. Child workflow spans,
        # when promoted, are emitted by downstream runtime call sites under this
        # root rather than replacing it with a synthetic session parent.
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
