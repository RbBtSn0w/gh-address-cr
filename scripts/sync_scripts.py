#!/usr/bin/env python3
"""Synchronize python compatibility scripts from src/gh_address_cr/legacy_scripts to skill/scripts."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "src" / "gh_address_cr" / "legacy_scripts"
TARGET_DIR = ROOT / "skill" / "scripts"

BOOTSTRAP_CODE = """def bootstrap_runtime_path() -> None:
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

"""


def process_script_content(filename: str, source_content: str) -> str:
    """Process the source script content to inject the bootstrap path helper if needed."""
    if filename == "cli.py":
        return source_content

    lines = source_content.splitlines(keepends=True)
    imports_gh = False
    first_gh_import_idx = -1

    for idx, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith("import gh_address_cr") or stripped.startswith("from gh_address_cr"):
            imports_gh = True
            if first_gh_import_idx == -1:
                first_gh_import_idx = idx

    if not imports_gh:
        return source_content

    # Inject bootstrap block before first gh_address_cr import
    processed_lines = []
    for idx, line in enumerate(lines):
        if idx == first_gh_import_idx:
            processed_lines.extend(BOOTSTRAP_CODE.splitlines(keepends=True))

        stripped = line.lstrip()
        if (stripped.startswith("import gh_address_cr") or stripped.startswith("from gh_address_cr")) and "# noqa" not in line:
            # Append # noqa: E402
            line = line.rstrip("\n").rstrip("\r") + "  # noqa: E402\n"

        processed_lines.append(line)

    return "".join(processed_lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Synchronize compatibility scripts to skill/scripts.")
    parser.add_argument("--check", action="store_true", help="Check if scripts are synchronized without writing changes.")
    args = parser.parse_args(argv)

    if not SOURCE_DIR.is_dir():
        print(f"Source directory does not exist: {SOURCE_DIR}", file=sys.stderr)
        return 1

    source_files = sorted(path for path in SOURCE_DIR.glob("*.py") if path.name != "__init__.py")
    discrepancies = []

    if args.check:
        # Check target directory
        target_files = sorted(path for path in TARGET_DIR.glob("*.py") if path.name != "__init__.py")
        source_basenames = {path.name for path in source_files}
        target_basenames = {path.name for path in target_files}

        # Check for missing files in target
        for name in sorted(source_basenames - target_basenames):
            discrepancies.append(f"Missing file in target skill/scripts/: {name}")

        # Check for extra files in target
        for name in sorted(target_basenames - source_basenames):
            discrepancies.append(f"Extra file in target skill/scripts/: {name}")

        # Check content match
        for path in source_files:
            target_path = TARGET_DIR / path.name
            if not target_path.exists():
                continue

            expected_content = process_script_content(path.name, path.read_text(encoding="utf-8"))
            actual_content = target_path.read_text(encoding="utf-8")

            if expected_content != actual_content:
                discrepancies.append(f"Content drift in skill/scripts/{path.name}")

        if discrepancies:
            print("Synchronization check FAILED. The following discrepancies were found:", file=sys.stderr)
            for diff in discrepancies:
                print(f"- {diff}", file=sys.stderr)
            print("\nRun 'python3 scripts/sync_scripts.py' to resolve these changes.", file=sys.stderr)
            return 1

        print("Synchronization check PASSED. All compatibility scripts are in sync.")
        return 0

    # Write / sync changes
    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    for path in source_files:
        target_path = TARGET_DIR / path.name
        processed_content = process_script_content(path.name, path.read_text(encoding="utf-8"))
        target_path.write_text(processed_content, encoding="utf-8")
        print(f"Synchronized: {target_path.relative_to(ROOT)}")

    # Clean up target files that are no longer in source
    source_basenames = {path.name for path in source_files}
    for path in TARGET_DIR.glob("*.py"):
        if path.name != "__init__.py" and path.name not in source_basenames:
            path.unlink()
            print(f"Removed orphaned file: {path.relative_to(ROOT)}")

    print("Synchronization complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
