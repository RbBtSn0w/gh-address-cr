#!/usr/bin/env python3
"""Measure runtime persistence cost and within-session slowdown.

This is an advisory local benchmark (specs/035-runtime-store-hardening). It
drives the public Python runtime API with local findings only, so it needs no
network and runs unchanged against any checkout that exposes
``agent_protocol.record_classification``, ``issue_action_request``, and
``submit_action_response``. Point ``PYTHONPATH`` at another checkout's ``src``
to record that checkout's baseline.

The simulated CR loop classifies, claims, and submits every item in order and
reports per-CR latency percentiles plus a degradation ratio: the median of the
last 10% of CRs divided by the median of the first 10%. A ratio well above 1
means each CR costs more as the session grows.

Timing assertions deliberately stay out of CI; use the JSON output in a PR
description or validation record.
"""

from __future__ import annotations

import argparse
import gc
import json
import math
import os
import platform
import statistics
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable
from unittest.mock import patch

REPO = "bench/runtime-store"
PR_NUMBER = "1"
PROFILES = {
    "S": {"items": 50, "evidence": 200},
    "M": {"items": 300, "evidence": 3000},
    "L": {"items": 1000, "evidence": 20000},
}


class _UnstackedClient:
    """Answers the one GitHub question local findings ask: this PR is not stacked."""

    def get_stack_context(self, repo: str, pr_number: str) -> Any:
        from gh_address_cr.core.runtime_kernel.stack import project_stack_context

        return project_stack_context(
            {
                "schema_version": "stack_observation.v1",
                "availability": "absent",
                "repo": repo,
                "selected_pr_number": str(pr_number),
                "observed_at": "2026-01-01T00:00:00Z",
                "selected_pr": {
                    "position": 1,
                    "pr_number": str(pr_number),
                    "state": "OPEN",
                    "is_draft": False,
                    "base_ref_name": "main",
                    "head_ref_name": "bench/runtime-store",
                    "head_oid": "a" * 40,
                    "merge_queue_state": None,
                },
                "members": [],
            }
        )


def _item(index: int) -> dict[str, Any]:
    return {
        "item_id": f"local:{index}",
        "item_kind": "local_finding",
        "source": "json",
        "title": f"Benchmark finding {index}",
        "body": "Synthetic finding used to measure runtime persistence cost. " * 4,
        "path": f"src/module_{index % 40}.py",
        "line": index + 1,
        "state": "open",
        "status": "OPEN",
        "blocking": True,
        "allowed_actions": ["fix", "clarify", "defer", "reject"],
    }


def _seed_legacy_workspace(items: int, evidence: int) -> None:
    """Write pre-035 JSON state so every checkout starts from identical inputs."""
    from gh_address_cr.core import session as session_store
    from gh_address_cr.evidence.ledger import EvidenceRecord

    session_id = f"{REPO}#{PR_NUMBER}"
    payload = {
        "session_id": session_id,
        "repo": REPO,
        "pr_number": PR_NUMBER,
        "status": "WAITING_FOR_CLASSIFICATION",
        "items": {f"local:{index}": _item(index) for index in range(items)},
        "leases": {},
        "metadata": {},
    }
    session_path = session_store.session_file(REPO, PR_NUMBER)
    session_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    ledger_path = session_store.default_ledger_path(REPO, PR_NUMBER)
    with ledger_path.open("w", encoding="utf-8") as handle:
        for index in range(evidence):
            record = EvidenceRecord.new(
                session_id=session_id,
                item_id=f"local:{index % max(items, 1)}",
                lease_id=None,
                agent_id="bench-seed",
                role="triage",
                event_type="benchmark_seed",
                payload={"sequence": index},
            )
            handle.write(json.dumps(record.to_json(), sort_keys=True, separators=(",", ":")))
            handle.write("\n")


def _timed(function: Callable[[], Any]) -> tuple[Any, int]:
    started = time.perf_counter_ns()
    value = function()
    return value, time.perf_counter_ns() - started


def _percentile(values: list[int], quantile: float) -> int:
    ordered = sorted(values)
    rank = max(1, math.ceil(quantile * len(ordered)))
    return ordered[rank - 1]


def _summary_ms(values: list[int]) -> dict[str, float]:
    return {
        "p50": round(statistics.median(values) / 1e6, 3),
        "p90": round(_percentile(values, 0.9) / 1e6, 3),
        "max": round(max(values) / 1e6, 3),
    }


def _degradation_ratio(per_cr_ns: list[int]) -> float:
    decile = max(1, len(per_cr_ns) // 10)
    first = statistics.median(per_cr_ns[:decile])
    last = statistics.median(per_cr_ns[-decile:])
    return round(last / first, 3) if first else 0.0


def _run_cr(agent_protocol: Any, client: Any, workdir: Path, index: int) -> dict[str, int]:
    item_id = f"local:{index}"
    agent_id = f"bench-fixer-{index}"
    _, classify_ns = _timed(
        lambda: agent_protocol.record_classification(
            REPO,
            PR_NUMBER,
            item_id=item_id,
            classification="fix",
            agent_id="bench-triage",
            note="Benchmark classification.",
        )
    )
    requested, next_ns = _timed(
        lambda: agent_protocol.issue_action_request(
            REPO, PR_NUMBER, role="fixer", agent_id=agent_id, item_id=item_id, github_client=client
        )
    )
    request = json.loads(Path(requested["request_path"]).read_text(encoding="utf-8"))
    response_path = workdir / f"response-{index}.json"
    response_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "request_id": request["request_id"],
                "lease_id": request["lease_id"],
                "agent_id": agent_id,
                "resolution": "fix",
                "note": "Benchmark fix.",
                "files": [f"src/module_{index % 40}.py"],
                "validation_commands": [{"command": "unit", "result": "passed"}],
            }
        ),
        encoding="utf-8",
    )
    accepted, submit_ns = _timed(
        lambda: agent_protocol.submit_action_response(
            REPO, PR_NUMBER, response_path=response_path, github_client=client
        )
    )
    if accepted.get("status") != "ACTION_ACCEPTED":
        raise AssertionError(f"{item_id} was not accepted: {accepted.get('status')}")
    return {"classify": classify_ns, "next": next_ns, "submit": submit_ns}


def _measure_loads(session_store: Any, samples: int) -> list[int]:
    return [_timed(lambda: session_store.load_session(REPO, PR_NUMBER))[1] for _ in range(samples)]


def run_profile(profile: str, *, load_samples: int, cr_limit: int | None) -> dict[str, Any]:
    from gh_address_cr.core import agent_protocol
    from gh_address_cr.core import session as session_store

    shape = PROFILES[profile]
    items = shape["items"] if cr_limit is None else min(shape["items"], cr_limit)
    with tempfile.TemporaryDirectory(prefix="gh-address-cr-bench-") as tmp:
        workdir = Path(tmp)
        with patch.dict(os.environ, {"GH_ADDRESS_CR_STATE_DIR": str(workdir / "state")}, clear=False):
            _seed_legacy_workspace(shape["items"], shape["evidence"])
            _, first_load_ns = _timed(lambda: session_store.load_session(REPO, PR_NUMBER))
            loads_before = _measure_loads(session_store, load_samples)

            client = _UnstackedClient()
            step_ns: dict[str, list[int]] = {"classify": [], "next": [], "submit": []}
            per_cr_ns: list[int] = []
            was_enabled = gc.isenabled()
            gc.disable()
            try:
                for index in range(items):
                    steps = _run_cr(agent_protocol, client, workdir, index)
                    for name, value in steps.items():
                        step_ns[name].append(value)
                    per_cr_ns.append(sum(steps.values()))
            finally:
                if was_enabled:
                    gc.enable()
            loads_after = _measure_loads(session_store, load_samples)

    return {
        "workload": {"items": shape["items"], "evidence": shape["evidence"], "crs_run": items},
        "first_load_ms": round(first_load_ns / 1e6, 3),
        "load_session_ms": {"before_loop": _summary_ms(loads_before), "after_loop": _summary_ms(loads_after)},
        "steps_ms": {name: _summary_ms(values) for name, values in step_ns.items()},
        "per_cr_ms": _summary_ms(per_cr_ns),
        "degradation_ratio": _degradation_ratio(per_cr_ns),
    }


def _runtime_label() -> str:
    try:
        from gh_address_cr import __version__

        return str(__version__)
    except ImportError:
        return "unknown"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--profile", choices=sorted(PROFILES), action="append", help="Repeatable; default M.")
    parser.add_argument("--load-samples", type=int, default=15)
    parser.add_argument("--cr-limit", type=int, help="Run at most this many CRs per profile (smoke runs).")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON only.")
    args = parser.parse_args()
    if args.load_samples <= 0 or (args.cr_limit is not None and args.cr_limit <= 0):
        parser.error("--load-samples and --cr-limit must be positive")

    profiles = args.profile or ["M"]
    report = {
        "schema_version": 1,
        "runtime": {
            "implementation": platform.python_implementation(),
            "python": platform.python_version(),
            "gh_address_cr": _runtime_label(),
        },
        "load_samples": args.load_samples,
        "profiles": {
            profile: run_profile(profile, load_samples=args.load_samples, cr_limit=args.cr_limit)
            for profile in profiles
        },
    }
    if args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
