# Telemetry Timing & Honest Reporting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the efficiency report honest when no operation timing exists (Phase 0), and let agent-reported validation commands carry real durations through the existing timing-replay path (Phase 1), so daily `telemetry summary` produces non-zero, actionable timing instead of misleading `0ms`.

**Architecture:** Two minimal, additive changes that reuse machinery already present. Phase 0 touches only the report builder/renderer in `core/telemetry.py`: it stops presenting `0ms` slowest-operations as if they were measured, adds a `duration_observed` flag, and emits a `TELEMETRY_TIMING_UNAVAILABLE` diagnostic. Phase 1 extends the validation-command CLI shorthand parser in `core/agent_protocol.py` to accept an optional `@<n>ms`/`@<n>s` timing suffix; the downstream replay path (`agent_protocol.py:1083-1091`) and runtime→event conversion (`telemetry.py:_runtime_events`) already turn that duration into real `duration_ms`. Neither change alters fail-soft semantics, redaction, or network-write contracts.

**Tech Stack:** Python 3.10+, stdlib only (`re`, `time`). Tests use `unittest` (not pytest). Run with `PYTHONPATH=src python -m unittest <module>`.

**Status:** IMPLEMENTED on branch `feat/telemetry-timing-honest-reporting` (2026-06-21). Full suite 792 tests OK, ruff clean. This document is retained as the design-of-record for the change.

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `src/gh_address_cr/core/telemetry.py` | `build_efficiency_report` (≈863), `efficiency_report_markdown` (≈961) | Phase 0: compute `duration_observed`, build slowest-ops from timed events only, emit timing-unavailable diagnostic, render an honest note |
| `src/gh_address_cr/core/agent_protocol.py` | `_split_validation_command_record` (≈1399), `_normalize_validation_command_records` (≈1365) | Phase 1: parse optional `@<n>ms`/`@<n>s` suffix into a `duration` (seconds) on the validation record |
| `tests/core/test_telemetry.py` | Behavior tests for the report | Phase 0 + Phase 1 end-to-end timing tests |
| `tests/test_agent_protocol.py` | Validation-record parser tests | Phase 1 parser unit tests |
| `skill/SKILL.md` | Agent-facing usage contract | Phase 1: instruct agents to include `@<n>ms` timing on `--validation` |
| `docs/troubleshooting.md` | Operator diagnostics | Phase 0 + Phase 1: explain `0ms`/timing-unavailable and the timed shorthand |
| `specs/015-external-agent-telemetry/acceptance-matrix.md` | Spec-owned risk→test matrix | Cite the new statistics test under TM-007 |

**Verification baseline (run once before starting, to know the green baseline):**

Run: `PYTHONPATH=src python -m unittest tests.core.test_telemetry tests.test_agent_protocol tests.test_telemetry_acceptance_matrix -v`
Expected: OK (all pass).

---

## Phase 0 — Honest reporting when timing is absent

### Task 1: Report flags timing as unavailable instead of showing 0ms

**Files:**
- Modify: `src/gh_address_cr/core/telemetry.py` (`build_efficiency_report` ≈863-935, `efficiency_report_markdown` ≈961-990)
- Test: `tests/core/test_telemetry.py`

- [x] **Step 1: Write the failing tests**

Add to `tests/core/test_telemetry.py` (the file already imports `SessionTelemetry`, `build_efficiency_report`, `efficiency_report_markdown`, `tempfile`, `Path`, and patches `core_paths.state_dir`; mirror the existing `test_runtime_only_efficiency_report_has_coverage_and_artifact` pattern at line 167):

```python
    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_report_marks_timing_unavailable_when_all_durations_zero(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            tracker = SessionTelemetry.get_instance()
            tracker.configure_context("octo/example", "77")
            # start == end => duration 0 (the validation-backfill fallback case)
            tracker.record("ruff check", 100.0, 100.0, 0)
            tracker.record("python3 -m unittest discover -s tests", 100.0, 100.0, 0)

            report = build_efficiency_report("octo/example", "77")

            self.assertEqual(report["total_events"], 2)
            self.assertFalse(report["duration_observed"])
            self.assertEqual(report["total_observed_duration_ms"], 0)
            self.assertEqual(report["slowest_operations"], [])
            self.assertIn("TELEMETRY_TIMING_UNAVAILABLE", report["diagnostics"])

    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_report_keeps_timing_when_durations_present(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            tracker = SessionTelemetry.get_instance()
            tracker.configure_context("octo/example", "77")
            tracker.record("python3 -m unittest discover -s tests", 100.0, 102.0, 0)  # 2000ms

            report = build_efficiency_report("octo/example", "77")

            self.assertTrue(report["duration_observed"])
            self.assertEqual(report["total_observed_duration_ms"], 2000)
            self.assertEqual(len(report["slowest_operations"]), 1)
            self.assertEqual(report["slowest_operations"][0]["duration_ms"], 2000)
            self.assertNotIn("TELEMETRY_TIMING_UNAVAILABLE", report["diagnostics"])

    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_markdown_omits_slowest_and_notes_when_timing_unavailable(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            tracker = SessionTelemetry.get_instance()
            tracker.configure_context("octo/example", "77")
            tracker.record("ruff check", 100.0, 100.0, 0)

            report = build_efficiency_report("octo/example", "77")
            markdown = efficiency_report_markdown(report)

            self.assertNotIn("### Slowest Operations", markdown)
            self.assertIn("operation timing was not reported", markdown)
```

- [x] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src python -m unittest tests.core.test_telemetry -v -k timing`
Expected: FAIL — `KeyError: 'duration_observed'` (report has no such key yet), and the markdown assertion fails because the note string is absent.

- [x] **Step 3: Implement the report changes**

In `src/gh_address_cr/core/telemetry.py`, inside `build_efficiency_report`, replace the slowest/total computation block (currently around lines 891-893):

```python
    total_duration = sum(event.duration_ms for event in events)
    host_metrics = _aggregate_host_metrics(external_events)
    slowest = sorted(events, key=lambda event: event.duration_ms, reverse=True)[:3]
```

with:

```python
    total_duration = sum(event.duration_ms for event in events)
    duration_observed = any(event.duration_ms > 0 for event in events)
    host_metrics = _aggregate_host_metrics(external_events)
    timed_events = [event for event in events if event.duration_ms > 0]
    slowest = sorted(timed_events, key=lambda event: event.duration_ms, reverse=True)[:3]
    if events and not duration_observed and "TELEMETRY_TIMING_UNAVAILABLE" not in diagnostics:
        diagnostics.append("TELEMETRY_TIMING_UNAVAILABLE")
```

Then add `duration_observed` to the report dict. Insert one line in the `report = {...}` literal, immediately after the `"total_observed_duration_ms": total_duration,` line (currently line 906):

```python
        "duration_observed": duration_observed,
```

- [x] **Step 4: Implement the markdown note**

In `efficiency_report_markdown`, replace the slowest-operations block (currently lines 978-983):

```python
    if report["slowest_operations"]:
        lines.extend(["", "### Slowest Operations"])
        lines.extend(
            f"- {row['operation']} [{row['source']}]: {row['duration_ms']}ms ({row['status']})"
            for row in report["slowest_operations"]
        )
```

with:

```python
    if report["slowest_operations"]:
        lines.extend(["", "### Slowest Operations"])
        lines.extend(
            f"- {row['operation']} [{row['source']}]: {row['duration_ms']}ms ({row['status']})"
            for row in report["slowest_operations"]
        )
    elif report["total_events"] and not report.get("duration_observed", True):
        lines.extend(["", "_Note: operation timing was not reported; duration analysis is unavailable._"])
```

- [x] **Step 5: Run the new tests to verify they pass**

Run: `PYTHONPATH=src python -m unittest tests.core.test_telemetry -v -k timing`
Expected: PASS (3 tests).

- [x] **Step 6: Run the full telemetry suite to check for contract regressions**

Run: `PYTHONPATH=src python -m unittest tests.core.test_telemetry tests.test_final_gate tests.test_issue78_agent_experience tests.test_telemetry_acceptance_matrix -v`
Expected: OK. If `test_host_source_and_error_prone_operations_are_reported` or any slowest-operations assertion fails, the cause is that a previously-listed `0ms` runtime event no longer appears in `slowest_operations`; update that test's expectation to reflect timed-only slowest operations (this is the intended behavior change), then re-run.

- [ ] **Step 7: Commit**

```bash
git add src/gh_address_cr/core/telemetry.py tests/core/test_telemetry.py
git commit -m "fix(telemetry): report timing-unavailable instead of misleading 0ms slowest ops"
```

### Task 2: Cite the new statistics test in the acceptance matrix

**Files:**
- Modify: `specs/015-external-agent-telemetry/acceptance-matrix.md` (TM-007 statistics row)
- Test: `tests/test_telemetry_acceptance_matrix.py` (meta-test, no edit)

- [x] **Step 1: Append the new test to the TM-007 evidence cell**

In `specs/015-external-agent-telemetry/acceptance-matrix.md`, find the `| TM-007 | statistics |` row. Append to its existing comma-separated evidence list (inside the final table cell, before the closing `|`):

```
, `core.test_telemetry.TestTelemetry.test_report_marks_timing_unavailable_when_all_durations_zero`
```

- [x] **Step 2: Run the meta-test to verify the citation resolves**

Run: `PYTHONPATH=src python -m unittest tests.test_telemetry_acceptance_matrix -v`
Expected: OK — the cited test method exists and the matrix still has exactly the required categories with unique ids.

- [ ] **Step 3: Commit**

```bash
git add specs/015-external-agent-telemetry/acceptance-matrix.md
git commit -m "docs(telemetry): cite timing-unavailable test in acceptance matrix"
```

---

## Phase 1 — Carry validation timing through the existing replay path

### Task 3: Parse an optional `@<n>ms` / `@<n>s` timing suffix on validation shorthand

**Files:**
- Modify: `src/gh_address_cr/core/agent_protocol.py` (`_split_validation_command_record` ≈1399, `_normalize_validation_command_records` ≈1365)
- Test: `tests/test_agent_protocol.py`

Background: `_normalize_validation_command_records` already accepts a `duration` field (in **seconds**, consumed at `agent_protocol.py:1086` as `start = end - float(duration)`). The dict input form can already carry it; only the string shorthand (`cmd=passed`) drops it. This task makes the shorthand able to carry it via a `@<n>ms`/`@<n>s` suffix on the result token, e.g. `ruff check=passed@1500ms`.

- [x] **Step 1: Write the failing parser tests**

Add to `tests/test_agent_protocol.py` (a new `ValidationRecordTimingTests` class; import the helpers inside each test from `gh_address_cr.core.agent_protocol`):

```python
    def test_split_validation_record_parses_ms_suffix(self):
        command, result, duration = _split_validation_command_record("ruff check=passed@1500ms")
        self.assertEqual(command, "ruff check")
        self.assertEqual(result, "passed")
        self.assertEqual(duration, 1.5)

    def test_split_validation_record_parses_seconds_suffix(self):
        command, result, duration = _split_validation_command_record("pytest=failed@3.5s")
        self.assertEqual(command, "pytest")
        self.assertEqual(result, "failed")
        self.assertEqual(duration, 3.5)

    def test_split_validation_record_without_suffix_has_no_duration(self):
        command, result, duration = _split_validation_command_record("ruff check=passed")
        self.assertEqual(command, "ruff check")
        self.assertEqual(result, "passed")
        self.assertIsNone(duration)

    def test_split_validation_record_bare_command_unchanged(self):
        command, result, duration = _split_validation_command_record("ruff check")
        self.assertEqual(command, "ruff check")
        self.assertEqual(result, "passed")
        self.assertIsNone(duration)

    def test_normalize_carries_duration_from_string_suffix(self):
        records = _normalize_validation_command_records(["ruff check=passed@1500ms"])
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["command"], "ruff check")
        self.assertEqual(records[0]["result"], "passed")
        self.assertEqual(records[0]["duration"], 1.5)
```

- [x] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src python -m unittest tests.test_agent_protocol.ValidationRecordTimingTests -v`
Expected: FAIL — `ValueError: not enough values to unpack (expected 3, got 2)` because `_split_validation_command_record` returns a 2-tuple today.

- [x] **Step 3: Add the suffix-stripping helper and constant**

In `src/gh_address_cr/core/agent_protocol.py`, add `import re` to the import block, and add this helper just above `_split_validation_command_record`:

```python
_VALIDATION_DURATION_SUFFIX_RE = re.compile(r"@(\d+(?:\.\d+)?)(ms|s)$")


def _strip_validation_duration_suffix(value: str) -> tuple[str, float | None]:
    """Split a trailing ``@<n>ms``/``@<n>s`` timing suffix off a validation result token.

    Returns ``(token_without_suffix, duration_seconds_or_None)``. Durations are
    normalized to seconds to match the existing validation ``duration`` contract.
    """
    match = _VALIDATION_DURATION_SUFFIX_RE.search(value.strip())
    if match is None:
        return value, None
    number = float(match.group(1))
    seconds = number / 1000.0 if match.group(2) == "ms" else number
    return value[: match.start()], seconds
```

- [x] **Step 4: Change `_split_validation_command_record` to a 3-tuple**

Replace the current body:

```python
def _split_validation_command_record(raw: str) -> tuple[str, str]:
    command, separator, result = raw.rpartition("=")
    if not separator or not _looks_like_validation_result(result):
        return raw.strip(), "passed"
    return command.strip(), result.strip()
```

with:

```python
def _split_validation_command_record(raw: str) -> tuple[str, str, float | None]:
    command, separator, result = raw.rpartition("=")
    result_token, duration = _strip_validation_duration_suffix(result)
    if not separator or not _looks_like_validation_result(result_token):
        return raw.strip(), "passed", None
    return command.strip(), result_token.strip(), duration
```

- [x] **Step 5: Capture the duration in the string branch of the normalizer**

In `_normalize_validation_command_records`, update the `else` (string) branch:

```python
        else:
            raw = str(entry or "").strip()
            command, result = _split_validation_command_record(raw)
            summary = ""
            duration = None
            start_time = None
            end_time = None
```

to:

```python
        else:
            raw = str(entry or "").strip()
            command, result, duration = _split_validation_command_record(raw)
            summary = ""
            start_time = None
            end_time = None
```

(The existing `if duration is not None: row["duration"] = duration` below already persists it.)

- [x] **Step 6: Run the parser tests to verify they pass**

Run: `PYTHONPATH=src python -m unittest tests.test_agent_protocol.ValidationRecordTimingTests -v`
Expected: PASS (5 tests).

- [ ] **Step 7: Commit**

```bash
git add src/gh_address_cr/core/agent_protocol.py tests/test_agent_protocol.py
git commit -m "feat(telemetry): accept @<n>ms/@<n>s timing suffix on validation shorthand"
```

### Task 4: End-to-end — timed validation produces non-zero report duration

**Files:**
- Modify: `tests/core/test_telemetry.py`
- Test: same file (this is the regression that proves the whole path works)

- [x] **Step 1: Write the end-to-end test**

Add to `tests/core/test_telemetry.py`. Import the recorder at the top of the file: `from gh_address_cr.core.agent_protocol import _record_validation_command_telemetry`.

```python
    @patch("gh_address_cr.core.telemetry.core_paths.state_dir")
    def test_timed_validation_shorthand_yields_nonzero_report_duration(self, state_dir):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir.return_value = Path(tmp)
            tracker = SessionTelemetry.get_instance()
            tracker.configure_context("octo/example", "77")

            # The skill reports a validation command with measured timing.
            _record_validation_command_telemetry({}, ["ruff check=passed@1500ms"])

            report = build_efficiency_report("octo/example", "77")

            self.assertEqual(report["total_events"], 1)
            self.assertTrue(report["duration_observed"])
            self.assertGreaterEqual(report["total_observed_duration_ms"], 1400)
            self.assertLessEqual(report["total_observed_duration_ms"], 1600)
            self.assertEqual(len(report["slowest_operations"]), 1)
            self.assertNotIn("TELEMETRY_TIMING_UNAVAILABLE", report["diagnostics"])
```

- [x] **Step 2: Run the test to verify it passes**

Run: `PYTHONPATH=src python -m unittest tests.core.test_telemetry -v -k timed_validation`
Expected: PASS.

Rationale this is a regression worth keeping: it exercises the full chain — string shorthand → `_normalize_validation_command_records` → `_record_validation_command_telemetry` replay arithmetic (`agent_protocol.py:1083-1091`) → `_runtime_events` seconds→ms conversion → report — which is exactly the path that silently produced `0ms` before.

- [ ] **Step 3: Commit**

```bash
git add tests/core/test_telemetry.py
git commit -m "test(telemetry): prove timed validation shorthand yields real report duration"
```

### Task 5: Document the timed shorthand and the timing-unavailable behavior

**Files:**
- Modify: `skill/SKILL.md` (Telemetry Coverage section, ≈85-99)
- Modify: `docs/troubleshooting.md`
- Test: `tests/test_skill_docs.py`, `tests/test_cli_skill_sync_artifacts.py` (existing doc-contract tests, no edit)

- [x] **Step 1: Update SKILL.md telemetry guidance**

In `skill/SKILL.md`, in the Telemetry Coverage section, add a paragraph before the "Telemetry degradation is visible…" paragraph:

```markdown
When recording validation evidence via `agent resolve ... --validation <cmd=result>`, include the measured runtime as a suffix so efficiency reports can analyze duration: `--validation "ruff check=passed@1500ms"` (also accepts `@<n>s`). Omitting the suffix is allowed but records the command with zero duration, and the efficiency report will label timing as unavailable via a `TELEMETRY_TIMING_UNAVAILABLE` diagnostic instead of presenting misleading `0ms` slowest-operation rows.
```

- [x] **Step 2: Update troubleshooting.md**

In `docs/troubleshooting.md`, under the telemetry/installation section, add two bullets:

```markdown
- Telemetry summary shows events with `0ms` durations: validation commands were reported without a timing suffix. The report emits a `TELEMETRY_TIMING_UNAVAILABLE` diagnostic and omits the Slowest Operations section instead of presenting misleading `0ms` rows. Re-record validation evidence with `--validation "<cmd>=<result>@<n>ms"` (or `@<n>s`) to populate timing.
- Telemetry summary is empty (`coverage_label: unavailable`) with no traceback: no runtime workflow ran under that PR scope and no host telemetry was ingested. This is an expected coverage outcome, not a failure. Run the workflow under the same `<owner/repo> <pr_number>`, or ingest host telemetry via `telemetry ingest`, then re-run `telemetry summary`.
```

- [x] **Step 3: Run the doc-contract and skill-sync tests**

Run: `PYTHONPATH=src python -m unittest tests.test_skill_docs tests.test_cli_skill_sync_artifacts -v`
Expected: OK.

- [ ] **Step 4: Commit**

```bash
git add skill/SKILL.md docs/troubleshooting.md
git commit -m "docs(telemetry): document timed validation shorthand and timing-unavailable reporting"
```

---

## Final verification

- [x] **Run the full suite**

Run: `PYTHONPATH=src python -m unittest discover -s tests`
Result: **Ran 792 tests … OK** (verified 2026-06-21).

- [x] **Lint**

Run: `ruff check src/gh_address_cr/core/telemetry.py src/gh_address_cr/core/agent_protocol.py`
Result: All checks passed.

- [x] **Manual smoke (from source) — proves the daily path**

From-source render of both behaviors verified:
- UNTIMED (`ruff check=passed`): no `### Slowest Operations`; shows the timing note + `TELEMETRY_TIMING_UNAVAILABLE` diagnostic.
- TIMED (`ruff check=passed@1500ms`, `pytest=failed@3.5s`): `total_observed_duration_ms: 5000`, sorted slowest ops (`pytest 3500ms`, `ruff check 1500ms`), inefficiency flag on the failure.

---

## Self-Review Notes (author checklist, completed)

- **Spec coverage:** Phase 0 (honest reporting) = Tasks 1-2. Phase 1 (timing flows) = Tasks 3-4. Docs = Task 5. All map to tasks.
- **Out of scope (deliberate):** Phase 2 (auto-discovering and ingesting host telemetry without `GH_ADDRESS_CR_HOST_TELEMETRY_INPUT`) is excluded; designed separately in `docs/superpowers/specs/2026-06-21-phase2-host-telemetry-design.md`.
- **Type consistency:** `_split_validation_command_record` returns a 3-tuple `(str, str, float | None)` everywhere. Duration is **seconds** at every boundary (suffix helper converts ms→s; `agent_protocol.py:1086` consumes seconds; `_runtime_events` converts seconds→ms via `int(metric.duration * 1000)`). Report key `duration_observed` (bool) and diagnostic string `TELEMETRY_TIMING_UNAVAILABLE` are spelled identically across tasks.
- **No placeholders:** every code step shows complete code; every run step shows the exact command and expected outcome.
- **Risk boundaries honored:** no change to fail-soft core flow, redaction (`telemetry_safety.py`), atomic writes, or network-write contracts. The only behavior change is presentational (slowest-ops now timed-only + diagnostic) plus an additive, backward-compatible CLI shorthand suffix.

## Implementation outcome (post-execution record)

Implemented on branch `feat/telemetry-timing-honest-reporting`. Changeset: 7 files, +149/−8, 9 new tests. Full suite 792 tests OK; ruff clean; doc-contract + skill-sync tests pass. Checkboxes for code/test/verification steps are checked; the per-task `git commit` steps remain unchecked because commits were deferred pending explicit user instruction.