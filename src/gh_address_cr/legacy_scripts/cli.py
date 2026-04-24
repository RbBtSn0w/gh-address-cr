#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def load_requirements() -> dict:
    path = Path(__file__).resolve().parents[1] / "runtime-requirements.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"gh-address-cr runtime compatibility requirements are unreadable: {exc}", file=sys.stderr)
        raise SystemExit(127) from exc


def parse_version(value: str) -> tuple[int, ...]:
    parts = []
    for part in value.split("."):
        if not part.isdigit():
            break
        parts.append(int(part))
    return tuple(parts or [0])


def version_is_at_least(actual: str, minimum: str) -> bool:
    actual_parts = parse_version(actual)
    minimum_parts = parse_version(minimum)
    width = max(len(actual_parts), len(minimum_parts))
    return actual_parts + (0,) * (width - len(actual_parts)) >= minimum_parts + (0,) * (width - len(minimum_parts))


def protocol_is_supported(runtime_protocols: tuple[str, ...], requirement: str) -> bool:
    # Current skill requirements use one bounded range: ">=1.0,<2.0".
    lower = "1.0"
    upper = "2.0"
    if requirement.startswith(">=") and ",<" in requirement:
        lower, upper = requirement[2:].split(",<", 1)
    return any(version_is_at_least(protocol, lower) and parse_version(protocol) < parse_version(upper) for protocol in runtime_protocols)


def fail_compatibility(status: str, remediation: str) -> int:
    print(
        json.dumps(
            {
                "status": status,
                "runtime_package": "gh-address-cr",
                "remediation": remediation,
            },
            sort_keys=True,
        ),
        file=sys.stderr,
    )
    return 127


def validate_runtime(runtime, runtime_cli, requirements: dict) -> int | None:
    minimum = str(requirements.get("minimum_runtime_version") or "0")
    runtime_version = str(getattr(runtime, "__version__", "0"))
    if not version_is_at_least(runtime_version, minimum):
        return fail_compatibility(
            "runtime_too_old",
            f"Install gh-address-cr runtime >= {minimum}; found {runtime_version}.",
        )

    supported_protocols = tuple(str(value) for value in getattr(runtime, "SUPPORTED_PROTOCOL_VERSIONS", ()))
    requirement = next(iter(requirements.get("supported_protocol_versions") or [">=1.0,<2.0"]))
    if not protocol_is_supported(supported_protocols, str(requirement)):
        return fail_compatibility(
            "protocol_unsupported",
            f"Install a gh-address-cr runtime supporting protocol {requirement}; found {supported_protocols}.",
        )

    if not callable(getattr(runtime_cli, "main", None)):
        return fail_compatibility(
            "missing_entrypoint",
            "Installed gh-address-cr runtime does not expose gh_address_cr.cli.main.",
        )
    return None


def bootstrap_runtime() -> int:
    requirements = load_requirements()
    if os.environ.get("GH_ADDRESS_CR_DISABLE_LOCAL_SRC_RUNTIME") != "1":
        repo_root = Path(__file__).resolve().parents[2]
        src_root = repo_root / "src"
        if src_root.is_dir():
            sys.path.insert(0, str(src_root))

    try:
        import gh_address_cr as runtime
        from gh_address_cr import cli as runtime_cli
    except ModuleNotFoundError as exc:
        if exc.name and exc.name.startswith("gh_address_cr"):
            print(
                "gh-address-cr runtime package is missing. "
                "Install the `gh-address-cr` CLI package or run from a repository checkout with `src/` available.",
                file=sys.stderr,
            )
            return 127
        raise
    compatibility_rc = validate_runtime(runtime, runtime_cli, requirements)
    if compatibility_rc is not None:
        return compatibility_rc

    return runtime_cli.main()


if __name__ == "__main__":
    raise SystemExit(bootstrap_runtime())
