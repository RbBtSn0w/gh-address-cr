# Per-CR Processing Metrics (`telemetry cr-summary`) — Design Spec

**Status:** Design / approved through §1–§5 in brainstorming
**Date:** 2026-06-21
**Related:** Phase 0/1/2 telemetry work on branch `feat/telemetry-timing-honest-reporting`.

## 1. Goal & Motivation

Existing efficiency telemetry aggregates *tool-call* durations (total / slowest / success-rate). It cannot answer per-CR questions — "how many review threads did this run handle, and how long did each take?" A naive `total_tool_time / cr_count` average is unreasonable: tool time interleaves across CRs, CRs are heterogeneous (a `reply` takes seconds, a `fix` minutes), human wait time shouldn't count, and tool-time is not wall-clock.

This feature adds a **per-CR processing report** computed from the **evidence ledger** (`evidence.jsonl`), which already records every per-item lifecycle event with `item_id` + `timestamp` + `session_id` + `event_type`. Validated on real data (pr-97): 17 CRs, per-CR span median 7s / p90 53s / max 53s, run wall-clock 620s, compactness 0.51 — concretely showing why a distribution (not a bare average) is required.

## 2. Data Source & Computation Rule Model

**Source:** read-only `core_paths.evidence_ledger_file(repo, pr)` (`evidence.jsonl`). Never reads Plan A telemetry events; never writes ledger or mutates review state.

Each ledger event carries: `session_id`, `item_id`, `event_type`, `timestamp` (ISO-8601), `payload`.

**Step 1 — select the latest processing pass.** Group events by `session_id`; choose the `session_id` owning the globally-latest `timestamp`. All computation uses only that session's events. (Events lacking `session_id` are treated as a single fallback session.)

**Step 2 — per-CR span.** Within the selected session, group by `item_id`:
- `start_ts` = earliest event timestamp for the item.
- **Completed** iff the item has a `thread_resolved` event (the authoritative terminal, matching the work-item `resolved_thread` completion criterion). `end_ts` = that `thread_resolved` timestamp. `span_ms = end_ts − start_ts`.
- No `thread_resolved` → **incomplete**: excluded from the span distribution, listed separately with its last event_type.

**Step 3 — aggregate (completed spans only).**
- `cr_count_completed`, `cr_count_incomplete`, `cr_count_total`
- `span_ms`: `median`, `p90`, `max`, `min` (over completed). **No bare `mean`** in the primary surface — distribution is the point.
- `run_wall_clock_ms` = max(ts) − min(ts) over the selected session's events.
- `active_cr_time_ms` = Σ(completed spans); `compactness_ratio` = `active_cr_time_ms / run_wall_clock_ms` (rounded 2dp) — quantifies idle/gap between CRs.
- `classification_mix` = counts by classification over **distinct items** (an item may have multiple `classification_recorded` events — re-classification; take the item's latest by timestamp), derived from the payload's `classification` field; omitted (+ diagnostic) when no payload carries it. Likewise all counts and grouping are by **distinct `item_id`**, never raw event counts (validated: pr-97 has 20 `classification_recorded` events but 17 distinct items).

**Span definition choice:** per-CR span = first-event → `thread_resolved` wall-clock (includes small in-CR gaps). Alternative (ClaimLease `created_at → resolved`) rejected: the ledger's first event is closer to "work on this CR began."

## 3. Output Schema (`telemetry cr-summary <owner/repo> <pr> [--format json|markdown]`)

JSON (default), machine fields consistent with `telemetry summary`:

```json
{
  "status": "SUCCESS",
  "reason_code": "CR_SUMMARY_READY",
  "repo": "owner/repo",
  "pr_number": "97",
  "session_id": "<latest session>",
  "cr_count_total": 17,
  "cr_count_completed": 17,
  "cr_count_incomplete": 0,
  "span_ms": { "median": 7000, "p90": 53000, "max": 53000, "min": 6000 },
  "run_wall_clock_ms": 620000,
  "active_cr_time_ms": 319000,
  "compactness_ratio": 0.51,
  "classification_mix": { "fix": 12, "reply": 5 },
  "incomplete_crs": [],
  "per_cr": [
    { "item_id": "github-thread:PRRT_…", "span_ms": 53000, "completed": true, "classification": "fix" }
  ],
  "report_artifact": "…/pr-97/cr-metrics.json",
  "diagnostics": []
}
```

- `span_ms` values are `null` when `cr_count_completed == 0`.
- `incomplete_crs`: list of `{ "item_id", "last_event_type" }`.
- `per_cr`: one row per item in the selected session (completed and incomplete), sorted by `span_ms` desc (incomplete with `span_ms: null` last).
- `report_artifact`: written to `<workspace>/cr-metrics.json` via `write_json_atomic`.

Markdown (`--format markdown`):
```
## CR Processing Summary (latest session)
- CRs: 17 completed, 0 incomplete
- per-CR span: median 7.0s | p90 53.0s | max 53.0s
- run wall-clock: 620s | active CR time: 319s | compactness: 0.51
- classification: fix 12, reply 5
### Slowest CRs
- github-thread:PRRT_… : 53.0s (fix)
### Incomplete CRs
- (none)
```

## 4. Edge Cases & Failure Behavior

Follows existing telemetry-command conventions (telemetry commands are fail-loud on corruption, but legitimately-empty is a valid result; never mutate review state):

| Situation | Behavior |
|---|---|
| Missing / empty ledger (PR not processed) | `status: SUCCESS`, `reason_code: CR_LEDGER_EMPTY`, `cr_count_total: 0`, exit 0 |
| Individual malformed JSON line / missing `item_id` or `timestamp` | skip that event, add a diagnostic (fail-soft) |
| Whole ledger file unreadable (OSError) | fail-loud `status: FAILED`, `reason_code: CR_SUMMARY_UNAVAILABLE`, exit 2 |
| Items exist but none completed | `SUCCESS`, `span_ms` all `null`, `cr_count_completed: 0`, incomplete listed, exit 0 |
| Multiple sessions in ledger | select latest; diagnostic notes the count of distinct sessions seen |
| Events missing `session_id` | treat as a single fallback session |

The command is read-only except for the atomic `cr-metrics.json` artifact; an artifact-write OSError appends a diagnostic but does not change the computed status.

## 5. Components & Testing

**Files:**
- Create `src/gh_address_cr/core/cr_metrics.py` — pure computation: `build_cr_summary(repo, pr) -> dict` + `cr_summary_markdown(report) -> str`. Reads the ledger, selects latest session, computes spans/stats, writes the artifact.
- Modify `src/gh_address_cr/commands/telemetry.py` — add the `cr-summary` subcommand to `handle_telemetry_command` (parse `--format json|markdown`, scope resolution via the existing `maybe_prepend_implicit_scope` helper, print + exit code).
- Create `tests/core/test_cr_metrics.py` + fixture `tests/fixtures/cr_metrics/evidence-sample.jsonl`.

**Component boundaries:** `cr_metrics.py` is a leaf computation (stdlib + `core_paths` + `core.io.write_json_atomic`), independently testable; the command layer only parses args and renders.

**Testing (unittest):**
- latest-session selection across multiple session_ids
- per-CR span computation; completed (has `thread_resolved`) vs incomplete
- distribution stats (median/p90/max/min) + `compactness_ratio`
- `classification_mix` present / absent (payload with and without `classification`)
- empty/missing ledger → `CR_LEDGER_EMPTY` exit 0
- malformed line skipped with diagnostic (fail-soft)
- whole-file unreadable → `CR_SUMMARY_UNAVAILABLE` exit 2
- CLI contract: `telemetry cr-summary` json + markdown shape
- Do NOT touch `specs/015-external-agent-telemetry/acceptance-matrix.md` (its meta-test asserts a fixed category set; adding a row breaks it). cr-summary tests stand alone.

## 6. Non-Goals / Future

- **Fine-grained per-CR tool time** (how long each CR spent in tool calls) requires tagging Plan A telemetry events with `item_id` at runtime — separate future step.
- **Cumulative-across-PR** and **both-views** aggregation modes — deferred; this spec ships latest-session only.
- No integration into `final-gate` output in this spec (dedicated command only).
