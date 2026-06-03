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
import zlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "skill"
PLUGIN_ROOT = ROOT / "plugin" / "gh-address-cr"
PLUGIN_SKILL_ROOT = PLUGIN_ROOT / "skills" / "gh-address-cr"
PYPROJECT = ROOT / "pyproject.toml"

EXCLUDED_DIRS = {
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".state",
    "dist",
    "build",
}
EXCLUDED_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".log",
}


def pyproject_version() -> str:
    match = re.search(r'^version = "([^"]+)"$', PYPROJECT.read_text(encoding="utf-8"), re.MULTILINE)
    if not match:
        raise SystemExit("Unable to resolve version from pyproject.toml")
    return match.group(1)


def should_exclude(path: Path) -> bool:
    return any(part in EXCLUDED_DIRS for part in path.parts) or path.suffix in EXCLUDED_SUFFIXES


def copy_skill_payload(destination: Path) -> None:
    def ignore(directory: str, names: list[str]) -> set[str]:
        ignored: set[str] = set()
        base = Path(directory)
        for name in names:
            candidate = base / name
            relative = candidate.relative_to(SKILL_ROOT) if candidate.is_relative_to(SKILL_ROOT) else Path(name)
            if should_exclude(relative):
                ignored.add(name)
        return ignored

    shutil.copytree(SKILL_ROOT, destination, ignore=ignore)


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


def manifest() -> dict:
    return {
        "name": "gh-address-cr",
        "version": pyproject_version(),
        "description": "Deterministic PR review-resolution control plane for AI coding agents.",
        "author": {
            "name": "rbbtsn0w",
            "url": "https://github.com/RbBtSn0w",
        },
        "homepage": "https://github.com/RbBtSn0w/gh-address-cr",
        "repository": "https://github.com/RbBtSn0w/gh-address-cr",
        "license": "MIT",
        "keywords": ["ai-agent", "codex", "github", "pull-request", "code-review"],
        "skills": "./skills/",
        "interface": {
            "displayName": "GH Address CR",
            "shortDescription": "Resolve PR review threads with evidence and a final gate.",
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
        },
    }


def build_payload(destination: Path) -> None:
    (destination / ".codex-plugin").mkdir(parents=True, exist_ok=True)
    copy_skill_payload(destination / "skills" / "gh-address-cr")
    write_assets(destination / "assets")
    manifest_text = json.dumps(manifest(), indent=2, ensure_ascii=False) + "\n"
    (destination / "plugin.json").write_text(manifest_text, encoding="utf-8")
    (destination / ".codex-plugin" / "plugin.json").write_text(manifest_text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the gh-address-cr Codex plugin payload.")
    parser.add_argument(
        "--output",
        type=Path,
        default=PLUGIN_ROOT,
        help="Directory where the plugin payload should be generated.",
    )
    parser.add_argument("--check", action="store_true", help="Verify the plugin payload can be generated.")
    args = parser.parse_args(argv)

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

        destination = args.output
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(expected_root, destination)
        display_path = destination.relative_to(ROOT) if destination.is_relative_to(ROOT) else destination
        print(f"built plugin payload at {display_path}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
