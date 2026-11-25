"""Build identity and reviewer evidence for the exact PR wheel."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tomllib
from email.parser import BytesParser
from pathlib import Path
from zipfile import ZipFile

from packaging.utils import canonicalize_name, parse_wheel_filename
from packaging.version import Version

PACKAGE = "gh-address-cr"


def version_for(base: str, pr: str, head: str) -> str:
    if not re.fullmatch(r"[1-9][0-9]*", pr) or not re.fullmatch(r"[a-f0-9]{40}", head):
        raise ValueError("Invalid PR identity")
    prefix = head[:7]
    if re.fullmatch(r"0[0-9]{6}", prefix):
        prefix = f"g{prefix}"
    parsed = Version(base)
    release = ".".join(map(str, parsed.release))
    epoch = f"{parsed.epoch}!" if parsed.epoch else ""
    return str(Version(f"{epoch}{release}.dev{pr}+{prefix}"))


def check_wheel(wheel: Path, expected: str) -> None:
    name, version, _, _ = parse_wheel_filename(wheel.name)
    if name != PACKAGE or str(version) != expected:
        raise ValueError("Wheel filename does not match the distribution or expected version")
    with ZipFile(wheel) as archive:
        [metadata] = [entry for entry in archive.namelist() if entry.endswith(".dist-info/METADATA")]
        fields = BytesParser().parsebytes(archive.read(metadata), headersonly=True)
    if canonicalize_name(fields["Name"] or "") != PACKAGE or fields["Version"] != expected:
        raise ValueError("Wheel METADATA does not match the distribution or expected version")


def checksum(wheel: Path) -> str:
    with wheel.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def seal(directory: Path, version: str, identity: dict[str, str]) -> dict[str, str]:
    [wheel] = directory.glob("*.whl")
    check_wheel(wheel, version)
    receipt = {
        **identity,
        "name": PACKAGE,
        "version": version,
        "file": wheel.name,
        "sha256": checksum(wheel),
    }
    (directory / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    (directory / "SHA256SUMS").write_text(f"{receipt['sha256']}  {wheel.name}\n")
    return receipt


def verify(directory: Path, expected: dict[str, str]) -> dict[str, str]:
    receipt = json.loads((directory / "receipt.json").read_text())
    if any(receipt[key] != value for key, value in expected.items()) or receipt["name"] != PACKAGE:
        raise ValueError("PR wheel receipt does not match the expected source")
    if version_for(receipt["version"], receipt["pr"], receipt["head"]) != receipt["version"]:
        raise ValueError("Wheel version does not match the PR and commit in the receipt")
    [wheel] = directory.glob("*.whl")
    if wheel.name != receipt["file"] or checksum(wheel) != receipt["sha256"]:
        raise ValueError("Wheel filename or SHA-256 does not match the receipt")
    if (directory / "SHA256SUMS").read_text() != f"{receipt['sha256']}  {wheel.name}\n":
        raise ValueError("Checksum file does not match the receipt")
    check_wheel(wheel, receipt["version"])
    return receipt


def card(receipt: dict[str, str], repository: str, artifact: str) -> str:
    sha, version, run, attempt, wheel, digest = (
        receipt[key] for key in ("head", "version", "runId", "attempt", "file", "sha256")
    )
    source = f"https://github.com/{repository}"
    return f"""## PR wheel · `{PACKAGE} {version}`

Commit [`{sha}`]({source}/commit/{sha}) · [CI run {run}]({source}/actions/runs/{run})
· packaging attempt `{attempt}` · artifact `{artifact}`

### Try this exact wheel

[Download the ZIP]({source}/actions/runs/{run}/artifacts/{artifact}) (14-day retention).
Sign in to GitHub with repository access. The commands below use Python 3.12 or newer.

```bash
preview_dir="$(mktemp -d)"
gh api repos/{repository}/actions/artifacts/{artifact}/zip > "$preview_dir/preview.zip" &&
  unzip -q "$preview_dir/preview.zip" -d "$preview_dir" &&
  cd "$preview_dir" &&
  printf '%s  %s\\n' '{digest}' '{wheel}' | shasum -a 256 -c -
```

Run the install after the checksum matches.

```bash
python3 -m venv "$preview_dir/venv"
"$preview_dir/venv/bin/python" -m pip install "$preview_dir/{wheel}"
"$preview_dir/venv/bin/gh-address-cr" --version
"$preview_dir/venv/bin/gh-address-cr" --help
```
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("version", "seal", "verify", "card"))
    parser.add_argument("directory", type=Path)
    parser.add_argument("--version")
    args = parser.parse_args()
    identity = {
        "pr": os.environ["PR_NUMBER"],
        "head": os.environ["PR_HEAD"],
        "runId": os.environ["GITHUB_RUN_ID"],
        "attempt": os.environ["GITHUB_RUN_ATTEMPT"],
    }
    if args.command == "version":
        manifest = tomllib.loads(Path("pyproject.toml").read_text())
        print(version_for(manifest["project"]["version"], identity["pr"], identity["head"]))
    elif args.command == "seal":
        seal(args.directory, args.version, identity)
    else:
        receipt = verify(args.directory, identity)
        if args.command == "card":
            print(card(receipt, os.environ["GITHUB_REPOSITORY"], os.environ["ARTIFACT_ID"]), end="")


if __name__ == "__main__":
    main()
