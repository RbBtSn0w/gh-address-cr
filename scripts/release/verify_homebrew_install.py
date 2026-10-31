"""Exercise the installed interpreter, dependency closure and a local OTLP sink."""

from __future__ import annotations

import argparse
import gzip
import importlib.metadata
import importlib.resources
import json
import os
import sqlite3
import ssl
import sys
import tempfile
import threading
import time
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name, parse_sdist_filename

import gh_address_cr
from scripts.release import homebrew_support as shared

RECEIVED: list[ExportTraceServiceRequest] = []


class Receiver(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        if self.headers.get("Content-Encoding") == "gzip":
            body = gzip.decompress(body)
        request = ExportTraceServiceRequest()
        request.ParseFromString(body)
        RECEIVED.append(request)
        self.send_response(200)
        self.end_headers()

    def log_message(self, *_args):
        pass


def dependency_inventory(snapshot: dict, prefix: Path) -> dict[str, str]:
    expected = {canonicalize_name(row["name"]): str(parse_sdist_filename(
        unquote(Path(urlsplit(row["url"]).path).name)
    )[1]) for row in snapshot["resources"]}
    expected["gh-address-cr"] = snapshot["version"]
    pending = ["gh-address-cr"]
    checked: dict[str, str] = {}
    while pending:
        name = canonicalize_name(pending.pop())
        if name in checked:
            continue
        distribution = importlib.metadata.distribution(name)
        if not Path(distribution.locate_file("")).resolve().is_relative_to((prefix / "libexec").resolve()):
            raise ValueError("runtime dependency was imported from outside the formula")
        if distribution.version != expected.get(name):
            raise ValueError(f"installed dependency differs from the resource snapshot: {name}")
        checked[name] = distribution.version
        for entry in distribution.requires or []:
            requirement = Requirement(entry)
            if requirement.marker and not requirement.marker.evaluate({"extra": ""}):
                continue
            installed = importlib.metadata.version(requirement.name)
            if installed not in requirement.specifier:
                raise ValueError(f"unsatisfied dependency constraint: {canonicalize_name(requirement.name)}")
            pending.append(requirement.name)
    if checked != expected:
        raise ValueError("resource snapshot and installed dependency closure differ")
    return dict(sorted(checked.items()))


def verify_data_and_platform() -> None:
    import opentelemetry.exporter.otlp.proto.http.trace_exporter
    import opentelemetry.sdk.trace

    if not (opentelemetry.sdk.trace.TracerProvider
            and opentelemetry.exporter.otlp.proto.http.trace_exporter.OTLPSpanExporter):
        raise ValueError("installed telemetry SDK or exporter is unavailable")
    metadata = json.loads(importlib.resources.files("gh_address_cr").joinpath(
        "runtime-requirements.json"
    ).read_text())
    if metadata["runtime_package"] != "gh-address-cr":
        raise ValueError("installed runtime package data differs")
    with tempfile.TemporaryDirectory() as directory:
        with closing(sqlite3.connect(Path(directory) / "probe.sqlite3")) as database, database:
            database.execute("CREATE TABLE probe(value INTEGER)")
            database.execute("INSERT INTO probe VALUES (7)")
            if database.execute("SELECT value FROM probe").fetchone() != (7,):
                raise ValueError("installed SQLite round-trip failed")
    ssl.create_default_context()


def verify_cli(prefix: Path, version: str) -> dict[str, float]:
    executable = str(prefix / "bin/gh-address-cr")
    started = time.monotonic()
    result = shared.command([executable, "--version"])
    first_start = time.monotonic() - started
    if result.stdout.strip() != f"gh-address-cr {version}":
        raise ValueError("installed console entrypoint version differs")
    shared.command([executable, "--help"])
    manifest = json.loads(shared.command([executable, "agent", "manifest"]).stdout)
    if manifest["runtime_version"] != version or manifest["status"] != "MANIFEST_READY":
        raise ValueError("installed agent manifest differs")
    return {"first_start_seconds": first_start, "cli_smoke_seconds": time.monotonic() - started}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    prefix = args.prefix.resolve()
    if (Path(sys.prefix).resolve() != (prefix / "libexec").resolve()
            or not Path(gh_address_cr.__file__).resolve().is_relative_to(prefix)):
        raise ValueError("verification is not using the installed formula interpreter and package")
    snapshot = json.loads(args.snapshot.read_text())
    inventory = dependency_inventory(snapshot, prefix)
    verify_data_and_platform()
    startup = verify_cli(prefix, snapshot["version"])
    spans = [span for request in RECEIVED for resource in request.resource_spans
             for scope in resource.scope_spans for span in scope.spans]
    if not spans or not any(attribute.key == "process.pid" for span in spans for attribute in span.attributes):
        raise ValueError("installed CLI did not export process spans to the local OTLP receiver")
    shared.write_json(args.output, {
        "dependencies": inventory, "python_version": sys.version.split()[0],
        "sqlite_version": sqlite3.sqlite_version, "openssl_version": ssl.OPENSSL_VERSION,
        **startup, "local_otlp_span_count": len(spans),
    })
    return 0


def local_main() -> int:
    with ThreadingHTTPServer(("127.0.0.1", 0), Receiver) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        os.environ["OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"] = f"http://127.0.0.1:{server.server_port}/v1/traces"
        os.environ.pop("DISABLE_TELEMETRY", None)
        os.environ.pop("DO_NOT_TRACK", None)
        try:
            return shared.traced_main(main)
        finally:
            server.shutdown()
            thread.join()


if __name__ == "__main__":
    raise SystemExit(local_main())
