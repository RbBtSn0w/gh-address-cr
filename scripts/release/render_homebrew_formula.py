#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import urlopen


DEFAULT_PACKAGE_NAME = "gh-address-cr"
DEFAULT_PYPI_BASE_URL = "https://pypi.org/pypi/"
DEFAULT_PYTHON_DEPENDENCY = "python@3.14"
DEFAULT_PYTHON_RESOURCES = (
    {
        "name": "packaging",
        "url": "https://files.pythonhosted.org/packages/d7/f1/e7a6dd94a8d4a5626c03e4e99c87f241ba9e350cd9e6d75123f992427270/packaging-26.2.tar.gz",
        "sha256": "ff452ff5a3e828ce110190feff1178bb1f2ea2281fa2075aadb987c2fb221661",
    },
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render the gh-address-cr Homebrew formula from PyPI sdist metadata.")
    parser.add_argument("--version", required=True, help="Released package version without a leading v.")
    parser.add_argument("--package-name", default=DEFAULT_PACKAGE_NAME, help="PyPI package name.")
    parser.add_argument("--pypi-base-url", default=DEFAULT_PYPI_BASE_URL, help="Base PyPI JSON URL.")
    parser.add_argument("--pypi-json", type=Path, help="Read PyPI JSON from a local fixture instead of the network.")
    parser.add_argument("--sdist-path", type=Path, help="Use a local sdist path for render smoke validation.")
    parser.add_argument("--sdist-url", help="Use an explicit sdist URL.")
    parser.add_argument("--sha256", help="SHA-256 for --sdist-url.")
    parser.add_argument("--output", type=Path, required=True, help="Formula output path.")
    parser.add_argument("--retries", type=int, default=1, help="PyPI JSON fetch attempts.")
    parser.add_argument("--retry-delay", type=float, default=5.0, help="Seconds between PyPI JSON fetch attempts.")
    parser.add_argument("--python-dependency", default=DEFAULT_PYTHON_DEPENDENCY, help="Homebrew Python dependency.")
    return parser.parse_args()


def validate_version(version: str) -> str:
    if version.startswith("v"):
        raise SystemExit("version must not include a leading v")
    if not re.match(r"^[0-9]+(?:\.[0-9]+)*(?:[a-zA-Z0-9_.!+-]+)?$", version):
        raise SystemExit(f"unsupported version: {version}")
    return version


def validate_sha256(value: str) -> str:
    normalized = value.lower()
    if not SHA256_RE.match(normalized):
        raise SystemExit(f"unsupported sha256: {value}")
    return normalized


def read_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise SystemExit("PyPI JSON must be an object")
    return payload


def fetch_pypi_json(package_name: str, version: str, base_url: str, retries: int, retry_delay: float) -> dict:
    if retries < 1:
        raise SystemExit("retries must be at least 1")

    url = urljoin(base_url.rstrip("/") + "/", f"{package_name}/{version}/json")
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            with urlopen(url, timeout=30) as response:
                payload = json.load(response)
            if not isinstance(payload, dict):
                raise SystemExit("PyPI JSON must be an object")
            return payload
        except (HTTPError, URLError, OSError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(retry_delay)

    raise SystemExit(f"failed to fetch PyPI metadata for {package_name} {version}: {last_error}")


def select_sdist_from_pypi(payload: dict, version: str) -> tuple[str, str]:
    info = payload.get("info") or {}
    payload_version = str(info.get("version") or version)
    if payload_version != version:
        raise SystemExit(f"PyPI metadata version {payload_version} does not match {version}")

    urls = payload.get("urls")
    if not isinstance(urls, list):
        raise SystemExit("PyPI metadata missing urls array")

    sdists = [item for item in urls if isinstance(item, dict) and item.get("packagetype") == "sdist"]
    if not sdists:
        raise SystemExit(f"expected at least one sdist for {version}")

    sdist = next((item for item in sdists if str(item.get("url") or "").endswith(".tar.gz")), sdists[0])
    url = str(sdist.get("url") or "")
    sha256 = str((sdist.get("digests") or {}).get("sha256") or "")
    if not url:
        raise SystemExit("sdist metadata missing url")
    return url, validate_sha256(sha256)


def source_from_local_sdist(path: Path) -> tuple[str, str]:
    if not path.is_file():
        raise SystemExit(f"sdist does not exist: {path}")
    sha256_hash = hashlib.sha256()
    with path.open("rb") as handle:
        for byte_block in iter(lambda: handle.read(1024 * 1024), b""):
            sha256_hash.update(byte_block)
    digest = sha256_hash.hexdigest()
    return path.resolve().as_uri(), digest


def formula_class_name(package_name: str) -> str:
    parts = re.split(r"[-_.]+", package_name)
    return "".join(part.capitalize() for part in parts if part)


def render_resources(resources: tuple[dict[str, str], ...]) -> str:
    blocks = []
    for resource in resources:
        blocks.append(
            f'''  resource "{resource["name"]}" do
    url "{resource["url"]}"
    sha256 "{resource["sha256"]}"
  end'''
        )
    return "\n\n".join(blocks)


def render_formula(
    *,
    class_name: str,
    url: str,
    sha256: str,
    python_dependency: str,
    resources: tuple[dict[str, str], ...] = DEFAULT_PYTHON_RESOURCES,
) -> str:
    resource_blocks = render_resources(resources)
    return f'''class {class_name} < Formula
  include Language::Python::Virtualenv

  desc "Deterministic PR review-resolution control plane runtime"
  homepage "https://github.com/RbBtSn0w/gh-address-cr"
  url "{url}"
  sha256 "{sha256}"
  license "MIT"

  depends_on "{python_dependency}"

{resource_blocks}

  def install
    virtualenv_install_with_resources using: "{python_dependency}"
  end

  test do
    assert_match version.to_s, shell_output("#{{bin}}/gh-address-cr --version")
    assert_match "\\"runtime_version\\"", shell_output("#{{bin}}/gh-address-cr agent manifest")
  end
end
'''


def resolve_source(args: argparse.Namespace) -> tuple[str, str]:
    explicit_count = sum(
        1
        for enabled in (
            args.pypi_json is not None,
            args.sdist_path is not None,
            args.sdist_url is not None or args.sha256 is not None,
        )
        if enabled
    )
    if explicit_count > 1:
        raise SystemExit("choose only one source: --pypi-json, --sdist-path, or --sdist-url/--sha256")
    if (args.sdist_url is None) != (args.sha256 is None):
        raise SystemExit("--sdist-url and --sha256 must be provided together")

    if args.pypi_json is not None:
        return select_sdist_from_pypi(read_json(args.pypi_json), args.version)
    if args.sdist_path is not None:
        return source_from_local_sdist(args.sdist_path)
    if args.sdist_url is not None and args.sha256 is not None:
        return args.sdist_url, validate_sha256(args.sha256)
    return select_sdist_from_pypi(
        fetch_pypi_json(args.package_name, args.version, args.pypi_base_url, args.retries, args.retry_delay),
        args.version,
    )


def main() -> int:
    args = parse_args()
    args.version = validate_version(args.version)

    url, sha256 = resolve_source(args)
    formula = render_formula(
        class_name=formula_class_name(args.package_name),
        url=url,
        sha256=sha256,
        python_dependency=args.python_dependency,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(formula, encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "RENDERED",
                "version": args.version,
                "url": url,
                "sha256": sha256,
                "resources": [resource["name"] for resource in DEFAULT_PYTHON_RESOURCES],
                "output": str(args.output),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
