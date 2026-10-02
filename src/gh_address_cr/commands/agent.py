from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime

from gh_address_cr import (
    MAX_PARALLEL_CLAIMS,
    PROTOCOL_VERSION,
    SUPPORTED_SKILL_CONTRACT_VERSIONS,
    __version__,
)
from gh_address_cr.agent.roles import TERMINAL_RESOLUTIONS
from gh_address_cr.commands.common import (
    agent_args_with_scope as _agent_args_with_scope,
)
from gh_address_cr.commands.common import (
    emit_scope_resolution_error as _emit_scope_resolution_error,
)
from gh_address_cr.commands.common import (
    output_generic_agent_error,
    output_session_error,
    output_workflow_error,
)
from gh_address_cr.commands.common import (
    prepend_optional as _prepend_optional,
)
from gh_address_cr.core import (
    agent_batch,
    agent_protocol,
    agent_protocol_validation,
    leases,
    protocol_codes,
    publisher,
    workflow,
    workflow_matching,
)
from gh_address_cr.core import session as session_store
from gh_address_cr.core.errors import WorkflowError

PUBLIC_COMMANDS = {
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
}


def build_agent_manifest() -> dict:
    return {
        "status": "MANIFEST_READY",
        "schema_version": PROTOCOL_VERSION,
        "runtime_package": "gh-address-cr",
        "runtime_version": __version__,
        "agent_id": "gh-address-cr-runtime",
        "protocol_versions": [PROTOCOL_VERSION],
        "supported_protocol_versions": [PROTOCOL_VERSION],
        "supported_skill_contract_versions": list(SUPPORTED_SKILL_CONTRACT_VERSIONS),
        "roles": [
            "coordinator",
            "review_producer",
            "triage",
            "fixer",
            "verifier",
            "publisher",
            "gatekeeper",
        ],
        "actions": [
            "review",
            "produce_findings",
            "triage",
            "classify",
            "resolve",
            "evidence",
            "clarify",
            "defer",
            "reject",
            "verify",
            "publish",
            "gate",
        ],
        "input_formats": [
            "action_request.v1",
            "finding.v1",
            "github_thread.v1",
            "evidence_profile.v1",
            "workflow_decision.v1",
        ],
        "output_formats": [
            "action_response.v1",
            "batch_action_response.v1",
            "batch_action_response_skeleton.v1",
            "evidence_record.v1",
            "evidence_profile.v1",
            "gate_report.v1",
            "dispatch_receipt.v2",
            "worker_packet.v2",
            "work_item_boundary.v1",
            "workflow_decision.v1",
        ],
        "constraints": {
            "max_parallel_claims": MAX_PARALLEL_CLAIMS,
        },
        "public_commands": sorted(PUBLIC_COMMANDS),
    }


def handle_agent_command(args: argparse.Namespace) -> int:
    try:
        return _route_agent_command(args)
    except session_store.SessionError as exc:
        # Any agent subcommand can hit a session or persistence failure after its own
        # error handling; surface its reason code instead of an unstructured traceback.
        return output_session_error(exc, repo=args.pr_number, pr_number=args.args[0] if args.args else None)


def _route_agent_command(args: argparse.Namespace) -> int:
    if args.repo in {None, "-h", "--help"}:
        sys.stdout.write(
            "usage: gh-address-cr agent {manifest,classify,next,submit,resolve,evidence,publish,leases,reclaim,orchestrate} ...\n\n"
            "Agent protocol utilities.\n"
        )
        return 0
    if args.repo == "manifest" and not args.pr_number and not args.args:
        sys.stdout.write(json.dumps(build_agent_manifest(), indent=2, sort_keys=True) + "\n")
        return 0
    if args.repo == "classify":
        return handle_agent_classify(args.pr_number, args.args)
    if args.repo == "next":
        return handle_agent_next(args.pr_number, args.args)
    if args.repo == "submit":
        return handle_agent_submit(args.pr_number, args.args)
    if args.repo == "resolve":
        return handle_agent_resolve(args.pr_number, args.args)
    if args.repo == "evidence":
        return handle_agent_evidence(args.pr_number, args.args)
    if args.repo == "publish":
        return handle_agent_publish(args.pr_number, args.args)
    if args.repo == "leases":
        return handle_agent_leases(args.pr_number, args.args)
    if args.repo == "reclaim":
        return handle_agent_reclaim(args.pr_number, args.args)
    if args.repo == "orchestrate":
        return handle_agent_orchestrate(args.pr_number, args.args)
    print(
        "Unknown agent command. Supported commands: manifest, classify, next, submit, resolve, evidence, publish, leases, reclaim, orchestrate.",
        file=sys.stderr,
    )
    return 2


def _parse_with_scope(
    parser: argparse.ArgumentParser, repo: str | None, passthrough: list[str]
) -> tuple[argparse.Namespace | None, int]:
    """Parse agent-subcommand args with uniform cached-PR-scope resolution (#122)."""
    scope_args, scope_error = _agent_args_with_scope(repo, passthrough)
    if scope_error is not None:
        return None, _emit_scope_resolution_error(scope_error)
    return parser.parse_args(scope_args), 0


def handle_agent_classify(repo: str | None, passthrough: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="gh-address-cr agent classify")
    parser.add_argument("repo")
    parser.add_argument("pr_number")
    parser.add_argument("item_id")
    parser.add_argument("--classification", required=True, choices=sorted(TERMINAL_RESOLUTIONS))
    parser.add_argument("--agent-id", default="agent")
    parser.add_argument("--note", required=True)
    parsed, scope_rc = _parse_with_scope(parser, repo, passthrough)
    if parsed is None:
        return scope_rc
    try:
        payload = agent_protocol.record_classification(
            parsed.repo,
            parsed.pr_number,
            item_id=parsed.item_id,
            classification=parsed.classification,
            agent_id=parsed.agent_id,
            note=parsed.note,
        )
    except WorkflowError as exc:
        return output_workflow_error(exc, repo=parsed.repo, pr_number=parsed.pr_number)
    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return 0


def handle_agent_next(repo: str | None, passthrough: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="gh-address-cr agent next")
    parser.add_argument("repo")
    parser.add_argument("pr_number")
    parser.add_argument("--role")
    parser.add_argument("--agent-id", default="agent")
    parser.add_argument("--item-id")
    parser.add_argument("--now")
    parser.add_argument(
        "--batch",
        action="store_true",
        help="Generate a skeleton batch-response-skeleton.json for all unresolved threads.",
    )
    parser.add_argument("--files", help="Only batch lease threads that affect these files (comma-separated).")
    parsed, scope_rc = _parse_with_scope(parser, repo, passthrough)
    if parsed is None:
        return scope_rc
    if not parsed.batch and not parsed.role:
        parser.error("one of the following arguments is required: --role or --batch")
    if parsed.batch and parsed.role:
        parser.error("arguments --role and --batch are mutually exclusive")
    if not parsed.batch and parsed.files:
        parser.error("argument --files can only be used with --batch")
    try:
        now_dt = None
        if parsed.now:
            now_dt = datetime.fromisoformat(parsed.now.replace("Z", "+00:00"))
        if parsed.batch:
            payload = agent_batch.issue_batch_action_request(
                parsed.repo,
                parsed.pr_number,
                agent_id=parsed.agent_id,
                files=_parse_agent_files(parsed.files),
                now=now_dt,
            )
        else:
            payload = agent_protocol.issue_action_request(
                parsed.repo,
                parsed.pr_number,
                role=parsed.role,
                agent_id=parsed.agent_id,
                item_id=parsed.item_id,
                now=now_dt,
            )
    except WorkflowError as exc:
        return output_workflow_error(exc, repo=parsed.repo, pr_number=parsed.pr_number)
    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return 0


def handle_agent_submit(repo: str | None, passthrough: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="gh-address-cr agent submit")
    parser.add_argument("repo")
    parser.add_argument("pr_number")
    parser.add_argument("--input", required=True)
    parser.add_argument(
        "--publish", action="store_true", help="Publish accepted GitHub-thread fix evidence immediately."
    )
    parser.add_argument("--now")
    parsed, scope_rc = _parse_with_scope(parser, repo, passthrough)
    if parsed is None:
        return scope_rc
    try:
        now_dt = None
        if parsed.now:
            now_dt = datetime.fromisoformat(parsed.now.replace("Z", "+00:00"))
        payload = agent_protocol.submit_action_response(
            parsed.repo,
            parsed.pr_number,
            response_path=parsed.input,
            now=now_dt,
            publish=parsed.publish,
        )
    except WorkflowError as exc:
        return output_workflow_error(exc, repo=parsed.repo, pr_number=parsed.pr_number)
    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return 0


def _parse_agent_files(files: str | None, extra_files: list[str] | None = None) -> list[str]:
    values: list[str] = []
    if files:
        values.extend(part.strip() for part in files.split(",") if part.strip())
    for item in extra_files or []:
        values.extend(part.strip() for part in item.split(",") if part.strip())
    return values


def _parse_agent_validation(values: list[str] | None) -> list[dict[str, str | float]]:
    commands: list[dict[str, str | float]] = []
    for raw in values or []:
        # Delegate to the core normalizer so the CLI honors the same result set
        # and the `@<n>ms`/`@<n>s` timing suffix the runtime records for
        # efficiency reporting. Splitting locally previously dropped the suffix
        # into the command name and recorded zero duration.
        command, result, duration = agent_protocol_validation.split_validation_command_record(raw.strip())
        if command and result:
            record: dict[str, str | float] = {"command": command, "result": result}
            if duration is not None:
                record["duration"] = duration
            commands.append(record)
    return commands


def _changed_files_for_commit(
    commit_hash: str,
    *,
    rejected_status: str = protocol_codes.FAST_FIX_ALL_REJECTED,
    command_name: str = "agent fix-all",
) -> list[str]:
    commit = commit_hash.strip()
    if not commit:
        return []
    if commit.startswith("-"):
        raise WorkflowError(
            status=rejected_status,
            reason_code="INVALID_COMMIT_HASH",
            waiting_on="git_commit",
            exit_code=2,
            message=f"{command_name} requires a commit-ish that does not start with '-'.",
        )
    commands = [
        ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", commit],
        ["git", "show", "--format=", "--name-only", commit],
    ]
    last_error = ""
    for command in commands:
        result = subprocess.run(command, text=True, capture_output=True)
        if result.returncode != 0:
            last_error = result.stderr.strip() or result.stdout.strip()
            continue
        files = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if files:
            return files
    raise WorkflowError(
        status=rejected_status,
        reason_code="COMMIT_FILES_UNAVAILABLE",
        waiting_on="git_commit",
        exit_code=2,
        message=last_error or f"Could not determine changed files for commit {commit}. Pass --files explicitly.",
    )


def handle_agent_resolve(repo: str | None, passthrough: list[str]) -> int:
    """Unified GitHub review-thread resolution surface.

    One command routes single, trivial, batch, homogeneous, and stale fixes
    through the same lease/evidence/publish contract. Classification is recorded
    internally, so no separate `agent classify` round-trip is required on this path.
    """
    parser = argparse.ArgumentParser(
        prog="gh-address-cr agent resolve",
        description=(
            "Resolve GitHub review threads through the supported canonical forms: "
            "a single <item_id>, a --files/--file selection, or per-thread decisions "
            "from --input. Use --stale for stale/outdated single or files selections."
        ),
    )
    parser.add_argument("repo")
    parser.add_argument("pr_number")
    parser.add_argument("item_id", nargs="?", help="Selection: which single thread (fresh or --stale) to resolve.")
    parser.add_argument(
        "--disposition",
        choices=["fix", "trivial", "reject", "clarify", "defer"],
        default=None,
        help="Disposition (primary axis): what to do with the selected thread(s) — "
        "fix (default), trivial (doc/typo fast path), reject, clarify, or defer.",
    )
    parser.add_argument("--stale", action="store_true", help="Condition (primary axis): resolve matching STALE/outdated threads.")
    parser.add_argument("--files", help="Selection: files-scope collective, instead of a single item_id.")
    parser.add_argument("--file", action="append", default=[], help="Selection: repeatable single-path form of --files.")
    parser.add_argument("--input", help="Selection: BatchActionResponse JSON for per-thread evidence.")
    parser.add_argument(
        "--why",
        help="Reason for a reject/clarify/defer disposition, or the shared "
        "rationale for a homogeneous fix (files selection with a repeated concern).",
    )
    parser.add_argument("--agent-id")
    parser.add_argument("--commit")
    parser.add_argument("--summary")
    parser.add_argument("--severity", choices=["P0", "P1", "P2", "P3", "P4"])
    parser.add_argument("--severity-note", "--severity-override-note", dest="severity_note")
    parser.add_argument("--review-priority", choices=["high", "medium", "low"])
    parser.add_argument("--validation", "--validation-cmd", dest="validation", action="append", default=[])
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--now")

    parsed, scope_rc = _parse_with_scope(parser, repo, passthrough)
    if parsed is None:
        return scope_rc

    try:
        _validate_resolve_mode(parsed)
        _validate_resolve_axes(parsed)
    except WorkflowError as exc:
        return output_workflow_error(exc, repo=parsed.repo, pr_number=parsed.pr_number)

    parsed.disposition = parsed.disposition or "fix"
    parsed.agent_id = parsed.agent_id or "agent"
    try:
        now_dt = None
        if parsed.now:
            now_dt = datetime.fromisoformat(parsed.now.replace("Z", "+00:00"))
        payload = _dispatch_agent_resolve(parsed, now_dt=now_dt)
    except WorkflowError as exc:
        return output_workflow_error(exc, repo=parsed.repo, pr_number=parsed.pr_number)
    payload.setdefault("published", _resolve_published_flag(payload))
    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return 0


def _resolve_published_flag(payload: dict) -> bool:
    """True only when a publish side effect actually posted at least one reply.

    The publish result lives at different depths depending on resolve mode:
    top-level `publish` (batch) or nested under `submit.publish` (single item via
    `submit_action_response`). Derive from `published_count`, not key presence, so
    `--publish` runs report `published` correctly and a no-op publish stays False.
    """
    candidates = [payload.get("publish")]
    submit = payload.get("submit")
    if isinstance(submit, dict):
        candidates.append(submit.get("publish"))
    for candidate in candidates:
        if isinstance(candidate, dict) and int(candidate.get("published_count") or 0) > 0:
            return True
    return False


def _validate_resolve_mode(parsed: argparse.Namespace) -> None:
    """Retained per spec 029 F2: `disposition=trivial` requires
    `selection=single` — the one intentional, documented cross-axis
    exclusion (a doc/typo fast path only makes sense for one thread), not
    leftover mode-matrix debris."""
    if parsed.disposition == "trivial" and not parsed.item_id:
        raise WorkflowError(
            status=protocol_codes.FAST_FIX_REJECTED,
            reason_code="TRIVIAL_REQUIRES_ITEM_ID",
            waiting_on="fast_fix_input",
            exit_code=2,
            message="agent resolve --disposition trivial requires a single <item_id>.",
        )


def _validate_resolve_axes(parsed: argparse.Namespace) -> None:
    """Reject conflicting selections and unsupported disposition/evidence shapes.

    `--files`/`--file` is overloaded: for fix/trivial it is **evidence**
    (which files were touched — always compatible with `item_id`, the normal
    single-item-fix shape); for reject/clarify it is a **selection**
    mechanism (files-scope collective decline, which `decline_item` does not
    consume) — only then does `item_id` + `--files` become a genuine
    same-axis conflict.
    """
    disposition = parsed.disposition or "fix"
    files_present = bool(parsed.files) or bool(parsed.file)
    files_is_selection = files_present and disposition in ("reject", "clarify", "defer")
    selection_sources = [
        name
        for name, present in (
            ("item_id", bool(parsed.item_id)),
            ("--files/--file", files_is_selection),
            ("--input", bool(parsed.input)),
        )
        if present
    ]
    if len(selection_sources) > 1:
        raise WorkflowError(
            status=protocol_codes.FAST_FIX_REJECTED,
            reason_code=protocol_codes.RESOLVE_AXIS_CONFLICT,
            waiting_on="resolve_axis",
            exit_code=2,
            message=(
                "agent resolve accepts exactly one selection source; got "
                f"{', '.join(selection_sources)}. Use a single item_id, "
                "--files/--file, or --input — not more than one."
            ),
        )
    if disposition in ("reject", "clarify", "defer") and (parsed.commit or parsed.validation):
        raise WorkflowError(
            status=protocol_codes.FAST_FIX_REJECTED,
            reason_code=protocol_codes.RESOLVE_EVIDENCE_INCOHERENT,
            waiting_on="resolve_axis",
            exit_code=2,
            message=(
                f"agent resolve --disposition {disposition} declines threads with a "
                "reason and does not accept --commit or --validation (use --disposition fix "
                "for code changes)."
            ),
        )
    if parsed.input and parsed.disposition is not None:
        # Every batch item's resolution lives inside the BatchActionResponse.
        # A top-level disposition would duplicate or override those decisions.
        raise WorkflowError(
            status=protocol_codes.FAST_FIX_REJECTED,
            reason_code=protocol_codes.RESOLVE_EVIDENCE_INCOHERENT,
            waiting_on="resolve_axis",
            exit_code=2,
            message=(
                "agent resolve --input <batch-response.json> does not accept a top-level "
                "--disposition. Set each item's resolution inside the BatchActionResponse "
                "JSON instead."
            ),
        )
    if parsed.input:
        unsupported_batch_flags = [
            flag
            for flag, present in (
                ("--agent-id", parsed.agent_id is not None),
                ("--commit", bool(parsed.commit)),
                ("--files/--file", files_present),
                ("--summary", bool(parsed.summary)),
                ("--why", bool(parsed.why)),
                ("--severity", bool(parsed.severity)),
                ("--severity-note", bool(parsed.severity_note)),
                ("--review-priority", bool(parsed.review_priority)),
                ("--validation", bool(parsed.validation)),
                ("--stale", bool(parsed.stale)),
            )
            if present
        ]
        if unsupported_batch_flags:
            raise WorkflowError(
                status=protocol_codes.FAST_FIX_REJECTED,
                reason_code=protocol_codes.RESOLVE_EVIDENCE_INCOHERENT,
                waiting_on="resolve_axis",
                exit_code=2,
                message=(
                    "agent resolve --input <batch-response.json> does not accept top-level flags: "
                    f"{', '.join(unsupported_batch_flags)}. Put per-item decisions and evidence "
                    "inside the BatchActionResponse JSON."
                ),
            )


def _dispatch_decline_resolution(parsed: argparse.Namespace, *, now_dt: datetime | None) -> dict:
    resolution = parsed.disposition
    # Disposition/evidence coherence is validated once, before dispatch;
    # --files/--file alone selects the files-scoped collective path.
    return workflow_matching.decline_matching_threads(
        parsed.repo,
        parsed.pr_number,
        agent_id=parsed.agent_id,
        files=_parse_agent_files(parsed.files, parsed.file),
        resolution=resolution,
        homogeneous_reason=parsed.why,
        concern_label=None,
        include_stale=parsed.stale,
        stale_only=parsed.stale,
        publish=parsed.publish,
        now=now_dt,
    )


def _dispatch_stale_resolution(parsed: argparse.Namespace, *, now_dt: datetime | None) -> dict:
    # A files selection is sufficient to route stale fixes.
    if not parsed.commit:
        raise WorkflowError(
            status="STALE_RESOLUTION_REJECTED",
            reason_code=protocol_codes.MISSING_FIX_REPLY_COMMIT_HASH,
            waiting_on="stale_resolution_input",
            exit_code=2,
            message="agent resolve --stale requires --commit.",
        )
    files = _parse_agent_files(parsed.files, parsed.file) or _changed_files_for_commit(
        parsed.commit, rejected_status="STALE_RESOLUTION_REJECTED", command_name="agent resolve --stale"
    )
    return workflow_matching.fast_fix_matching_threads(
        parsed.repo,
        parsed.pr_number,
        agent_id=parsed.agent_id,
        commit_hash=parsed.commit,
        files=files,
        validation_commands=_parse_agent_validation(parsed.validation),
        include_stale=True,
        stale_only=True,
        severity=parsed.severity,
        severity_note=parsed.severity_note,
        publish=parsed.publish,
        now=now_dt,
    )


def _dispatch_match_all_resolution(parsed: argparse.Namespace, *, now_dt: datetime | None) -> dict:
    if not parsed.commit:
        raise WorkflowError(
            status=protocol_codes.FAST_FIX_ALL_REJECTED,
            reason_code=protocol_codes.MISSING_FIX_REPLY_COMMIT_HASH,
            waiting_on="fast_fix_input",
            exit_code=2,
            message="agent resolve requires --commit, or pass an <item_id> for a single-thread fix.",
        )
    files = _parse_agent_files(parsed.files, parsed.file) or _changed_files_for_commit(parsed.commit)
    return workflow_matching.fast_fix_matching_threads(
        parsed.repo,
        parsed.pr_number,
        agent_id=parsed.agent_id,
        commit_hash=parsed.commit,
        files=files,
        validation_commands=_parse_agent_validation(parsed.validation),
        include_stale=False,
        severity=parsed.severity,
        severity_note=parsed.severity_note,
        homogeneous_reason=parsed.why,
        concern_label=None,
        publish=parsed.publish,
        now=now_dt,
    )


def _dispatch_single_item_resolution(parsed: argparse.Namespace, *, now_dt: datetime | None) -> dict:
    parsed.item_id = workflow.resolve_thread_alias(parsed.repo, parsed.pr_number, parsed.item_id)
    disposition = parsed.disposition
    if disposition in ("reject", "clarify", "defer"):
        return workflow.decline_item(
            parsed.repo,
            parsed.pr_number,
            item_id=parsed.item_id,
            agent_id=parsed.agent_id,
            resolution=disposition,
            why=parsed.why,
            publish=parsed.publish,
            now=now_dt,
        )
    missing = [
        flag
        for flag, value in (
            ("--commit", parsed.commit),
            ("--summary", parsed.summary),
            ("--why", parsed.why),
        )
        if not value
    ]
    if missing:
        raise WorkflowError(
            status=protocol_codes.FAST_FIX_REJECTED,
            reason_code="MISSING_RESOLVE_ARGS",
            waiting_on="fast_fix_input",
            exit_code=2,
            message=f"agent resolve {parsed.item_id} requires {', '.join(missing)} for a single-thread fix.",
        )
    shared_kwargs = {
        "repo": parsed.repo,
        "pr_number": parsed.pr_number,
        "item_id": parsed.item_id,
        "agent_id": parsed.agent_id,
        "commit_hash": parsed.commit,
        "files": _parse_agent_files(parsed.files, parsed.file),
        "validation_commands": _parse_agent_validation(parsed.validation),
        "summary": parsed.summary,
        "why": parsed.why,
        "publish": parsed.publish,
        "now": now_dt,
    }
    if disposition == "trivial":
        return workflow.trivial_fix_item(**shared_kwargs)
    return workflow.fast_fix_item(
        **shared_kwargs,
        severity=parsed.severity,
        severity_note=parsed.severity_note,
        review_priority=parsed.review_priority,
    )


def _dispatch_agent_resolve(parsed: argparse.Namespace, *, now_dt: datetime | None) -> dict:
    """Route on SELECTION first, disposition/condition second (spec 029 T013).

    Routing disposition/condition before selection was the #204 bug: a
    single-item decline (`<item_id> --disposition clarify --stale`) would be
    caught by an outer `--stale`/`--reject` check before `item_id` was ever
    examined, sending it into the collective, `--commit`-requiring path.
    """
    if parsed.item_id:
        return _dispatch_single_item_resolution(parsed, now_dt=now_dt)
    if parsed.input:
        return workflow.fast_fix_from_batch_input(
            parsed.repo, parsed.pr_number, batch_path=parsed.input, publish=parsed.publish, now=now_dt
        )
    if parsed.disposition in ("reject", "clarify", "defer"):
        return _dispatch_decline_resolution(parsed, now_dt=now_dt)
    if parsed.stale:
        return _dispatch_stale_resolution(parsed, now_dt=now_dt)
    return _dispatch_match_all_resolution(parsed, now_dt=now_dt)


def _resolve_viewer_login() -> str:
    """Best-effort authenticated gh login, used as the default reply author."""
    try:
        from gh_address_cr.github.client import GitHubClient

        return GitHubClient().viewer_login() or ""
    except Exception:
        return ""


def handle_agent_evidence(repo: str | None, passthrough: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="gh-address-cr agent evidence")
    parser.add_argument("subcommand", choices=["add", "list"])
    parser.add_argument("repo")
    parser.add_argument("pr_number")
    parser.add_argument("--name")
    parser.add_argument("--agent-id", default="agent")
    parser.add_argument("--commit")
    parser.add_argument("--files")
    parser.add_argument("--file", action="append", default=[])
    parser.add_argument("--validation", "--validation-cmd", dest="validation", action="append", default=[])
    parser.add_argument("--summary")
    parser.add_argument("--why")
    parser.add_argument("--test-command")
    parser.add_argument("--test-result")
    parser.add_argument("--severity", choices=["P0", "P1", "P2", "P3", "P4"])
    parser.add_argument("--severity-note", "--severity-override-note", dest="severity_note")
    parser.add_argument("--reply-url")
    parser.add_argument("--thread-id")
    parser.add_argument("--item-id")
    parser.add_argument("--author-login")
    parser.add_argument("--now")
    parsed = parser.parse_args(_prepend_optional(repo, passthrough))
    try:
        if parsed.subcommand == "list":
            payload = workflow.list_evidence_profiles(parsed.repo, parsed.pr_number)
        elif parsed.reply_url:
            now_dt = None
            if parsed.now:
                now_dt = datetime.fromisoformat(parsed.now.replace("Z", "+00:00"))
            validation_payload = None
            if parsed.validation or parsed.commit or parsed.files or parsed.file:
                # Validation arguments next to --reply-url used to be dropped silently.
                # Record them first: an incomplete set is rejected before anything is
                # written, and both records are idempotent, so a corrected rerun is safe.
                validation_payload = workflow.record_validation_evidence(
                    parsed.repo,
                    parsed.pr_number,
                    item_id=parsed.item_id,
                    thread_id=parsed.thread_id,
                    commit_hash=parsed.commit or "",
                    files=_parse_agent_files(parsed.files, parsed.file),
                    validation_commands=_parse_agent_validation(parsed.validation),
                    summary=parsed.summary,
                    why=parsed.why,
                    agent_id=parsed.agent_id,
                    now=now_dt,
                )
            author_login = parsed.author_login or _resolve_viewer_login()
            payload = workflow.record_reply_evidence(
                parsed.repo,
                parsed.pr_number,
                reply_url=parsed.reply_url,
                author_login=author_login,
                thread_id=parsed.thread_id,
                item_id=parsed.item_id,
                agent_id=parsed.agent_id,
                now=now_dt,
            )
            if validation_payload is not None:
                payload = {
                    "status": "REPLY_AND_VALIDATION_EVIDENCE_RECORDED",
                    "repo": payload["repo"],
                    "pr_number": payload["pr_number"],
                    "item_id": payload["item_id"],
                    "reply_evidence": payload,
                    "validation_evidence": validation_payload,
                }
        elif not parsed.name and (parsed.item_id or parsed.thread_id) and parsed.validation:
            now_dt = None
            if parsed.now:
                now_dt = datetime.fromisoformat(parsed.now.replace("Z", "+00:00"))
            payload = workflow.record_validation_evidence(
                parsed.repo,
                parsed.pr_number,
                item_id=parsed.item_id,
                thread_id=parsed.thread_id,
                commit_hash=parsed.commit or "",
                files=_parse_agent_files(parsed.files, parsed.file),
                validation_commands=_parse_agent_validation(parsed.validation),
                summary=parsed.summary,
                why=parsed.why,
                agent_id=parsed.agent_id,
                now=now_dt,
            )
        else:
            if not parsed.name:
                raise WorkflowError(
                    status=protocol_codes.EVIDENCE_PROFILE_REJECTED,
                    reason_code="MISSING_EVIDENCE_PROFILE_NAME",
                    waiting_on="evidence_profile",
                    exit_code=2,
                    message="agent evidence add requires --name.",
                )
            now_dt = None
            if parsed.now:
                now_dt = datetime.fromisoformat(parsed.now.replace("Z", "+00:00"))
            payload = workflow.record_evidence_profile(
                parsed.repo,
                parsed.pr_number,
                name=parsed.name,
                agent_id=parsed.agent_id,
                commit_hash=parsed.commit or "",
                files=_parse_agent_files(parsed.files, parsed.file),
                validation_commands=_parse_agent_validation(parsed.validation),
                summary=parsed.summary,
                why=parsed.why,
                test_command=parsed.test_command,
                test_result=parsed.test_result,
                severity=parsed.severity,
                severity_note=parsed.severity_note,
                now=now_dt,
            )
    except WorkflowError as exc:
        return output_workflow_error(exc, repo=parsed.repo, pr_number=parsed.pr_number)
    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return 0


def handle_agent_publish(repo: str | None, passthrough: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="gh-address-cr agent publish")
    parser.add_argument("repo")
    parser.add_argument("pr_number")
    parser.add_argument("--agent-id", default="gh-address-cr-publisher")
    parser.add_argument("--now")
    parsed, scope_rc = _parse_with_scope(parser, repo, passthrough)
    if parsed is None:
        return scope_rc
    try:
        now_dt = None
        if parsed.now:
            now_dt = datetime.fromisoformat(parsed.now.replace("Z", "+00:00"))
        payload = publisher.publish_github_thread_responses(
            parsed.repo,
            parsed.pr_number,
            agent_id=parsed.agent_id,
            now=now_dt,
        )
    except WorkflowError as exc:
        return output_workflow_error(exc, repo=parsed.repo, pr_number=parsed.pr_number)
    except session_store.SessionError as exc:
        return output_session_error(exc, repo=parsed.repo, pr_number=parsed.pr_number)
    except Exception as exc:
        return output_generic_agent_error(parsed.repo, parsed.pr_number, "PUBLISH_ERROR", str(exc))
    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return 0


def handle_agent_leases(repo: str | None, passthrough: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="gh-address-cr agent leases")
    parser.add_argument("repo")
    parser.add_argument("pr_number")
    parsed, scope_rc = _parse_with_scope(parser, repo, passthrough)
    if parsed is None:
        return scope_rc
    try:
        payload = leases.list_leases(parsed.repo, parsed.pr_number)
    except WorkflowError as exc:
        return output_workflow_error(exc, repo=parsed.repo, pr_number=parsed.pr_number)
    except session_store.SessionError as exc:
        return output_session_error(exc, repo=parsed.repo, pr_number=parsed.pr_number)
    except Exception as exc:
        return output_generic_agent_error(parsed.repo, parsed.pr_number, protocol_codes.SESSION_ERROR, str(exc))
    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return 0


def handle_agent_reclaim(repo: str | None, passthrough: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="gh-address-cr agent reclaim")
    parser.add_argument("repo")
    parser.add_argument("pr_number")
    parser.add_argument("--now")
    parsed, scope_rc = _parse_with_scope(parser, repo, passthrough)
    if parsed is None:
        return scope_rc
    now = datetime.fromisoformat(parsed.now.replace("Z", "+00:00")) if parsed.now else None
    try:
        payload = leases.reclaim_leases(parsed.repo, parsed.pr_number, now=now)
    except WorkflowError as exc:
        return output_workflow_error(exc, repo=parsed.repo, pr_number=parsed.pr_number)
    except session_store.SessionError as exc:
        return output_session_error(exc, repo=parsed.repo, pr_number=parsed.pr_number)
    except Exception as exc:
        return output_generic_agent_error(parsed.repo, parsed.pr_number, protocol_codes.SESSION_ERROR, str(exc))
    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return 0


def handle_agent_orchestrate(repo: str | None, passthrough: list[str]) -> int:
    from gh_address_cr.orchestrator import harness

    return harness.handle_agent_orchestrate(repo, passthrough)
