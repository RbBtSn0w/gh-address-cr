"""Shared release boundaries; never reads or writes PR-session state."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from opentelemetry.trace import NoOpTracer, SpanKind, Status, StatusCode
from packaging.version import InvalidVersion, Version

from gh_address_cr.otel_tracing import (
    DEVELOPMENT_TRACES_ENDPOINT,
    add_current_span_event,
    initialize_telemetry,
    run_traced,
    shutdown_telemetry,
    start_child_span,
)
from scripts.release.render_homebrew_formula import formula_class_name, render_formula

REPOSITORY = "RbBtSn0w/gh-address-cr"
TAP_REPOSITORY = "RbBtSn0w/homebrew-tap"
TAP = "rbbtsn0w/tap"
FORMULA = f"{TAP}/gh-address-cr"
TARGETS = {
    "macos-15": "arm64_sequoia",
    "macos-15-intel": "sequoia",
    "macos-26": "arm64_tahoe",
    "macos-26-intel": "tahoe",
}
RESOURCE_RE = re.compile(
    r'^  resource "([a-z0-9]+(?:-[a-z0-9]+)*)" do\n'
    r'    url "([^"\n]+)"\n'
    r'    sha256 "([a-f0-9]{64})"\n'
    r"  end\n",
    re.MULTILINE,
)


def digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def stable_version(value: str) -> str:
    if not re.fullmatch(r"\d+\.\d+\.\d+", value):
        raise ValueError("expected a stable major.minor.patch version")
    return value


def public_url(value: str, hosts: set[str]) -> str:
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or parsed.hostname not in hosts or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.port not in (None, 443)
            or any(token in value for token in ('"', "\\", "\n", "\r", "#{"))):
        raise ValueError("expected an immutable public HTTPS source URL")
    return value


def _field(text: str, name: str) -> str:
    matches = re.findall(rf'^  {name} "([^"\n]+)"$', text, re.MULTILINE)
    if len(matches) != 1:
        raise ValueError(f"formula must have exactly one {name}")
    return matches[0]


def parse_resources(text: str) -> list[dict[str, str]]:
    rows = [{"name": name, "url": public_url(url, {"files.pythonhosted.org"}), "sha256": sha}
            for name, url, sha in RESOURCE_RE.findall(text)]
    if ("RESOURCE-ERROR" in text or not rows or len(rows) != text.count('  resource "')
            or len({row["name"] for row in rows}) != len(rows)):
        raise ValueError("missing, malformed or duplicate resource")
    return rows


def formula_text(snapshot: dict, *, bottle_block: str = "") -> str:
    name = snapshot["formula_name"]
    if name not in {"gh-address-cr", "gh-address-cr-dev"}:
        raise ValueError("unsupported release formula")
    return render_formula(
        class_name=formula_class_name(name), url=snapshot["source_url"], sha256=snapshot["source_sha256"],
        version=snapshot["version"], python_dependency=snapshot["python_dependency"],
        resources=tuple(snapshot["resources"]), bottle_block=bottle_block,
        conflicts_with=("gh-address-cr",) if name.endswith("-dev") else (),
    )


def make_snapshot(text: str, *, version: str, commit: str) -> dict:
    if not re.fullmatch(r"[a-f0-9]{40}", commit):
        raise ValueError("snapshot needs the source commit")
    classes = re.findall(r"^class (GhAddressCr(?:Dev)?) < Formula$", text, re.MULTILINE)
    if len(classes) != 1:
        raise ValueError("unsupported formula class")
    name = "gh-address-cr-dev" if classes[0].endswith("Dev") else "gh-address-cr"
    url = public_url(_field(text, "url"), {"files.pythonhosted.org", "github.com"})
    sha = _field(text, "sha256")
    if not re.fullmatch(r"[a-f0-9]{64}", sha):
        raise ValueError("invalid source checksum")
    if _field(text, "version") != version:
        raise ValueError("formula version differs from release")
    try:
        Version(version)
    except InvalidVersion as exc:
        raise ValueError("invalid package version") from exc
    python = re.findall(r'^  depends_on "(python@\d+\.\d+)"$', text, re.MULTILINE)
    if len(python) != 1:
        raise ValueError("formula needs one versioned Python")
    snapshot = {
        "schema_version": 1, "formula_name": name, "version": version, "commit": commit,
        "source_url": url, "source_sha256": sha, "python_dependency": python[0],
        "resources": parse_resources(text),
    }
    canonical = formula_text(snapshot)
    # Accept Homebrew's blank-line layout, but not executable additions to its DSL.
    if [line for line in text.splitlines() if line.strip()] != [
        line for line in canonical.splitlines() if line.strip()
    ]:
        raise ValueError("formula contains unsupported executable content")
    snapshot["formula_sha256"] = hashlib.sha256(canonical.encode()).hexdigest()
    return snapshot


def validate_snapshot(snapshot: dict, text: str, *, version: str, commit: str,
                      source_url: str, source_sha256: str) -> None:
    actual = make_snapshot(text, version=version, commit=commit)
    expected = {**actual, "source_url": source_url, "source_sha256": source_sha256}
    if snapshot != expected or hashlib.sha256(text.encode()).hexdigest() != snapshot["formula_sha256"]:
        raise ValueError("snapshot or published source identity differs")


def require_all_targets(rows: list[dict], formula_sha256: str) -> None:
    if len(rows) != len(TARGETS) or {row.get("target") for row in rows} != set(TARGETS):
        raise ValueError("all four unique bottle targets are required")
    if any(row.get("status") != "passed" or row.get("formula_sha256") != formula_sha256 for row in rows):
        raise ValueError("a bottle verification failed or used a different formula")


def preview_asset_name(pr: int, head: str, run_id: int, attempt: int) -> str:
    if min(pr, run_id, attempt) < 1 or not re.fullmatch(r"[a-f0-9]{40}", head):
        raise ValueError("invalid preview identity")
    return f"gh-address-cr-pr{pr}-{head}-{run_id}-{attempt}.tar.gz"


def validate_preview(run: dict, pr: dict, metadata: dict, *, run_id: int) -> None:
    head = metadata.get("head_sha", "")
    identity = (
        run.get("id") == run_id == metadata.get("run_id")
        and run.get("event") == "pull_request" and run.get("conclusion") == "success"
        and run.get("path") == ".github/workflows/ci.yml"
        and run.get("head_repository", {}).get("full_name") == REPOSITORY
        and run.get("head_sha") == head == pr.get("head", {}).get("sha")
        and run.get("run_attempt") == metadata.get("run_attempt")
        and pr.get("head", {}).get("repo", {}).get("full_name") == REPOSITORY
        and pr.get("state") == "open" and pr.get("number") == metadata.get("pr")
        and any(row.get("number") == pr.get("number") for row in run.get("pull_requests", []))
    )
    try:
        version = Version(metadata.get("version", ""))
    except InvalidVersion as exc:
        raise ValueError("invalid preview version") from exc
    if (not identity or not re.fullmatch(r"[a-f0-9]{40}", head) or not version.is_devrelease
            or version.dev != metadata.get("pr") or version.local != head[:7]
            or not isinstance(metadata.get("run_attempt"), int) or metadata["run_attempt"] < 1):
        raise ValueError("preview provenance or current PR head differs")


def command(argv: list[str], *, cwd: Path | None = None, check: bool = True,
            env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    executable = Path(argv[0]).name
    child_env = (os.environ if env is None else env).copy()
    if executable not in {"gh", "git"}:
        for key in ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN",
                    "RELEASE_BOT_PRIVATE_KEY"):
            child_env.pop(key, None)
    started = time.monotonic()
    process = None
    with start_child_span(executable, kind=SpanKind.CLIENT,
                          attributes={"process.executable.name": executable}) as span:
        try:
            with subprocess.Popen(argv, cwd=cwd, env=child_env, text=True, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE) as process:
                span.set_attribute("process.pid", process.pid)
                try:
                    stdout, stderr = process.communicate(timeout=3600)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate()
                    raise
                result = subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)
        except (OSError, subprocess.SubprocessError):
            span.set_attribute("process.exit.code",
                               process.returncode if process and process.returncode is not None else -1)
            span.set_attribute("error.type", "process_start_or_wait_error")
            span.set_status(Status(StatusCode.ERROR))
            raise
        span.set_attribute("process.exit.code", result.returncode)
        if result.returncode:
            span.set_attribute("error.type", "nonzero_exit")
            span.set_status(Status(StatusCode.ERROR))
        add_current_span_event("release.command.completed", {
            "release.tool": executable, "release.duration_seconds": time.monotonic() - started,
            "process.exit.code": result.returncode,
        })
    if check and result.returncode:
        print(result.stdout, file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        raise ValueError(f"{executable} failed with exit code {result.returncode}")
    return result


def traced_main(operation: Callable[[], int]) -> int:
    os.environ.setdefault("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", DEVELOPMENT_TRACES_ENDPOINT)
    try:
        tracer = initialize_telemetry()
    except Exception:
        print("Release telemetry initialization unavailable; continuing.", file=sys.stderr)
        tracer = NoOpTracer()
    # Runtime CLI diagnostics are intentionally quiet. Release operators need a
    # visible failure signal, without exporting the logger's raw error content.
    class ExportDiagnostic(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            print("Release telemetry exporter diagnostic; build result is unchanged.", file=sys.stderr)

    diagnostic = ExportDiagnostic(level=logging.WARNING)
    logger_states = []
    for name in ("opentelemetry.exporter.otlp.proto.http.trace_exporter",
                 "opentelemetry.sdk._shared_internal"):
        logger = logging.getLogger(name)
        logger_states.append((logger, logger.disabled, logger.propagate, logger.handlers[:]))
        logger.disabled, logger.propagate, logger.handlers = False, False, [diagnostic]
    try:
        result = run_traced(tracer, Path(sys.executable).name, operation, attributes={
            "process.executable.name": Path(sys.executable).name, "process.pid": os.getpid(),
        })
        return int(result)
    finally:
        try:
            shutdown_telemetry()
        except Exception:
            print("Release telemetry export unavailable; continuing.", file=sys.stderr)
        finally:
            for logger, disabled, propagate, handlers in logger_states:
                logger.disabled, logger.propagate, logger.handlers = disabled, propagate, handlers


class ReleaseAssets:
    def __init__(self, tag: str):
        if not re.fullmatch(r"v\d+\.\d+\.\d+|pr-preview", tag):
            raise ValueError("unsupported release tag")
        self.tag = tag

    def names(self) -> set[str]:
        assets = github_json(f"repos/{REPOSITORY}/releases/tags/{self.tag}")["assets"]
        names = [row["name"] for row in assets]
        if len(names) != len(set(names)):
            raise ValueError("ambiguous release assets")
        return set(names)

    def download(self, name: str, directory: Path) -> Path:
        if Path(name).name != name or not re.fullmatch(r"[a-zA-Z0-9_.+-]+", name):
            raise ValueError("unsafe asset name")
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / name
        started = time.monotonic()
        with urlopen(f"https://github.com/{REPOSITORY}/releases/download/{self.tag}/{name}", timeout=60) as response:
            with path.open("wb") as handle:
                import shutil

                shutil.copyfileobj(response, handle)
        add_current_span_event("release.asset.download.completed", {
            "release.duration_seconds": time.monotonic() - started,
        })
        return path

    def upload(self, path: Path) -> None:
        if path.name not in self.names():
            command(["gh", "release", "upload", self.tag, str(path), "--repo", REPOSITORY])
        self.verify(path)

    def verify(self, path: Path) -> None:
        with tempfile.TemporaryDirectory() as directory:
            existing = self.download(path.name, Path(directory))
            if digest(existing) != digest(path):
                raise ValueError("immutable asset has different bytes; use a new rebuild")


def github_json(endpoint: str) -> dict:
    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(f"https://api.github.com/{endpoint}", headers=headers)
    with urlopen(request, timeout=60) as response:
        return json.load(response)


def update_tap(checkout: Path, formula: Path, *, name: str, version: str, attempts: int = 4) -> bool:
    if name not in {"gh-address-cr", "gh-address-cr-dev"}:
        raise ValueError("unsupported tap formula")
    relative = f"Formula/{name}.rb"
    content = formula.read_bytes()
    # Detached worktrees retain checkout authentication but start at the latest
    # remote tree, preserving other writers without reset or force-push.
    for _ in range(attempts):
        command(["git", "-C", str(checkout), "fetch", "--quiet", "origin", "main"])
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory) / "tap"
            command(["git", "-C", str(checkout), "worktree", "add", "--quiet", "--detach", str(work), "FETCH_HEAD"])
            try:
                result = _write_and_push(work, relative, content, name, version)
                if result is not False:
                    return result is True
            finally:
                command(["git", "-C", str(checkout), "worktree", "remove", str(work)])
    raise ValueError("tap changed concurrently; retry publication")


def _write_and_push(work: Path, relative: str, content: bytes, name: str, version: str) -> bool | None:
    target = work / relative
    if target.exists() and target.read_bytes() == content:
        return None
    if target.exists() and name == "gh-address-cr":
        old = re.search(r'^  version "([^"]+)"$', target.read_text(), re.MULTILINE)
        if old and Version(old[1]) > Version(version):
            raise ValueError("refusing to replace a newer tap version")
        if old and Version(old[1]) == Version(version):
            before = re.search(r"^    rebuild (\d+)$", target.read_text(), re.MULTILINE)
            after = re.search(rb"^    rebuild (\d+)$", content, re.MULTILINE)
            if int(before[1] if before else 0) > int(after[1] if after else 0):
                raise ValueError("refusing to replace a newer bottle rebuild")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    command(["git", "-C", str(work), "add", "--", relative])
    command(["git", "-C", str(work), "-c", "user.name=github-actions[bot]",
             "-c", "user.email=41898282+github-actions[bot]@users.noreply.github.com",
             "commit", "--quiet", "-m", f"{name} {version}"])
    return command(["git", "-C", str(work), "push", "origin", "HEAD:main"], check=False).returncode == 0
