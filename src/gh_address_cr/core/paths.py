from __future__ import annotations

import os
import platform
import re
from pathlib import Path


class PathResolutionError(RuntimeError):
    def __init__(self, reason_code: str, detail: str):
        self.reason_code = reason_code
        super().__init__(detail)


# GitHub owner logins are alphanumeric with inner hyphens; repository names also
# allow `.` and `_`. Anything else (spaces, a second slash, `.`/`..`) would name a
# different or escaping state path, so it is rejected before any path is built.
_REPO_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9._-]+")
_PR_NUMBER_PATTERN = re.compile(r"[1-9][0-9]*")
_TARGET_HINT = "Pass owner/repo and the PR number as two separate arguments."


def validate_repo(repo: str) -> None:
    if not isinstance(repo, str) or not _REPO_PATTERN.fullmatch(repo) or repo.split("/", 1)[1] in (".", ".."):
        raise PathResolutionError("INVALID_REPO", f"Repository must be in owner/repo form. {_TARGET_HINT}")


def validate_pr_number(pr_number: str | int) -> None:
    if not _PR_NUMBER_PATTERN.fullmatch(str(pr_number)):
        raise PathResolutionError(
            "INVALID_PR_NUMBER",
            f"Pull request number must be a positive integer. {_TARGET_HINT}",
        )


def validate_pr_target(repo: str, pr_number: str | int) -> None:
    validate_repo(repo)
    validate_pr_number(pr_number)


def normalize_repo(repo: str) -> str:
    validate_repo(repo)
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
    # Only the repository is enforced here: `submit-feedback` keeps its audit in the
    # non-PR `pr-feedback` workspace. PR-scoped commands validate the number at entry.
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


def run_manifest_file(repo: str, pr_number: str) -> Path:
    return workspace_dir(repo, pr_number) / "run-manifest.v1.json"


def evaluation_root() -> Path:
    return state_dir() / "evaluation"


def evaluation_observations_file(repo: str, pr_number: str) -> Path:
    return evaluation_root() / normalize_repo(repo) / f"pr-{pr_number}" / "evaluation-observations.v1.jsonl"


def evaluation_catalog_file(repo: str, pr_number: str) -> Path:
    _ = (repo, pr_number)
    return evaluation_root() / "evaluation-catalog.v1.sqlite3"


def global_evaluation_catalog_file() -> Path:
    return evaluation_root() / "evaluation-catalog.v1.sqlite3"


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

    @property
    def run_manifest_file(self) -> Path:
        return run_manifest_file(self.repo, self.pr_number)

    @property
    def evaluation_observations_file(self) -> Path:
        return evaluation_observations_file(self.repo, self.pr_number)

    @property
    def evaluation_catalog_file(self) -> Path:
        return evaluation_catalog_file(self.repo, self.pr_number)
