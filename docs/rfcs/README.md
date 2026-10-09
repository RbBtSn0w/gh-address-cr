# Static Architecture References

Spec Kit was retired on 2026-10-03. `AGENTS.md` owns current engineering
constraints. This archive preserves long-lived architecture, public contracts,
and unfinished design investigations, not a development lifecycle. Archived
plans may contain obsolete commands, paths, statuses, or storage assumptions;
current code, tests, and `AGENTS.md` govern execution. Do not execute archived
scaffolding instructions or infer delivery status from these documents.

Task lists, requirement checklists, delivery-only specifications, quickstarts,
validation snapshots, and scaffolding were removed. Git history preserves them.
The 039 first-run investigation remains a design reference because its draft
status does not prove delivery. No runtime or packaged-skill behavior changed.

## Asset Disposition

| Original feature | Disposition |
| --- | --- |
| 025-complexity-reduction | Architecture/contracts retained; delivery specs, checklists and evidence snapshots removed. |
| 026-cli-otel-agent-integration | Architecture/contracts retained; delivery specs, checklists and evidence snapshots removed. |
| 027-otel-layered-model | Architecture/contracts retained; delivery specs, checklists and evidence snapshots removed. |
| 028-workflow-gap-recovery | Architecture/contracts retained; delivery specs, checklists and evidence snapshots removed. |
| 029-resolve-orthogonalization | Architecture/contracts retained; delivery specs, checklists and evidence snapshots removed. |
| 030-otel-gateway-hardening | Architecture/contracts retained; delivery specs, checklists and evidence snapshots removed. |
| 031-stacked-pr-support | Architecture/contracts retained; delivery specs, checklists and evidence snapshots removed. |
| 032-otel-release-channel-endpoint | Architecture/contracts retained; delivery specs, checklists and evidence snapshots removed. |
| 033-lease-state-machine | Architecture/contracts retained; delivery specs, checklists and evidence snapshots removed. |
| 034-transactional-lease-runtime | Architecture/contracts retained; delivery specs, checklists and evidence snapshots removed. |
| 035-runtime-store-hardening | Architecture/contracts retained; delivery specs, checklists and evidence snapshots removed. |
| 036-runtime-transaction-hot-path | Architecture/contracts retained; delivery specs, checklists and evidence snapshots removed. |
| 037-cr-lifecycle-metrics | Architecture/contracts retained; delivery specs, checklists and evidence snapshots removed. |
| 038-runtime-store-consistency | Architecture/contracts retained; delivery specs, checklists and evidence snapshots removed. |
| 039-agent-first-run-ux | Architecture/contracts retained; delivery specs, checklists and evidence snapshots removed. |
| 041-telemetry-shutdown-wait | Architecture preflight for the bounded exit-time telemetry wait (issue #346). |

## Migration Verification

This migration itself exercised autonomous implementation and verification after
removing task lists and scaffolding. Runtime behavior was not changed; code
comments and executable documentation contracts were updated to the new paths.

Verified on 2026-10-03:

- Editable installation and wheel build succeeded.
- Ruff passed; mypy passed for 90 source files with zero errors.
- Full unittest discovery passed: 1,408 tests, one skipped.
- CLI help, agent manifest, plugin payload generation/check, and diff checks passed.
- Governance tests verify the current persistence owner, absence of retired
  directories, absence of executable scaffolding dependencies, and archive links.
- The wheel excludes repository-only RFCs and retired scaffolding.

The full suite was run with a writable isolated state directory:

```sh
GH_ADDRESS_CR_STATE_DIR=/tmp/spec-retirement-state .venv/bin/python -m unittest discover -s tests
```

Without that override, one persistence-reason-code test attempts to write to the
user cache outside the sandbox and fails with a permission error. Its ten-test
module also passed independently with a writable state directory. No production
state or GitHub side effects were required. Changes remain unstaged; Git history
is the recovery source for removed artifacts.
