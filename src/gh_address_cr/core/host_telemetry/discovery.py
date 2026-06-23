from __future__ import annotations

import glob as globlib
import os
import sys
from collections.abc import Mapping
from pathlib import Path


def project_slug_from_cwd(cwd: str) -> str:
    # Claude Code slug = absolute cwd with path separators replaced by '-'.
    # Handle both POSIX ('/') and Windows ('\\') separators.
    return cwd.replace("\\", "-").replace("/", "-")


def resolve_glob(pattern: str, *, project_slug: str, session_id: str = "") -> str:
    expanded = os.path.expanduser(pattern.replace("{project_slug}", project_slug).replace("{session_id}", session_id))
    return expanded


def first_env_value(
    env_names: str | list[str] | tuple[str, ...], environ: Mapping[str, str] | None = None
) -> str | None:
    source = environ if environ is not None else os.environ
    names = [env_names] if isinstance(env_names, str) else env_names
    for name in names:
        value = source.get(str(name))
        if value:
            return value
    return None


def discover_transcript(resolved_glob: str) -> Path | None:
    matches = [Path(p) for p in globlib.glob(resolved_glob)]
    matches = [p for p in matches if p.is_file()]
    if not matches:
        return None
    return max(matches, key=lambda p: p.stat().st_mtime)


def consent_notice_once(source: str, marker: Path) -> bool:
    """Print a one-time consent notice. Returns True if shown this call."""
    if marker.exists():
        return False
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("acknowledged\n", encoding="utf-8")
    except OSError:
        return False
    sys.stderr.write(
        f"gh-address-cr: detected {source} session transcript; reading "
        "operation/status/timing only (no prompts, file contents, or tokens) "
        "for efficiency telemetry. Opt out: GH_ADDRESS_CR_HOST_TELEMETRY_AUTO=0. "
        "This notice is shown once.\n"
    )
    return True
