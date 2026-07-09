# Quickstart: Validating Resolve Orthogonalization

Runnable validation scenarios proving the orthogonal surface works end-to-end.
Details of axes, routing, and reason codes live in
[contracts/resolve-axes-cli.md](./contracts/resolve-axes-cli.md) and
[data-model.md](./data-model.md); this guide is the run/validation checklist.

## Prerequisites

- `pip install -e .` (runtime importable for test discovery).
- No network/GitHub access needed — contract tests use in-memory sessions and
  fake GitHub clients (see `tests/test_native_workflow.py` patterns).

## Full gate (run before claiming done)

```bash
pip install -e .
ruff check src tests scripts/build_plugin_payload.py
python3 -m unittest discover -s tests
python3 -m gh_address_cr agent resolve --help        # axes, not a preset matrix
python3 -m gh_address_cr submit-action --help        # shared disposition vocabulary
python3 -m gh_address_cr agent manifest              # agent contract smoke
```

## Scenario 1 — Close #204: decline one fresh thread by id (P1)

Expected: single thread declined (reject), reply published, terminal; no
`ITEM_ID_NOT_ALLOWED_FOR_MODE` / `CONFLICTING_RESOLVE_MODE`.

```bash
# item_id + --disposition reject + reason on a single fresh thread
python3 -m gh_address_cr agent resolve <owner/repo> <pr> <item_id> \
  --disposition reject --why "Declining: matches stdlib behavior; no change warranted."
python3 -m gh_address_cr agent publish <owner/repo> <pr>
python3 -m gh_address_cr final-gate <owner/repo> <pr>
```

Contract test equivalent: `tests/contract/test_resolve_axes_contract.py`
asserts the (single × reject × fresh) cell resolves the one item and emits no
mode-conflict code.

## Scenario 2 — Decline one STALE thread by id (P1, the previously-blocked cell)

Expected: single stale thread declined by id (no `--match-files` needed); the
independent `stale` condition composes with single selection + decline.

```bash
python3 -m gh_address_cr agent resolve <owner/repo> <pr> <stale_item_id> \
  --disposition clarify --stale --why "Need author confirmation before acting."
```

Contract test equivalent: the (single × clarify × stale) cell is reachable and
routes through the classify+submit primitives (research R-1).

## Scenario 3 — No cross-axis matrix; only same-axis conflicts fail (P2)

Expected: every cross-axis combination accepted; two selection sources or two
dispositions → `RESOLVE_AXIS_CONFLICT` (directive).

```bash
# valid: files selection + reject disposition + stale condition
# (--why is the decline reason flag for EVERY selection — single and files;
#  reason-flag unification, data-model Entity 1. --homogeneous-reason is a
#  deprecated alias for --why.)
python3 -m gh_address_cr agent resolve <owner/repo> <pr> \
  --files src/a.py --disposition reject --stale --why "Declining across this file."

# invalid (same-axis): item_id AND files selector at once
python3 -m gh_address_cr agent resolve <owner/repo> <pr> <item_id> \
  --files src/a.py --disposition reject --why x   # -> RESOLVE_AXIS_CONFLICT (directive)
```

Contract test equivalent: the enumerated product test asserts all valid cells
pass and each same-axis conflict yields exactly one directive code.

## Scenario 4 — Disposition/evidence coherence (P2)

Expected: fix-only evidence with a decline disposition → directive
`RESOLVE_EVIDENCE_INCOHERENT`; a fix missing evidence → existing
`MISSING_RESOLVE_ARGS` / `MISSING_FIX_REPLY_COMMIT_HASH` (unchanged).

```bash
# invalid: fix-only evidence (--commit) supplied with a decline disposition
python3 -m gh_address_cr agent resolve <owner/repo> <pr> <item_id> \
  --disposition reject --commit <sha> --why x   # -> RESOLVE_EVIDENCE_INCOHERENT (directive)

# invalid: fix disposition missing its required evidence (existing code, unchanged)
python3 -m gh_address_cr agent resolve <owner/repo> <pr> <item_id> \
  --disposition fix   # -> MISSING_RESOLVE_ARGS (requires --commit/--summary/--why)
```

## Scenario 5 — Deprecation aliasing stays green (P3)

Expected: today's mode-preset invocations still resolve the same threads with
the same evidence, each emitting a visible deprecation notice.

```bash
# legacy form still works during the window (with a deprecation notice)
python3 -m gh_address_cr agent resolve <owner/repo> <pr> \
  --commit <sha> --files src/a.py --validation "unit=passed@100ms" \
  --stale --match-files
# -> resolves as before + "deprecated: use --files (+ --stale); see ..."
```

Contract test equivalent: `tests/test_agent_resolve_guards.py` (updated) checks
each deprecated flag aliases to its axis equivalent and warns.

## Scenario 6 — Shared disposition vocabulary (Option B)

Expected: `agent resolve` and `submit-action` accept the same disposition
names, drawn from one canonical constant across 5 sites (C-V2). `agent
evidence add` has no disposition/resolution surface and is excluded by
construction — the test does not (and should not) assert anything about it
(E1 correction).

```bash
python3 -m unittest tests.test_disposition_vocabulary
```

## Success signals

- Issue #204 scenarios (1 & 2) pass with no mode-conflict rejection.
- `agent resolve --help` shows ≤3 axis parameters, not ~9 preset switches (SC-004).
- Full `unittest` suite green; `ruff` clean; `final-gate` PASSES for the
  driven PR sessions.
