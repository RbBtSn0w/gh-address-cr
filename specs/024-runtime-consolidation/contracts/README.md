# Contracts: Evidence-Gated Runtime Consolidation

This feature's external surface is (1) advanced CLI commands, (2) versioned
control/report artifacts, and (3) the reversibility invariants those artifacts
guarantee. The core `review` orchestration path and existing machine summaries
are unchanged. Schemas below are the authoritative contract; executable contract
tests under `tests/consolidation/` and `tests/contract/` MUST enforce them.

## CLI contract — `consolidation` family (additive)

All commands are read-only or control-only; none execute review side effects.

| Command | Purpose | Output | Side effects |
|---------|---------|--------|--------------|
| `consolidation status [--cohort <id>]` | Show the Runtime Authority Map + each slice's rollout stage for a projected cohort | `authority-map.v1` + slice stages (JSON with `--json`) | none |
| `consolidation parity --slice <id>` | Replay recorded facts through legacy vs candidate paths | `parity-report.v1` | none (0 GitHub calls) |
| `consolidation rollout --slice <id> --to <stage> [--evidence-file <path>]` | Request a stage transition; deterministically allowed or blocked | transition result + reason code | atomic `rollout-state.v1` write only |
| `consolidation deprecations` | List the duplicate models/shims/telemetry fields queued for removal and their contract boundary | `deprecation-inventory.v1` (JSON with `--json`) | none |

**Guarantees**: unknown slice → fail loud (non-zero, `UNKNOWN_SLICE`); a blocked
transition returns a reason code (`INSUFFICIENT_EVIDENCE`, `PARITY_DIFF`,
`QUALITY_REGRESSION`, `DEPRECATION_WINDOW_OPEN`) and non-zero exit; `status`
keeps legacy authority during `shadow`/`opt_in` and switches an axis to kernel
authority only once the slice reaches `default` or later for the projected
supported cohort; exit codes, reason codes, and JSON field names are
stable/versioned.

## `authority-map.v1`

```json
{
  "schema": "authority-map.v1",
  "runtime_version": "string",
  "axes": [
    {
      "axis": "check",
      "authoritative_owner": "kernel",
      "compatibility_direction": "legacy_from_kernel",
      "slice_id": "slice-check-state"
    }
  ]
}
```

Invariants: exactly one entry per `axis`; duplicate owner → `DUPLICATE_STATE_OWNER`
fail-loud; every axis present during partial migration (FR-001, FR-005, FR-019,
SC-001).

## `parity-report.v1`

```json
{
  "schema": "parity-report.v1",
  "slice_id": "slice-check-state",
  "fact_digest": "sha256:...",
  "projection_match": true,
  "decision_match": true,
  "command_plan_match": true,
  "side_effects_executed": 0,
  "differences": []
}
```

Invariants: `side_effects_executed` MUST be `0` (FR-007, SC-003); deterministic
for a given `fact_digest` (SC-002); any non-empty `differences` blocks default
rollout unless explained/versioned (FR-008, SC-004).

## `rollout-state.v1`

```json
{
  "schema": "rollout-state.v1",
  "slices": [
    {
      "slice_id": "slice-check-state",
      "stage": "opt_in",
      "enabled": true,
      "evidence_ref": "evaluation.v1:run-cohort-abc",
      "deprecation_window_complete": false
    }
  ],
  "hypotheses": [
    {
      "hypothesis_id": "output_truncation",
      "stage": "shadow",
      "enabled": false,
      "safe_fallback": "--full output remains default"
    }
  ]
}
```

Invariants: `stage` advances only when the Migration Slice Acceptance Gate holds;
`default`/`deleted` reject provisional-only evidence (SC-008); `deleted` requires
`deprecation_window_complete == true`; `consolidation rollout` accepts durable
feature-023 proof from an explicit `--evidence-file` `evaluation.v1` document
rather than inferring truth from session state or reports; rollback is a stage
transition that never rewrites runtime facts (FR-016, SC-005). The three
`hypotheses` accept/reject/roll back independently (SC-007).

## `deprecation-inventory.v1` (FR-017)

```json
{
  "schema": "deprecation-inventory.v1",
  "entries": [
    {
      "kind": "duplicate_model",
      "target": "core.workflow_matching",
      "replaced_by": "core.runtime_kernel.projections",
      "slice_id": "slice-check-state",
      "contract_boundary": "kernel projection is authoritative; legacy kept until deprecation window completes",
      "removable": false
    }
  ]
}
```

Invariants: deprecation of duplicate models, compatibility shims, and telemetry
fields proceeds only through this explicit, documented inventory (FR-017). An
entry is `removable: true` only when its slice has reached `deprecating` with a
completed window; the coordinated code/test/doc/skill removal itself is deferred
to a follow-up feature (spec FR-018).

## Reversibility & compatibility invariants (cross-cutting)

- Disabling any enabled slice restores the prior authoritative path with runtime
  facts and execution evidence intact (SC-005).
- Unsupported cohorts stay on the established supported path during partial
  migration (SC-006).
- No legacy path is deleted on provisional evidence alone (SC-008).
- Public-contract changes (truncation default, `workflow_decision.v1` handoff)
  update code, executable tests, docs, and `skill/` guidance in the same
  versioned change (FR-009, SC-009).
- Every completed slice reduces a duplicate owner or decision surface without
  adding hidden fallback branches (FR-020, SC-010).
