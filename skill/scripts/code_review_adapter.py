#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

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

from gh_address_cr.intake.findings import normalize_finding, parse_records  # noqa: E402


def load_payload(input_path: str) -> str:
    if input_path == "-":
        return sys.stdin.read()
    return Path(input_path).read_text(encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize structured code-review findings into adapter output JSON.")
    parser.add_argument(
        "--input",
        default="-",
        help="Input file containing findings JSON. Use '-' or omit to read from stdin.",
    )
    args = parser.parse_args()

    findings = [normalize_finding(record) for record in parse_records(load_payload(args.input))]
    json.dump(findings, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
