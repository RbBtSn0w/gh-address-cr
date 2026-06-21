from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime

from gh_address_cr import (
    MAX_PARALLEL_CLAIMS,
    PROTOCOL_VERSION,
    SUPPORTED_PROTOCOL_VERSIONS,
    SUPPORTED_SKILL_CONTRACT_VERSIONS,
    __version__,
)
from gh_address_cr.commands.common import (
    agent_args_with_scope as _agent_args_with_scope,
)
from gh_address_cr.commands.common import (
    emit_scope_resolution_error as _emit_scope_resolution_error,
)
from gh_address_cr.commands.common import (
    output_generic_agent_error,
    output_workflow_error,
)
from gh_address_cr.commands.common import (
    prepend_optional as _prepend_optional,
)
from gh_address_cr.core import agent_protocol, leases, protocol_codes, publisher, workflow
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
    "telemetry",
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
        "protocol_versions": list(SUPPORTED_PROTOCOL_VERSIONS),
        "supported_protocol_versions": list(SUPPORTED_PROTOCOL_VERSIONS),
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
            "work_item_boundary.v1",
            "workflow_decision.v1",
        ],
        "constraints": {
            "max_parallel_claims": MAX_PARALLEL_CLAIMS,
        },
        "public_commands": sorted(PUBLIC_COMMANDS),
    }


def handle_agent_command(args: argparse.Namespace) -> int:
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
    parser.add_argument("--classification", required=True, choices=["fix", "clarify", "defer", "reject"])
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
    parser.add_argument("--batch", action="store_true", help="Generate a skeleton batch-response-skeleton.json for all unresolved threads.")
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
            payload = agent_protocol.issue_batch_action_request(
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
    parser.add_argument("--publish", action="store_true", help="Publish accepted GitHub-thread fix evidence immediately.")
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


def _parse_agent_validation(values: list[str] | None) -> list[dict[str, str]]:
    commands: list[dict[str, str]] = []
    for raw in values or []:
        command, result = _split_agent_validation_record(raw.strip())
        if command and result:
            commands.append({"command": command, "result": result})
    return commands


def _split_agent_validation_record(raw: str) -> tuple[str, str]:
    command, separator, result = raw.rpartition("=")
    if not separator or not _looks_like_agent_validation_result(result):
        return raw.strip(), "passed"
    return command.strip(), result.strip()


def _looks_like_agent_validation_result(value: str) -> bool:
    normalized = value.strip().lower()
    if not normalized or any(char.isspace() for char in normalized):
        return False
    return normalized in {"pass", "passed", "success", "succeeded", "ok", "fail", "failed", "error", "skipped"}


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
            "Resolve one or more GitHub review threads. Modes: default single item; "
            "--trivial doc/typo item; --batch --input <BatchActionResponse>; "
            "--homogeneous-reason <why> for a repeated concern; --stale --match-files; "
            "--reject/--clarify --homogeneous-reason --match-files to decline a repeated concern."
        ),
    )
    parser.add_argument("repo")
    parser.add_argument("pr_number")
    parser.add_argument("item_id", nargs="?")
    parser.add_argument("--agent-id", default="agent")
    parser.add_argument("--commit")
    parser.add_argument("--files")
    parser.add_argument("--file", action="append", default=[])
    parser.add_argument("--summary")
    parser.add_argument("--why")
    parser.add_argument("--severity", choices=["P0", "P1", "P2", "P3", "P4"])
    parser.add_argument("--severity-note", "--severity-override-note", dest="severity_note")
    parser.add_argument("--review-priority", choices=["high", "medium", "low"])
    parser.add_argument("--validation", "--validation-cmd", dest="validation", action="append", default=[])
    parser.add_argument("--input", help="BatchActionResponse JSON for --batch mode.")
    parser.add_argument("--batch", action="store_true", help="Resolve multiple threads from a BatchActionResponse.")
    parser.add_argument("--trivial", action="store_true", help="Documentation/typo-only fast path.")
    parser.add_argument("--stale", action="store_true", help="Resolve matching STALE/outdated threads.")
    parser.add_argument(
        "--reject",
        action="store_true",
        help="Decline matching threads (reject) with one shared --homogeneous-reason; requires --match-files.",
    )
    parser.add_argument(
        "--clarify",
        action="store_true",
        help="Decline matching threads (clarify) with one shared --homogeneous-reason; requires --match-files.",
    )
    parser.add_argument("--homogeneous-reason", help="Rationale for the homogeneous repeated-concern shortcut.")
    parser.add_argument("--concern-label", help="Short label for the homogeneous repeated concern.")
    parser.add_argument("--match-files", action="store_true", help="Required for --stale: keep resolution file-scoped.")
    parser.add_argument("--include-stale", action="store_true")
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--now")
    parsed, scope_rc = _parse_with_scope(parser, repo, passthrough)
    if parsed is None:
        return scope_rc

    selected_modes = [
        name
        for name, active in (
            ("--batch", parsed.batch or bool(parsed.input)),
            ("--trivial", parsed.trivial),
            ("--stale", parsed.stale),
            ("--reject", parsed.reject),
            ("--clarify", parsed.clarify),
        )
        if active
    ]
    if len(selected_modes) > 1:
        return output_workflow_error(
            WorkflowError(
                status=protocol_codes.FAST_FIX_REJECTED,
                reason_code="CONFLICTING_RESOLVE_MODE",
                waiting_on="resolve_mode",
                exit_code=2,
                message=f"agent resolve modes are mutually exclusive; got {', '.join(selected_modes)}.",
            ),
            repo=parsed.repo,
            pr_number=parsed.pr_number,
        )

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


def _dispatch_agent_resolve(parsed: argparse.Namespace, *, now_dt: datetime | None) -> dict:
    if parsed.trivial and not parsed.item_id:
        # Without this guard, --trivial with no <item_id> would fall through to the
        # match-all branch and bypass the trivial-eligibility check entirely (#117).
        raise WorkflowError(
            status=protocol_codes.FAST_FIX_REJECTED,
            reason_code="TRIVIAL_REQUIRES_ITEM_ID",
            waiting_on="fast_fix_input",
            exit_code=2,
            message="agent resolve --trivial requires a single <item_id>.",
        )
    if parsed.item_id and (
        parsed.batch or parsed.input or parsed.stale or parsed.homogeneous_reason or parsed.reject or parsed.clarify
    ):
        # Match-all / batch modes are file/lease-scoped and do not consume an
        # <item_id>; fail fast instead of silently ignoring it.
        raise WorkflowError(
            status=protocol_codes.FAST_FIX_REJECTED,
            reason_code="ITEM_ID_NOT_ALLOWED_FOR_MODE",
            waiting_on="resolve_mode",
            exit_code=2,
            message=(
                "agent resolve <item_id> cannot be combined with --batch/--input, --stale, "
                "--reject/--clarify, or --homogeneous-reason."
            ),
        )
    if parsed.reject or parsed.clarify:
        resolution = "reject" if parsed.reject else "clarify"
        if not parsed.match_files:
            raise WorkflowError(
                status="DECLINE_ALL_REJECTED",
                reason_code="MISSING_MATCH_FILES",
                waiting_on="decline_input",
                exit_code=2,
                message=f"agent resolve --{resolution} requires --match-files so the decline stays file-scoped.",
            )
        if parsed.commit or parsed.validation:
            raise WorkflowError(
                status="DECLINE_ALL_REJECTED",
                reason_code="CONFLICTING_RESOLVE_MODE",
                waiting_on="resolve_mode",
                exit_code=2,
                message=(
                    f"agent resolve --{resolution} declines threads with a shared reply and "
                    "does not accept --commit or --validation (use the fix path for code changes)."
                ),
            )
        return workflow.decline_matching_threads(
            parsed.repo,
            parsed.pr_number,
            agent_id=parsed.agent_id,
            files=_parse_agent_files(parsed.files, parsed.file),
            resolution=resolution,
            homogeneous_reason=parsed.homogeneous_reason,
            concern_label=parsed.concern_label,
            include_stale=parsed.include_stale,
            publish=parsed.publish,
            now=now_dt,
        )
    if parsed.batch or parsed.input:
        if not parsed.input:
            raise WorkflowError(
                status=protocol_codes.FAST_FIX_ALL_REJECTED,
                reason_code="MISSING_BATCH_INPUT",
                waiting_on="batch_action_response",
                exit_code=2,
                message="agent resolve --batch requires --input <BatchActionResponse>.",
            )
        return workflow.fast_fix_from_batch_input(
            parsed.repo, parsed.pr_number, batch_path=parsed.input, publish=parsed.publish, now=now_dt
        )

    if parsed.stale:
        if not parsed.match_files:
            raise WorkflowError(
                status="STALE_RESOLUTION_REJECTED",
                reason_code="MISSING_MATCH_FILES",
                waiting_on="stale_resolution_input",
                exit_code=2,
                message="agent resolve --stale requires --match-files so stale synchronization stays file-scoped.",
            )
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
        return workflow.fast_fix_matching_threads(
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

    if not parsed.item_id:
        # Match-all-by-files mode (was `fix-all`): homogeneous shortcut or per-thread rejection.
        if not parsed.commit:
            raise WorkflowError(
                status=protocol_codes.FAST_FIX_ALL_REJECTED,
                reason_code=protocol_codes.MISSING_FIX_REPLY_COMMIT_HASH,
                waiting_on="fast_fix_input",
                exit_code=2,
                message="agent resolve requires --commit, or pass an <item_id> for a single-thread fix.",
            )
        files = _parse_agent_files(parsed.files, parsed.file) or _changed_files_for_commit(parsed.commit)
        return workflow.fast_fix_matching_threads(
            parsed.repo,
            parsed.pr_number,
            agent_id=parsed.agent_id,
            commit_hash=parsed.commit,
            files=files,
            validation_commands=_parse_agent_validation(parsed.validation),
            include_stale=parsed.include_stale,
            severity=parsed.severity,
            severity_note=parsed.severity_note,
            homogeneous_reason=parsed.homogeneous_reason,
            concern_label=parsed.concern_label,
            publish=parsed.publish,
            now=now_dt,
        )

    # Accept a lean thread alias (T1..Tn) in place of the long item_id (#135).
    parsed.item_id = workflow.resolve_thread_alias(parsed.repo, parsed.pr_number, parsed.item_id)

    # Single-item modes (default fix or --trivial) require commit + summary + why.
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
    if parsed.trivial:
        return workflow.trivial_fix_item(
            parsed.repo,
            parsed.pr_number,
            item_id=parsed.item_id,
            agent_id=parsed.agent_id,
            commit_hash=parsed.commit,
            files=_parse_agent_files(parsed.files, parsed.file),
            validation_commands=_parse_agent_validation(parsed.validation),
            summary=parsed.summary,
            why=parsed.why,
            publish=parsed.publish,
            now=now_dt,
        )
    return workflow.fast_fix_item(
        parsed.repo,
        parsed.pr_number,
        item_id=parsed.item_id,
        agent_id=parsed.agent_id,
        commit_hash=parsed.commit,
        files=_parse_agent_files(parsed.files, parsed.file),
        validation_commands=_parse_agent_validation(parsed.validation),
        summary=parsed.summary,
        why=parsed.why,
        severity=parsed.severity,
        severity_note=parsed.severity_note,
        review_priority=parsed.review_priority,
        publish=parsed.publish,
        now=now_dt,
    )


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
    except Exception as exc:
        return output_generic_agent_error(parsed.repo, parsed.pr_number, protocol_codes.SESSION_ERROR, str(exc))
    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return 0


def handle_agent_orchestrate(repo: str | None, passthrough: list[str]) -> int:
    from gh_address_cr.orchestrator import harness

    return harness.handle_agent_orchestrate(repo, passthrough)
