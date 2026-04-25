#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


def bootstrap_runtime_path() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    src_root = repo_root / "src"
    if src_root.is_dir():
        sys.path.insert(0, str(src_root))


bootstrap_runtime_path()

from gh_address_cr.core.session_engine import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
