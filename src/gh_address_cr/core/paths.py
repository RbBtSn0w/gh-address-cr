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
        raise PathResolutionError("STATE_DIR_UNAVAILABLE", "Set GH_ADDRESS_CR_STATE_DIR or HOME before running gh-address-cr.")
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
