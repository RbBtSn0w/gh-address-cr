# Migrating to gh-address-cr 3.0

3.0 is a breaking release. It converges the agent mutating surface into a single
`agent resolve` command, tightens gate authority, and adds machine fields that
distinguish the inline pre-gate from the authoritative final gate. There are no
compatibility aliases for the removed commands — update your automation.

## Removed commands → `agent resolve`

| 2.x command | 3.0 replacement |
| --- | --- |
| `agent fix <item_id> …` | `agent resolve <item_id> …` |
| `agent trivial-fix <item_id> …` | `agent resolve <item_id> --trivial …` |
| `agent fix-all --input <batch.json>` | `agent resolve --batch --input <batch.json>` |
| `agent fix-all --commit … --homogeneous-reason <why>` | `agent resolve --commit … --homogeneous-reason <why>` |
| `agent fix-all --commit …` (match all by files) | `agent resolve --commit …` (no `<item_id>`) |
| `agent resolve-stale --commit … --match-files` | `agent resolve --commit … --stale --match-files` |
| `agent submit-batch --input <batch.json>` | `agent resolve --batch --input <batch.json>` |

`agent classify`, `agent next`, `agent submit`, `agent publish`, `agent evidence`,
`agent leases`, `agent reclaim`, and `agent orchestrate` are unchanged. The granular
`classify → next → submit → publish` protocol still works; `agent resolve` is the
single shortcut built on top of it.

### Mode rules

- `agent resolve` records classification internally — no separate `agent classify`
  round-trip is required on this path.
- `<item_id>` is single-item only. Combining it with `--batch`/`--input`, `--stale`,
  or `--homogeneous-reason` now fails fast with `ITEM_ID_NOT_ALLOWED_FOR_MODE`
  instead of being silently ignored.
- `--trivial` requires a single `<item_id>` (`TRIVIAL_REQUIRES_ITEM_ID`).
- `--batch` requires `--input` (`MISSING_BATCH_INPUT`). The homogeneous shortcut is
  the **non-batch** `agent resolve --commit … --homogeneous-reason <why>` form.

## Behavior and machine-field changes

- **Gate scope (#119).** Every machine summary now carries `gate_scope`:
  `"inline"` for the `review`/`address`/`threads` pre-gate and `"final"` for
  `final-gate`. Only `gate_scope: "final"` output is completion proof — an inline
  `PASSED` no longer implies the PR is complete (it evaluates neither pending
  reviews nor PR checks). Note that `final-gate` evaluates current-login pending
  reviews by default, but evaluates **PR checks only when you pass
  `--require-checks` or `--require-required-checks`**; add the appropriate flag
  when green checks are part of your completion bar.
- **Stricter validation evidence (#117).** Failing validation results no longer
  satisfy the gate. A record with `result: "failed"`/`exit_code != 0`, or a
  `<cmd>=failed` string, is rejected as missing validation evidence.
- **`published` field.** `agent resolve` reports `published: true|false` derived
  from the actual publish result (`published_count`), including the nested
  single-item `submit.publish` location. `agent publish` remains the canonical
  publish path; each resolve mode also accepts `--publish`.
- **Autopilot is plan-only.** `agent orchestrate autopilot` returns
  `status: "PLAN_ONLY"` with `executes_side_effects: false`. It never performs
  side effects; run the planned `agent resolve` / `agent publish` / `final-gate`
  steps yourself.
- **stdin guard.** `review`/`findings --input -` fail loudly on an interactive TTY
  instead of blocking on EOF; pipe `[]` for an explicit empty producer result.
- **Event-sourced rebuild (#116).** `response_accepted` ledger events carry the
  full applied response, and the session cache can be rebuilt from the ledger
  (`rebuild_session_items`), so a crash between an event append and the cache
  write is recoverable.

## Runtime/skill compatibility

The 3.0 skill is a thin adapter over the 3.0 runtime; `runtime-requirements.json`
declares `minimum_runtime_version: 3.0.0`. Installing the 3.0 skill against an
older runtime that lacks `agent resolve` will fail.

Confirm your installed runtime is **3.0.0 or newer**:

```bash
gh-address-cr version
```

> `gh-address-cr adapter check-runtime` only reports **protocol** compatibility
> (still `1.0` in 3.0); it does not compare the installed package version against
> the skill's `minimum_runtime_version`, so a 2.x runtime can still report
> `status: compatible`. Use `gh-address-cr version` to verify the package version.
