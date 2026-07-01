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
from gh_address_cr.core.consolidation.authority_map import AuthorityEntry, derive_authority_map
from gh_address_cr.core.consolidation.deprecations import default_deprecation_inventory
from gh_address_cr.core.consolidation.evidence import (
    RolloutEvidence,
    RolloutEvidenceStatus,
    evaluation_to_rollout_evidence,
)
from gh_address_cr.core.consolidation.migration_slice import get_registered_slice
from gh_address_cr.core.consolidation.parity import ParityObserver
from gh_address_cr.core.consolidation.rollout import RolloutPolicy
from gh_address_cr.core.consolidation.rollout_state import load_or_default, rollout_state_path
from gh_address_cr.core.consolidation.types import CompatibilityDirection, ConsolidationError, Owner, RolloutStage
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
        return
    sys.stdout.write(_render_human(payload) + "\n")


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


def _slice_owners_for_status(
    *, cohort: str, rollout_state: Any
) -> list[AuthorityEntry]:
    owners: list[AuthorityEntry] = []
    for slice_state in rollout_state.slices:
        if slice_state.stage not in {RolloutStage.DEFAULT, RolloutStage.DEPRECATING, RolloutStage.DELETED}:
            continue
        slice_def = get_registered_slice(slice_state.slice_id)
        if slice_def.authority_for_cohort(cohort) != Owner.KERNEL:
            continue
        direction = CompatibilityDirection.NONE if slice_state.stage == RolloutStage.DELETED else CompatibilityDirection.LEGACY_FROM_KERNEL
        for axis in slice_def.axes:
            owners.append(
                AuthorityEntry(
                    axis=axis,
                    authoritative_owner=Owner.KERNEL,
                    compatibility_direction=direction,
                    slice_id=slice_state.slice_id,
                )
            )
    return owners


def _load_rollout_evidence(path: str | None, fallback_reference: str | None) -> RolloutEvidence:
    if not path:
        return RolloutEvidence(
            status=RolloutEvidenceStatus.PROVISIONAL,
            reason_code="PROVISIONAL_EVIDENCE",
            reference=fallback_reference,
        )
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("evidence file must contain a JSON object")
    return evaluation_to_rollout_evidence(payload)


def _load_parity_differences(path: str | None) -> tuple[str, ...]:
    if not path:
        return ()
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("parity file must contain a JSON object")
    differences = payload.get("differences")
    if differences is None:
        return ()
    if not isinstance(differences, list):
        raise ValueError("parity file differences must be a JSON array")
    return tuple(str(item) for item in differences)


def _handle_status(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="gh-address-cr consolidation status", add_help=True)
    parser.add_argument("--json", action="store_true", help="Emit the authority-map.v1 JSON document.")
    parser.add_argument(
        "--cohort",
        default="github-review-thread",
        help="Cohort id used to project authority ownership for migration slices.",
    )
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 2)
    rollout_state = load_or_default()
    authority_map = derive_authority_map(__version__, _slice_owners_for_status(cohort=args.cohort, rollout_state=rollout_state))
    payload = authority_map.to_dict()
    payload["slices"] = [slice_state.to_dict() for slice_state in rollout_state.slices]
    payload["hypotheses"] = [hypothesis.to_dict() for hypothesis in rollout_state.hypotheses]
    _emit(payload, args.json)
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


def _handle_rollout(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="gh-address-cr consolidation rollout", add_help=True)
    parser.add_argument("--slice", dest="slice_id", required=True, help="Migration slice id to transition.")
    parser.add_argument(
        "--to",
        dest="target_stage",
        required=True,
        choices=["shadow", "opt_in", "default", "deprecating", "deleted"],
    )
    parser.add_argument(
        "--evidence-file",
        help="Path to an evaluation.v1 JSON object used to derive rollout evidence for default/deleted gates.",
    )
    parser.add_argument(
        "--parity-file",
        help="Path to a parity-report.v1 JSON object whose differences gate rollout transitions.",
    )
    parser.add_argument("--json", action="store_true", help="Emit the rollout transition JSON document.")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 2)

    try:
        slice_def = get_registered_slice(args.slice_id)
    except KeyError:
        return _error(UNKNOWN_SLICE, f"unknown migration slice: {args.slice_id}")

    rollout_state = load_or_default(rollout_state_path())
    try:
        current_slice_state = rollout_state.slice_for(args.slice_id)
    except KeyError:
        return _error(UNKNOWN_SLICE, f"unknown rollout state slice: {args.slice_id}")

    try:
        evidence = _load_rollout_evidence(args.evidence_file, current_slice_state.evidence_ref)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return _error(INVALID_ARGUMENTS, f"could not load rollout evidence: {exc}")
    try:
        parity_differences = _load_parity_differences(args.parity_file)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return _error(INVALID_ARGUMENTS, f"could not load parity report: {exc}")
    decision = RolloutPolicy().evaluate(
        current_stage=current_slice_state.stage,
        target_stage=RolloutStage(args.target_stage),
        evidence=evidence,
        parity_differences=parity_differences,
        deprecation_window_complete=current_slice_state.deprecation_window_complete,
    )
    if not decision.allowed:
        return _error(decision.reason_code, f"cannot transition {args.slice_id} from {current_slice_state.stage.value} to {args.target_stage}")

    updated = rollout_state.with_slice_stage(
        args.slice_id,
        decision.next_stage,
        evidence_ref=current_slice_state.evidence_ref,
        deprecation_window_complete=current_slice_state.deprecation_window_complete,
    )
    updated.write(rollout_state_path())
    payload: JsonDict = {
        "schema": "rollout-transition.v1",
        "slice_id": args.slice_id,
        "current_stage": current_slice_state.stage.value,
        "requested_stage": args.target_stage,
        "resulting_stage": decision.next_stage.value,
        "reason_code": decision.reason_code,
        "evidence": evidence.to_dict(),
        "parity_differences": list(parity_differences),
        "state": updated.to_dict(),
        "slice": slice_def.to_dict(),
    }
    _emit(payload, args.json)
    return 0


def _handle_deprecations(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="gh-address-cr consolidation deprecations", add_help=True)
    parser.add_argument("--json", action="store_true", help="Emit the deprecation-inventory.v1 JSON document.")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 2)
    _emit(default_deprecation_inventory().to_dict(), args.json)
    return 0


def handle_consolidation_command(repo: str | None, pr_number: str | None, args: list[str]) -> int:
    """Dispatch a ``consolidation`` subcommand.

    The root CLI still parses the first two trailing positionals as ``repo`` and
    ``pr_number`` placeholders before command-specific dispatch. Consolidation is
    not PR-scoped, so we treat a recognized subcommand in ``repo`` as the real
    subcommand and ignore accidental explicit scope values.
    """

    known_subcommands = {"status", "parity", "rollout", "deprecations", "-h", "--help"}
    argv = list(args)
    if repo in known_subcommands:
        argv = [repo, *argv]
    elif repo is not None and "/" not in repo and pr_number is None:
        argv = [repo, *argv]

    if not argv or argv[0] in {"-h", "--help"}:
        sys.stdout.write(
            "Consolidation commands:\n"
            "  gh-address-cr consolidation status [--cohort <id>] [--json]\n"
            "  gh-address-cr consolidation parity --slice <id> --facts <path> [--json]\n"
            "  gh-address-cr consolidation rollout --slice <id> --to <stage> [--evidence-file <path>] [--parity-file <path>] [--json]\n"
            "  gh-address-cr consolidation deprecations [--json]\n"
        )
        return 0

    subcommand, rest = argv[0], argv[1:]
    if subcommand == "status":
        return _handle_status(rest)
    if subcommand == "parity":
        return _handle_parity(rest)
    if subcommand == "rollout":
        return _handle_rollout(rest)
    if subcommand == "deprecations":
        return _handle_deprecations(rest)
    return _error(INVALID_ARGUMENTS, f"unknown consolidation subcommand: {subcommand}")


def _render_human(payload: JsonDict) -> str:
    schema = str(payload.get("schema") or "")
    if schema == "authority-map.v1":
        lines = [f"authority-map {payload.get('runtime_version', 'unknown')}"]
        lines.extend(
            f"- {row['axis']}: {row['authoritative_owner']} ({row['compatibility_direction']})"
            for row in payload.get("axes", [])
        )
        return "\n".join(lines)
    if schema == "parity-report.v1":
        differences = payload.get("differences", [])
        return "\n".join(
            [
                f"parity {payload.get('slice_id', 'unknown')}",
                f"- side_effects_executed: {payload.get('side_effects_executed', 0)}",
                f"- differences: {len(differences)}",
            ]
        )
    if schema == "rollout-transition.v1":
        return (
            f"rollout {payload.get('slice_id', 'unknown')}: "
            f"{payload.get('current_stage', 'unknown')} -> {payload.get('resulting_stage', 'unknown')} "
            f"({payload.get('reason_code', 'UNKNOWN')})"
        )
    if schema == "deprecation-inventory.v1":
        entries = payload.get("entries", [])
        return "\n".join(
            [
                "deprecation-inventory",
                f"- entries: {len(entries)}",
            ]
        )
    return json.dumps(payload, indent=2, sort_keys=True)
