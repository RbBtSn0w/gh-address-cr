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
    map_vcs_attributes,
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

    effective_argv = argv if argv is not None else sys.argv[1:]
    command = derive_tool_name(effective_argv)

    # Tier 1 VCS GitHub-PR mapping (fail-open, best-effort argv parse). The plain
    # owner/repo is a private identifier for a published skill, so it MUST NOT
    # reach telemetry: it is redacted from command_args below and only its
    # one-way hash appears (as vcs.repository.name). session state is unavailable
    # at span start, so vcs.change.state is omitted.
    repo = None
    pr_number = None
    vcs_attrs: dict[str, str] = {}
    try:
        repo = next((t for t in effective_argv if t.count("/") == 1 and " " not in t), None)
        pr_number = next((t for t in effective_argv if t.isdigit()), None)
        vcs_attrs = map_vcs_attributes(command, repo, pr_number)
    except Exception:
        repo, pr_number, vcs_attrs = None, None, {}

    sanitized_args = safe_command_args([sys.argv[0]] + effective_argv)
    # If this is a PR-scoped invocation, redact the plain owner/repo token from
    # the recorded arguments (position-preserving); the PR stays identifiable via
    # the hashed vcs.repository.name + vcs.change.id.
    if vcs_attrs and repo is not None:
        sanitized_args = ["[redacted]" if arg == repo else arg for arg in sanitized_args]

    attributes = {
        "service.version": __version__,
        "cli.entrypoint": "gh-address-cr",
        PROCESS_EXECUTABLE_NAME: os.path.basename(sys.argv[0]) or "gh-address-cr",
        PROCESS_PID: os.getpid(),
        PROCESS_COMMAND_ARGS: sanitized_args,
        GEN_AI_OPERATION_NAME: "execute_tool",
        GEN_AI_TOOL_NAME: derive_tool_name(effective_argv),
        GEN_AI_TOOL_CALL_ARGUMENTS: json.dumps(sanitized_args),
    }

    try:
        attributes[PROCESS_PARENT_PID] = os.getppid()
    except Exception:
        pass

    attributes.update(detect_agent_session(os.environ))
    attributes.update(vcs_attrs)

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
