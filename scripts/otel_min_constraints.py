#!/usr/bin/env python3
"""Pin the OpenTelemetry packages to the lower bounds declared in pyproject.toml.

The otel-minimum-versions CI job installs these pins to prove the declared floor still
imports. The sdk pins opentelemetry-semantic-conventions exactly, so the sdk floor decides
which `_incubating` constants exist (see src/gh_address_cr/core/otel_semconv.py).

    python scripts/otel_min_constraints.py                     # print `name==floor` lines
    python scripts/otel_min_constraints.py --check-installed   # fail unless installed == floor

Both modes fail loudly instead of skipping what they cannot read: an unpinned package would
make the job test the newest release while still reporting success.
"""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PYPROJECT = ROOT / "pyproject.toml"
PREFIX = "opentelemetry-"
# Resolved for context in --check-installed; pinned transitively by the sdk, not declared.
SEMCONV_PACKAGE = "opentelemetry-semantic-conventions"
_PLAIN_FLOOR = re.compile(r"(?P<name>opentelemetry-[A-Za-z0-9._-]+)>=(?P<version>[0-9][A-Za-z0-9._!+-]*)")


def declared_floors(pyproject_text: str) -> dict[str, str]:
    """Return {package: floor} for every opentelemetry-* dependency in pyproject.toml.

    Raises ValueError for a spec that is not a plain `name>=version` (an upper bound, extras, a
    marker, `~=`, or no bound at all), and when there is no opentelemetry-* dependency.
    """
    dependencies = tomllib.loads(pyproject_text)["project"]["dependencies"]
    floors: dict[str, str] = {}
    for spec in dependencies:
        if not spec.strip().lower().startswith(PREFIX):
            continue
        match = _PLAIN_FLOOR.fullmatch(spec.strip())
        if match is None:
            raise ValueError(f"cannot pin {spec!r}: expected a plain 'opentelemetry-<name>>=<version>' lower bound")
        floors[match["name"]] = match["version"]
    if not floors:
        raise ValueError("pyproject.toml declares no opentelemetry-* dependency to pin")
    return floors


def installed_mismatches(floors: dict[str, str]) -> tuple[list[str], list[str]]:
    """Return (report lines, problems) comparing each installed version with its floor."""
    from packaging.version import Version  # runtime dependency; imported late so pinning needs only the stdlib

    report: list[str] = []
    problems: list[str] = []
    for name, floor in sorted(floors.items()):
        try:
            installed = metadata.version(name)
        except metadata.PackageNotFoundError:
            problems.append(f"{name} is not installed (floor {floor})")
            continue
        report.append(f"{name} {installed} (floor {floor})")
        if Version(installed) != Version(floor):
            problems.append(f"{name} is {installed}, expected exactly the floor {floor}")
    try:
        report.append(f"{SEMCONV_PACKAGE} {metadata.version(SEMCONV_PACKAGE)} (pinned by the sdk)")
    except metadata.PackageNotFoundError:
        problems.append(f"{SEMCONV_PACKAGE} is not installed")
    return report, problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pyproject", type=Path, default=DEFAULT_PYPROJECT, help="pyproject.toml to read.")
    parser.add_argument(
        "--check-installed",
        action="store_true",
        help="Verify the installed versions equal the declared floors instead of printing constraints.",
    )
    args = parser.parse_args(argv)

    try:
        floors = declared_floors(args.pyproject.read_text(encoding="utf-8"))
    except (OSError, ValueError, tomllib.TOMLDecodeError, KeyError) as error:
        print(f"otel_min_constraints: {error}", file=sys.stderr)
        return 1

    if not args.check_installed:
        for name, floor in sorted(floors.items()):
            print(f"{name}=={floor}")
        return 0

    report, problems = installed_mismatches(floors)
    for line in report:
        print(line)
    for problem in problems:
        print(f"otel_min_constraints: {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
