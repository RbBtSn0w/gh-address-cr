from __future__ import annotations

import os
import sys

from gh_address_cr import __version__
from gh_address_cr.cli import main as cli_main
from gh_address_cr.core.otel_semconv import (
    PROCESS_COMMAND_ARGS,
    PROCESS_EXECUTABLE_NAME,
    PROCESS_PID,
)
from gh_address_cr.core.telemetry_safety import safe_command_args
from gh_address_cr.telemetry import initialize_telemetry, run_traced, shutdown_telemetry


def main(argv: list[str] | None = None) -> int:
    """Run the CLI under one process-level span and always flush telemetry."""
    tracer = initialize_telemetry()
    try:
        return run_traced(
            tracer,
            "gh-address-cr.cli",
            lambda: cli_main(argv),
            attributes={
                "service.version": __version__,
                "cli.entrypoint": "gh-address-cr",
                PROCESS_EXECUTABLE_NAME: os.path.basename(sys.argv[0]) or "gh-address-cr",
                PROCESS_PID: os.getpid(),
                PROCESS_COMMAND_ARGS: safe_command_args(
                    [sys.argv[0]] + (argv if argv is not None else sys.argv[1:])
                ),
            },
        )
    finally:
        shutdown_telemetry()

if __name__ == "__main__":
    raise SystemExit(main())
