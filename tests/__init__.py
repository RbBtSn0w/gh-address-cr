from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "src"

try:
    import gh_address_cr  # noqa: F401
except ModuleNotFoundError as exc:
    raise RuntimeError(
        "gh_address_cr is not installed. "
        "Run 'pip install -e .' before running tests. "
        "See AGENTS.md § Verification Commands."
    ) from exc

