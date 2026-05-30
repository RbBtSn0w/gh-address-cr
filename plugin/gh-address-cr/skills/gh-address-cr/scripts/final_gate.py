#!/usr/bin/env python3
from __future__ import annotations

import sys

def bootstrap_runtime_path() -> None:
    import os
    import sys
    from pathlib import Path
    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parents[1]
    src_root = repo_root / "src"
    if src_root.is_dir():
        sys.path.insert(0, str(src_root))
    os.environ.setdefault("GH_ADDRESS_CR_COMPAT_SCRIPT_DIR", str(script_dir))


bootstrap_runtime_path()

from gh_address_cr.cli import handle_final_gate  # noqa: E402


def main() -> int:
    return handle_final_gate(None, None, sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
