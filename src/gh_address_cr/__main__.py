from __future__ import annotations

from gh_address_cr import __version__
from gh_address_cr.cli import main as cli_main
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
            },
        )
    finally:
        shutdown_telemetry()

if __name__ == "__main__":
    raise SystemExit(main())
