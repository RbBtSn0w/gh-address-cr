from __future__ import annotations

import atexit
import os
import shutil
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "src"

try:
    import gh_address_cr  # noqa: F401
except ModuleNotFoundError as exc:
    raise RuntimeError(
        "gh_address_cr is not installed. "
        "Run scripts/dev_setup.sh and activate .venv (or `python3 -m pip install -e '.[dev]'` inside a virtual environment) before running tests. "
        "See AGENTS.md § Verification Commands."
    ) from exc


GH_GUARD_MESSAGE = "gh is blocked in tests: install a fake gh in the test bin_dir or inject a GitHub client"


def _install_github_cli_guard() -> Path:
    """Put a fail-fast `gh` first on PATH for the whole test process.

    Without it, tests that do not install a fake `gh` reach the developer's real
    `gh` and the GitHub API (for example the stack-context read during evidence
    submission, whose failure the runtime tolerates). The guard keeps that outcome
    (the call fails) but makes it local, fast, and independent of auth and network.
    A test's own fake `gh` in its bin_dir comes earlier on PATH and still wins.

    unittest imports every discovered module before running any test, and many
    modules import this package, so the guard is active before the first test.
    """
    guard_dir = Path(tempfile.mkdtemp(prefix="gh-address-cr-gh-guard-"))
    atexit.register(shutil.rmtree, guard_dir, ignore_errors=True)
    guard = guard_dir / "gh"
    # A quoted heredoc prints the message verbatim, whatever quotes it contains.
    guard.write_text(f"#!/bin/sh\ncat >&2 <<'MESSAGE'\n{GH_GUARD_MESSAGE}\nMESSAGE\nexit 1\n", encoding="utf-8")
    guard.chmod(0o755)
    os.environ["PATH"] = f"{guard_dir}{os.pathsep}{os.environ.get('PATH', '')}"
    return guard_dir


GH_GUARD_DIR = _install_github_cli_guard()
