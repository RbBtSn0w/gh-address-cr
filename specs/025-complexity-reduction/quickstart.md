# Quickstart: Core-Path-Anchored Complexity Reduction

Per-stage verification that each removal preserves the protected baseline. Details
live in [contracts/](contracts/README.md) and [data-model.md](data-model.md).

## Prerequisites

- `.venv/bin/python` with the package installed (`pip install -e .`).
- Baseline before any change: record the actual green test count from the local
  suite run.
- Capture the baseline once:

```bash
.venv/bin/python -m unittest discover -s tests 2>&1 | grep -E "^(Ran|OK|FAILED)"
.venv/bin/python -m gh_address_cr --help
```

## Per-stage gate (run after EVERY stage US5→US4)

```bash
.venv/bin/python -m unittest discover -s tests 2>&1 | grep -E "^(Ran|OK|FAILED)"   # green
.venv/bin/ruff check src tests                                                      # clean
.venv/bin/python -m gh_address_cr --help                                            # core commands present
.venv/bin/python -m gh_address_cr final-gate --help                                 # gate intact
# FR-010 protected-layer survival (must succeed after every stage):
.venv/bin/python -c "import gh_address_cr.core.agent_protocol, gh_address_cr.core.leases, gh_address_cr.core.agent_batch, gh_address_cr.github.client, gh_address_cr.core.publisher, gh_address_cr.core.session, gh_address_cr.core.gate, gh_address_cr.core.runtime_kernel.final_gate; print('protected layers OK')"
```

Expected each time: suite `OK`, `ruff` clean, `review`/`address`/`threads`/
`findings`/`agent`/`final-gate` still listed, no dangling-import traceback, and
the observed test count is recorded rather than hard-coded.

## US5 — Governance amendment (P0, first)

```bash
grep -nE "blast.?radius|Complexity Budget|Minimal Viable" .specify/memory/constitution.md
grep -n "Version:" .specify/memory/constitution.md   # MAJOR bump present
```

Expected: Principles VI/VIII/IX carry a blast-radius-triggered qualifier, a new
Principle X exists, version bumped with a Sync Impact Report, and `AGENTS.md`'s
Preflight Gate is trigger-scoped. No code changed yet.

## US1 — Remove consolidation + evaluation

```bash
test ! -d src/gh_address_cr/core/consolidation && echo "consolidation removed"
test ! -d src/gh_address_cr/core/evaluation && echo "evaluation removed"
.venv/bin/python -m gh_address_cr consolidation status; echo "exit=$?"   # unknown command, non-zero
```

Expected: both packages + their commands gone; removed commands fail as unknown;
suite green; `final-gate` verdict unchanged on fixtures (SC-002). In the same
change, `skill/` and affected repo-root command-surface docs stop referencing
`consolidation` / `evaluation`.

## US2 — Collapse to one engine

```bash
grep -rn "runtime_kernel.projections\|runtime_kernel.policies\|runtime_kernel.commands" src/ || echo "no live import of kernel review engine"
test -f src/gh_address_cr/core/runtime_kernel/final_gate.py && echo "final_gate KEPT"
```

Expected: kernel review-state-machine modules gone, no live importer; `final_gate.py`
present; reply/resolve/gate outputs unchanged. `skill/` guidance no longer
describes the deleted dual-engine / kernel review-state-machine architecture as
live.

## US3 — Deprecated sweep to zero

```bash
# hits minus the enumerated allowlist must be zero:
grep -rniE "deprecated|legacy|compat|shim" src/gh_address_cr --include="*.py" \
  | grep -vFf specs/025-complexity-reduction/.deprecated-allowlist.txt | wc -l
```

Expected: `0` (SC-011 — hits outside `.deprecated-allowlist.txt`); `_legacy_module`,
the reject table, the overlapping command sets, and the unused
`ReplyPoster`/`ThreadResolver` are gone; unknown-command handling still works.

## US4 — Telemetry shrink + orchestrator demote (KEEP OpenTelemetry)

```bash
grep -n "start_as_current_span\|run_traced" src/gh_address_cr/telemetry.py src/gh_address_cr/__main__.py   # OTel intact
GH_ADDRESS_CR_DISABLE_INTERNAL_TELEMETRY=1 .venv/bin/python -m gh_address_cr final-gate --help; echo "exit=$?"  # fail-open
```

Expected: OTLP span still emits per invocation (SC-005); core flows complete with
internal telemetry absent (SC-006); single-agent path works without the orchestrator.
In the same change, `skill/` and affected repo-root telemetry/orchestration docs
drop stale references to removed behavior.

## Skill sync (every command-removing stage — FR-017)

```bash
grep -rniE "consolidation|evaluation" skill/ || echo "skill has no reference to removed commands"
```

Expected: zero references to removed commands in `skill/` (SC-012).

## Repo-root docs sync (story-local FR-011 gate)

After each story that removes a documented surface, verify the matching repo-root
docs were updated in the same change instead of deferred to a final sweep.

```bash
rg -n "consolidation|evaluation|dual-engine|runtime kernel|telemetry subcommand|orchestrator" README.md docs/ .github/ 2>/dev/null
```

Expected: only intentional surviving references remain, and no removed command or
removed architecture is still described as live after its story lands.

## Final acceptance

- ≥4,500 LOC (src+test) removed across US1–US3 (SC-004).
- Full suite green; `ruff` clean; core smoke intact; OpenTelemetry intact.
- Constitution amended (MAJOR + Sync Impact Report); AGENTS.md consistent; skill clean.
