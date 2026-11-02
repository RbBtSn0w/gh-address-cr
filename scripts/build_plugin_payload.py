#!/usr/bin/env python3
"""Build the repo-local Codex plugin payload for gh-address-cr."""

from __future__ import annotations

import argparse
import binascii
import json
import re
import shutil
import struct
import sys
import tempfile
import zipfile
import zlib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "skill"
DEFAULT_OUTPUT_ROOT = ROOT / "dist" / "plugin" / "gh-address-cr"
PYPROJECT = ROOT / "pyproject.toml"

EXCLUDED_DIRS = {
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".state",
    "dist",
    "build",
    "node_modules",
    ".venv",
    "venv",
    ".git",
    ".mypy_cache",
}
EXCLUDED_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".log",
}
SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
TEXT_SUFFIXES = {".md", ".json", ".yaml", ".yml"}
UNSAFE_CONTENT = re.compile(
    r"(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|"
    r"sk-[A-Za-z0-9_-]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY-----|"
    r"(?<![A-Za-z0-9:/])/(?:Users|home|private|tmp|var|opt|etc)/|(?<![A-Za-z0-9])[A-Za-z]:[\\/])"
)
SECRET_KEYS = {"api_key", "apikey", "token", "access_token", "password", "secret", "credentials"}


def validate_metadata(value: object) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str) or key.lower().replace("-", "_") in SECRET_KEYS:
                raise ValueError("Unsafe metadata key in plugin payload")
            validate_metadata(child)
    elif isinstance(value, list):
        for child in value:
            validate_metadata(child)
    elif isinstance(value, str) and (
        value.startswith(("/", "~", "file:", "../", "..\\")) or UNSAFE_CONTENT.search(value)
    ):
        raise ValueError("Unsafe local path or credential in plugin metadata")


def validate_text(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if UNSAFE_CONTENT.search(text):
        raise ValueError("Unsafe local path or credential in plugin payload")
    metadata = None
    try:
        if path.suffix == ".json":
            metadata = json.loads(text)
        elif path.suffix in {".yaml", ".yml"}:
            metadata = load_yaml(text)
        elif path.name == "SKILL.md":
            if not text.startswith("---\n") or "\n---\n" not in text[4:]:
                raise ValueError("Missing SKILL.md frontmatter")
            metadata = load_yaml(text.split("\n---\n", 1)[0][4:])
    except (yaml.YAMLError, json.JSONDecodeError) as exc:
        raise ValueError("Malformed plugin metadata") from exc
    if path.suffix != ".md" or path.name == "SKILL.md":
        if not isinstance(metadata, dict):
            raise ValueError("Plugin metadata must be an object")
        validate_metadata(metadata)


def load_yaml(text: str) -> object:
    if any(isinstance(token, yaml.tokens.AliasToken) for token in yaml.scan(text)):
        raise ValueError("YAML aliases are not supported in plugin metadata")
    return yaml.safe_load(text)


def validate_tree(root: Path, *, source: bool) -> None:
    if root.is_symlink():
        raise ValueError("Symlinks are not allowed in plugin payloads")
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if path.is_symlink():
            raise ValueError("Symlinks are not allowed in plugin payloads")
        if source and should_exclude(relative):
            continue
        if any("\\" in part or ":" in part or part in {".", ".."} for part in relative.parts):
            raise ValueError("Unsafe plugin member path")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError("Plugin payload members must be regular files")
        if path.suffix in TEXT_SUFFIXES:
            validate_text(path)
        elif source or relative.as_posix() not in {"assets/icon.png", "assets/logo.png", "assets/screenshot-1.png"}:
            raise ValueError("Unsupported file in plugin payload")


def pyproject_version(pyproject_path: Path | None = None) -> str:
    match = re.search(r'^version = "([^"]+)"$', (pyproject_path or PYPROJECT).read_text(encoding="utf-8"), re.MULTILINE)
    if not match:
        raise SystemExit("Unable to resolve version from pyproject.toml")
    return match.group(1)


def should_exclude(path: Path) -> bool:
    return any(part in EXCLUDED_DIRS for part in path.parts) or path.suffix in EXCLUDED_SUFFIXES


def copy_skill_payload(destination: Path, source_root: Path | None = None) -> None:
    source_root = source_root or SKILL_ROOT
    validate_tree(source_root, source=True)
    def ignore(directory: str, names: list[str]) -> set[str]:
        ignored: set[str] = set()
        base = Path(directory)
        for name in names:
            candidate = base / name
            relative = candidate.relative_to(source_root) if candidate.is_relative_to(source_root) else Path(name)
            if should_exclude(relative):
                ignored.add(name)
        return ignored

    shutil.copytree(source_root, destination, ignore=ignore)


def png_bytes(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        payload = kind + data
        return struct.pack(">I", len(data)) + payload + struct.pack(">I", binascii.crc32(payload) & 0xFFFFFFFF)

    row = b"\x00" + bytes(rgb) * width
    raw = row * height
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(
        b"IDAT", zlib.compress(raw)
    ) + chunk(b"IEND", b"")


def write_assets(assets_dir: Path) -> None:
    assets_dir.mkdir(parents=True, exist_ok=True)
    assets = {
        "icon.png": png_bytes(256, 256, (16, 163, 127)),
        "logo.png": png_bytes(512, 512, (16, 163, 127)),
        "screenshot-1.png": png_bytes(1280, 720, (24, 35, 47)),
    }
    for filename, data in assets.items():
        (assets_dir / filename).write_bytes(data)


def manifest(pyproject_path: Path | None = None) -> dict:
    return {
        "$schema": SCHEMA,
        "name": "gh-address-cr",
        "version": pyproject_version(pyproject_path),
        "description": "Deterministic PR review-resolution control plane for AI coding agents.",
        "author": {
            "name": "rbbtsn0w",
            "url": "https://github.com/RbBtSn0w",
        },
        "homepage": "https://github.com/RbBtSn0w/gh-address-cr",
        "repository": "https://github.com/RbBtSn0w/gh-address-cr",
        "license": "MIT",
        "keywords": ["ai-agent", "codex", "github", "pull-request", "code-review"],
        "extensions": {"com.openai": {"interface": {
            "displayName": "GH Address CR",
            "shortDescription": "Resolve PR reviews safely",
            "longDescription": (
                "Packages the gh-address-cr skill for Codex. The skill delegates state, GitHub side effects, "
                "leases, evidence, and final-gate checks to the deterministic gh-address-cr runtime CLI."
            ),
            "developerName": "rbbtsn0w",
            "category": "Developer Tools",
            "capabilities": ["Read", "Write"],
            "websiteURL": "https://github.com/RbBtSn0w/gh-address-cr",
            "privacyPolicyURL": "https://github.com/RbBtSn0w/gh-address-cr/blob/main/PRIVACY.md",
            "termsOfServiceURL": "https://github.com/RbBtSn0w/gh-address-cr/blob/main/TERMS.md",
            "defaultPrompt": [
                "Use GH Address CR to handle this PR review.",
                "Run final-gate proof for this pull request.",
                "Resolve stale PR review threads safely.",
            ],
            "brandColor": "#10A37F",
            "composerIcon": "./assets/icon.png",
            "logo": "./assets/logo.png",
            "screenshots": ["./assets/screenshot-1.png"],
        }}},
    }


def build_payload(destination: Path, *, source_root: Path | None = None, pyproject_path: Path | None = None) -> None:
    (destination / ".codex-plugin").mkdir(parents=True, exist_ok=True)
    copy_skill_payload(destination / "skills" / "gh-address-cr", source_root)
    write_assets(destination / "assets")
    root_manifest = manifest(pyproject_path)
    manifest_text = json.dumps(root_manifest, indent=2, ensure_ascii=False) + "\n"
    (destination / "plugin.json").write_text(manifest_text, encoding="utf-8")
    overlay = {**root_manifest, "skills": "./skills/", "interface": root_manifest["extensions"]["com.openai"]["interface"]}
    (destination / ".codex-plugin" / "plugin.json").write_text(
        json.dumps(overlay, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    validate_payload(destination, pyproject_path=pyproject_path)


def validate_manifest_structure(root: dict, expected_version: str) -> dict:
    if (root.get("$schema") != SCHEMA or root.get("name") != "gh-address-cr" or
            root.get("version") != expected_version or "skills" in root or "interface" in root):
        raise ValueError("Plugin manifest identity or version does not match the expected contract")
    for key in ("description", "homepage", "repository", "license"):
        if not isinstance(root.get(key), str) or not root[key]:
            raise ValueError("Plugin manifest is missing required metadata")
    extensions = root.get("extensions")
    if not isinstance(extensions, dict) or "com.openai.interface" in extensions:
        raise ValueError("Plugin manifest must use the com.openai extension namespace")
    namespace = extensions.get("com.openai")
    interface = namespace.get("interface") if isinstance(namespace, dict) else None
    if not isinstance(interface, dict):
        raise ValueError("Plugin manifest is missing its OpenAI interface")
    for key in ("displayName", "shortDescription", "composerIcon", "logo"):
        if not isinstance(interface.get(key), str) or not interface[key]:
            raise ValueError("Plugin interface is missing required metadata")
    screenshots = interface.get("screenshots")
    if not isinstance(screenshots, list) or not all(isinstance(item, str) for item in screenshots):
        raise ValueError("Plugin screenshots must be a list of relative paths")
    return interface


def validate_payload(
    payload_root: Path, *, pyproject_path: Path | None = None, expected_version: str | None = None,
) -> None:
    """Reject unsafe files and inconsistent generated manifests before distribution."""
    validate_tree(payload_root, source=False)
    for path in payload_root.rglob("*"):
        relative = path.relative_to(payload_root).as_posix()
        if path.is_file() and not (
            relative in {"plugin.json", ".codex-plugin/plugin.json", "assets/icon.png", "assets/logo.png",
                         "assets/screenshot-1.png"} or relative.startswith("skills/gh-address-cr/")
        ):
            raise ValueError("Unexpected file outside the plugin payload boundary")
    root = json.loads((payload_root / "plugin.json").read_text(encoding="utf-8"))
    overlay = json.loads((payload_root / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    version = pyproject_version(pyproject_path) if expected_version is None else expected_version
    interface = validate_manifest_structure(root, version)
    if expected_version is None and root != manifest(pyproject_path):
        raise ValueError("Plugin manifest does not match the generated contract")
    if overlay != {**root, "skills": "./skills/", "interface": interface}:
        raise ValueError("Plugin manifests do not match the generated contract")
    for raw_path in [overlay["skills"], interface["composerIcon"], interface["logo"], *interface["screenshots"]]:
        if not raw_path.startswith("./") or ".." in Path(raw_path).parts or not (payload_root / raw_path).exists():
            raise ValueError("Missing or unsafe plugin asset path")
    if not (payload_root / "skills" / "gh-address-cr" / "SKILL.md").is_file():
        raise ValueError("Plugin skill payload was not generated")


def write_archive(
    payload_root: Path, archive_path: Path, *, pyproject_path: Path | None = None, expected_version: str | None = None,
) -> None:
    """Write a validated, reproducible ZIP with a gh-address-cr enclosing directory."""
    validate_payload(payload_root, pyproject_path=pyproject_path, expected_version=expected_version)
    validate_output_path(archive_path)
    if archive_path.resolve().is_relative_to(payload_root.resolve()) or archive_path.is_symlink():
        raise ValueError("Archive must be outside the plugin payload and not a symlink")
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_STORED) as archive:
        for path in sorted(payload_root.rglob("*")):
            if not path.is_file():
                continue
            info = zipfile.ZipInfo("gh-address-cr/" + path.relative_to(payload_root).as_posix(), (1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())


def output_path(raw_path: Path) -> Path:
    if raw_path.is_absolute():
        return raw_path
    return ROOT / raw_path


def validate_output_path(path: Path) -> None:
    resolved = path.resolve()
    if path.is_symlink() or ROOT.is_relative_to(resolved):
        raise ValueError("Output must not overwrite repository files or a symlink")
    protected = [ROOT / name for name in ("skill", "src", "scripts", "tests", "docs", ".git", ".github", ".agents", ".venv")]
    protected.extend(path for path in ROOT.iterdir() if path.is_file())
    if any(resolved.is_relative_to(path) or path.is_relative_to(resolved) for path in protected):
        raise ValueError("Output must not overwrite repository source files")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the gh-address-cr Codex plugin payload.")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Directory where the plugin payload should be generated.",
    )
    parser.add_argument("--check", action="store_true", help="Verify the plugin payload can be generated.")
    parser.add_argument("--archive", type=Path, help="Write a deterministic ZIP archive of the plugin payload.")
    args = parser.parse_args(argv)
    if args.check and args.archive:
        parser.error("--check cannot be combined with --archive")

    with tempfile.TemporaryDirectory() as temp_dir:
        expected_root = Path(temp_dir) / "gh-address-cr"
        build_payload(expected_root)
        if args.check:
            if not (expected_root / ".codex-plugin" / "plugin.json").exists():
                print("plugin payload manifest was not generated", file=sys.stderr)
                return 1
            if not (expected_root / "skills" / "gh-address-cr" / "SKILL.md").exists():
                print("plugin skill payload was not generated", file=sys.stderr)
                return 1
            print("plugin payload can be generated")
            return 0

        destination = output_path(args.output)
        validate_output_path(destination)
        resolved = destination.resolve()
        archive_path = output_path(args.archive) if args.archive else None
        if archive_path and (archive_path.resolve().is_relative_to(resolved) or archive_path.is_symlink()):
            raise ValueError("Archive must be outside the plugin payload and not a symlink")
        if destination.exists():
            shutil.rmtree(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(expected_root, destination)
        if archive_path:
            write_archive(destination, archive_path)
        display_path = destination.relative_to(ROOT) if destination.is_relative_to(ROOT) else destination
        print(f"built plugin payload at {display_path}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
