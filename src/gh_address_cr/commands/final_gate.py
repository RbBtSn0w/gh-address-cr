from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from gh_address_cr.commands.common import (
    emit_scope_resolution_error,
    maybe_prepend_implicit_scope,
    prepend_optional,
)
from gh_address_cr.core import gate as core_gate
from gh_address_cr.core import paths as core_paths
from gh_address_cr.core import session as session_store
from gh_address_cr.core import telemetry as core_telemetry


HOST_TELEMETRY_INPUT_ENV = "GH_ADDRESS_CR_HOST_TELEMETRY_INPUT"
HOST_TELEMETRY_SOURCE_ENV = "GH_ADDRESS_CR_HOST_TELEMETRY_SOURCE"
HOST_TELEMETRY_FORMAT_ENV = "GH_ADDRESS_CR_HOST_TELEMETRY_FORMAT"


def handle_final_gate(repo: str | None, pr_number: str | None, passthrough: list[str]) -> int:
    if repo in {"-h", "--help"} or pr_number in {"-h", "--help"} or passthrough[:1] in (["-h"], ["--help"]):
        print(
            "usage: gh-address-cr final-gate <owner/repo> <pr_number> [--no-auto-clean] [--require-checks|--require-required-checks]\n\n"
            "Host telemetry hook:\n"
            "  GH_ADDRESS_CR_HOST_TELEMETRY_INPUT=<path> gh-address-cr final-gate <owner/repo> <pr_number>\n"
            "  GH_ADDRESS_CR_HOST_TELEMETRY_SOURCE defaults to assistant-host.\n"
            "  GH_ADDRESS_CR_HOST_TELEMETRY_FORMAT defaults to agent-jsonl."
        )
        return 0
    parser = argparse.ArgumentParser(
        prog="gh-address-cr final-gate",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Host telemetry hook:\n"
            "  GH_ADDRESS_CR_HOST_TELEMETRY_INPUT=<path> gh-address-cr final-gate <owner/repo> <pr_number>\n"
            "  GH_ADDRESS_CR_HOST_TELEMETRY_SOURCE defaults to assistant-host.\n"
            "  GH_ADDRESS_CR_HOST_TELEMETRY_FORMAT defaults to agent-jsonl.\n"
        ),
    )
    output_group = parser.add_mutually_exclusive_group()
    output_group.add_argument("--machine", action="store_true", help="Emit structured machine-readable JSON.")
    output_group.add_argument("--human", action="store_true", help="Emit human-oriented narrative text (default).")
    auto_group = parser.add_mutually_exclusive_group()
    auto_group.add_argument("--auto-clean", dest="auto_clean", action="store_true")
    auto_group.add_argument("--no-auto-clean", dest="auto_clean", action="store_false")
    parser.set_defaults(auto_clean=True)
    parser.add_argument("--audit-id", default="default")
    parser.add_argument("--snapshot", default="")
    checks_group = parser.add_mutually_exclusive_group()
    checks_group.add_argument("--require-checks", action="store_true", help="Require all PR checks to be green.")
    checks_group.add_argument(
        "--require-required-checks",
        action="store_true",
        help="Require required PR checks to be green.",
    )
    parser.add_argument("repo")
    parser.add_argument("pr_number")
    scoped_args = prepend_optional(repo, prepend_optional(pr_number, passthrough))
    scoped_args, scope_error = maybe_prepend_implicit_scope(scoped_args)
    if scope_error is not None:
        return emit_scope_resolution_error(scope_error)
    parsed = parser.parse_args(scoped_args)
    ingest_host_telemetry_from_environment(parsed.repo, parsed.pr_number)
    machine_requested = "--machine" in scoped_args and "--human" not in scoped_args
    try:
        result = core_gate.Gatekeeper().run(
            parsed.repo,
            parsed.pr_number,
            snapshot_path=parsed.snapshot or None,
            require_checks=parsed.require_checks,
            require_required_checks=parsed.require_required_checks,
        )
    except FileNotFoundError as exc:
        if machine_requested:
            emit_final_gate_machine_error(parsed.repo, parsed.pr_number, "FINAL_GATE_INPUT_MISSING", str(exc), 2)
        else:
            print(str(exc), file=sys.stderr)
        return 2
    except Exception as exc:
        message = f"Final gate failed to evaluate: {exc}"
        if machine_requested:
            emit_final_gate_machine_error(parsed.repo, parsed.pr_number, "FINAL_GATE_EVALUATION_FAILED", message, 5)
        else:
            print(message, file=sys.stderr)
        return 5

    summary_path, telemetry_report = write_native_final_gate_artifacts(parsed.repo, parsed.pr_number, parsed.audit_id, result)
    if result.passed and parsed.auto_clean:
        workspace_path = session_store.workspace_dir(parsed.repo, parsed.pr_number)
        archive_target = archive_and_clean_workspace(parsed.repo, parsed.pr_number, parsed.audit_id)
        if archive_target is not None:
            summary_path = archive_target / summary_path.name
            if telemetry_report is not None:
                paths = core_paths.SessionPaths(parsed.repo, parsed.pr_number)
                archived_report_path = archive_target / paths.efficiency_report_file.name
                telemetry_report["report_artifact"] = str(archived_report_path)
                telemetry_report = replace_path_occurrences(
                    telemetry_report,
                    str(workspace_path),
                    str(archive_target),
                )
                rewrite_archived_efficiency_report_path(summary_path, telemetry_report["report_artifact"])
                rewrite_archived_efficiency_report_artifact(archived_report_path, telemetry_report)
                rewrite_archived_audit_artifacts(
                    archive_target,
                    original_workspace=workspace_path,
                    summary_path=summary_path,
                    telemetry_report=telemetry_report,
                )
    if parsed.machine:
        machine_summary = result.to_machine_summary()
        if summary_path:
            machine_summary["artifact_path"] = str(summary_path)
        if telemetry_report is not None:
            machine_summary["telemetry"] = {
                "coverage_label": telemetry_report["coverage_label"],
                "report_artifact": telemetry_report.get("report_artifact"),
                "total_events": telemetry_report.get("total_events"),
                "success_rate": telemetry_report.get("success_rate"),
                "inefficiency_flags": telemetry_report.get("inefficiency_flags", []),
                "diagnostics": telemetry_report.get("diagnostics", []),
            }
            machine_summary["completion_summary_line"] = build_completion_summary_line(result, telemetry_report)
            machine_summary["completion_summary_guidance"] = build_completion_summary_guidance(
                result, telemetry_report, summary_path=summary_path, include_sha256=True
            )
        sys.stdout.write(json.dumps(machine_summary, indent=2, sort_keys=True) + "\n")
    else:
        emit_final_gate_result(result, summary_path=summary_path, telemetry_report=telemetry_report)
    if not result.passed:
        print(f"\nGate FAILED: {final_gate_failure_message(result)}. Do not send completion summary.", file=sys.stderr)
        return result.exit_code

    return 0


def emit_final_gate_machine_error(repo: str, pr_number: str, reason_code: str, message: str, exit_code: int) -> None:
    payload = {
        "status": "BLOCKED",
        "reason_code": reason_code,
        "next_action": message,
        "waiting_on": "final_gate",
        "exit_code": exit_code,
        "repo": repo,
        "pr_number": str(pr_number),
        "counts": {},
        "failure_codes": [reason_code],
    }
    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def ingest_host_telemetry_from_environment(repo: str, pr_number: str) -> dict | None:
    input_path = os.environ.get(HOST_TELEMETRY_INPUT_ENV)
    if not input_path:
        return None
    source = os.environ.get(HOST_TELEMETRY_SOURCE_ENV) or "assistant-host"
    fmt = os.environ.get(HOST_TELEMETRY_FORMAT_ENV) or "agent-jsonl"
    try:
        return ingest_host_telemetry_input(repo, pr_number, input_path=input_path, source=source, fmt=fmt)
    except Exception:
        return safe_hook_unavailable_import_summary(repo, pr_number, source=source, fmt=fmt)


def ingest_host_telemetry_input(
    repo: str,
    pr_number: str,
    *,
    input_path: str,
    source: str,
    fmt: str,
) -> dict | None:
    try:
        raw = Path(input_path).read_text(encoding="utf-8")
    except OSError:
        return safe_input_unavailable_import_summary(repo, pr_number, source=source, fmt=fmt)
    return core_telemetry.import_external_telemetry(repo, pr_number, source=source, fmt=fmt, raw=raw)


def safe_input_unavailable_import_summary(repo: str, pr_number: str, *, source: str, fmt: str) -> dict | None:
    try:
        return core_telemetry.input_unavailable_import_summary(repo, pr_number, source=source, fmt=fmt)
    except Exception:
        return None


def safe_hook_unavailable_import_summary(repo: str, pr_number: str, *, source: str, fmt: str) -> dict | None:
    try:
        return core_telemetry.hook_unavailable_import_summary(repo, pr_number, source=source, fmt=fmt)
    except Exception:
        return None


def rewrite_archived_efficiency_report_path(summary_path: Path, report_artifact: str) -> None:
    try:
        lines = summary_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    updated = []
    for line in lines:
        if line.startswith("- efficiency_report_path:"):
            updated.append(f"- efficiency_report_path: {report_artifact}")
        elif line.strip().startswith("- Efficiency Report:"):
            leading = line[:line.find("-")]
            updated.append(f"{leading}- Efficiency Report: {report_artifact}")
        elif line.strip().startswith("- Audit Summary:"):
            leading = line[:line.find("-")]
            updated.append(f"{leading}- Audit Summary: {summary_path}")
        else:
            updated.append(line)
    try:
        summary_path.write_text("\n".join(updated) + "\n", encoding="utf-8")
    except OSError:
        return


def rewrite_archived_efficiency_report_artifact(report_path: Path, telemetry_report: dict) -> None:
    try:
        current = json.loads(report_path.read_text(encoding="utf-8"))
    except Exception:
        current = {}
    current.update(telemetry_report)
    current["report_artifact"] = str(report_path)
    try:
        if report_path.is_dir():
            shutil.rmtree(report_path)
        report_path.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError:
        return


def rewrite_archived_audit_artifacts(
    archive_target: Path,
    *,
    original_workspace: Path,
    summary_path: Path,
    telemetry_report: dict,
) -> None:
    summary_sha256 = read_file_sha256(summary_path)
    for path in (archive_target / "audit.jsonl", archive_target / "trace.jsonl"):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        updated_lines: list[str] = []
        changed = False
        for line in lines:
            if not line.strip():
                updated_lines.append(line)
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                updated_lines.append(line)
                continue
            rewritten = replace_path_occurrences(entry, str(original_workspace), str(archive_target))
            if isinstance(rewritten, dict):
                if path.name == "audit.jsonl":
                    details = rewritten.get("details")
                    if isinstance(details, dict):
                        details["summary_file"] = str(summary_path)
                        details["summary_sha256"] = summary_sha256
                        details["efficiency_report"] = dict(telemetry_report)
                elif path.name == "trace.jsonl":
                    rewritten["efficiency_report_path"] = telemetry_report["report_artifact"]
            changed = changed or rewritten != entry
            updated_lines.append(json.dumps(rewritten, sort_keys=True))
        if changed:
            try:
                path.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")
            except OSError:
                continue


def replace_path_occurrences(value: object, original_path: str, archived_path: str) -> object:
    if isinstance(value, str):
        return value.replace(original_path, archived_path)
    if isinstance(value, list):
        return [replace_path_occurrences(item, original_path, archived_path) for item in value]
    if isinstance(value, dict):
        return {key: replace_path_occurrences(nested, original_path, archived_path) for key, nested in value.items()}
    return value


def read_file_sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return "unavailable"


def build_completion_summary_line(result: core_gate.GateResult, telemetry_report: dict) -> str:
    status_str = "PASSED" if result.passed else "FAILED"
    unresolved_threads = result.counts.get("unresolved_remote_threads_count", 0)
    pending_reviews = result.counts.get("pending_current_login_review_count", 0)
    checks_failed = result.counts.get("pr_checks_failed_count", 0)
    checks_pending = result.counts.get("pr_checks_pending_count", 0)
    checks_concise = f"{checks_failed}/{checks_pending}" if result.check_requirement else "N/A"

    coverage = telemetry_report.get("coverage_label") or "unavailable"
    total_events = _safe_int(telemetry_report.get("total_events"), default=0)
    success_rate = _safe_float(telemetry_report.get("success_rate"), default=0.0)
    inefficiency_flags = _string_list(telemetry_report.get("inefficiency_flags"))
    flags_str = "; ".join(inefficiency_flags) if inefficiency_flags else "none"

    return (
        f"[gh-address-cr: {status_str} | "
        f"threads: {unresolved_threads} | "
        f"reviews: {pending_reviews} | "
        f"checks: {checks_concise} | "
        f"telemetry: {coverage} ({total_events} events, {success_rate:.1f}%) | "
        f"inefficiency: {flags_str}]"
    )


def _safe_int(value: object, *, default: int) -> int:
    try:
        return int(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _safe_float(value: object, *, default: float) -> float:
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _string_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if str(item)]
    return [str(value)]


def build_completion_summary_guidance(
    result: core_gate.GateResult,
    telemetry_report: dict,
    summary_path: Path | None,
    *,
    include_sha256: bool = True,
) -> str:
    unresolved_threads = result.counts.get("unresolved_remote_threads_count", 0)
    pending_reviews = result.counts.get("pending_current_login_review_count", 0)
    blocking_local = result.counts.get("blocking_local_items_count", 0)
    blocking_github = result.counts.get("blocking_github_items_count", 0)
    missing_reply = result.counts.get("github_threads_missing_reply_count", 0)
    missing_validation = result.counts.get("missing_validation_evidence_count", 0)
    blocking_items = result.counts.get("blocking_items_count", 0)
    logic_validation_blocking = result.counts.get("logic_validation_blocking_count", 0)

    checks_failed = result.counts.get("pr_checks_failed_count", 0)
    checks_pending = result.counts.get("pr_checks_pending_count", 0)
    checks_not_green = result.counts.get("pr_checks_not_green_count", 0)

    coverage = telemetry_report.get("coverage_label") or "unavailable"
    total_events = _safe_int(telemetry_report.get("total_events"), default=0)
    success_rate = _safe_float(telemetry_report.get("success_rate"), default=0.0)
    inefficiency_flags = _string_list(telemetry_report.get("inefficiency_flags"))
    flags_str = "; ".join(inefficiency_flags) if inefficiency_flags else "none"
    telemetry_diagnostics = [
        diagnostic
        for diagnostic in _string_list(telemetry_report.get("diagnostics"))
        if diagnostic.strip()
    ]
    telemetry_diagnostics_str = "; ".join(telemetry_diagnostics)
    report_artifact = telemetry_report.get("report_artifact") or "N/A"

    summary_path_str = str(summary_path) if summary_path else "N/A"
    metrics_line = build_completion_summary_line(result, telemetry_report)

    audit_summary_line = f"- Audit Summary: {summary_path_str}"
    if include_sha256 and summary_path:
        summary_sha256 = read_file_sha256(summary_path)
        audit_summary_line += f" (sha256: {summary_sha256})"

    abnormal_implications = []
    abnormal_names = []

    if coverage != "complete":
        abnormal_names.append(f"incomplete telemetry coverage ({coverage})")
        if coverage == "runtime-only":
            desc = (
                "Telemetry coverage is runtime-only. This indicates that host-side telemetry was not explicitly "
                "imported/ingested prior to the final gate check, meaning the metrics represent only command-level "
                "events tracked by the local session runner."
            )
        elif coverage == "unavailable":
            desc = "Telemetry coverage is unavailable. No usable efficiency telemetry events exist for the current session."
        else:
            desc = (
                f"Telemetry coverage is {coverage} (not complete). Some agent interactions or tool runs "
                "were not fully recorded in telemetry, which might make efficiency tracking partially incomplete."
            )
        abnormal_implications.append(f"- {desc}")

    if total_events > 0 and success_rate < 100.0:
        abnormal_names.append(f"success rate below 100% ({success_rate:.1f}%)")
        abnormal_implications.append(
            f"- Telemetry success rate is {success_rate:.1f}% (below 100%). Some tool calls, actions, "
            "or validation runs encountered errors or retries during the session."
        )

    if inefficiency_flags:
        abnormal_names.append(f"inefficiency flags present ({flags_str})")
        abnormal_implications.append(
            f"- Inefficiency flags detected: {flags_str}. This indicates potential execution friction, "
            "redundant tool calls, or loop behaviors that occurred during the session."
        )

    if telemetry_diagnostics:
        abnormal_names.append("telemetry diagnostics present")
        abnormal_implications.append(f"- Telemetry diagnostics: {telemetry_diagnostics_str}")

    threads_checks_remain = (
        unresolved_threads > 0 or
        pending_reviews > 0 or
        blocking_items > 0 or
        blocking_local > 0 or
        blocking_github > 0 or
        missing_reply > 0 or
        missing_validation > 0 or
        logic_validation_blocking > 0 or
        checks_not_green > 0 or
        checks_failed > 0
    )
    if threads_checks_remain:
        remain_details = []
        if unresolved_threads > 0:
            remain_details.append(f"{unresolved_threads} unresolved threads")
        if pending_reviews > 0:
            remain_details.append(f"{pending_reviews} pending reviews")
        if checks_not_green > 0:
            remain_details.append(f"{checks_not_green} non-green checks ({checks_failed} failed, {checks_pending} pending)")
        if blocking_items > 0:
            remain_details.append(f"{blocking_items} blocking items")
        if missing_reply > 0:
            remain_details.append(f"{missing_reply} threads missing reply")
        if missing_validation > 0:
            remain_details.append(f"{missing_validation} local items missing validation")
        if logic_validation_blocking > 0:
            remain_details.append(f"{logic_validation_blocking} blocking logic-validation signals")
        remain_str = ", ".join(remain_details)
        abnormal_names.append(f"unresolved threads/checks/blocking items ({remain_str})")
        abnormal_implications.append(
            f"- Session contains unresolved items: {remain_str}. "
            "PR completion is blocked until all threads are resolved, reviews submitted, checks pass, reply/validation evidence is recorded, and all blocking items are addressed."
        )

    header = (
        "Recommended user-facing completion summary:"
        if result.passed
        else "Gate FAILED: Do not send completion summary. Recommended status update:"
    )
    lines = [
        header,
        "",
        "```text",
        f"{metrics_line}",
        f"{audit_summary_line}",
        f"- Efficiency Report: {report_artifact}",
        "```",
    ]

    if abnormal_implications:
        lines.extend([
            "",
            "### Attention Items & Implications",
            *abnormal_implications,
            "",
            "> [!IMPORTANT]",
            "> One or more metrics are abnormal. You MUST explain the implications of these metrics in your completion summary rather than just pasting raw fields.",
            ">",
            "> **IMPLICATION PROMPT**:",
            f"> Please explain the impact of: {', '.join(abnormal_names)}."
        ])

    return "\n".join(lines)


def emit_final_gate_result(
    result: core_gate.GateResult,
    *,
    summary_path: Path | None = None,
    telemetry_report: dict | None = None,
) -> None:
    print("== Final Freshness Check ==")
    print(f"Unresolved thread count: {result.counts['unresolved_remote_threads_count']}")
    print(f"Pending review count: {result.counts['pending_current_login_review_count']}")
    if result.check_requirement:
        print(
            "PR checks: "
            f"{result.counts['pr_checks_failed_count']} failed, "
            f"{result.counts['pr_checks_pending_count']} pending "
            f"({result.check_requirement})"
        )
    print()
    if result.passed:
        print("Final gate PASSED")
        print("\n== Gate Result ==")
        print("Verified: 0 Unresolved Threads found")
        print("Verified: 0 Pending Reviews found")
        if result.check_requirement:
            print("Verified: 0 Non-green PR Checks found")
        print(f"Session blocking items: {result.counts['blocking_items_count']}")
    else:
        print("Final gate BLOCKED")
        print("\n== Gate Result ==")
        print(f"Gate FAILED: {final_gate_failure_message(result)}")
    print()
    print("== Machine Gate Diagnostics ==")
    for key in core_gate.COUNT_KEYS:
        print(f"{key}={result.counts[key]}")
    print(f"reason_code={result.reason_code or 'PASSED'}")
    print(f"exit_code={result.exit_code}")
    if telemetry_report is None:
        telemetry_report = core_telemetry.build_efficiency_report(result.repo, result.pr_number)
    print()
    print("== Agent Efficiency Summary ==")
    print(f"telemetry_coverage_label={telemetry_report['coverage_label']}")
    print(f"telemetry_total_events={telemetry_report['total_events']}")
    print(f"telemetry_success_rate={telemetry_report['success_rate']:.1f}")
    print(f"telemetry_sources={telemetry_sources_summary(telemetry_report)}")
    print(f"telemetry_diagnostics={telemetry_diagnostics_summary(telemetry_report)}")
    if telemetry_report["inefficiency_flags"]:
        print("telemetry_inefficiency_flags=" + "; ".join(telemetry_report["inefficiency_flags"]))
    else:
        print("telemetry_inefficiency_flags=none")
    print(f"Efficiency report path: {telemetry_report['report_artifact']}")
    if summary_path is not None:
        print(f"Audit summary path: {summary_path}")
        summary_sha256 = read_file_sha256(summary_path)
        print(f"Audit summary sha256: {summary_sha256}")
    print()
    print("== PR Completion Summary Guidance ==")
    print(build_completion_summary_guidance(result, telemetry_report, summary_path=summary_path, include_sha256=True))


def write_native_final_gate_artifacts(
    repo: str,
    pr_number: str,
    audit_id: str,
    result: core_gate.GateResult,
) -> tuple[Path, dict]:
    paths = core_paths.SessionPaths(repo, pr_number)
    workspace = paths.workspace_dir
    timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    run_id = audit_id or "final-gate"
    summary_path = paths.audit_summary_file
    audit_path = paths.audit_log_file
    trace_path = workspace / "trace.jsonl"
    status = "ok" if result.passed else "failed"
    summary_lines = [
        "# Audit Summary",
        "",
        f"- repo: {repo}",
        f"- pr: {pr_number}",
        f"- run_id: {run_id}",
        f"- final_gate_status: {status}",
        f"- reason_code: {result.reason_code or 'PASSED'}",
        f"- check_requirement: {result.check_requirement or 'none'}",
    ]
    summary_lines.extend(f"- {key}: {result.counts[key]}" for key in core_gate.COUNT_KEYS)
    telemetry_report = core_telemetry.build_efficiency_report(repo, pr_number)
    summary_lines.extend(
        [
            "",
            "## Agent Efficiency Summary",
            f"- telemetry_coverage_label: {telemetry_report['coverage_label']}",
            f"- telemetry_total_events: {telemetry_report['total_events']}",
            f"- telemetry_success_rate: {telemetry_report['success_rate']:.1f}",
            f"- efficiency_report_path: {telemetry_report['report_artifact']}",
            f"- telemetry_sources: {telemetry_sources_summary(telemetry_report)}",
            f"- telemetry_diagnostics: {telemetry_diagnostics_summary(telemetry_report)}",
            f"- telemetry_inefficiency_flags: {', '.join(telemetry_report['inefficiency_flags']) if telemetry_report['inefficiency_flags'] else 'none'}",
        ]
    )
    if result.failure_codes:
        summary_lines.extend(["", "## Failure Codes", *[f"- {code}" for code in result.failure_codes]])
    guidance_md = build_completion_summary_guidance(
        result, telemetry_report, summary_path=summary_path, include_sha256=False
    )
    summary_lines.extend(["", "## PR Completion Summary Guidance", guidance_md])
    summary_path.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    summary_sha256 = read_file_sha256(summary_path)
    audit_entry = {
        "ts": timestamp,
        "run_id": run_id,
        "audit_id": run_id,
        "repo": repo,
        "pr": str(pr_number),
        "action": "final-gate",
        "status": status,
        "message": (
            "Gate passed with zero unresolved threads"
            if result.passed
            else f"Gate failed; {final_gate_failure_message(result)} remain"
        ),
        "details": {
            "counts": dict(result.counts),
            "failure_codes": list(result.failure_codes),
            "check_requirement": result.check_requirement,
            "summary_file": str(summary_path),
            "summary_sha256": summary_sha256,
            "efficiency_report": telemetry_report,
        },
    }
    trace_entry = {
        "ts": timestamp,
        "run_id": run_id,
        "repo": repo,
        "pr": str(pr_number),
        "event": "final_gate",
        "status": status,
        "reason_code": result.reason_code or "PASSED",
        "counts": dict(result.counts),
        "check_requirement": result.check_requirement,
        "telemetry_coverage_label": telemetry_report["coverage_label"],
        "efficiency_report_path": telemetry_report["report_artifact"],
    }
    for path, entry in ((audit_path, audit_entry), (trace_path, trace_entry)):
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")
    return summary_path, telemetry_report


def telemetry_sources_summary(telemetry_report: dict) -> str:
    sources = telemetry_report.get("sources")
    if not isinstance(sources, list) or not sources:
        return "none"
    rows: list[str] = []
    for source in sources:
        if not isinstance(source, dict):
            continue
        name = source.get("source", "unknown")
        source_type = source.get("source_type", "unknown")
        event_count = source.get("event_count", 0)
        coverage = source.get("coverage_status", "unknown")
        rows.append(f"{name} ({source_type}): {event_count} events, {coverage}")
    return "; ".join(rows) if rows else "none"


def telemetry_diagnostics_summary(telemetry_report: dict) -> str:
    diagnostics = telemetry_report.get("diagnostics")
    if not isinstance(diagnostics, list) or not diagnostics:
        return "none"
    return "; ".join(str(diagnostic) for diagnostic in diagnostics)


def final_gate_failure_message(result: core_gate.GateResult) -> str:
    reasons: list[str] = []
    if result.counts["unresolved_remote_threads_count"]:
        reasons.append(f"{result.counts['unresolved_remote_threads_count']} unresolved thread(s)")
    if result.counts["blocking_local_items_count"]:
        reasons.append(f"{result.counts['blocking_local_items_count']} blocking item(s)")
    if result.counts["github_threads_missing_reply_count"]:
        reasons.append(f"{result.counts['github_threads_missing_reply_count']} GitHub thread(s) missing reply evidence")
    if result.counts["pending_current_login_review_count"]:
        reasons.append(f"{result.counts['pending_current_login_review_count']} pending review(s)")
    if result.counts["missing_validation_evidence_count"]:
        reasons.append(
            f"{result.counts['missing_validation_evidence_count']} local item(s) missing validation evidence"
        )
    if result.counts["pr_checks_not_green_count"]:
        reasons.append(f"{result.counts['pr_checks_not_green_count']} non-green PR check(s)")
    return " and ".join(reasons) or "gate checks reported failure"


def archive_and_clean_workspace(repo: str, pr_number: str, audit_id: str) -> Path | None:
    workspace = session_store.workspace_dir(repo, pr_number)
    if not workspace.exists():
        return None
    archive_root = core_paths.state_dir() / "archive" / core_paths.normalize_repo(repo) / f"pr-{pr_number}"
    archive_root.mkdir(parents=True, exist_ok=True)
    base_name = audit_id or "final-gate"
    archive_target = archive_root / base_name
    suffix = 1
    while archive_target.exists():
        archive_target = archive_root / f"{base_name}-{suffix}"
        suffix += 1
    shutil.copytree(workspace, archive_target)
    shutil.rmtree(workspace, ignore_errors=True)
    print(f"Archived PR workspace: {archive_target}", file=sys.stderr)
    print(f"Auto-cleaned PR workspace: {workspace}", file=sys.stderr)
    return archive_target
