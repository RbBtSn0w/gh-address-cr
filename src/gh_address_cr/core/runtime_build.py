"""Which runtime build is running, for efficiency reports (Spec 039 L4).

Telemetry from a development checkout and from a release looked identical
because both report the same version. Install metadata (PEP 610
`direct_url.json`) tells them apart without changing release versioning:
no record means an installed package, `dir_info.editable` an editable
checkout, and `vcs_info` a git install with its commit.
"""

from __future__ import annotations

import json
from importlib import metadata
from typing import Any

from gh_address_cr import __version__

DISTRIBUTION = "gh-address-cr"
COMMIT_PREFIX = 12


def origin_from_direct_url(direct_url: dict[str, Any] | None) -> dict[str, Any]:
    """Classify the install. The URL itself is never kept: it can be a local path."""
    if not isinstance(direct_url, dict):
        return {"origin": "package", "commit": None}
    vcs_info = direct_url.get("vcs_info")
    if isinstance(vcs_info, dict) and vcs_info.get("commit_id"):
        return {"origin": "vcs", "commit": str(vcs_info["commit_id"])[:COMMIT_PREFIX]}
    dir_info = direct_url.get("dir_info")
    if isinstance(dir_info, dict) and dir_info.get("editable"):
        return {"origin": "editable", "commit": None}
    return {"origin": "local", "commit": None}


def runtime_build() -> dict[str, Any]:
    # The version comes from the package: editable installs keep a stale metadata version.
    try:
        raw = metadata.distribution(DISTRIBUTION).read_text("direct_url.json")
        direct_url = json.loads(raw) if raw else None
    except (metadata.PackageNotFoundError, ValueError):
        direct_url = None
    return {"version": __version__, **origin_from_direct_url(direct_url)}
