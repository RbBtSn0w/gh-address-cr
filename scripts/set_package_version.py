#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PYPROJECT = ROOT / "pyproject.toml"
DEFAULT_INIT_FILE = ROOT / "src" / "gh_address_cr" / "__init__.py"
VERSION_RE = re.compile(r"^[0-9]+(?:\.[0-9]+)*(?:[a-zA-Z0-9_.!+-]+)?$")


def _replace_required(pattern: str, replacement: str, text: str, label: str) -> str:
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.MULTILINE)
    if count != 1:
        raise SystemExit(f"failed to update {label}: expected exactly one match")
    return updated


def _write_version(path: Path, pattern: str, replacement: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    path.write_text(_replace_required(pattern, replacement, text, label), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Synchronize Python package version metadata.")
    parser.add_argument("positional_version", nargs="?", help="PEP 440 package version to write.")
    parser.add_argument("--version", dest="option_version", help="PEP 440 package version to write.")
    parser.add_argument("--pyproject", type=Path, default=DEFAULT_PYPROJECT)
    parser.add_argument("--init-file", type=Path, default=DEFAULT_INIT_FILE)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    version = args.option_version or args.positional_version
    if not version:
        raise SystemExit("version is required")
    if version.startswith("v"):
        raise SystemExit("version must not include a leading 'v'")
    if not VERSION_RE.match(version):
        raise SystemExit(f"unsupported package version: {version}")

    _write_version(args.pyproject, r'^version = "[^"]+"$', f'version = "{version}"', "pyproject version")
    _write_version(args.init_file, r'^__version__ = "[^"]+"$', f'__version__ = "{version}"', "runtime version")

    print(
        json.dumps(
            {
                "status": "UPDATED",
                "version": version,
                "pyproject": str(args.pyproject),
                "init_file": str(args.init_file),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
