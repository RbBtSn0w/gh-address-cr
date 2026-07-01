from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from gh_address_cr.core.telemetry_models import EfficiencyReportPayload

from gh_address_cr.commands.common import (
    emit_scope_resolution_error,
    maybe_prepend_implicit_scope,
    prepend_optional,
)
from gh_address_cr.core import gate as core_gate
from gh_address_cr.core import paths as core_paths
from gh_address_cr.core import session as session_store
from gh_address_cr.core import telemetry as core_telemetry
from gh_address_cr.core import telemetry_health
from gh_address_cr.core.evaluation.archive import finalize_run_manifest
from gh_address_cr.core.host_telemetry import attribution as host_attribution
from gh_address_cr.core.host_telemetry import capture as host_capture
from gh_address_cr.core.host_telemetry import discovery as host_discovery
from gh_address_cr.core.host_telemetry import profile as host_profile
from gh_address_cr.core.io import write_json_atomic

HOST_TELEMETRY_INPUT_ENV = "GH_ADDRESS_CR_HOST_TELEMETRY_INPUT"
HOST_TELEMETRY_SOURCE_ENV = "GH_ADDRESS_CR_HOST_TELEMETRY_SOURCE"
HOST_TELEMETRY_FORMAT_ENV = "GH_ADDRESS_CR_HOST_TELEMETRY_FORMAT"


def finalize_manifest_fail_open(
    target: Path,
    *,
    repo: str,
    pr_number: str,
    run_id: str,
    passed: bool,
    counts: dict[str, int],
    telemetry_report: Any | None,
) -> dict[str, Any] | None:
    try:
        sources = []
        if telemetry_report:
            sources = [str(row.get("source")) for row in telemetry_report.get("sources", []) if isinstance(row, dict)]
        manifest = finalize_run_manifest(
            target,
            repo=repo,
            pr_number=pr_number,
            run_id=run_id,
            final_gate_passed=passed,
            final_gate_counts=counts,
            telemetry_sources=sources,
        )
        if telemetry_report is not None:
            overhead = float(manifest.get("evaluation_capture_overhead_ms") or 0.0)
            telemetry_report["evaluation_capture_overhead_ms"] = overhead
            telemetry_report["evaluation_capture_budget_ms"] = 250.0
            telemetry_report["evaluation_capture_status"] = "degraded" if overhead > 250.0 else "healthy"
            if overhead > 250.0:
                telemetry_report.setdefault("diagnostics", []).append("EVALUATION_CAPTURE_OVERHEAD_EXCEEDED")
        return manifest
    except Exception:
        if telemetry_report is not None:
            telemetry_report.setdefault("diagnostics", []).append("EVALUATION_MANIFEST_UNAVAILABLE")
        return None


def _parse_final_gate_args(
    repo: str | None, pr_number: str | None, passthrough: list[str]
) -> tuple[argparse.Namespace | None, int | None]:
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
        return None, emit_scope_resolution_error(scope_error)
    return parser.parse_args(scoped_args), None


def _ingest_telemetry_if_needed(repo: str, pr_number: str) -> None:
    if ingest_host_telemetry_from_environment(repo, pr_number) is None:
        autodiscovery_summary = ingest_host_telemetry_via_autodiscovery(repo, pr_number)
        if autodiscovery_summary is None:
            telemetry_health.record_autodiscovery_miss(
                repo,
                pr_number,
                telemetry_health.active_autodiscovery_misses(repo, pr_number),
            )


def _archive_and_clean_workspace_if_passed(
    parsed: argparse.Namespace,
    result: core_gate.GateResult,
    summary_path: Path,
    telemetry_report: EfficiencyReportPayload | None,
) -> tuple[Path, EfficiencyReportPayload | None]:
    if result.passed and parsed.auto_clean:
        workspace_path = session_store.workspace_dir(parsed.repo, parsed.pr_number)
        archive_target = archive_and_clean_workspace(parsed.repo, parsed.pr_number, parsed.audit_id)
        if archive_target is not None:
            summary_path = archive_target / summary_path.name
            if telemetry_report is not None:
                paths = core_paths.SessionPaths(parsed.repo, parsed.pr_number)
                archived_report_path = archive_target / paths.efficiency_report_file.name
                telemetry_report["report_artifact"] = str(archived_report_path)
                # replace_path_occurrences rebuilds the mapping with identical
                # keys, so the result still satisfies EfficiencyReportPayload.
                telemetry_report = cast(
                    "EfficiencyReportPayload",
                    replace_path_occurrences(
                        telemetry_report,
                        str(workspace_path),
                        str(archive_target),
                    ),
                )
                rewrite_archived_efficiency_report_path(summary_path, telemetry_report["report_artifact"])
                rewrite_archived_efficiency_report_artifact(archived_report_path, telemetry_report)
                rewrite_archived_audit_artifacts(
                    archive_target,
                    original_workspace=workspace_path,
                    summary_path=summary_path,
                    telemetry_report=telemetry_report,
                )
    return summary_path, telemetry_report


def _emit_machine_summary(
    result: core_gate.GateResult,
    summary_path: Path,
    telemetry_report: EfficiencyReportPayload | None,
) -> None:
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
        completion_summary = build_completion_summary_model(result, telemetry_report)
        machine_summary["completion_summary"] = completion_summary
        machine_summary["completion_summary_line"] = completion_summary["line"]
        machine_summary["completion_summary_guidance"] = build_completion_summary_guidance(
            result, telemetry_report, summary_path=summary_path, include_sha256=True
        )
    sys.stdout.write(json.dumps(machine_summary, indent=2, sort_keys=True) + "\n")


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

    parsed, error_code = _parse_final_gate_args(repo, pr_number, passthrough)
    if error_code is not None:
        return error_code
    assert parsed is not None

    _ingest_telemetry_if_needed(parsed.repo, parsed.pr_number)
    machine_requested = bool(parsed.machine)

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

    telemetry_report: EfficiencyReportPayload | None
    summary_path, telemetry_report = write_native_final_gate_artifacts(
        parsed.repo, parsed.pr_number, parsed.audit_id, result
    )
    summary_path, telemetry_report = _archive_and_clean_workspace_if_passed(
        parsed, result, summary_path, telemetry_report
    )
    finalize_manifest_fail_open(
        summary_path.parent,
        repo=parsed.repo,
        pr_number=parsed.pr_number,
        run_id=parsed.audit_id or "final-gate",
        passed=result.passed,
        counts=dict(result.counts),
        telemetry_report=telemetry_report,
    )

    if parsed.machine:
        _emit_machine_summary(result, summary_path, telemetry_report)
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
    except Exception as exc:
        core_telemetry._log_telemetry_failure("host telemetry ingestion", exc)
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
    except Exception as exc:
        core_telemetry._log_telemetry_failure("input unavailable summary creation", exc)
        return None


def safe_hook_unavailable_import_summary(repo: str, pr_number: str, *, source: str, fmt: str) -> dict | None:
    try:
        return core_telemetry.hook_unavailable_import_summary(repo, pr_number, source=source, fmt=fmt)
    except Exception as exc:
        core_telemetry._log_telemetry_failure("hook unavailable summary creation", exc)
        return None


AUTO_ENV = "GH_ADDRESS_CR_HOST_TELEMETRY_AUTO"
_HOST_PROFILE_DIR = Path(__file__).resolve().parents[1] / "core" / "host_telemetry" / "profiles"


def _autodiscovery_session_id(profile: host_profile.HostProfile) -> str | None:
    return host_discovery.first_env_value(profile.discovery.get("session_id_env") or ["SESSION_ID"])


def _load_host_profiles() -> list[host_profile.HostProfile]:
    profiles: list[host_profile.HostProfile] = []
    for path in sorted(_HOST_PROFILE_DIR.glob("*.json")):
        try:
            profiles.append(host_profile.load_profile(path))
        except ValueError:
            continue
    return profiles


def ingest_host_telemetry_via_autodiscovery(repo: str, pr_number: str, *, session_id: str | None = None) -> dict | None:
    if os.environ.get(HOST_TELEMETRY_INPUT_ENV):
        return None  # explicit input wins; handled by ingest_host_telemetry_from_environment
    if os.environ.get(AUTO_ENV) == "0":
        return None
    for profile in _load_host_profiles():
        active_session_id = session_id or _autodiscovery_session_id(profile)
        if not active_session_id:
            continue
        summary = _ingest_profile_via_autodiscovery(repo, pr_number, profile, active_session_id)
        if summary is not None:
            return summary
    return None


def _ingest_profile_via_autodiscovery(
    repo: str,
    pr_number: str,
    profile: host_profile.HostProfile,
    session_id: str,
) -> dict | None:
    try:
        slug = host_discovery.project_slug_from_cwd(os.getcwd())
        resolved = host_discovery.resolve_glob(profile.discovery["glob"], project_slug=slug, session_id=session_id)
        transcript = host_discovery.discover_transcript(resolved)
        if transcript is None:
            return None
        start_iso = host_attribution.session_created_at(repo, pr_number)
        now_iso = host_attribution.now_iso()
        if not start_iso:
            return None
        all_lines = host_capture.read_lines(transcript)
        sid_path = profile.record.get("session_id_path", "sessionId")
        timestamp_path = profile.fields.get("timestamp_path", "timestamp")
        sessions = host_attribution.distinct_sessions_in_window(
            all_lines, start_iso=start_iso, now_iso=now_iso, session_id_path=sid_path, timestamp_path=timestamp_path
        )
        if len(sessions) > 1:
            return safe_hook_unavailable_import_summary(repo, pr_number, source=profile.source, fmt="agent-jsonl")
        text, outcome = host_capture.capture_agent_jsonl(
            profile, transcript=transcript, session_id=session_id, start_iso=start_iso, now_iso=now_iso
        )
        if outcome != "captured" or not text:
            if outcome == "degraded":
                return safe_hook_unavailable_import_summary(repo, pr_number, source=profile.source, fmt="agent-jsonl")
            return None
        marker = core_paths.state_dir() / ".host-telemetry-consent" / f"{profile.source}.marker"
        host_discovery.consent_notice_once(profile.source, marker)
        return core_telemetry.import_external_telemetry(
            repo, pr_number, source=profile.source, fmt="agent-jsonl", raw=text
        )
    except Exception as exc:
        core_telemetry._log_telemetry_failure("auto-discovery session telemetry capture", exc)
        return safe_hook_unavailable_import_summary(repo, pr_number, source=profile.source, fmt="agent-jsonl")


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
            leading = line[: line.find("-")]
            updated.append(f"{leading}- Efficiency Report: {report_artifact}")
        elif line.strip().startswith("- Audit Summary:"):
            leading = line[: line.find("-")]
            updated.append(f"{leading}- Audit Summary: {summary_path}")
        else:
            updated.append(line)
    try:
        summary_path.write_text("\n".join(updated) + "\n", encoding="utf-8")
    except OSError:
        return


def rewrite_archived_efficiency_report_artifact(report_path: Path, telemetry_report: EfficiencyReportPayload) -> None:
    try:
        current = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        core_telemetry._log_telemetry_failure("read/decode archived report", exc)
        current = {}
    current.update(telemetry_report)
    current["report_artifact"] = str(report_path)
    try:
        if report_path.is_dir():
            shutil.rmtree(report_path)
        write_json_atomic(report_path, current)
    except OSError:
        return


def rewrite_archived_audit_artifacts(
    archive_target: Path,
    *,
    original_workspace: Path,
    summary_path: Path,
    telemetry_report: EfficiencyReportPayload,
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


def build_completion_summary_line(result: core_gate.GateResult, telemetry_report: EfficiencyReportPayload) -> str:
    return build_completion_summary_model(result, telemetry_report)["line"]


def build_completion_summary_model(
    result: core_gate.GateResult, telemetry_report: EfficiencyReportPayload
) -> dict[str, str]:
    status_str = "PASSED" if result.passed else "FAILED"
    unresolved_threads = result.counts.get("unresolved_remote_threads_count", 0)
    pending_reviews = result.counts.get("pending_current_login_review_count", 0)
    checks_failed = result.counts.get("pr_checks_failed_count", 0)
    checks_pending = result.counts.get("pr_checks_pending_count", 0)
    checks_concise = f"{checks_failed}/{checks_pending}" if result.check_requirement else "N/A"

    coverage = telemetry_report.get("coverage_label") or "unavailable"
    total_events = _safe_int(telemetry_report.get("total_events"), default=0)
    success_rate = _safe_float(telemetry_report.get("success_rate"), default=0.0)
    confidence = str(telemetry_report.get("confidence") or _default_confidence_for_coverage(coverage))
    coverage_note = _coverage_note(coverage, confidence, total_events, success_rate)
    source_summary = _source_summary(telemetry_report.get("sources"))
    duration_summary = _duration_summary(telemetry_report.get("total_observed_duration_ms"))
    top_operation_summary = _top_operation_summary(telemetry_report.get("slowest_operations"))
    issue_summary = _issue_summary(telemetry_report, success_rate=success_rate, total_events=total_events)
    artifact_summary = str(telemetry_report.get("report_artifact") or "N/A")
    line = (
        f"[gh-address-cr: {status_str} | "
        f"threads: {unresolved_threads} | "
        f"reviews: {pending_reviews} | "
        f"checks: {checks_concise} | "
        f"telemetry: {coverage}/{confidence} ({total_events} events, {success_rate:.1f}%"
        f"{_coverage_line_suffix(coverage)}) | "
        f"sources: {source_summary} | "
        f"duration: {duration_summary} | "
        f"{top_operation_summary} | "
        f"issues: {issue_summary}]"
    )
    return {
        "line": line,
        "coverage_note": coverage_note,
        "source_summary": source_summary,
        "duration_summary": duration_summary,
        "top_operation_summary": top_operation_summary,
        "issue_summary": issue_summary,
        "artifact_summary": artifact_summary,
    }


def _default_confidence_for_coverage(coverage: str) -> str:
    if coverage == "complete":
        return "high"
    if coverage in {"partial", "runtime-only"}:
        return "medium"
    return "low"


def _coverage_line_suffix(coverage: str) -> str:
    if coverage == "runtime-only":
        return "; runtime only, no host import"
    return ""


def _coverage_note(coverage: str, confidence: str, total_events: int, success_rate: float) -> str:
    base = f"{coverage} telemetry with {confidence} confidence, {total_events} events, and {success_rate:.1f}% success."
    if coverage == "runtime-only":
        return f"{base} host telemetry was not imported; metrics cover runtime command events only."
    if coverage == "complete":
        return f"{base} Runtime and imported host telemetry were both available."
    if coverage == "partial":
        return f"{base} Some telemetry sources were unavailable or incomplete."
    return f"{base} No usable efficiency telemetry was available."


def _source_summary(value: object) -> str:
    if not isinstance(value, list):
        return "none"
    rows: list[str] = []
    for source in value:
        if not isinstance(source, dict):
            continue
        name = str(source.get("source") or "unknown")
        event_count = _safe_int(source.get("event_count"), default=0)
        rows.append(f"{name} {event_count}")
    return "; ".join(rows) if rows else "none"


def _duration_summary(value: object) -> str:
    duration_ms = _safe_int(value, default=0)
    if duration_ms <= 0:
        return "no observed duration"
    return f"{_format_duration(duration_ms)} observed"


def _top_operation_summary(value: object) -> str:
    if not isinstance(value, list) or not value:
        return "slowest: none"
    first = next((row for row in value if isinstance(row, dict)), None)
    if first is None:
        return "slowest: none"
    operation = str(first.get("operation") or "unknown")
    duration_ms = _safe_int(first.get("duration_ms"), default=0)
    status = str(first.get("status") or "unknown")
    if duration_ms <= 0:
        return f"slowest: {operation} {status}"
    return f"slowest: {operation} {_format_duration(duration_ms)} {status}"


def _issue_summary(telemetry_report: EfficiencyReportPayload, *, success_rate: float, total_events: int) -> str:
    parts: list[str] = []
    if total_events > 0 and success_rate < 100.0:
        parts.append(f"success {success_rate:.1f}%")
    flags = _string_list(telemetry_report.get("inefficiency_flags"))
    if flags:
        parts.append("flags: " + "; ".join(flags))
    error_rows = telemetry_report.get("error_prone_operations")
    if isinstance(error_rows, list):
        for row in error_rows[:2]:
            if not isinstance(row, dict):
                continue
            operation = str(row.get("operation") or "unknown")
            failures = _safe_int(row.get("failures"), default=0)
            timeouts = _safe_int(row.get("timeouts"), default=0)
            retries = _safe_int(row.get("retries"), default=0)
            parts.append(f"{operation} failures={failures} timeouts={timeouts} retries={retries}")
    diagnostics = _string_list(telemetry_report.get("diagnostics"))
    if diagnostics:
        parts.append("diagnostics: " + "; ".join(diagnostics[:2]))
    return "; ".join(parts) if parts else "none"


def _format_duration(duration_ms: int) -> str:
    if duration_ms >= 1000:
        return f"{duration_ms / 1000:.1f}s"
    return f"{duration_ms}ms"


def _safe_int(value: object, *, default: int) -> int:
    try:
        if value is None:
            return default
        if isinstance(value, float):
            return int(value) if math.isfinite(value) else default
        parsed = int(cast(Any, value))
        return parsed
    except (OverflowError, TypeError, ValueError):
        return default


def _safe_float(value: object, *, default: float) -> float:
    try:
        if value is None:
            return default
        parsed = float(cast(Any, value))
        return parsed if math.isfinite(parsed) else default
    except (TypeError, ValueError):
        return default


def _string_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [text for item in value if (text := str(item).strip())]
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    return []


def _gather_attention_items(
    coverage: str,
    total_events: int,
    success_rate: float,
    inefficiency_flags: list[str],
    flags_str: str,
    telemetry_diagnostics: list[str],
    telemetry_diagnostics_str: str,
    result: core_gate.GateResult,
    threads_checks_remain: bool,
) -> tuple[list[str], list[str]]:
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

    if threads_checks_remain:
        remain_details = []
        unresolved_threads = result.counts.get("unresolved_remote_threads_count", 0)
        pending_reviews = result.counts.get("pending_current_login_review_count", 0)
        blocking_items = result.counts.get("blocking_items_count", 0)
        missing_reply = result.counts.get("github_threads_missing_reply_count", 0)
        missing_validation = result.counts.get("missing_validation_evidence_count", 0)
        logic_validation_blocking = result.counts.get("logic_validation_blocking_count", 0)
        checks_failed = result.counts.get("pr_checks_failed_count", 0)
        checks_pending = result.counts.get("pr_checks_pending_count", 0)
        checks_not_green = result.counts.get("pr_checks_not_green_count", 0)

        if unresolved_threads > 0:
            remain_details.append(f"{unresolved_threads} unresolved threads")
        if pending_reviews > 0:
            remain_details.append(f"{pending_reviews} pending reviews")
        if checks_not_green > 0:
            remain_details.append(
                f"{checks_not_green} non-green checks ({checks_failed} failed, {checks_pending} pending)"
            )
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
    return abnormal_implications, abnormal_names


def build_completion_summary_guidance(
    result: core_gate.GateResult,
    telemetry_report: EfficiencyReportPayload,
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
    checks_not_green = result.counts.get("pr_checks_not_green_count", 0)

    coverage = telemetry_report.get("coverage_label") or "unavailable"
    total_events = _safe_int(telemetry_report.get("total_events"), default=0)
    success_rate = _safe_float(telemetry_report.get("success_rate"), default=0.0)
    inefficiency_flags = _string_list(telemetry_report.get("inefficiency_flags"))
    flags_str = "; ".join(inefficiency_flags) if inefficiency_flags else "none"
    telemetry_diagnostics = [
        diagnostic for diagnostic in _string_list(telemetry_report.get("diagnostics")) if diagnostic.strip()
    ]
    telemetry_diagnostics_str = "; ".join(telemetry_diagnostics)
    report_artifact = telemetry_report.get("report_artifact") or "N/A"

    summary_path_str = str(summary_path) if summary_path else "N/A"
    metrics_line = build_completion_summary_line(result, telemetry_report)

    audit_summary_line = f"- Audit Summary: {summary_path_str}"
    if include_sha256 and summary_path:
        summary_sha256 = read_file_sha256(summary_path)
        audit_summary_line += f" (sha256: {summary_sha256})"

    threads_checks_remain = (
        unresolved_threads > 0
        or pending_reviews > 0
        or blocking_items > 0
        or blocking_local > 0
        or blocking_github > 0
        or missing_reply > 0
        or missing_validation > 0
        or logic_validation_blocking > 0
        or checks_not_green > 0
        or checks_failed > 0
    )

    abnormal_implications, abnormal_names = _gather_attention_items(
        coverage,
        total_events,
        success_rate,
        inefficiency_flags,
        flags_str,
        telemetry_diagnostics,
        telemetry_diagnostics_str,
        result,
        threads_checks_remain,
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
        lines.extend(
            [
                "",
                "### Attention Items & Implications",
                *abnormal_implications,
                "",
                "> [!IMPORTANT]",
                "> One or more metrics are abnormal. You MUST explain the implications of these metrics in your completion summary rather than just pasting raw fields.",
                ">",
                "> **IMPLICATION PROMPT**:",
                f"> Please explain the impact of: {', '.join(abnormal_names)}.",
            ]
        )

    return "\n".join(lines)


def emit_final_gate_result(
    result: core_gate.GateResult,
    *,
    summary_path: Path | None = None,
    telemetry_report: EfficiencyReportPayload | None = None,
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
) -> tuple[Path, EfficiencyReportPayload]:
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


def telemetry_sources_summary(telemetry_report: EfficiencyReportPayload) -> str:
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


def telemetry_diagnostics_summary(telemetry_report: EfficiencyReportPayload) -> str:
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
