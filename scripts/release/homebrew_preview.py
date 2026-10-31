"""Trusted preview publisher; PR artifacts are data, never helper code."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from scripts.release import homebrew_release as release
from scripts.release import homebrew_support as shared


def validate_input(directory: Path, run_id: int) -> tuple[dict, Path]:
    metadata = json.loads((directory / "preview.json").read_text())
    if not isinstance(metadata.get("pr"), int) or metadata["pr"] < 1:
        raise ValueError("invalid preview PR")
    run = shared.github_json(f"repos/{shared.REPOSITORY}/actions/runs/{run_id}")
    pr = shared.github_json(f"repos/{shared.REPOSITORY}/pulls/{metadata['pr']}")
    shared.validate_preview(run, pr, metadata, run_id=run_id)
    name = shared.preview_asset_name(metadata["pr"], metadata["head_sha"], run_id, metadata["run_attempt"])
    source = directory / name
    if (metadata.get("source_name") != name or source.is_symlink() or not source.is_file()
            or shared.digest(source) != metadata.get("source_sha256")):
        raise ValueError("preview source artifact differs from its validated identity")
    metadata["source_url"] = f"https://github.com/{shared.REPOSITORY}/releases/download/pr-preview/{name}"
    return metadata, source


def inspect(directory: Path, output: Path, run_id: int) -> None:
    metadata, source = validate_input(directory, run_id)
    output.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, output / source.name)
    shared.write_json(output / "preview.json", metadata)


def publish_source(directory: Path, run_id: int) -> None:
    _metadata, source = validate_input(directory, run_id)
    probe = shared.command(["gh", "api", f"repos/{shared.REPOSITORY}/releases/tags/pr-preview"], check=False)
    if probe.returncode:
        if "HTTP 404" not in probe.stderr:
            raise ValueError("cannot determine whether the preview release exists")
        shared.command(["gh", "release", "create", "pr-preview", "--repo", shared.REPOSITORY,
                        "--prerelease", "--title", "PR Preview Builds",
                        "--notes", "Immutable source packages for validated PR development previews."])
    shared.ReleaseAssets("pr-preview").upload(source)


def prepare(directory: Path, output: Path, run_id: int) -> None:
    metadata, _source = validate_input(directory, run_id)
    payload, text = release.resolve_formula(
        version=metadata["version"], commit=metadata["head_sha"], url=metadata["source_url"],
        sha=metadata["source_sha256"], name="gh-address-cr-dev",
    )
    output.mkdir(parents=True, exist_ok=True)
    stem = f"gh-address-cr-{metadata['version']}.homebrew-source"
    (output / f"{stem}.rb").write_text(text, encoding="utf-8")
    shared.write_json(output / f"{stem}.json", payload)
    shared.write_json(output / "preview.json", metadata)
    full_name = f"{shared.TAP}/gh-address-cr-dev"
    release.stage_formula(text, "gh-address-cr-dev")
    shared.command(["brew", "install", "--verbose", "--display-times", "--build-from-source", full_name])
    shared.command(["brew", "test", full_name])
    shared.command(["brew", "linkage", "--test", full_name])
    prefix = Path(shared.command(["brew", "--prefix", full_name]).stdout.strip())
    env = os.environ.copy()
    for key in ("GH_TOKEN", "GITHUB_TOKEN", "PYTHONPATH"):
        env.pop(key, None)
    env["GH_ADDRESS_CR_TEST_IN_PROCESS"] = "1"
    shared.command([str(prefix / "libexec/bin/python"), "-m", "scripts.release.verify_homebrew_install",
                    "--prefix", str(prefix), "--snapshot", str(output / f"{stem}.json"),
                    "--output", str(output / "installed.json")], env=env)
    shared.command([str(prefix / "libexec/bin/python"), "-m", "unittest",
                    "tests.contract.test_agent_journey_contract"], env=env)


def publish(directory: Path, input_dir: Path, checkout: Path, run_id: int) -> None:
    metadata, _source = validate_input(input_dir, run_id)
    payload, formula = release.load_snapshot(directory)
    expected = {
        "version": metadata["version"], "commit": metadata["head_sha"],
        "source_url": metadata["source_url"], "source_sha256": metadata["source_sha256"],
    }
    shared.validate_snapshot(payload, formula.read_text(), **expected)
    if payload["formula_name"] != "gh-address-cr-dev":
        raise ValueError("preview attempted to update another formula")
    shared.update_tap(checkout, formula, name="gh-address-cr-dev", version=metadata["version"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["inspect", "publish-source", "prepare", "publish"])
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--checkout", type=Path)
    parser.add_argument("--run-id", type=int, required=True)
    args = parser.parse_args()
    required = {"inspect": ("output",), "prepare": ("output",), "publish": ("input", "checkout")}
    for key in required.get(args.operation, ()):
        if getattr(args, key) is None:
            parser.error(f"{args.operation} requires --{key}")
    shared.add_current_span_event("release.phase.started", {"release.phase": args.operation})
    if args.operation == "inspect":
        inspect(args.directory, args.output, args.run_id)
    elif args.operation == "publish-source":
        publish_source(args.directory, args.run_id)
    elif args.operation == "prepare":
        prepare(args.directory, args.output, args.run_id)
    else:
        publish(args.directory, args.input, args.checkout, args.run_id)
    shared.add_current_span_event("release.phase.completed", {"release.phase": args.operation})
    print(json.dumps({"status": "PASSED", "operation": args.operation}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(shared.traced_main(main))
    except (ValueError, KeyError, OSError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from None
