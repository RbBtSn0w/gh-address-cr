"""Thin wrapper around `gh` calls made by PR-scoped commands."""

from __future__ import annotations

import subprocess

GH_COMMAND_TIMEOUT_SECONDS = 60.0


def run_gh(args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run one `gh` call; every GitHubClient call shares this timeout."""
    return subprocess.run(["gh", *args], text=True, capture_output=True, timeout=GH_COMMAND_TIMEOUT_SECONDS)
