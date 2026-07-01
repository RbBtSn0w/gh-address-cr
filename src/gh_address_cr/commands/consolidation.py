"""Advanced ``consolidation`` CLI family (feature 024).

Read-only / control-only commands that expose the reversible migration
framework. None of these commands execute review side effects. This is an
advanced integration surface; it does not replace `review` as the default
orchestration path.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from gh_address_cr import __version__
from gh_address_cr.core.consolidation.authority_map import derive_authority_map
from gh_address_cr.core.consolidation.parity import ParityObserver
from gh_address_cr.core.consolidation.types import ConsolidationError
from gh_address_cr.core.protocol_codes import INVALID_ARGUMENTS, UNKNOWN_SLICE
from gh_address_cr.core.runtime_kernel.projections import project_review_threads

JsonDict = dict[str, Any]

# US1 pilot registry: slice_id -> candidate projection. The full MigrationSlice
# registry (with acceptance gates and rollback triggers) is added in US2; here
# the pilot registers the identity candidate to prove the parity machinery.
_KNOWN_SLICES = {"slice-check-state": project_review_threads}


def _emit(payload: JsonDict, as_json: bool) -> None:
    if as_json:
        sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    else:
        sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _error(reason_code: str, message: str, exit_code: int = 2) -> int:
    sys.stderr.write(f"{reason_code}: {message}\n")
    return exit_code


def _load_facts(path: str) -> list[JsonDict]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(raw, dict) and "facts" in raw:
        return list(raw["facts"])
    if isinstance(raw, list):
        return raw
    raise ValueError("facts file must be a JSON list or an object with a 'facts' array")


def _handle_status(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="gh-address-cr consolidation status", add_help=True)
    parser.add_argument("--json", action="store_true", help="Emit the authority-map.v1 JSON document.")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 2)
    # No slice has reached `default` yet, so every axis is legacy-authoritative.
    authority_map = derive_authority_map(__version__, {})
    _emit(authority_map.to_dict(), args.json)
    return 0


def _handle_parity(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="gh-address-cr consolidation parity", add_help=True)
    parser.add_argument("--slice", dest="slice_id", required=True, help="Migration slice id to replay.")
    parser.add_argument("--facts", dest="facts", required=True, help="Path to a runtime-facts JSON file to replay.")
    parser.add_argument("--json", action="store_true", help="Emit the parity-report.v1 JSON document.")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 2)

    candidate = _KNOWN_SLICES.get(args.slice_id)
    if candidate is None:
        return _error(UNKNOWN_SLICE, f"unknown migration slice: {args.slice_id}")

    try:
        facts = _load_facts(args.facts)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return _error(INVALID_ARGUMENTS, f"could not load facts: {exc}")

    observer = ParityObserver()
    observer.register_candidate(args.slice_id, candidate)
    try:
        observation = observer.observe(args.slice_id, facts)
    except ConsolidationError as exc:
        return _error(exc.reason_code, str(exc))
    _emit(observation.to_dict(), args.json)
    return 0


def handle_consolidation_command(repo: str | None, pr_number: str | None, args: list[str]) -> int:
    """Dispatch a ``consolidation`` subcommand. ``repo``/``pr_number`` are folded
    back into ``args`` by the CLI, so the subcommand name leads ``args``."""

    argv = list(args)
    if repo is not None:
        argv = [repo, *argv]
    if pr_number is not None:
        argv = [pr_number, *argv]

    if not argv or argv[0] in {"-h", "--help"}:
        sys.stdout.write(
            "Consolidation commands:\n"
            "  gh-address-cr consolidation status [--json]\n"
            "  gh-address-cr consolidation parity --slice <id> --facts <path> [--json]\n"
        )
        return 0

    subcommand, rest = argv[0], argv[1:]
    if subcommand == "status":
        return _handle_status(rest)
    if subcommand == "parity":
        return _handle_parity(rest)
    return _error(INVALID_ARGUMENTS, f"unknown consolidation subcommand: {subcommand}")
