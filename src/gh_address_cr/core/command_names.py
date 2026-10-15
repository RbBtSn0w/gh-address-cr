"""The command names the CLI accepts: one vocabulary for display, validation and telemetry.

Only passive names live here. What a command does (dispatch stage, output mode, PR scoping)
stays in ``cli.py`` and ``commands/``. This module imports nothing from them so that ``core``
can depend on it (docs/rfcs/044-command-vocabulary).
"""

from __future__ import annotations

# Top-level commands, in the order the argparse command list shows them.
PUBLIC_COMMAND_NAMES: tuple[str, ...] = (
    "active-pr",
    "agent",
    "address",
    "review",
    "threads",
    "findings",
    "adapter",
    "doctor",
    "command-session",
    "final-gate",
    "review-to-findings",
    "submit-feedback",
    "submit-action",
    "version",
)
PUBLIC_COMMANDS: frozenset[str] = frozenset(PUBLIC_COMMAND_NAMES)

# `agent` subcommands, in the order the `agent` usage line and error message show them.
AGENT_SUBCOMMANDS: tuple[str, ...] = (
    "manifest",
    "classify",
    "next",
    "submit",
    "resolve",
    "evidence",
    "publish",
    "leases",
    "reclaim",
    "orchestrate",
)
