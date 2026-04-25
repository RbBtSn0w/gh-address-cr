#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path


def bootstrap_runtime_path() -> None:
    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parents[1]
    src_root = repo_root / "src"
    if src_root.is_dir():
        sys.path.insert(0, str(src_root))
    os.environ.setdefault("GH_ADDRESS_CR_COMPAT_SCRIPT_DIR", str(script_dir))


bootstrap_runtime_path()

from gh_address_cr.core.cr_loop import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
