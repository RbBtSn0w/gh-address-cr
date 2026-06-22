# Phase 2 Plan A — Host Telemetry Auto-Capture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically capture whole-session efficiency telemetry by reading Claude Code and Codex native transcripts, mapping them to agent-jsonl via declarative profiles + strategy primitives, scoping them to the active PR, and feeding the existing ingest pipeline at `final-gate` — with first-run consent and fail-open everywhere.

**Architecture:** A new self-contained package `core/host_telemetry/` produces **agent-jsonl text** from a host log; that text is handed to the *existing* `core.telemetry.import_external_telemetry(raw=...)`, which already does normalize → redact → fingerprint → dedupe → store. So the new code is purely: profile model + JSONL extraction strategies + first-party host profiles + log discovery + PR-scope filtering + consent notice + a thin `final-gate` auto-discovery path. No downstream telemetry code changes.

**Tech Stack:** Python 3.10+, stdlib only (`json`, `re`, `glob`, `datetime`, `pathlib`). Tests use `unittest`: `PYTHONPATH=src python -m unittest <module>`.

**Scope (Plan A only):** Ships the `paired-correlation-timestamp` strategy + the Claude Code profile, then adds the generic `record-pair-timestamp` strategy + Codex native profile so first-party hosts use profile-driven `agent-jsonl` projection without adding final-gate host branches. The explicit `codex-host-json` adapter remains supported for aggregate Codex exports. OTel increments (`error_type`, `parent_event_id`, fingerprint-repeat flag, profile validator) are **Plan B**.

**Reference spec:** `docs/superpowers/specs/2026-06-21-phase2-host-telemetry-design.md`.

---

## File Structure

| File | Responsibility |
|---|---|
| Create `src/gh_address_cr/core/host_telemetry/__init__.py` | Package marker + public re-exports |
| Create `src/gh_address_cr/core/host_telemetry/profile.py` | `HostProfile` dataclass + JSON loader |
| Create `src/gh_address_cr/core/host_telemetry/strategies.py` | `paired_correlation_timestamp` extractor → agent-jsonl events (dicts) |
| Create `src/gh_address_cr/core/host_telemetry/discovery.py` | Resolve transcript path + active session id from cwd; consent notice |
| Create `src/gh_address_cr/core/host_telemetry/attribution.py` | PR-scope time-window + session filter; read session `created_at` |
| Create `src/gh_address_cr/core/host_telemetry/capture.py` | Orchestrator: discover → extract → scope → emit agent-jsonl text + summary |
| Create `src/gh_address_cr/core/host_telemetry/profiles/claude_code.json` | First-party Claude Code profile |
| Modify `src/gh_address_cr/commands/final_gate.py` | Add `ingest_host_telemetry_via_autodiscovery`, call it when env INPUT unset and AUTO not disabled |
| Create `tests/core/test_host_telemetry.py` | Unit + integration tests |
| Create `tests/fixtures/host_telemetry/claude-code-sample.jsonl` | Synthetic transcript fixture |
| Modify `specs/015-external-agent-telemetry/acceptance-matrix.md` | Cite new host-hook tests |

**Baseline (run before starting):**
Run: `PYTHONPATH=src python -m unittest tests.core.test_telemetry tests.test_final_gate -v`
Expected: OK.

---

## Task 1: Host profile model + JSON loader

**Files:**
- Create: `src/gh_address_cr/core/host_telemetry/__init__.py`
- Create: `src/gh_address_cr/core/host_telemetry/profile.py`
- Test: `tests/core/test_host_telemetry.py`

- [ ] **Step 1: Create the package marker**

Create `src/gh_address_cr/core/host_telemetry/__init__.py`:

```python
"""Host telemetry auto-capture: native session log -> agent-jsonl text.

Output is fed to core.telemetry.import_external_telemetry; this package never
touches the ingest/normalize/redact/fingerprint pipeline directly.
"""
```

- [ ] **Step 2: Write the failing test**

Create `tests/core/test_host_telemetry.py`:

```python
import json
import tempfile
import unittest
from pathlib import Path

from gh_address_cr.core.host_telemetry.profile import HostProfile, load_profile


class HostProfileTests(unittest.TestCase):
    def _write(self, tmp, payload):
        path = Path(tmp) / "p.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_load_minimal_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, {
                "profile_version": "1.0",
                "source": "claude-code",
                "strategy": "paired-correlation-timestamp",
                "discovery": {"glob": "~/.claude/projects/{project_slug}/*.jsonl", "project_slug_from": "cwd"},
                "record": {"container": "jsonl-lines", "session_id_path": "sessionId"},
                "fields": {"timestamp_path": "timestamp"},
                "kind_classification": {"default": "tool_call", "wait": ["AskUserQuestion"]},
                "safety_allowlist": ["operation", "status", "timestamp"],
                "scope_attribution": {"mode": "active-pr-time-window"},
            })
            profile = load_profile(path)
            self.assertEqual(profile.source, "claude-code")
            self.assertEqual(profile.strategy, "paired-correlation-timestamp")
            self.assertEqual(profile.kind_for("AskUserQuestion"), "wait")
            self.assertEqual(profile.kind_for("Bash"), "tool_call")

    def test_load_rejects_missing_required_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, {"source": "x"})
            with self.assertRaises(ValueError):
                load_profile(path)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `PYTHONPATH=src python -m unittest tests.core.test_host_telemetry.HostProfileTests -v`
Expected: FAIL — `ModuleNotFoundError: gh_address_cr.core.host_telemetry.profile`.

- [ ] **Step 4: Implement the profile model**

Create `src/gh_address_cr/core/host_telemetry/profile.py`:

```python
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_REQUIRED_KEYS = ("source", "strategy", "discovery", "record", "fields", "safety_allowlist")


@dataclass(frozen=True)
class HostProfile:
    source: str
    strategy: str
    discovery: dict[str, Any]
    record: dict[str, Any]
    fields: dict[str, Any]
    safety_allowlist: tuple[str, ...]
    kind_classification: dict[str, Any] = field(default_factory=dict)
    scope_attribution: dict[str, Any] = field(default_factory=dict)
    profile_version: str = "1.0"

    def kind_for(self, operation: str) -> str:
        kc = self.kind_classification or {}
        if operation in (kc.get("wait") or []):
            return "wait"
        by_op = kc.get("by_operation") or {}
        if operation in by_op:
            return str(by_op[operation])
        return str(kc.get("default") or "tool_call")


def load_profile(path: Path) -> HostProfile:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid host profile: {exc}") from None
    if not isinstance(payload, dict):
        raise ValueError("host profile must be a JSON object")
    missing = [k for k in _REQUIRED_KEYS if k not in payload]
    if missing:
        raise ValueError(f"host profile missing required key(s): {', '.join(missing)}")
    return HostProfile(
        source=str(payload["source"]),
        strategy=str(payload["strategy"]),
        discovery=dict(payload["discovery"]),
        record=dict(payload["record"]),
        fields=dict(payload["fields"]),
        safety_allowlist=tuple(str(x) for x in payload["safety_allowlist"]),
        kind_classification=dict(payload.get("kind_classification") or {}),
        scope_attribution=dict(payload.get("scope_attribution") or {}),
        profile_version=str(payload.get("profile_version") or "1.0"),
    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `PYTHONPATH=src python -m unittest tests.core.test_host_telemetry.HostProfileTests -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add src/gh_address_cr/core/host_telemetry/__init__.py src/gh_address_cr/core/host_telemetry/profile.py tests/core/test_host_telemetry.py
git commit -m "feat(host-telemetry): add HostProfile model and JSON loader"
```

---

## Task 2: `paired-correlation-timestamp` extraction strategy

**Files:**
- Create: `src/gh_address_cr/core/host_telemetry/strategies.py`
- Test: `tests/core/test_host_telemetry.py`

The strategy turns transcript JSONL lines into agent-jsonl event dicts. It pairs `tool_use`→`tool_result` by id, derives duration from timestamps, classifies kind, and emits **only allowlisted fields**. Unpaired `tool_use` → event with no duration (Phase 0 reports it honestly). Returns `(events, stats)` where stats carries pairing counts for the health check (Task 6).

- [ ] **Step 1: Write the failing test**

Append to `tests/core/test_host_telemetry.py`:

```python
from gh_address_cr.core.host_telemetry.profile import HostProfile
from gh_address_cr.core.host_telemetry.strategies import paired_correlation_timestamp


def _cc_profile():
    return HostProfile(
        source="claude-code",
        strategy="paired-correlation-timestamp",
        discovery={},
        record={"container": "jsonl-lines", "session_id_path": "sessionId"},
        fields={
            "event_blocks_path": "message.content[]",
            "tool_use": {"match": {"type": "tool_use"}, "id_path": "id", "operation_path": "name"},
            "tool_result": {"match": {"type": "tool_result"}, "correlation_path": "tool_use_id",
                            "status_path": "is_error", "status_map": {"true": "failure", "false": "success"}},
            "timestamp_path": "timestamp",
        },
        kind_classification={"default": "tool_call", "wait": ["AskUserQuestion"], "by_operation": {"Bash": "command"}},
        safety_allowlist=("operation", "status", "timestamp", "correlation_id"),
    )


class PairedStrategyTests(unittest.TestCase):
    def _lines(self):
        return [
            {"sessionId": "s1", "timestamp": "2026-06-21T10:00:00Z",
             "message": {"content": [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "secret"}}]}},
            {"sessionId": "s1", "timestamp": "2026-06-21T10:00:02Z",
             "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "is_error": False, "content": "SECRET OUTPUT"}]}},
            {"sessionId": "s1", "timestamp": "2026-06-21T10:00:05Z",
             "message": {"content": [{"type": "tool_use", "id": "t2", "name": "AskUserQuestion", "input": {}}]}},
            {"sessionId": "s1", "timestamp": "2026-06-21T10:00:35Z",
             "message": {"content": [{"type": "tool_result", "tool_use_id": "t2", "is_error": True}]}},
        ]

    def test_pairs_and_derives_duration(self):
        events, stats = paired_correlation_timestamp(self._lines(), _cc_profile(), session_id="s1")
        by_op = {e["operation"]: e for e in events}
        self.assertEqual(by_op["Bash"]["duration_ms"], 2000)
        self.assertEqual(by_op["Bash"]["status"], "success")
        self.assertEqual(by_op["Bash"]["kind"], "command")
        self.assertEqual(by_op["AskUserQuestion"]["duration_ms"], 30000)
        self.assertEqual(by_op["AskUserQuestion"]["status"], "failure")
        self.assertEqual(by_op["AskUserQuestion"]["kind"], "wait")
        self.assertEqual(stats["tool_use_seen"], 2)
        self.assertEqual(stats["paired"], 2)

    def test_never_emits_input_or_content(self):
        events, _ = paired_correlation_timestamp(self._lines(), _cc_profile(), session_id="s1")
        blob = json.dumps(events)
        self.assertNotIn("secret", blob)
        self.assertNotIn("SECRET OUTPUT", blob)
        for e in events:
            self.assertNotIn("input", e)
            self.assertNotIn("content", e)

    def test_filters_other_sessions(self):
        lines = self._lines() + [
            {"sessionId": "other", "timestamp": "2026-06-21T10:00:00Z",
             "message": {"content": [{"type": "tool_use", "id": "x", "name": "Bash"}]}},
        ]
        events, stats = paired_correlation_timestamp(lines, _cc_profile(), session_id="s1")
        self.assertEqual(stats["tool_use_seen"], 2)  # the 'other' session tool_use is excluded
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python -m unittest tests.core.test_host_telemetry.PairedStrategyTests -v`
Expected: FAIL — `ImportError: cannot import name 'paired_correlation_timestamp'`.

- [ ] **Step 3: Implement the strategy**

Create `src/gh_address_cr/core/host_telemetry/strategies.py`:

```python
from __future__ import annotations

from datetime import datetime
from typing import Any

from gh_address_cr.core.host_telemetry.profile import HostProfile


def _parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _blocks(line: dict[str, Any]) -> list[dict[str, Any]]:
    # event_blocks_path is fixed to message.content[] for this strategy.
    message = line.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    return [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []


def paired_correlation_timestamp(
    lines: list[dict[str, Any]],
    profile: HostProfile,
    *,
    session_id: str,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    f = profile.fields
    tu = f["tool_use"]
    tr = f["tool_result"]
    ts_path = f["timestamp_path"]
    status_map = {str(k): str(v) for k, v in (tr.get("status_map") or {}).items()}

    starts: dict[str, dict[str, Any]] = {}
    results: dict[str, dict[str, Any]] = {}
    sid_path = profile.record.get("session_id_path", "sessionId")

    for line in lines:
        if str(line.get(sid_path) or "") != session_id:
            continue
        when = _parse_ts(line.get(ts_path))
        for block in _blocks(line):
            btype = block.get("type")
            if btype == tu["match"].get("type"):
                starts[str(block.get(tu["id_path"]))] = {
                    "operation": str(block.get(tu["operation_path"]) or "unknown"),
                    "ts": when,
                }
            elif btype == tr["match"].get("type"):
                results[str(block.get(tr["correlation_path"]))] = {
                    "is_error": block.get(tr["status_path"]),
                    "ts": when,
                }

    events: list[dict[str, Any]] = []
    paired = 0
    for tool_id, start in starts.items():
        operation = start["operation"]
        event: dict[str, Any] = {
            "schema_version": "1.0",
            "source": profile.source,
            "source_session_id": session_id,
            "event_id": tool_id,
            "kind": profile.kind_for(operation),
            "operation": operation,
            "status": "unknown",
            "correlation_id": tool_id,
        }
        result = results.get(tool_id)
        if result is not None:
            paired += 1
            key = str(bool(result.get("is_error"))).lower()
            event["status"] = status_map.get(key, "unknown")
            if start["ts"] is not None and result["ts"] is not None:
                event["duration_ms"] = max(0, int((result["ts"] - start["ts"]).total_seconds() * 1000))
        events.append(event)

    stats = {"tool_use_seen": len(starts), "paired": paired}
    return events, stats
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src python -m unittest tests.core.test_host_telemetry.PairedStrategyTests -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/gh_address_cr/core/host_telemetry/strategies.py tests/core/test_host_telemetry.py
git commit -m "feat(host-telemetry): paired-correlation-timestamp strategy with allowlist + kind classification"
```

---

## Task 3: PR-scope attribution (time-window + session)

**Files:**
- Create: `src/gh_address_cr/core/host_telemetry/attribution.py`
- Test: `tests/core/test_host_telemetry.py`

Reads the PR session `created_at` from `session.json` and produces the attribution window `[created_at, now]`. Filters transcript lines to that window (a line with no/invalid timestamp is excluded). Also detects multiple session ids in-window for the ambiguity guard.

- [ ] **Step 1: Write the failing test**

Append to `tests/core/test_host_telemetry.py`:

```python
from gh_address_cr.core.host_telemetry.attribution import lines_in_window, distinct_sessions_in_window


class AttributionTests(unittest.TestCase):
    def _lines(self):
        return [
            {"sessionId": "s1", "timestamp": "2026-06-21T10:00:30Z"},  # in window
            {"sessionId": "s1", "timestamp": "2026-06-21T09:59:00Z"},  # before window
            {"sessionId": "s1", "timestamp": "not-a-date"},            # unparseable -> excluded
        ]

    def test_window_filters_by_time(self):
        kept = lines_in_window(self._lines(), start_iso="2026-06-21T10:00:00Z", now_iso="2026-06-21T10:01:00Z")
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["timestamp"], "2026-06-21T10:00:30Z")

    def test_distinct_sessions_detects_ambiguity(self):
        lines = self._lines() + [{"sessionId": "s2", "timestamp": "2026-06-21T10:00:40Z"}]
        sessions = distinct_sessions_in_window(lines, start_iso="2026-06-21T10:00:00Z",
                                               now_iso="2026-06-21T10:01:00Z", session_id_path="sessionId")
        self.assertEqual(sessions, {"s1", "s2"})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python -m unittest tests.core.test_host_telemetry.AttributionTests -v`
Expected: FAIL — `ModuleNotFoundError: ...attribution`.

- [ ] **Step 3: Implement attribution**

Create `src/gh_address_cr/core/host_telemetry/attribution.py`:

```python
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from gh_address_cr.core import paths as core_paths


def _parse(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def session_created_at(repo: str, pr_number: str) -> str | None:
    try:
        payload = json.loads(core_paths.session_file(repo, pr_number).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    value = payload.get("created_at") if isinstance(payload, dict) else None
    return value if isinstance(value, str) else None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def lines_in_window(lines: list[dict[str, Any]], *, start_iso: str, now_iso: str) -> list[dict[str, Any]]:
    start, end = _parse(start_iso), _parse(now_iso)
    if start is None or end is None:
        return []
    kept = []
    for line in lines:
        when = _parse(line.get("timestamp"))
        if when is not None and start <= when <= end:
            kept.append(line)
    return kept


def distinct_sessions_in_window(
    lines: list[dict[str, Any]], *, start_iso: str, now_iso: str, session_id_path: str
) -> set[str]:
    return {
        str(line.get(session_id_path))
        for line in lines_in_window(lines, start_iso=start_iso, now_iso=now_iso)
        if line.get(session_id_path)
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src python -m unittest tests.core.test_host_telemetry.AttributionTests -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/gh_address_cr/core/host_telemetry/attribution.py tests/core/test_host_telemetry.py
git commit -m "feat(host-telemetry): PR-scope time-window attribution + ambiguity detection"
```

---

## Task 4: Claude Code profile + transcript discovery + consent

**Files:**
- Create: `src/gh_address_cr/core/host_telemetry/profiles/claude_code.json`
- Create: `src/gh_address_cr/core/host_telemetry/discovery.py`
- Test: `tests/core/test_host_telemetry.py`

Claude Code stores transcripts at `~/.claude/projects/<slug>/<session>.jsonl`, where `<slug>` is the cwd with `/` replaced by `-`. Discovery resolves the slug from cwd, globs the dir, and returns the most-recently-modified transcript. Consent prints a one-time stderr notice gated by a marker file in the state dir.

- [ ] **Step 1: Create the Claude Code profile JSON**

Create `src/gh_address_cr/core/host_telemetry/profiles/claude_code.json`:

```json
{
  "profile_version": "1.0",
  "source": "claude-code",
  "format": "claude-code-transcript",
  "discovery": { "glob": "~/.claude/projects/{project_slug}/*.jsonl", "project_slug_from": "cwd" },
  "record": { "container": "jsonl-lines", "session_id_path": "sessionId" },
  "strategy": "paired-correlation-timestamp",
  "fields": {
    "event_blocks_path": "message.content[]",
    "tool_use": { "match": {"type": "tool_use"}, "id_path": "id", "operation_path": "name" },
    "tool_result": { "match": {"type": "tool_result"}, "correlation_path": "tool_use_id",
                     "status_path": "is_error", "status_map": {"true": "failure", "false": "success"} },
    "timestamp_path": "timestamp"
  },
  "kind_classification": {
    "default": "tool_call",
    "wait": ["AskUserQuestion", "ExitPlanMode"],
    "by_operation": { "Bash": "command" }
  },
  "safety_allowlist": ["operation", "status", "timestamp", "correlation_id"],
  "scope_attribution": { "mode": "active-pr-time-window" }
}
```

Note: this JSON is package data. Ensure `pyproject.toml` includes it in the wheel. Check the existing `[tool.setuptools.package-data]` / `include` config; if package-data is not already globbed, add `"gh_address_cr.core.host_telemetry.profiles" = ["*.json"]` (verify against the current packaging test `tests/test_runtime_packaging.py` expectations and run it after).

- [ ] **Step 2: Write the failing discovery test**

Append to `tests/core/test_host_telemetry.py`:

```python
from gh_address_cr.core.host_telemetry.discovery import project_slug_from_cwd, discover_transcript, consent_notice_once


class DiscoveryTests(unittest.TestCase):
    def test_project_slug_replaces_separators(self):
        self.assertEqual(project_slug_from_cwd("/Users/me/Documents/GitHub/repo"),
                         "-Users-me-Documents-GitHub-repo")

    def test_discover_picks_newest_transcript(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "proj"
            d.mkdir()
            old = d / "old.jsonl"; old.write_text("{}", encoding="utf-8")
            new = d / "new.jsonl"; new.write_text("{}", encoding="utf-8")
            import os, time
            os.utime(old, (1, 1))
            os.utime(new, (time.time(), time.time()))
            found = discover_transcript(str(d / "*.jsonl"))
            self.assertEqual(found, new)

    def test_consent_notice_only_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "consent.marker"
            self.assertTrue(consent_notice_once("claude-code", marker))   # first time -> notice shown
            self.assertFalse(consent_notice_once("claude-code", marker))  # second time -> suppressed
```

- [ ] **Step 3: Run test to verify it fails**

Run: `PYTHONPATH=src python -m unittest tests.core.test_host_telemetry.DiscoveryTests -v`
Expected: FAIL — `ModuleNotFoundError: ...discovery`.

- [ ] **Step 4: Implement discovery + consent**

Create `src/gh_address_cr/core/host_telemetry/discovery.py`:

```python
from __future__ import annotations

import glob as globlib
import os
import sys
from pathlib import Path


def project_slug_from_cwd(cwd: str) -> str:
    # Claude Code slug = absolute cwd with path separators replaced by '-'.
    return cwd.replace("/", "-")


def resolve_glob(pattern: str, *, project_slug: str) -> str:
    expanded = os.path.expanduser(pattern.replace("{project_slug}", project_slug))
    return expanded


def discover_transcript(resolved_glob: str) -> Path | None:
    matches = [Path(p) for p in globlib.glob(resolved_glob)]
    matches = [p for p in matches if p.is_file()]
    if not matches:
        return None
    return max(matches, key=lambda p: p.stat().st_mtime)


def consent_notice_once(source: str, marker: Path) -> bool:
    """Print a one-time consent notice. Returns True if shown this call."""
    if marker.exists():
        return False
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("acknowledged\n", encoding="utf-8")
    except OSError:
        return False
    sys.stderr.write(
        f"gh-address-cr: detected {source} session transcript; reading "
        "operation/status/timing only (no prompts, file contents, or tokens) "
        "for efficiency telemetry. Opt out: GH_ADDRESS_CR_HOST_TELEMETRY_AUTO=0. "
        "This notice is shown once.\n"
    )
    return True
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `PYTHONPATH=src python -m unittest tests.core.test_host_telemetry.DiscoveryTests -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add src/gh_address_cr/core/host_telemetry/profiles/claude_code.json src/gh_address_cr/core/host_telemetry/discovery.py tests/core/test_host_telemetry.py
git commit -m "feat(host-telemetry): Claude Code profile, transcript discovery, one-time consent"
```

---

## Task 5: Capture orchestrator (discover → extract → scope → agent-jsonl) + health check

**Files:**
- Create: `src/gh_address_cr/core/host_telemetry/capture.py`
- Test: `tests/core/test_host_telemetry.py`

Ties the pieces together and returns `(agent_jsonl_text, outcome)` where `outcome` is one of `captured` / `unavailable` / `ambiguous` / `degraded`. The health check (R3): if `tool_use_seen > 0` and `paired / tool_use_seen < 0.5`, return `degraded` (the strategy assumptions likely broke) so the caller emits a hook-unavailable diagnostic rather than trusting partial data.

- [ ] **Step 1: Write the failing test**

Append to `tests/core/test_host_telemetry.py`:

```python
from gh_address_cr.core.host_telemetry.capture import capture_agent_jsonl


class CaptureTests(unittest.TestCase):
    def _transcript(self, path):
        rows = [
            {"sessionId": "s1", "timestamp": "2026-06-21T10:00:00Z",
             "message": {"content": [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "x"}}]}},
            {"sessionId": "s1", "timestamp": "2026-06-21T10:00:02Z",
             "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "is_error": False}]}},
        ]
        path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")

    def test_capture_produces_agent_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp) / "s1.jsonl"
            self._transcript(t)
            text, outcome = capture_agent_jsonl(
                _cc_profile(), transcript=t, session_id="s1",
                start_iso="2026-06-21T09:59:00Z", now_iso="2026-06-21T10:01:00Z",
            )
            self.assertEqual(outcome, "captured")
            line = json.loads(text.splitlines()[0])
            self.assertEqual(line["operation"], "Bash")
            self.assertEqual(line["duration_ms"], 2000)
            self.assertNotIn("input", text)

    def test_capture_degraded_when_pairing_low(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp) / "s1.jsonl"
            # two tool_use, zero tool_result -> 0% pairing
            rows = [
                {"sessionId": "s1", "timestamp": "2026-06-21T10:00:00Z",
                 "message": {"content": [{"type": "tool_use", "id": "a", "name": "Bash"}]}},
                {"sessionId": "s1", "timestamp": "2026-06-21T10:00:01Z",
                 "message": {"content": [{"type": "tool_use", "id": "b", "name": "Edit"}]}},
            ]
            t.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
            text, outcome = capture_agent_jsonl(
                _cc_profile(), transcript=t, session_id="s1",
                start_iso="2026-06-21T09:59:00Z", now_iso="2026-06-21T10:01:00Z",
            )
            self.assertEqual(outcome, "degraded")
            self.assertEqual(text, "")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python -m unittest tests.core.test_host_telemetry.CaptureTests -v`
Expected: FAIL — `ModuleNotFoundError: ...capture`.

- [ ] **Step 3: Implement the orchestrator**

Create `src/gh_address_cr/core/host_telemetry/capture.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from gh_address_cr.core.host_telemetry.attribution import lines_in_window
from gh_address_cr.core.host_telemetry.profile import HostProfile
from gh_address_cr.core.host_telemetry.strategies import paired_correlation_timestamp

_MIN_PAIRING_RATIO = 0.5
_STRATEGIES = {"paired-correlation-timestamp": paired_correlation_timestamp}


def _read_lines(path: Path) -> list[dict]:
    out = []
    try:
        for raw in Path(path).read_text(encoding="utf-8").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                out.append(obj)
    except OSError:
        return []
    return out


def capture_agent_jsonl(
    profile: HostProfile,
    *,
    transcript: Path,
    session_id: str,
    start_iso: str,
    now_iso: str,
) -> tuple[str, str]:
    strategy = _STRATEGIES.get(profile.strategy)
    if strategy is None:
        return "", "unavailable"
    all_lines = _read_lines(transcript)
    scoped = lines_in_window(all_lines, start_iso=start_iso, now_iso=now_iso)
    if not scoped:
        return "", "unavailable"
    events, stats = strategy(scoped, profile, session_id=session_id)
    seen = stats.get("tool_use_seen", 0)
    if seen > 0 and (stats.get("paired", 0) / seen) < _MIN_PAIRING_RATIO:
        return "", "degraded"
    if not events:
        return "", "unavailable"
    text = "\n".join(json.dumps(e, sort_keys=True) for e in events)
    return text, "captured"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src python -m unittest tests.core.test_host_telemetry.CaptureTests -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/gh_address_cr/core/host_telemetry/capture.py tests/core/test_host_telemetry.py
git commit -m "feat(host-telemetry): capture orchestrator with pairing-ratio health check"
```

---

## Task 6: Wire auto-discovery into final-gate

**Files:**
- Modify: `src/gh_address_cr/commands/final_gate.py` (add function near line 163; call near line 72)
- Test: `tests/core/test_host_telemetry.py`

Precedence: explicit `GH_ADDRESS_CR_HOST_TELEMETRY_INPUT` wins (existing behavior, untouched). Otherwise, if `GH_ADDRESS_CR_HOST_TELEMETRY_AUTO != "0"`, attempt auto-discovery. Every failure path is fail-open and returns without raising.

- [ ] **Step 1: Write the failing integration test**

Append to `tests/core/test_host_telemetry.py`:

```python
from unittest.mock import patch
from gh_address_cr.core import paths as core_paths


class FinalGateAutodiscoveryTests(unittest.TestCase):
    def _seed_session(self, state, repo, pr, created_at):
        wd = core_paths.workspace_dir(repo, pr)
        wd.mkdir(parents=True, exist_ok=True)
        core_paths.session_file(repo, pr).write_text(json.dumps({"created_at": created_at}), encoding="utf-8")

    @patch("gh_address_cr.commands.final_gate.host_capture.discover_transcript")
    @patch("gh_address_cr.commands.final_gate.core_paths.state_dir")
    def test_autodiscovery_ingests_when_enabled(self, state_dir, discover):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            self._seed_session(tmp, "octo/example", "5", "2026-06-21T09:59:00Z")
            transcript = Path(tmp) / "s1.jsonl"
            rows = [
                {"sessionId": "s1", "timestamp": "2026-06-21T10:00:00Z",
                 "message": {"content": [{"type": "tool_use", "id": "t1", "name": "Bash"}]}},
                {"sessionId": "s1", "timestamp": "2026-06-21T10:00:03Z",
                 "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "is_error": False}]}},
            ]
            transcript.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
            discover.return_value = transcript

            from gh_address_cr.commands import final_gate
            env = {"GH_ADDRESS_CR_HOST_TELEMETRY_AUTO": "1", "SESSION_ID": "s1"}
            with patch.dict("os.environ", env, clear=False), \
                 patch.dict("os.environ", {"GH_ADDRESS_CR_HOST_TELEMETRY_INPUT": ""}, clear=False):
                summary = final_gate.ingest_host_telemetry_via_autodiscovery("octo/example", "5", session_id="s1")
            self.assertIsNotNone(summary)
            self.assertIn(summary["status"], {"SUCCESS", "PARTIAL"})

    @patch("gh_address_cr.commands.final_gate.core_paths.state_dir")
    def test_autodiscovery_skipped_when_disabled(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            from gh_address_cr.commands import final_gate
            with patch.dict("os.environ", {"GH_ADDRESS_CR_HOST_TELEMETRY_AUTO": "0"}, clear=False):
                self.assertIsNone(final_gate.ingest_host_telemetry_via_autodiscovery("octo/example", "5", session_id="s1"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python -m unittest tests.core.test_host_telemetry.FinalGateAutodiscoveryTests -v`
Expected: FAIL — `AttributeError: module 'gh_address_cr.commands.final_gate' has no attribute 'ingest_host_telemetry_via_autodiscovery'`.

- [ ] **Step 3: Add imports and the auto-discovery function to final_gate.py**

In `src/gh_address_cr/commands/final_gate.py`, add to the imports near the top (after the existing `core_telemetry` / `core_paths` imports):

```python
from gh_address_cr.core.host_telemetry import capture as host_capture
from gh_address_cr.core.host_telemetry import attribution as host_attribution
from gh_address_cr.core.host_telemetry import discovery as host_discovery
from gh_address_cr.core.host_telemetry import profile as host_profile
```

Add the resolver + function (place after `ingest_host_telemetry_from_environment`, ~line 173). The session id is read from the `SESSION_ID` env Claude Code sets; if absent, auto-discovery is skipped (fail-open):

```python
AUTO_ENV = "GH_ADDRESS_CR_HOST_TELEMETRY_AUTO"
_CLAUDE_CODE_PROFILE = (
    Path(__file__).resolve().parents[1] / "core" / "host_telemetry" / "profiles" / "claude_code.json"
)


def _autodiscovery_session_id() -> str | None:
    value = os.environ.get("SESSION_ID")
    return value or None


def ingest_host_telemetry_via_autodiscovery(repo: str, pr_number: str, *, session_id: str | None = None) -> dict | None:
    if os.environ.get(HOST_TELEMETRY_INPUT_ENV):
        return None  # explicit input wins; handled elsewhere
    if os.environ.get(AUTO_ENV) == "0":
        return None
    session_id = session_id or _autodiscovery_session_id()
    if not session_id:
        return None
    try:
        profile = host_profile.load_profile(_CLAUDE_CODE_PROFILE)
        slug = host_discovery.project_slug_from_cwd(os.getcwd())
        resolved = host_discovery.resolve_glob(profile.discovery["glob"], project_slug=slug)
        transcript = host_discovery.discover_transcript(resolved)
        if transcript is None:
            return None
        start_iso = host_attribution.session_created_at(repo, pr_number)
        now_iso = host_attribution.now_iso()
        if not start_iso:
            return None
        all_lines = host_capture._read_lines(transcript)
        sid_path = profile.record.get("session_id_path", "sessionId")
        sessions = host_attribution.distinct_sessions_in_window(
            all_lines, start_iso=start_iso, now_iso=now_iso, session_id_path=sid_path
        )
        if len(sessions) > 1:
            return safe_hook_unavailable_import_summary(repo, pr_number, source=profile.source, fmt="agent-jsonl")
        text, outcome = host_capture.capture_agent_jsonl(
            profile, transcript=transcript, session_id=session_id, start_iso=start_iso, now_iso=now_iso
        )
        if outcome != "captured" or not text:
            if outcome == "degraded":
                return safe_hook_unavailable_import_summary(repo, pr_number, source=profile.source, fmt="agent-jsonl")
            return None
        marker = core_paths.state_dir() / ".host-telemetry-consent" / f"{profile.source}.marker"
        host_discovery.consent_notice_once(profile.source, marker)
        return core_telemetry.import_external_telemetry(
            repo, pr_number, source=profile.source, fmt="agent-jsonl", raw=text
        )
    except Exception:
        return safe_hook_unavailable_import_summary(repo, pr_number, source="claude-code", fmt="agent-jsonl")
```

Confirm `from pathlib import Path` and `import os` are already imported in `final_gate.py` (they are used by existing code); if not, add them.

- [ ] **Step 4: Call auto-discovery from handle_final_gate**

In `handle_final_gate`, find the existing line (~72):

```python
    ingest_host_telemetry_from_environment(parsed.repo, parsed.pr_number)
```

Replace with:

```python
    if ingest_host_telemetry_from_environment(parsed.repo, parsed.pr_number) is None:
        ingest_host_telemetry_via_autodiscovery(parsed.repo, parsed.pr_number)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `PYTHONPATH=src python -m unittest tests.core.test_host_telemetry.FinalGateAutodiscoveryTests -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add src/gh_address_cr/commands/final_gate.py tests/core/test_host_telemetry.py
git commit -m "feat(host-telemetry): wire auto-discovery into final-gate with env precedence and fail-open"
```

---

## Task 7: End-to-end report proof + acceptance matrix

**Files:**
- Create: `tests/fixtures/host_telemetry/claude-code-sample.jsonl`
- Modify: `tests/core/test_host_telemetry.py`
- Modify: `specs/015-external-agent-telemetry/acceptance-matrix.md`

- [ ] **Step 1: Create the synthetic transcript fixture**

Create `tests/fixtures/host_telemetry/claude-code-sample.jsonl` (note: `tests/fixtures/*` are data dirs — do NOT add `__init__.py`):

```
{"sessionId": "sess-e2e", "timestamp": "2026-06-21T10:00:00Z", "message": {"content": [{"type": "tool_use", "id": "u1", "name": "Bash", "input": {"command": "DO NOT LEAK"}}]}}
{"sessionId": "sess-e2e", "timestamp": "2026-06-21T10:00:04Z", "message": {"content": [{"type": "tool_result", "tool_use_id": "u1", "is_error": false, "content": "DO NOT LEAK OUTPUT"}]}}
{"sessionId": "sess-e2e", "timestamp": "2026-06-21T10:00:05Z", "message": {"content": [{"type": "tool_use", "id": "u2", "name": "AskUserQuestion", "input": {}}]}}
{"sessionId": "sess-e2e", "timestamp": "2026-06-21T10:00:35Z", "message": {"content": [{"type": "tool_result", "tool_use_id": "u2", "is_error": false}]}}
```

- [ ] **Step 2: Write the failing end-to-end test**

Append to `tests/core/test_host_telemetry.py`:

```python
from gh_address_cr.core.telemetry import build_efficiency_report, SessionTelemetry


class EndToEndReportTests(unittest.TestCase):
    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_captured_transcript_flows_into_report(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            SessionTelemetry.reset()
            fixture = Path(__file__).resolve().parents[1] / "fixtures" / "host_telemetry" / "claude-code-sample.jsonl"
            text, outcome = capture_agent_jsonl(
                _cc_profile(), transcript=fixture, session_id="sess-e2e",
                start_iso="2026-06-21T09:59:00Z", now_iso="2026-06-21T10:01:00Z",
            )
            self.assertEqual(outcome, "captured")
            from gh_address_cr.core.telemetry import import_external_telemetry
            summary = import_external_telemetry("octo/example", "5", source="claude-code", fmt="agent-jsonl", raw=text)
            self.assertEqual(summary["status"], "SUCCESS")

            report = build_efficiency_report("octo/example", "5")
            self.assertTrue(report["duration_observed"])
            # Bash (command) is a real op; AskUserQuestion is wait. Slowest list excludes 0ms only.
            ops = {row["operation"]: row for row in report["slowest_operations"]}
            self.assertEqual(ops["Bash"]["duration_ms"], 4000)
            # Safety: no leaked content anywhere in the artifact
            self.assertNotIn("DO NOT LEAK", json.dumps(report))

    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_wait_kind_not_counted_as_command_failure(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            SessionTelemetry.reset()
            fixture = Path(__file__).resolve().parents[1] / "fixtures" / "host_telemetry" / "claude-code-sample.jsonl"
            text, _ = capture_agent_jsonl(
                _cc_profile(), transcript=fixture, session_id="sess-e2e",
                start_iso="2026-06-21T09:59:00Z", now_iso="2026-06-21T10:01:00Z",
            )
            line_kinds = {json.loads(l)["operation"]: json.loads(l)["kind"] for l in text.splitlines()}
            self.assertEqual(line_kinds["AskUserQuestion"], "wait")
            self.assertEqual(line_kinds["Bash"], "command")
```

- [ ] **Step 3: Run the end-to-end tests to verify they pass**

Run: `PYTHONPATH=src python -m unittest tests.core.test_host_telemetry.EndToEndReportTests -v`
Expected: PASS (2 tests). (Implementation already exists from Tasks 2-5; this proves the full chain.)

- [ ] **Step 4: Add acceptance-matrix citations**

In `specs/015-external-agent-telemetry/acceptance-matrix.md`, find the `host-hook` category row(s) and append to the evidence cell:

```
, `core.test_host_telemetry.EndToEndReportTests.test_captured_transcript_flows_into_report`, `core.test_host_telemetry.FinalGateAutodiscoveryTests.test_autodiscovery_skipped_when_disabled`
```

- [ ] **Step 5: Run the meta-test and the full suite**

Run: `PYTHONPATH=src python -m unittest tests.test_telemetry_acceptance_matrix tests.core.test_host_telemetry -v`
Then: `PYTHONPATH=src python -m unittest discover -s tests`
Expected: OK for both. If `tests.test_runtime_packaging` fails on the new JSON package data, add the package-data entry noted in Task 4 Step 1 and re-run.

- [ ] **Step 6: Commit**

```bash
git add tests/fixtures/host_telemetry/claude-code-sample.jsonl tests/core/test_host_telemetry.py specs/015-external-agent-telemetry/acceptance-matrix.md
git commit -m "test(host-telemetry): end-to-end transcript->report proof + acceptance matrix"
```

---

## Final verification

- [ ] **Full suite + lint**

Run: `PYTHONPATH=src python -m unittest discover -s tests`
Expected: OK.
Run: `ruff check src/gh_address_cr/core/host_telemetry src/gh_address_cr/commands/final_gate.py`
Expected: no findings.

- [ ] **Manual smoke (real transcript, this machine)**

```bash
PYTHONPATH=src python -m gh_address_cr final-gate <owner/repo> <pr_number> 2>&1 | head
gh-address-cr telemetry summary <owner/repo> <pr_number> --format markdown
```
Expected: when a Claude Code transcript exists for the cwd and a PR session exists, the summary shows `coverage_label: complete` or `runtime-only`+host events with real `wait`-excluded durations; the one-time consent notice prints on first run only.

---

## Self-Review (author checklist, completed)

- **Spec coverage:** §3 architecture → Tasks 1-6; §4 profile schema → Task 1+4; §5 strategy (`paired-correlation-timestamp`) → Task 2; §6 attribution → Task 3; §7 discovery+consent+default-on+R1 → Tasks 4,6; §9 fail-open + R3 health check → Tasks 5,6; §12 testing → every task + Task 7. **Deferred (stated):** §5 `flat-duration-field` (Codex already works), §8/§9 OTel increments, §10 mapping doc, R5 validator → Plan B.
- **Placeholder scan:** no TBD/TODO; all code complete. One conditional packaging step (Task 4 Step 1 / Task 7 Step 5) is gated on the existing packaging test and gives the exact entry to add.
- **Type consistency:** `capture_agent_jsonl(...) -> (str, str)` outcome strings `captured/unavailable/degraded` used identically in Task 5 and Task 6. `paired_correlation_timestamp(lines, profile, *, session_id) -> (events, stats)` with `stats={"tool_use_seen","paired"}` consistent across Tasks 2,5. Profile field names match `claude_code.json` (Task 4) and `_cc_profile()` test fixture (Task 2).
- **Risk boundaries:** no change to the ingest/normalize/redact/fingerprint pipeline; allowlist enforced at emit time (Task 2 `test_never_emits_input_or_content`) with redaction as backstop; every final-gate path fail-open; default-on gated by env opt-out + one-time consent.
