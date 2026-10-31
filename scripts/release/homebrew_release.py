"""Homebrew publication commands, run as python -m scripts.release.homebrew_release."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
import tomllib
import zipfile
from pathlib import Path
from urllib.parse import unquote

from scripts.release import homebrew_support as shared
from scripts.release.render_homebrew_formula import (
    DEFAULT_PYPI_BASE_URL,
    DEFAULT_PYTHON_DEPENDENCY,
    fetch_pypi_json,
    formula_class_name,
    render_formula,
    select_sdist_from_pypi,
)


def source_names(version: str) -> tuple[str, str]:
    stem = f"gh-address-cr-{version}.homebrew-source"
    return f"{stem}.rb", f"{stem}.json"


def load_snapshot(directory: Path) -> tuple[dict, Path]:
    files = list(directory.glob("*.homebrew-source.json"))
    if len(files) != 1:
        raise ValueError("expected exactly one formula snapshot")
    payload = json.loads(files[0].read_text())
    formula = files[0].with_suffix(".rb")
    shared.validate_snapshot(payload, formula.read_text(), version=payload["version"], commit=payload["commit"],
                             source_url=payload["source_url"], source_sha256=payload["source_sha256"])
    return payload, formula


def stage_formula(text: str, name: str = "gh-address-cr") -> Path:
    result = shared.command(["brew", "--repository", shared.TAP], check=False)
    if result.returncode:
        shared.command(["brew", "tap-new", shared.TAP, "--no-git"])
        result = shared.command(["brew", "--repository", shared.TAP])
    path = Path(result.stdout.strip()) / "Formula" / f"{name}.rb"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    # Trust only this locally staged formula, not every formula in the tap.
    shared.command(["brew", "trust", "--formula", f"{shared.TAP}/{name}"])
    return path


def stable_source(version: str) -> tuple[str, str, str]:
    shared.stable_version(version)
    shared.command(["git", "fetch", "--no-tags", "origin", f"refs/tags/v{version}:refs/tags/v{version}"])
    commit = shared.command(["git", "rev-parse", f"refs/tags/v{version}^{{commit}}"]).stdout.strip()
    project = tomllib.loads(shared.command(["git", "show", f"v{version}:pyproject.toml"]).stdout)
    if project["project"]["version"] != version:
        raise ValueError("release tag does not describe the requested package version")
    metadata = fetch_pypi_json("gh-address-cr", version, DEFAULT_PYPI_BASE_URL, 12, 10)
    url, sha = select_sdist_from_pypi(metadata, version)
    return commit, shared.public_url(url, {"files.pythonhosted.org"}), sha


def resolve_formula(*, version: str, commit: str, url: str, sha: str, name: str) -> tuple[dict, str]:
    formula = render_formula(class_name=formula_class_name(name), version=version, url=url, sha256=sha,
                             python_dependency=DEFAULT_PYTHON_DEPENDENCY,
                             conflicts_with=("gh-address-cr",) if name.endswith("-dev") else ())
    path = stage_formula(formula, name)
    # Only the first-party root bypasses the cooldown; dependency cooldowns stay enabled.
    shared.command(["brew", "update-python-resources", "--ignore-main-package-cooldown", f"{shared.TAP}/{name}"])
    payload = shared.make_snapshot(path.read_text(), version=version, commit=commit)
    return payload, shared.formula_text(payload)


def prepare(directory: Path, version: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    commit, url, sha = stable_source(version)
    assets = shared.ReleaseAssets(f"v{version}")
    names = assets.names()
    formula_name, metadata_name = source_names(version)
    if formula_name in names:
        formula = assets.download(formula_name, directory)
        payload = shared.make_snapshot(formula.read_text(), version=version, commit=commit)
        if metadata_name in names:
            payload = json.loads(assets.download(metadata_name, directory).read_text())
        shared.validate_snapshot(payload, formula.read_text(), version=version, commit=commit,
                                 source_url=url, source_sha256=sha)
    else:
        if metadata_name in names:
            raise ValueError("snapshot metadata exists without its immutable formula")
        payload, text = resolve_formula(version=version, commit=commit, url=url, sha=sha, name="gh-address-cr")
        (directory / formula_name).write_text(text, encoding="utf-8")
    shared.write_json(directory / metadata_name, payload)


def preserve_snapshot(directory: Path, version: str) -> None:
    payload, formula = load_snapshot(directory)
    commit, url, sha = stable_source(version)
    shared.validate_snapshot(payload, formula.read_text(), version=version, commit=commit,
                             source_url=url, source_sha256=sha)
    assets = shared.ReleaseAssets(f"v{version}")
    assets.upload(formula)
    assets.upload(formula.with_suffix(".json"))


def bottle_root(version: str) -> str:
    return f"https://github.com/{shared.REPOSITORY}/releases/download/v{shared.stable_version(version)}"


def build_record_name(version: str, target: str, rebuild: int) -> str:
    if target not in shared.TARGETS or rebuild < 0:
        raise ValueError("unsupported bottle target or rebuild")
    return f"gh-address-cr-{version}.{target}.bottle-r{rebuild}.json"


def bottle_entry(payload: dict, version: str, target: str, rebuild: int) -> dict:
    if set(payload) != {shared.FORMULA}:
        raise ValueError("bottle metadata describes a different formula")
    entry = payload[shared.FORMULA]
    bottle = entry["bottle"]
    if (entry["formula"]["pkg_version"] != version or bottle["root_url"] != bottle_root(version)
            or bottle["rebuild"] != rebuild or set(bottle["tags"]) != {shared.TARGETS[target]}):
        raise ValueError("bottle version, platform, root URL or rebuild differs")
    for row in bottle["tags"].values():
        if (not re.fullmatch(r"[a-f0-9]{64}", row["sha256"])
                or Path(row["local_filename"]).name != row["local_filename"]
                or not re.fullmatch(r"[a-zA-Z0-9_.+-]+", unquote(row["filename"]))
                or unquote(row["filename"]) in {".", ".."}):
            raise ValueError("unsafe bottle filename or checksum")
    return entry


def recovery_bundle(directory: Path, record_path: Path, filenames: list[str]) -> Path:
    """Seal one target atomically before exposing its individual assets."""
    path = directory / record_path.with_suffix(".zip").name
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        for name in sorted([record_path.name, *filenames]):
            archive.writestr(zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0)),
                             (directory / name).read_bytes())
    return path


def restore_bundle(bundle: Path, directory: Path, payload: dict, target: str, rebuild: int) -> None:
    record_name = build_record_name(payload["version"], target, rebuild)
    with zipfile.ZipFile(bundle) as archive:
        record = json.loads(archive.read(record_name))
        entry = bottle_entry(record["metadata"], payload["version"], target, rebuild)
        names = [unquote(row["filename"]) for row in entry["bottle"]["tags"].values()]
        if (record["formula_sha256"] != payload["formula_sha256"]
                or sorted(archive.namelist()) != sorted([record_name, *names])):
            raise ValueError("recovery bundle differs from the resource snapshot")
        for name in [record_name, *names]:
            (directory / name).write_bytes(archive.read(name))
        for row in entry["bottle"]["tags"].values():
            if shared.digest(directory / unquote(row["filename"])) != row["sha256"]:
                raise ValueError("recovery bottle checksum differs")


def validate_merged_bottles(spec: dict, expected: dict, *, version: str, rebuild: int) -> None:
    if (spec.get("rebuild") != rebuild or spec.get("root_url") != bottle_root(version)
            or set(spec.get("files", {})) != set(shared.TARGETS.values())
            or {tag: {key: row.get(key) for key in ("sha256", "url")}
                for tag, row in spec["files"].items()} != expected):
        raise ValueError("merged bottle specification differs from the four build records")


def build(directory: Path, snapshot_dir: Path, target: str, rebuild: int) -> None:
    payload, _ = load_snapshot(snapshot_dir)
    version = payload["version"]
    directory.mkdir(parents=True, exist_ok=True)
    record_name = build_record_name(version, target, rebuild)
    assets = shared.ReleaseAssets(f"v{version}")
    names = assets.names()
    bundle_name = Path(record_name).with_suffix(".zip").name
    if bundle_name in names:
        restore_bundle(assets.download(bundle_name, directory), directory, payload, target, rebuild)
        return
    if record_name in names:
        raise ValueError("published build record is missing its atomic recovery bundle")
    block = f'  bottle do\n    root_url "{bottle_root(version)}"\n    rebuild {rebuild}\n  end' if rebuild else ""
    stage_formula(shared.formula_text(payload, bottle_block=block))
    started = time.monotonic()
    shared.command(["brew", "install", "--only-dependencies", shared.FORMULA])
    dependency_seconds = time.monotonic() - started
    shared.command(["brew", "audit", "--formula", "--strict", shared.FORMULA])
    started = time.monotonic()
    installed = shared.command(["brew", "install", "--verbose", "--display-times", "--build-bottle", shared.FORMULA])
    (directory / "source-build.log").write_text(installed.stdout + installed.stderr)
    shared.command(["brew", "test", shared.FORMULA])
    shared.command(["brew", "linkage", "--test", shared.FORMULA])
    shared.command(["brew", "bottle", "--json",
                    "--keep-old" if rebuild else "--no-rebuild", "--root-url", bottle_root(version),
                    shared.FORMULA], cwd=directory)
    files = list(directory.glob("*.bottle.json"))
    if len(files) != 1:
        raise ValueError("expected one standard bottle metadata file")
    metadata = json.loads(files[0].read_text())
    entry = bottle_entry(metadata, version, target, rebuild)
    for row in entry["bottle"]["tags"].values():
        local = directory / row["local_filename"]
        if shared.digest(local) != row["sha256"]:
            raise ValueError("built bottle checksum differs")
        local.rename(directory / unquote(row["filename"]))
    shared.write_json(directory / record_name, {
        "target": target, "formula_sha256": payload["formula_sha256"], "metadata": metadata,
        "dependency_seconds": dependency_seconds, "build_seconds": time.monotonic() - started,
        "homebrew": shared.command(["brew", "--version"]).stdout.strip(),
        "build_configuration": shared.command(["brew", "config"]).stdout,
        "python": shared.command(["brew", "list", "--versions", payload["python_dependency"]]).stdout.strip(),
    })


def merge(directory: Path, snapshot_dir: Path, builds_dir: Path, rebuild: int) -> None:
    payload, source = load_snapshot(snapshot_dir)
    version = payload["version"]
    directory.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, directory / source.name)
    shutil.copy2(source.with_suffix(".json"), directory / source.with_suffix(".json").name)
    formula = stage_formula(shared.formula_text(payload))
    expected = {}
    json_paths = []
    for target in shared.TARGETS:
        matches = list(builds_dir.rglob(build_record_name(version, target, rebuild)))
        if len(matches) != 1:
            raise ValueError("missing or duplicate bottle build target")
        record = json.loads(matches[0].read_text())
        if record["target"] != target or record["formula_sha256"] != payload["formula_sha256"]:
            raise ValueError("bottle build snapshot differs")
        entry = bottle_entry(record["metadata"], version, target, rebuild)
        for row in entry["bottle"]["tags"].values():
            filename = unquote(row["filename"])
            path = matches[0].parent / filename
            if shared.digest(path) != row["sha256"]:
                raise ValueError("bottle asset differs from metadata")
            shutil.copy2(path, directory / filename)
        expected.update({
            tag: {"sha256": row["sha256"], "url": f"{bottle_root(version)}/{row['filename']}"}
            for tag, row in entry["bottle"]["tags"].items()
        })
        shared.write_json(directory / matches[0].name, record)
        # The standard merge command resolves the formula through this field.
        entry["formula"]["path"] = str(formula.relative_to(Path(
            shared.command(["brew", "--repository"]).stdout.strip()
        )))
        standard = directory / f"{target}.bottle.json"
        shared.write_json(standard, record["metadata"])
        json_paths.append(str(standard))
    shared.command(["brew", "bottle", "--merge", "--write", "--no-commit", "--no-all-checks", *json_paths])
    info = json.loads(shared.command(["brew", "info", "--json=v2", shared.FORMULA]).stdout)
    validate_merged_bottles(info["formulae"][0]["bottle"]["stable"], expected, version=version, rebuild=rebuild)
    text = formula.read_text()
    block_match = re.search(r"^  bottle do\n.*?^  end$", text, re.MULTILINE | re.DOTALL)
    if block_match is None:
        raise ValueError("Homebrew did not produce a bottle block")
    final = shared.formula_text(payload, bottle_block=block_match[0])
    if [line for line in text.splitlines() if line.strip()] != [
        line for line in final.splitlines() if line.strip()
    ]:
        raise ValueError("Homebrew merge changed source formula content")
    (directory / "gh-address-cr.rb").write_text(final, encoding="utf-8")
    shared.write_json(directory / "publication.json", {
        "version": version, "rebuild": rebuild, "source_formula_sha256": payload["formula_sha256"],
        "formula_sha256": shared.digest(directory / "gh-address-cr.rb"),
        "targets": list(shared.TARGETS),
    })


def publish_bottles(directory: Path, *, verify_only: bool = False) -> None:
    payload, _ = load_snapshot(directory)
    publication = json.loads((directory / "publication.json").read_text())
    if set(publication["targets"]) != set(shared.TARGETS):
        raise ValueError("publication is missing bottle targets")
    assets = shared.ReleaseAssets(f"v{payload['version']}")
    publish = assets.verify if verify_only else assets.upload
    for target in shared.TARGETS:
        path = directory / build_record_name(payload["version"], target, publication["rebuild"])
        record = json.loads(path.read_text())
        if record["formula_sha256"] != payload["formula_sha256"]:
            raise ValueError("bottle build snapshot differs")
        entry = bottle_entry(record["metadata"], payload["version"], target, publication["rebuild"])
        filenames = [unquote(row["filename"]) for row in entry["bottle"]["tags"].values()]
        # A single immutable upload is the recovery boundary. A retry restores
        # exact build bytes even when later individual uploads were interrupted.
        bundle = recovery_bundle(directory, path, filenames)
        publish(bundle)
        for row in entry["bottle"]["tags"].values():
            bottle = directory / unquote(row["filename"])
            if shared.digest(bottle) != row["sha256"]:
                raise ValueError("bottle asset checksum differs")
            publish(bottle)
        publish(path)
    suffix = f"r{publication['rebuild']}"
    for name in ("gh-address-cr.rb", "publication.json"):
        published = directory / f"gh-address-cr-{payload['version']}.{suffix}.{name}"
        shutil.copy2(directory / name, published)
        publish(published)


def verify(directory: Path, snapshot_dir: Path, target: str) -> None:
    payload, _ = load_snapshot(snapshot_dir)
    publication = json.loads((snapshot_dir / "publication.json").read_text())
    formula = snapshot_dir / "gh-address-cr.rb"
    if shared.digest(formula) != publication["formula_sha256"]:
        raise ValueError("final formula differs from publication")
    directory.mkdir(parents=True, exist_ok=True)
    # Exercise the upgrade from the currently published tap before staging the
    # candidate. On retry this can already be the requested version.
    shared.command(["brew", "tap", shared.TAP])
    shared.command(["brew", "install", shared.FORMULA])
    previous_python = shared.command(["brew", "list", "--versions", "python@3.14"]).stdout.strip()
    previous = shared.command(["gh-address-cr", "--version"]).stdout.strip()
    stage_formula(formula.read_text())
    started = time.monotonic()
    shared.command(["brew", "install", "--only-dependencies", shared.FORMULA])
    dependencies = time.monotonic() - started
    samples = []
    for cache_state in ("empty", "warm"):
        for iteration in range(3):
            if cache_state == "empty":
                cached = shared.command(["brew", "--cache", shared.FORMULA]).stdout.strip()
                cache_file = Path(cached)
                # Only remove this candidate's disposable download cache.
                if cache_file.is_file():
                    cache_file.unlink()
            started = time.monotonic()
            shared.command(["brew", "fetch", shared.FORMULA])
            download_seconds = time.monotonic() - started
            started = time.monotonic()
            verb = "upgrade" if cache_state == "empty" and iteration == 0 and previous != f"gh-address-cr {payload['version']}" else "reinstall"
            installed = shared.command(["brew", verb, "--verbose", "--display-times", shared.FORMULA])
            elapsed = time.monotonic() - started
            output = installed.stdout + installed.stderr
            if any(marker in output for marker in ("uv pip", "Building gh-address-cr", "pypi.org",
                                                    "pythonhosted.org", "pip install")):
                raise ValueError("bottle installation invoked an application build")
            prefix = Path(shared.command(["brew", "--prefix", shared.FORMULA]).stdout.strip())
            receipt = json.loads((prefix / "INSTALL_RECEIPT.json").read_text())
            if receipt.get("poured_from_bottle") is not True:
                raise ValueError("normal install did not use a matching bottle")
            samples.append({"cache": cache_state, "iteration": iteration + 1,
                            "download_seconds": download_seconds, "install_seconds": elapsed})
    shared.command(["brew", "test", shared.FORMULA])
    shared.command(["brew", "linkage", "--test", shared.FORMULA])
    prefix = Path(shared.command(["brew", "--prefix", shared.FORMULA]).stdout.strip())
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("GH_TOKEN", None)
    env.pop("GITHUB_TOKEN", None)
    env["GH_ADDRESS_CR_TEST_IN_PROCESS"] = "1"
    shared.command([str(prefix / "libexec/bin/python"), "-m", "scripts.release.verify_homebrew_install",
                    "--prefix", str(prefix), "--snapshot", str(load_snapshot(snapshot_dir)[1].with_suffix(".json")),
                    "--output", str(directory / "installed.json")], env=env)
    shared.command([str(prefix / "libexec/bin/python"), "-m", "unittest",
                    "tests.contract.test_agent_journey_contract"], env=env)
    # Reinstall exercises a changed Cellar installation without claiming that
    # the runner provided two different Python patch versions.
    started = time.monotonic()
    shared.command(["brew", "reinstall", "python@3.14"])
    python_reinstall_seconds = time.monotonic() - started
    shared.command(["brew", "linkage", "--test", shared.FORMULA])
    shared.command([str(prefix / "libexec/bin/python"), "-m", "scripts.release.verify_homebrew_install",
                    "--prefix", str(prefix), "--snapshot", str(load_snapshot(snapshot_dir)[1].with_suffix(".json")),
                    "--output", str(directory / "after-python-reinstall.json")], env=env)
    current_python = shared.command(["brew", "list", "--versions", "python@3.14"]).stdout.strip()
    tools = {
        "homebrew": shared.command(["brew", "--version"]).stdout.strip(),
        "python": shared.command([str(prefix / "libexec/bin/python"), "--version"]).stdout.strip(),
        "build_tools": shared.command(["brew", "config"]).stdout,
    }
    shared.write_json(directory / f"verify-{target}.json", {
        "target": target, "status": "passed", "formula_sha256": publication["formula_sha256"],
        "previous_version": previous, "dependency_seconds": dependencies, "samples": samples,
        "python_before": previous_python, "python_after": current_python,
        "python_upgraded": previous_python != current_python,
        "python_reinstall_seconds": python_reinstall_seconds,
        "tools": tools,
    })
    lines = [
        f"# Homebrew verification: {target}", "",
        f"Version: {payload['version']}; previous installation: {previous}.",
        f"System dependency installation: {dependencies:.3f} seconds.",
        f"Python changed during upgrade: {previous_python != current_python}.",
        "A false value means a Python-version upgrade was not exercised on this runner.", "",
        f"Python reinstall and subsequent runtime/linkage verification: {python_reinstall_seconds:.3f} seconds "
        "for reinstall; verification is separate.", "",
        "| Application cache | Trial | Download seconds | Install including unpack seconds |",
        "| --- | ---: | ---: | ---: |",
        *[f"| {row['cache']} | {row['iteration']} | {row['download_seconds']:.3f} | "
          f"{row['install_seconds']:.3f} |" for row in samples], "",
        "Three samples per cache state are observations, not a P95 estimate.",
        "Homebrew does not expose a separate stable unpack timer; installation includes unpack.",
        "Startup, dependency and local OTLP evidence are in installed.json.",
    ]
    (directory / "summary.md").write_text("\n".join(lines) + "\n")


def publish_tap(directory: Path, evidence: Path, checkout: Path) -> None:
    payload, _ = load_snapshot(directory)
    publication = json.loads((directory / "publication.json").read_text())
    formula = directory / "gh-address-cr.rb"
    if shared.digest(formula) != publication["formula_sha256"]:
        raise ValueError("final formula checksum differs")
    shared.require_all_targets([json.loads(path.read_text()) for path in evidence.rglob("verify-*.json")],
                               publication["formula_sha256"])
    # Recheck uploaded assets before exposing their URLs through the tap.
    publish_bottles(directory, verify_only=True)
    shared.update_tap(checkout, formula, name="gh-address-cr", version=payload["version"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["prepare", "preserve-snapshot", "build", "merge",
                                             "publish-bottles", "verify", "publish-tap"])
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--version")
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--builds", type=Path)
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--checkout", type=Path)
    parser.add_argument("--target", choices=shared.TARGETS)
    parser.add_argument("--rebuild", type=int, default=0)
    args = parser.parse_args()
    if args.rebuild < 0:
        parser.error("rebuild must be non-negative")
    required = {
        "prepare": ("version",), "preserve-snapshot": ("version",),
        "build": ("snapshot", "target"), "merge": ("snapshot", "builds"),
        "verify": ("snapshot", "target"), "publish-tap": ("evidence", "checkout"),
    }
    for field in required.get(args.operation, ()):
        if getattr(args, field) is None:
            parser.error(f"{args.operation} requires --{field}")
    shared.add_current_span_event("release.phase.started", {"release.phase": args.operation})
    operations = {
        "prepare": lambda: prepare(args.directory, args.version),
        "preserve-snapshot": lambda: preserve_snapshot(args.directory, args.version),
        "build": lambda: build(args.directory.resolve(), args.snapshot, args.target, args.rebuild),
        "merge": lambda: merge(args.directory.resolve(), args.snapshot, args.builds, args.rebuild),
        "publish-bottles": lambda: publish_bottles(args.directory),
        "verify": lambda: verify(args.directory, args.snapshot, args.target),
        "publish-tap": lambda: publish_tap(args.directory, args.evidence, args.checkout),
    }
    operations[args.operation]()
    shared.add_current_span_event("release.phase.completed", {"release.phase": args.operation})
    print(json.dumps({"status": "PASSED", "operation": args.operation}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(shared.traced_main(main))
    except (ValueError, KeyError, OSError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from None
