# Per-CR Processing Metrics (`telemetry cr-summary`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only `telemetry cr-summary` command that computes per-CR processing metrics (count, per-CR span distribution, compactness, classification mix) for the latest processing pass from the evidence ledger.

**Architecture:** A leaf computation module `core/cr_metrics.py` reads `evidence.jsonl` (read-only), selects the latest session, groups events by distinct `item_id`, derives per-CR wall-clock spans (first event → `thread_resolved`), aggregates completed-only span stats + compactness, and writes a `cr-metrics.json` artifact. A new `cr-summary` subcommand in `commands/telemetry.py` renders json/markdown. No existing telemetry/report code changes.

**Tech Stack:** Python 3.10+, stdlib only (`json`, `math`, `statistics`, `datetime`). Tests use `unittest`: `PYTHONPATH=src python -m unittest <module>`.

**Reference spec:** `docs/superpowers/specs/2026-06-21-per-cr-metrics-design.md`.

---

## File Structure

| File | Responsibility |
|---|---|
| Create `src/gh_address_cr/core/cr_metrics.py` | `build_cr_summary(repo, pr) -> dict` + `cr_summary_markdown(report) -> str` |
| Modify `src/gh_address_cr/commands/telemetry.py` | add `cr-summary` subcommand to `handle_telemetry_command` |
| Create `tests/core/test_cr_metrics.py` | unit + edge-case tests |
| Create `tests/fixtures/cr_metrics/evidence-sample.jsonl` | synthetic ledger fixture (no `__init__.py`) |

**Baseline (run before starting):**
Run: `PYTHONPATH=src python -m unittest tests.test_python_wrappers -v 2>&1 | tail -3`
Expected: OK.

Reference — ledger event shape (real): each line is a JSON object with `session_id`, `item_id`, `event_type`, `timestamp` (ISO-8601), `payload`. Lifecycle event types include `classification_recorded` (payload has `classification` + `note`), `request_issued`, `response_accepted`, `reply_posted`, `thread_resolved` (terminal), `response_published`.

---

## Task 1: Core computation `build_cr_summary`

**Files:**
- Create: `src/gh_address_cr/core/cr_metrics.py`
- Create: `tests/fixtures/cr_metrics/evidence-sample.jsonl`
- Test: `tests/core/test_cr_metrics.py`

- [ ] **Step 1: Create the fixture** `tests/fixtures/cr_metrics/evidence-sample.jsonl` (do NOT add `__init__.py` to fixtures). Two completed CRs (item-A span 4s fix, item-B span 30s reply) + one incomplete (item-C, classified deferred, no thread_resolved). item-A is re-classified twice (distinct-item dedup must keep latest = "fix"):

```
{"session_id":"s1","item_id":"A","event_type":"classification_recorded","timestamp":"2026-06-21T10:00:00Z","payload":{"classification":"reply","note":"x"}}
{"session_id":"s1","item_id":"A","event_type":"classification_recorded","timestamp":"2026-06-21T10:00:01Z","payload":{"classification":"fix","note":"x"}}
{"session_id":"s1","item_id":"A","event_type":"reply_posted","timestamp":"2026-06-21T10:00:03Z","payload":{}}
{"session_id":"s1","item_id":"A","event_type":"thread_resolved","timestamp":"2026-06-21T10:00:04Z","payload":{}}
{"session_id":"s1","item_id":"B","event_type":"classification_recorded","timestamp":"2026-06-21T10:00:05Z","payload":{"classification":"reply","note":"y"}}
{"session_id":"s1","item_id":"B","event_type":"thread_resolved","timestamp":"2026-06-21T10:00:35Z","payload":{}}
{"session_id":"s1","item_id":"C","event_type":"classification_recorded","timestamp":"2026-06-21T10:00:36Z","payload":{"classification":"defer","note":"z"}}
```

- [ ] **Step 2: Write the failing test** `tests/core/test_cr_metrics.py`:

```python
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gh_address_cr.core import paths as core_paths
from gh_address_cr.core.cr_metrics import build_cr_summary

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "cr_metrics" / "evidence-sample.jsonl"


class BuildCrSummaryTests(unittest.TestCase):
    def _seed(self, state, repo, pr, ledger_text):
        with patch("gh_address_cr.core.paths.state_dir", return_value=Path(state)):
            wd = core_paths.workspace_dir(repo, pr)
            wd.mkdir(parents=True, exist_ok=True)
            core_paths.evidence_ledger_file(repo, pr).write_text(ledger_text, encoding="utf-8")

    def test_happy_path_spans_and_stats(self):
        with tempfile.TemporaryDirectory() as state:
            self._seed(state, "o/r", "5", FIXTURE.read_text(encoding="utf-8"))
            with patch("gh_address_cr.core.paths.state_dir", return_value=Path(state)):
                r = build_cr_summary("o/r", "5")
            self.assertEqual(r["status"], "SUCCESS")
            self.assertEqual(r["reason_code"], "CR_SUMMARY_READY")
            self.assertEqual(r["cr_count_total"], 3)
            self.assertEqual(r["cr_count_completed"], 2)
            self.assertEqual(r["cr_count_incomplete"], 1)
            self.assertEqual(r["span_ms"]["max"], 30000)
            self.assertEqual(r["span_ms"]["min"], 4000)
            self.assertEqual(r["active_cr_time_ms"], 34000)
            self.assertEqual(r["classification_mix"], {"fix": 1, "reply": 1, "defer": 1})
            self.assertEqual(r["incomplete_crs"], [{"item_id": "C", "last_event_type": "classification_recorded"}])
            self.assertTrue(Path(r["report_artifact"]).exists())

    def test_empty_ledger_is_success_empty(self):
        with tempfile.TemporaryDirectory() as state:
            self._seed(state, "o/r", "5", "")
            with patch("gh_address_cr.core.paths.state_dir", return_value=Path(state)):
                r = build_cr_summary("o/r", "5")
            self.assertEqual(r["status"], "SUCCESS")
            self.assertEqual(r["reason_code"], "CR_LEDGER_EMPTY")
            self.assertEqual(r["cr_count_total"], 0)
            self.assertIsNone(r["span_ms"]["median"])

    def test_missing_ledger_is_success_empty(self):
        with tempfile.TemporaryDirectory() as state:
            with patch("gh_address_cr.core.paths.state_dir", return_value=Path(state)):
                core_paths.workspace_dir("o/r", "5").mkdir(parents=True, exist_ok=True)
                r = build_cr_summary("o/r", "5")
            self.assertEqual(r["reason_code"], "CR_LEDGER_EMPTY")
```

- [ ] **Step 3: Run to verify it fails**

Run: `PYTHONPATH=src python -m unittest tests.core.test_cr_metrics.BuildCrSummaryTests -v`
Expected: FAIL — `ModuleNotFoundError: gh_address_cr.core.cr_metrics`.

- [ ] **Step 4: Implement `src/gh_address_cr/core/cr_metrics.py`**

```python
from __future__ import annotations

import json
import math
import statistics
from datetime import datetime
from pathlib import Path
from typing import Any

from gh_address_cr.core import paths as core_paths
from gh_address_cr.core.io import write_json_atomic

TERMINAL_EVENT = "thread_resolved"
CLASSIFY_EVENT = "classification_recorded"


def _parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _read_ledger(path: Path) -> tuple[list[dict[str, Any]], bool, list[str]]:
    """Return (events, unreadable, diagnostics). Missing file is empty (not unreadable)."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return [], False, []
    except OSError:
        return [], True, []
    events: list[dict[str, Any]] = []
    diagnostics: list[str] = []
    for index, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            diagnostics.append(f"evidence ledger line {index}: invalid JSON")
            continue
        if not isinstance(obj, dict):
            diagnostics.append(f"evidence ledger line {index}: not an object")
            continue
        events.append(obj)
    return events, diagnostics and False or False, diagnostics


def _percentile(values: list[int], q: float) -> int:
    ordered = sorted(values)
    rank = max(1, math.ceil(q * len(ordered)))
    return ordered[rank - 1]


def _empty_report(repo: str, pr_number: str, artifact: Path, diagnostics: list[str], session_id: str = "") -> dict[str, Any]:
    return {
        "status": "SUCCESS",
        "reason_code": "CR_LEDGER_EMPTY",
        "repo": repo,
        "pr_number": str(pr_number),
        "session_id": session_id,
        "cr_count_total": 0,
        "cr_count_completed": 0,
        "cr_count_incomplete": 0,
        "span_ms": {"median": None, "p90": None, "max": None, "min": None},
        "run_wall_clock_ms": 0,
        "active_cr_time_ms": 0,
        "compactness_ratio": None,
        "classification_mix": {},
        "incomplete_crs": [],
        "per_cr": [],
        "report_artifact": str(artifact),
        "diagnostics": diagnostics,
    }


def _write_artifact(artifact: Path, report: dict[str, Any]) -> None:
    try:
        artifact.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(artifact, report)
    except OSError as exc:
        report["diagnostics"].append(f"cr-metrics artifact unavailable: {type(exc).__name__}")


def build_cr_summary(repo: str, pr_number: str) -> dict[str, Any]:
    path = core_paths.evidence_ledger_file(repo, pr_number)
    artifact = core_paths.workspace_dir(repo, pr_number) / "cr-metrics.json"
    events, unreadable, diagnostics = _read_ledger(path)
    if unreadable:
        return {
            "status": "FAILED",
            "reason_code": "CR_SUMMARY_UNAVAILABLE",
            "repo": repo,
            "pr_number": str(pr_number),
            "diagnostics": ["evidence ledger unreadable"],
            "report_artifact": str(artifact),
        }

    valid = [(e, _parse_ts(e.get("timestamp"))) for e in events]
    valid = [(e, t) for e, t in valid if t is not None]
    if not valid:
        report = _empty_report(repo, pr_number, artifact, diagnostics)
        _write_artifact(artifact, report)
        return report

    latest_event, _ = max(valid, key=lambda et: et[1])
    latest_session = str(latest_event.get("session_id") or "")
    session_ids = {str(e.get("session_id") or "") for e, _ in valid}
    if len(session_ids) > 1:
        diagnostics.append(f"multiple sessions in ledger: {len(session_ids)}; using latest")

    session_events = [
        (e, t) for e, t in valid if str(e.get("session_id") or "") == latest_session and e.get("item_id")
    ]
    if not session_events:
        report = _empty_report(repo, pr_number, artifact, diagnostics, session_id=latest_session)
        _write_artifact(artifact, report)
        return report

    by_item: dict[str, list[tuple[datetime, dict[str, Any]]]] = {}
    for e, t in session_events:
        by_item.setdefault(str(e["item_id"]), []).append((t, e))

    per_cr: list[dict[str, Any]] = []
    completed_spans: list[int] = []
    incomplete: list[dict[str, Any]] = []
    classification_mix: dict[str, int] = {}
    all_ts = [t for _, t in session_events]

    for item_id, entries in by_item.items():
        entries.sort(key=lambda te: te[0])
        start = entries[0][0]
        classification: str | None = None
        for _, e in entries:
            if e.get("event_type") == CLASSIFY_EVENT:
                value = (e.get("payload") or {}).get("classification")
                if isinstance(value, str):
                    classification = value
        if classification:
            classification_mix[classification] = classification_mix.get(classification, 0) + 1
        terminal = [t for t, e in entries if e.get("event_type") == TERMINAL_EVENT]
        if terminal:
            span = max(0, int((max(terminal) - start).total_seconds() * 1000))
            completed_spans.append(span)
            per_cr.append({"item_id": item_id, "span_ms": span, "completed": True, "classification": classification})
        else:
            incomplete.append({"item_id": item_id, "last_event_type": entries[-1][1].get("event_type")})
            per_cr.append({"item_id": item_id, "span_ms": None, "completed": False, "classification": classification})

    if completed_spans:
        span_ms = {
            "median": int(statistics.median(completed_spans)),
            "p90": _percentile(completed_spans, 0.9),
            "max": max(completed_spans),
            "min": min(completed_spans),
        }
    else:
        span_ms = {"median": None, "p90": None, "max": None, "min": None}

    wall = int((max(all_ts) - min(all_ts)).total_seconds() * 1000)
    active = sum(completed_spans)
    compactness = round(active / wall, 2) if wall > 0 else None
    per_cr.sort(key=lambda row: (row["span_ms"] is None, -(row["span_ms"] or 0)))

    report = {
        "status": "SUCCESS",
        "reason_code": "CR_SUMMARY_READY",
        "repo": repo,
        "pr_number": str(pr_number),
        "session_id": latest_session,
        "cr_count_total": len(by_item),
        "cr_count_completed": len(completed_spans),
        "cr_count_incomplete": len(incomplete),
        "span_ms": span_ms,
        "run_wall_clock_ms": wall,
        "active_cr_time_ms": active,
        "compactness_ratio": compactness,
        "classification_mix": classification_mix,
        "incomplete_crs": incomplete,
        "per_cr": per_cr,
        "report_artifact": str(artifact),
        "diagnostics": diagnostics,
    }
    _write_artifact(artifact, report)
    return report
```

Note: the `_read_ledger` return expression `diagnostics and False or False` always yields `False` for the unreadable flag in the normal path — the unreadable case already returned early above. Write it plainly as `return events, False, diagnostics`.

- [ ] **Step 5: Fix the unreadable-flag return line**

In `_read_ledger`, the final line must be exactly:
```python
    return events, False, diagnostics
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `PYTHONPATH=src python -m unittest tests.core.test_cr_metrics.BuildCrSummaryTests -v`
Expected: PASS (3 tests).

- [ ] **Step 7: Run ruff**

Run: `ruff check src/gh_address_cr/core/cr_metrics.py`
Expected: clean.

- [ ] **Step 8: Commit**

```bash
git add src/gh_address_cr/core/cr_metrics.py tests/core/test_cr_metrics.py tests/fixtures/cr_metrics/evidence-sample.jsonl
git commit -m "feat(cr-metrics): per-CR span computation from evidence ledger

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Edge cases + markdown renderer

**Files:**
- Modify: `src/gh_address_cr/core/cr_metrics.py` (add `cr_summary_markdown`)
- Test: `tests/core/test_cr_metrics.py`

- [ ] **Step 1: Write the failing tests** (append to `tests/core/test_cr_metrics.py`):

```python
from gh_address_cr.core.cr_metrics import cr_summary_markdown


class EdgeAndMarkdownTests(unittest.TestCase):
    def _build(self, state, ledger_text):
        with patch("gh_address_cr.core.paths.state_dir", return_value=Path(state)):
            wd = core_paths.workspace_dir("o/r", "5")
            wd.mkdir(parents=True, exist_ok=True)
            core_paths.evidence_ledger_file("o/r", "5").write_text(ledger_text, encoding="utf-8")
            return build_cr_summary("o/r", "5")

    def test_malformed_line_is_skipped_with_diagnostic(self):
        with tempfile.TemporaryDirectory() as state:
            good = FIXTURE.read_text(encoding="utf-8")
            r = self._build(state, good + "\nnot json at all\n")
            self.assertEqual(r["status"], "SUCCESS")
            self.assertTrue(any("invalid JSON" in d for d in r["diagnostics"]))
            self.assertEqual(r["cr_count_total"], 3)

    def test_unreadable_ledger_fails_loud(self):
        with tempfile.TemporaryDirectory() as state:
            with patch("gh_address_cr.core.paths.state_dir", return_value=Path(state)):
                core_paths.workspace_dir("o/r", "5").mkdir(parents=True, exist_ok=True)
                # make the ledger path a directory so read_text raises OSError (not FileNotFoundError)
                core_paths.evidence_ledger_file("o/r", "5").mkdir()
                r = build_cr_summary("o/r", "5")
            self.assertEqual(r["status"], "FAILED")
            self.assertEqual(r["reason_code"], "CR_SUMMARY_UNAVAILABLE")

    def test_markdown_renders_counts_and_slowest(self):
        with tempfile.TemporaryDirectory() as state:
            r = self._build(state, FIXTURE.read_text(encoding="utf-8"))
            md = cr_summary_markdown(r)
            self.assertIn("CR Processing Summary", md)
            self.assertIn("2 completed, 1 incomplete", md)
            self.assertIn("Slowest CRs", md)

    def test_markdown_handles_empty(self):
        with tempfile.TemporaryDirectory() as state:
            r = self._build(state, "")
            md = cr_summary_markdown(r)
            self.assertIn("0 completed", md)
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=src python -m unittest tests.core.test_cr_metrics.EdgeAndMarkdownTests -v`
Expected: FAIL — `ImportError: cannot import name 'cr_summary_markdown'`.

- [ ] **Step 3: Implement `cr_summary_markdown`** (append to `src/gh_address_cr/core/cr_metrics.py`):

```python
def _ms(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "n/a"
    return f"{value / 1000:.1f}s"


def cr_summary_markdown(report: dict[str, Any]) -> str:
    span = report.get("span_ms") or {}
    lines = [
        "## CR Processing Summary (latest session)",
        f"- CRs: {report.get('cr_count_completed', 0)} completed, {report.get('cr_count_incomplete', 0)} incomplete",
        f"- per-CR span: median {_ms(span.get('median'))} | p90 {_ms(span.get('p90'))} | max {_ms(span.get('max'))}",
        f"- run wall-clock: {_ms(report.get('run_wall_clock_ms'))} | active CR time: {_ms(report.get('active_cr_time_ms'))} | compactness: {report.get('compactness_ratio')}",
    ]
    mix = report.get("classification_mix") or {}
    if mix:
        lines.append("- classification: " + ", ".join(f"{k} {v}" for k, v in sorted(mix.items())))
    completed = [r for r in report.get("per_cr", []) if r.get("completed")]
    if completed:
        lines.extend(["", "### Slowest CRs"])
        for row in completed[:5]:
            lines.append(f"- {row['item_id']} : {_ms(row['span_ms'])} ({row.get('classification') or 'n/a'})")
    incomplete = report.get("incomplete_crs") or []
    lines.extend(["", "### Incomplete CRs"])
    if incomplete:
        for row in incomplete:
            lines.append(f"- {row['item_id']} : {row['last_event_type']}")
    else:
        lines.append("- (none)")
    return "\n".join(lines) + "\n"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src python -m unittest tests.core.test_cr_metrics -v`
Expected: PASS (7 tests total).

- [ ] **Step 5: Run ruff**

Run: `ruff check src/gh_address_cr/core/cr_metrics.py`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/gh_address_cr/core/cr_metrics.py tests/core/test_cr_metrics.py
git commit -m "feat(cr-metrics): markdown renderer + edge-case handling (empty/malformed/unreadable)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Wire the `cr-summary` CLI subcommand

**Files:**
- Modify: `src/gh_address_cr/commands/telemetry.py`
- Test: `tests/core/test_cr_metrics.py`

Background: `handle_telemetry_command(repo, pr_number, passthrough)` dispatches on `subcommand = repo`. The existing `summary` block (lines ~65-89) is the pattern to mirror: argparse `repo`/`pr_number`/`--format`, `maybe_prepend_implicit_scope(args)` for scope resolution, then compute + print. Add a `cr-summary` block and update the usage/error strings.

- [ ] **Step 1: Write the failing CLI contract test** (append to `tests/core/test_cr_metrics.py`):

```python
import io
import contextlib
from gh_address_cr.commands.telemetry import handle_telemetry_command


class CrSummaryCliTests(unittest.TestCase):
    def _seed(self, state):
        with patch("gh_address_cr.core.paths.state_dir", return_value=Path(state)):
            wd = core_paths.workspace_dir("o/r", "5")
            wd.mkdir(parents=True, exist_ok=True)
            core_paths.evidence_ledger_file("o/r", "5").write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")

    def test_cli_cr_summary_json(self):
        with tempfile.TemporaryDirectory() as state:
            self._seed(state)
            with patch("gh_address_cr.core.paths.state_dir", return_value=Path(state)):
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    rc = handle_telemetry_command("cr-summary", "o/r", ["5"])
            self.assertEqual(rc, 0)
            payload = json.loads(buf.getvalue())
            self.assertEqual(payload["reason_code"], "CR_SUMMARY_READY")
            self.assertEqual(payload["cr_count_completed"], 2)

    def test_cli_cr_summary_markdown(self):
        with tempfile.TemporaryDirectory() as state:
            self._seed(state)
            with patch("gh_address_cr.core.paths.state_dir", return_value=Path(state)):
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    rc = handle_telemetry_command("cr-summary", "o/r", ["5", "--format", "markdown"])
            self.assertEqual(rc, 0)
            self.assertIn("CR Processing Summary", buf.getvalue())
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=src python -m unittest tests.core.test_cr_metrics.CrSummaryCliTests -v`
Expected: FAIL — `Unknown telemetry command: cr-summary` (returns 2, json parse fails).

- [ ] **Step 3: Add the import** at the top of `src/gh_address_cr/commands/telemetry.py` (with the other `from gh_address_cr.core import ...` imports):

```python
from gh_address_cr.core import cr_metrics as core_cr_metrics
```

- [ ] **Step 4: Add the `cr-summary` block** in `handle_telemetry_command`, immediately before the final `print(f"Unknown telemetry command: {subcommand}", ...)` line:

```python
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
```

- [ ] **Step 5: Update the usage and the no-subcommand error strings** so they mention cr-summary. Change the help block's usage text (the `print(...)` under `if repo in {"-h", "--help"}`) to add a third line:
```python
            "       gh-address-cr telemetry cr-summary <owner/repo> <pr_number> [--format json|markdown]"
```
and change the no-subcommand message:
```python
        print("telemetry requires a subcommand: ingest, summary, or cr-summary", file=sys.stderr)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `PYTHONPATH=src python -m unittest tests.core.test_cr_metrics -v`
Expected: PASS (9 tests total).

- [ ] **Step 7: Run the full suite + ruff gate**

Run: `PYTHONPATH=src python -m unittest discover -s tests 2>&1 | grep -E '^(Ran|OK|FAILED)'`
Expected: OK.
Run: `ruff check src tests`
Expected: All checks passed.

- [ ] **Step 8: Commit**

```bash
git add src/gh_address_cr/commands/telemetry.py tests/core/test_cr_metrics.py
git commit -m "feat(cr-metrics): add telemetry cr-summary CLI subcommand (json/markdown)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Final verification

- [ ] **Full suite + lint + real-ledger smoke**

Run: `PYTHONPATH=src python -m unittest discover -s tests 2>&1 | grep -E '^(Ran|OK|FAILED)'`
Expected: OK.
Run: `ruff check src tests`
Expected: All checks passed.
Smoke (real ledger, this machine): build the summary directly against a real evidence.jsonl and confirm sensible numbers:
```bash
PYTHONPATH=src python -c "
from gh_address_cr.core.cr_metrics import build_cr_summary, cr_summary_markdown
import gh_address_cr.core.paths as p, json
# point state_dir at the real cache via env if needed; or call against a known processed PR
print(cr_summary_markdown(build_cr_summary('RbBtSn0w/gh-address-cr','97')))
"
```
Expected: a CR Processing Summary with non-zero completed count and a median/p90/max span line (when run with the real cache state dir).

---

## Self-Review (author checklist, completed)

- **Spec coverage:** §2 computation rule → Task 1 (`build_cr_summary`); §3 schema → Task 1 (fields) + Task 2 (markdown); §4 edge/fail → Task 2 (empty/malformed/unreadable) + Task 1 (empty); §5 components/testing → all tasks; distinct-item dedup + latest-classification → Task 1 fixture (item A re-classified) + assertion. Non-goals (fine-grained tool time, cumulative mode, final-gate integration) correctly excluded.
- **Placeholder scan:** no TBD/TODO; full code in every step. The one tricky line in `_read_ledger` is explicitly corrected in Task 1 Step 5.
- **Type consistency:** `build_cr_summary(repo, pr) -> dict` and `cr_summary_markdown(report) -> str` used identically in Tasks 1-3. Report keys (`status`, `reason_code`, `cr_count_completed`, `span_ms`, `classification_mix`, `incomplete_crs`, `per_cr`, `report_artifact`) consistent across computation, markdown, and CLI tests. `CR_SUMMARY_READY` / `CR_LEDGER_EMPTY` / `CR_SUMMARY_UNAVAILABLE` spelled identically everywhere.
- **Risk boundaries:** read-only on the ledger; only new artifact is `cr-metrics.json` via `write_json_atomic`; no change to existing telemetry/report/final-gate code; does not touch the 015 acceptance matrix (fixed category set).
