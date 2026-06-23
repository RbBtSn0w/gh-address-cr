from __future__ import annotations

import glob
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gh_address_cr.core import telemetry_import, telemetry_reporting
from gh_address_cr.core.host_telemetry import attribution as host_attribution
from gh_address_cr.core.host_telemetry import discovery as host_discovery
from gh_address_cr.core.host_telemetry import profile as host_profile


@dataclass(frozen=True)
class TelemetryHealthIssue:
    reason_code: str
    severity: str
    source: str
    retryable: bool
    detail: str
    next_action: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "reason_code": self.reason_code,
            "severity": self.severity,
            "source": self.source,
            "retryable": self.retryable,
            "detail": self.detail,
            "next_action": self.next_action,
        }


def profile_dir() -> Path:
    return Path(__file__).resolve().parent / "host_telemetry" / "profiles"


def load_host_profiles() -> tuple[list[host_profile.HostProfile], list[TelemetryHealthIssue]]:
    profiles: list[host_profile.HostProfile] = []
    issues: list[TelemetryHealthIssue] = []
    for path in sorted(profile_dir().glob("*.json")):
        try:
            profiles.append(host_profile.load_profile(path))
        except Exception as exc:
            issues.append(
                TelemetryHealthIssue(
                    reason_code="TELEMETRY_PROFILE_INVALID",
                    severity="warning",
                    source="profile",
                    retryable=False,
                    detail=f"{path.name}: {exc}",
                    next_action="Fix or remove the invalid packaged host telemetry profile.",
                )
            )
    return profiles, issues


def autodiscovery_profile_check(
    profile: host_profile.HostProfile,
    *,
    cwd: str | None = None,
    environ: dict[str, str] | None = None,
    repo: str | None = None,
    pr_number: str | None = None,
) -> dict[str, Any]:
    env = environ if environ is not None else os.environ
    env_names = profile.discovery.get("session_id_env") or ["SESSION_ID"]
    session_id = host_discovery.first_env_value(env_names, env)
    base = {
        "profile": profile.source,
        "status": "skipped",
        "reason_code": "TELEMETRY_PROFILE_ENV_MISSING",
        "detail": "No configured session id environment variable is set.",
        "next_action": "Run from an active supported agent session or set the profile session id environment variable.",
    }
    if not session_id:
        return base

    try:
        current_dir = os.getcwd()
    except OSError:
        current_dir = "."
    slug = host_discovery.project_slug_from_cwd(cwd or current_dir)
    resolved_glob = host_discovery.resolve_glob(profile.discovery["glob"], project_slug=slug, session_id=session_id)
    matches = [Path(path) for path in glob.glob(resolved_glob) if Path(path).is_file()]
    if not matches:
        return {
            **base,
            "status": "failed",
            "reason_code": "TELEMETRY_TRANSCRIPT_NOT_FOUND",
            "detail": "No transcript matched the active profile session id.",
            "next_action": "Verify the agent host writes transcripts for the active session and rerun telemetry doctor.",
        }

    if repo and pr_number:
        start_iso = host_attribution.session_created_at(repo, pr_number)
        if not start_iso:
            return {
                **base,
                "status": "failed",
                "reason_code": "TELEMETRY_SESSION_WINDOW_MISSING",
                "detail": "No PR session start timestamp is available for attribution.",
                "next_action": "Run a PR-scoped gh-address-cr command before relying on host telemetry autodiscovery.",
            }

    return {
        **base,
        "status": "passed",
        "reason_code": "TELEMETRY_AUTODISCOVERY_READY",
        "detail": "A profile session id and transcript candidate are available.",
        "next_action": "Run final-gate or telemetry ingest to import host telemetry.",
    }


def active_autodiscovery_misses(
    repo: str,
    pr_number: str,
    *,
    cwd: str | None = None,
    environ: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    profiles, _issues = load_host_profiles()
    checks = [
        autodiscovery_profile_check(profile, cwd=cwd, environ=environ, repo=repo, pr_number=pr_number)
        for profile in profiles
    ]
    return [
        check
        for check in checks
        if check["status"] == "failed"
        and check["reason_code"] in {"TELEMETRY_TRANSCRIPT_NOT_FOUND", "TELEMETRY_TRANSCRIPT_OUT_OF_WINDOW"}
    ]


def record_autodiscovery_miss(repo: str, pr_number: str, misses: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not misses:
        return None
    diagnostics = [
        f"host telemetry autodiscovery {miss['profile']}: {miss['reason_code']}"
        for miss in misses
        if isinstance(miss.get("profile"), str) and isinstance(miss.get("reason_code"), str)
    ]
    if not diagnostics:
        return None
    return telemetry_import.autodiscovery_miss_import_summary(repo, pr_number, diagnostics=diagnostics)


def build_doctor_report(repo: str, pr_number: str) -> dict[str, Any]:
    profiles, profile_issues = load_host_profiles()
    profile_checks = [
        autodiscovery_profile_check(profile, repo=repo, pr_number=pr_number)
        for profile in profiles
    ]
    efficiency_report = telemetry_reporting.build_efficiency_report(repo, pr_number)
    cli_health_issues = [
        *[issue.to_dict() for issue in profile_issues],
        *efficiency_report.get("cli_health_issues", []),
    ]
    failed_checks = [check for check in profile_checks if check.get("status") == "failed"]
    storage_issues = [
        issue
        for issue in cli_health_issues
        if issue.get("reason_code") in {"TELEMETRY_STORE_UNAVAILABLE", "CORRUPTED_TELEMETRY_STORE"}
    ]
    status = "FAILED" if failed_checks or storage_issues else "PASSED"
    return {
        "status": status,
        "reason_code": "TELEMETRY_DOCTOR_ISSUES" if status == "FAILED" else "TELEMETRY_DOCTOR_PASSED",
        "repo": repo,
        "pr_number": str(pr_number),
        "coverage_label": efficiency_report.get("coverage_label"),
        "profile_checks": profile_checks,
        "cli_health_issues": cli_health_issues,
        "telemetry_report_artifact": efficiency_report.get("report_artifact"),
        "next_action": (
            "Inspect failed checks and rerun telemetry doctor."
            if status == "FAILED"
            else "Use telemetry summary or final-gate to inspect PR completion evidence."
        ),
    }


def doctor_report_markdown(report: dict[str, Any]) -> str:
    lines = [
        "## CLI Health Telemetry Doctor",
        "",
        f"- status: {report['status']}",
        f"- reason_code: {report['reason_code']}",
        f"- coverage_label: {report.get('coverage_label')}",
        f"- telemetry_report_artifact: {report.get('telemetry_report_artifact')}",
        "",
        "### Profile Checks",
    ]
    for check in report.get("profile_checks", []):
        lines.append(
            f"- {check['profile']}: {check['status']} ({check['reason_code']}) - {check['detail']}"
        )
    issues = report.get("cli_health_issues") or []
    if issues:
        lines.extend(["", "### CLI Health Issues"])
        lines.extend(
            f"- {issue['reason_code']} [{issue['severity']}]: {issue['detail']}"
            for issue in issues
        )
    return "\n".join(lines) + "\n"
