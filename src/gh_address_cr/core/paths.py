from __future__ import annotations

import os
import platform
from pathlib import Path


class PathResolutionError(RuntimeError):
    def __init__(self, reason_code: str, detail: str):
        self.reason_code = reason_code
        super().__init__(detail)


def normalize_repo(repo: str) -> str:
    if not repo or "/" not in repo:
        raise PathResolutionError("INVALID_REPO", "Repository must be in owner/repo form.")
    return repo.replace("/", "__")


def state_dir() -> Path:
    override = os.environ.get("GH_ADDRESS_CR_STATE_DIR")
    if override:
        return Path(override)

    home = os.environ.get("HOME")
    if platform.system() == "Darwin":
        base = os.environ.get("XDG_CACHE_HOME") or (f"{home}/Library/Caches" if home else None)
    else:
        base = os.environ.get("XDG_CACHE_HOME") or (f"{home}/.cache" if home else None)
    if not base:
        raise PathResolutionError(
            "STATE_DIR_UNAVAILABLE", "Set GH_ADDRESS_CR_STATE_DIR or HOME before running gh-address-cr."
        )
    return Path(base) / "gh-address-cr"


def workspace_dir(repo: str, pr_number: str) -> Path:
    return state_dir() / normalize_repo(repo) / f"pr-{pr_number}"


def session_file(repo: str, pr_number: str) -> Path:
    return workspace_dir(repo, pr_number) / "session.json"


def audit_log_file(repo: str, pr_number: str) -> Path:
    return workspace_dir(repo, pr_number) / "audit.jsonl"


def audit_summary_file(repo: str, pr_number: str) -> Path:
    return workspace_dir(repo, pr_number) / "audit_summary.md"


def evidence_ledger_file(repo: str, pr_number: str) -> Path:
    return workspace_dir(repo, pr_number) / "evidence.jsonl"


def external_telemetry_file(repo: str, pr_number: str) -> Path:
    return workspace_dir(repo, pr_number) / "external-telemetry.jsonl"


def telemetry_imports_file(repo: str, pr_number: str) -> Path:
    return workspace_dir(repo, pr_number) / "telemetry-imports.jsonl"


def telemetry_fingerprints_file(repo: str, pr_number: str) -> Path:
    return workspace_dir(repo, pr_number) / "telemetry-fingerprints.json"


def efficiency_report_file(repo: str, pr_number: str) -> Path:
    return workspace_dir(repo, pr_number) / "efficiency-report.json"


def github_pr_cache_file(repo: str, pr_number: str) -> Path:
    return workspace_dir(repo, pr_number) / "github_pr_cache.json"


def last_machine_summary_file(repo: str, pr_number: str) -> Path:
    return workspace_dir(repo, pr_number) / "last-machine-summary.json"


class SessionPaths:
    def __init__(self, repo: str, pr_number: str | int) -> None:
        self.repo = repo
        self.pr_number = str(pr_number)

    @property
    def workspace_dir(self) -> Path:
        return workspace_dir(self.repo, self.pr_number)

    @property
    def session_file(self) -> Path:
        return session_file(self.repo, self.pr_number)

    @property
    def audit_log_file(self) -> Path:
        return audit_log_file(self.repo, self.pr_number)

    @property
    def audit_summary_file(self) -> Path:
        return audit_summary_file(self.repo, self.pr_number)

    @property
    def evidence_ledger_file(self) -> Path:
        return evidence_ledger_file(self.repo, self.pr_number)

    @property
    def external_telemetry_file(self) -> Path:
        return external_telemetry_file(self.repo, self.pr_number)

    @property
    def telemetry_imports_file(self) -> Path:
        return telemetry_imports_file(self.repo, self.pr_number)

    @property
    def telemetry_fingerprints_file(self) -> Path:
        return telemetry_fingerprints_file(self.repo, self.pr_number)

    @property
    def efficiency_report_file(self) -> Path:
        return efficiency_report_file(self.repo, self.pr_number)

