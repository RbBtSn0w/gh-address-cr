from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from gh_address_cr.commands.common import (
    emit_scope_resolution_error,
    maybe_prepend_implicit_scope,
    prepend_optional,
)
from gh_address_cr.core import cr_metrics as core_cr_metrics
from gh_address_cr.core import telemetry as core_telemetry
from gh_address_cr.core import telemetry_health
from gh_address_cr.core.io import write_json_atomic


def handle_telemetry_command(repo: str | None, pr_number: str | None, passthrough: list[str]) -> int:
    if repo in {"-h", "--help"}:
        print(
            "usage: gh-address-cr telemetry ingest <owner/repo> <pr_number> --source <source> --format agent-jsonl --input <path>|-\n"
            "       gh-address-cr telemetry summary <owner/repo> <pr_number> [--format json|markdown]\n"
            "       gh-address-cr telemetry cr-summary <owner/repo> <pr_number> [--format json|markdown]\n"
            "       gh-address-cr telemetry doctor <owner/repo> <pr_number> [--format json|markdown]"
        )
        return 0
    if not repo:
        print("telemetry requires a subcommand: ingest, summary, cr-summary, or doctor", file=sys.stderr)
        return 2

    subcommand = repo
    args = prepend_optional(pr_number, passthrough)
    if subcommand == "ingest":
        parser = argparse.ArgumentParser(prog="gh-address-cr telemetry ingest")
        parser.add_argument("repo")
        parser.add_argument("pr_number")
        parser.add_argument("--source", required=True)
        parser.add_argument("--format", default="agent-jsonl")
        parser.add_argument("--input", required=True)
        scoped_args, scope_error = maybe_prepend_implicit_scope(args)
        if scope_error is not None:
            return emit_scope_resolution_error(scope_error)
        parsed = parser.parse_args(scoped_args)
        if parsed.input == "-":
            raw = sys.stdin.read()
        else:
            try:
                raw = Path(parsed.input).read_text(encoding="utf-8")
            except OSError:
                payload = core_telemetry.input_unavailable_import_summary(
                    parsed.repo,
                    parsed.pr_number,
                    source=parsed.source,
                    fmt=parsed.format,
                )
                print(json.dumps(payload, sort_keys=True))
                return 2
        summary = core_telemetry.import_external_telemetry(
            parsed.repo,
            parsed.pr_number,
            source=parsed.source,
            fmt=parsed.format,
            raw=raw,
        )
        print(json.dumps(summary, sort_keys=True))
        return 0 if summary["status"] in {"SUCCESS", "PARTIAL"} else 2

    if subcommand == "summary":
        parser = argparse.ArgumentParser(prog="gh-address-cr telemetry summary")
        parser.add_argument("repo")
        parser.add_argument("pr_number")
        parser.add_argument("--format", choices=("json", "markdown"), default="json")
        scoped_args, scope_error = maybe_prepend_implicit_scope(args)
        if scope_error is not None:
            return emit_scope_resolution_error(scope_error)
        parsed = parser.parse_args(scoped_args)
        report = core_telemetry.build_efficiency_report(parsed.repo, parsed.pr_number)
        if telemetry_report_has_storage_diagnostics(report):
            payload = {
                **report,
                "status": "FAILED",
                "reason_code": "TELEMETRY_REPORT_UNAVAILABLE",
                "next_action": "FIX_TELEMETRY_STORAGE",
            }
            write_telemetry_report_payload(payload)
            print(json.dumps(payload, sort_keys=True))
            return 2
        if parsed.format == "markdown":
            print(core_telemetry.efficiency_report_markdown(report), end="")
        else:
            print(json.dumps(report, sort_keys=True))
        return 0

    if subcommand == "cr-summary":
        parser = argparse.ArgumentParser(prog="gh-address-cr telemetry cr-summary")
        parser.add_argument("repo")
        parser.add_argument("pr_number")
        parser.add_argument("--format", choices=("json", "markdown"), default="json")
        scoped_args, scope_error = maybe_prepend_implicit_scope(args)
        if scope_error is not None:
            return emit_scope_resolution_error(scope_error)
        parsed = parser.parse_args(scoped_args)
        report = core_cr_metrics.build_cr_summary(parsed.repo, parsed.pr_number)
        if report["status"] == "FAILED":
            print(json.dumps(report, sort_keys=True))
            return 2
        if parsed.format == "markdown":
            print(core_cr_metrics.cr_summary_markdown(report), end="")
        else:
            print(json.dumps(report, sort_keys=True))
        return 0

    if subcommand == "doctor":
        parser = argparse.ArgumentParser(prog="gh-address-cr telemetry doctor")
        parser.add_argument("repo")
        parser.add_argument("pr_number")
        parser.add_argument("--format", choices=("json", "markdown"), default="json")
        scoped_args, scope_error = maybe_prepend_implicit_scope(args)
        if scope_error is not None:
            return emit_scope_resolution_error(scope_error)
        parsed = parser.parse_args(scoped_args)
        report = telemetry_health.build_doctor_report(parsed.repo, parsed.pr_number)
        if parsed.format == "markdown":
            print(telemetry_health.doctor_report_markdown(report), end="")
        else:
            print(json.dumps(report, sort_keys=True))
        return 0 if report["status"] == "PASSED" else 2

    print(f"Unknown telemetry command: {subcommand}", file=sys.stderr)
    return 2


def reported_telemetry_source(source: str) -> str:
    return core_telemetry._reported_source_label(source)


def telemetry_report_has_storage_diagnostics(report: dict) -> bool:
    diagnostics = report.get("diagnostics")
    if not isinstance(diagnostics, list):
        return False
    return any(
        isinstance(diagnostic, str)
        and (
            diagnostic.startswith("external telemetry line ")
            or diagnostic.startswith("external telemetry unreadable:")
            or diagnostic.startswith("external telemetry store is not a regular file:")
            or diagnostic.startswith("telemetry import summary line ")
            or diagnostic.startswith("telemetry import summary unreadable:")
            or diagnostic.startswith("telemetry import summary is not a regular file:")
            or diagnostic.startswith("efficiency report artifact unavailable:")
        )
        for diagnostic in diagnostics
    )


def write_telemetry_report_payload(payload: dict) -> None:
    report_artifact = payload.get("report_artifact")
    if not isinstance(report_artifact, str) or not report_artifact:
        return
    path = Path(report_artifact)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(path, payload)
    except OSError:
        return
