#!/usr/bin/env python3
"""Compare archived efficiency reports by runtime build (Spec 039 L4).

The 3.16.0 telemetry regression (needs-action exits counted as failures) was
found by hand: every report written by 3.16.0 had a lower success rate and new
flags, and no earlier one did. This script does that comparison.

    python3 scripts/compare_telemetry_by_runtime.py                     # summary
    python3 scripts/compare_telemetry_by_runtime.py \\
        --baseline "3.15.3 package" --candidate "3.16.0 editable"       # check, exit 1 on regression

Reports are read from the gh-address-cr state directory (live sessions and the
archive). Output carries runtime labels and aggregates only, never paths.
Reports written before the `runtime` field existed group under "unknown".
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any

FLAG_KINDS = (
    (re.compile(r"^(?P<op>.+?) had \d+ failures"), "error_prone"),
    (re.compile(r"^(?P<op>.+?) exceeded \d+s threshold"), "duration"),
    (re.compile(r"^(?P<op>.+?) latency grew"), "latency_growth"),
)


def flag_kind(flag: str) -> str:
    """A flag's kind and operation, without the counts that vary per session."""
    for pattern, kind in FLAG_KINDS:
        match = pattern.match(flag)
        if match:
            return f"{kind}:{match.group('op')}"
    return "other"


def runtime_label(report: dict[str, Any]) -> str:
    runtime = report.get("runtime")
    if not isinstance(runtime, dict) or not runtime.get("version"):
        return "unknown"
    label = f"{runtime['version']} {runtime.get('origin') or 'unknown'}"
    return f"{label} {runtime['commit']}" if runtime.get("commit") else label


def collect_reports(state_dir: Path) -> list[dict[str, Any]]:
    reports = []
    for path in sorted(state_dir.rglob("efficiency-report.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(payload, dict):
            reports.append(payload)
    return reports


def summarize(reports: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for report in reports:
        grouped.setdefault(runtime_label(report), []).append(report)
    summary = {}
    for label, rows in grouped.items():
        rates = [float(row["success_rate"]) for row in rows if isinstance(row.get("success_rate"), (int, float))]
        kinds: Counter[str] = Counter()
        for row in rows:
            flags = row.get("inefficiency_flags")
            # Archived JSON can be malformed; only a list of flags is meaningful.
            if isinstance(flags, list):
                kinds.update({flag_kind(str(flag)) for flag in flags})
        summary[label] = {
            "sessions": len(rows),
            "median_success_rate": statistics.median(rates) if rates else None,
            "needs_action_total": sum(int(row.get("needs_action_count") or 0) for row in rows),
            "flag_kinds": dict(sorted(kinds.items())),
        }
    return dict(sorted(summary.items()))


def compare(
    groups: dict[str, dict[str, Any]], *, baseline: str, candidate: str, max_success_drop: float
) -> list[str]:
    """Regressions of `candidate` against `baseline`; empty means no regression."""
    missing = [label for label in (baseline, candidate) if label not in groups]
    if missing:
        return [f"no reports for runtime {label!r}; known: {', '.join(groups) or 'none'}" for label in missing]
    base, cand = groups[baseline], groups[candidate]
    problems = []
    if base["median_success_rate"] is not None and cand["median_success_rate"] is not None:
        drop = base["median_success_rate"] - cand["median_success_rate"]
        if drop > max_success_drop:
            problems.append(
                f"median success rate fell {drop:.1f} points ({base['median_success_rate']:.1f} -> "
                f"{cand['median_success_rate']:.1f}), more than {max_success_drop:.1f}"
            )
    new_kinds = sorted(set(cand["flag_kinds"]) - set(base["flag_kinds"]))
    if new_kinds:
        problems.append(f"new inefficiency flag kinds: {', '.join(new_kinds)}")
    return problems


def _default_state_dir() -> Path:
    from gh_address_cr.core.paths import state_dir

    return state_dir()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--state-dir", type=Path, help="gh-address-cr state directory (default: the runtime's).")
    parser.add_argument("--baseline", help="Runtime label to compare against, as printed in the summary.")
    parser.add_argument("--candidate", help="Runtime label to check.")
    parser.add_argument("--max-success-drop", type=float, default=5.0, help="Allowed median drop in points.")
    args = parser.parse_args(argv)
    if bool(args.baseline) != bool(args.candidate):
        parser.error("--baseline and --candidate go together")

    groups = summarize(collect_reports(args.state_dir or _default_state_dir()))
    output: dict[str, Any] = {"runtimes": groups}
    problems: list[str] = []
    if args.baseline:
        problems = compare(
            groups, baseline=args.baseline, candidate=args.candidate, max_success_drop=args.max_success_drop
        )
        output["check"] = {
            "baseline": args.baseline,
            "candidate": args.candidate,
            "status": "REGRESSION" if problems else "OK",
            "problems": problems,
        }
    sys.stdout.write(json.dumps(output, indent=2, sort_keys=True) + "\n")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
