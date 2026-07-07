# Research: Workflow Gap Recovery

## Decision 1: Reuse `agent evidence add` as the terminal-item reconcile surface

- **Decision**: Keep terminal GitHub-thread recovery centered on `agent evidence add` for reply and validation evidence reconciliation, and make `final-gate` next actions route there when the blocker is a closed historical item rather than blindly routing to `agent publish`.
- **Rationale**: The runtime already contains reconcile-only entrypoints in `src/gh_address_cr/core/workflow.py` for out-of-band reply evidence and validation evidence. Reusing them keeps the state model narrow: claimable items still go through `agent resolve`/`agent publish`, while terminal items use explicit evidence reconciliation.
- **Alternatives considered**:
  - Extend `agent publish` with hidden auto-reconcile behavior. Rejected because it would make publish mutate terminal historical state without explicit operator intent.
  - Allow manual session artifact edits. Rejected because artifacts are evidence outputs, not authoritative truth.

## Decision 2: Do not overload `agent resolve <item_id>` with stale or homogeneous modes

- **Decision**: Keep `agent resolve <item_id>` mutually exclusive from `--stale`, `--batch`, and `--homogeneous-reason`, and solve item-specific closed-thread recovery through reconcile commands plus better next-action guidance instead of collapsing all modes into one overloaded entrypoint.
- **Rationale**: `src/gh_address_cr/commands/agent.py` explicitly rejects `ITEM_ID_NOT_ALLOWED_FOR_MODE` today. Preserving that separation avoids a larger state explosion in claim/lease semantics. The missing capability is not “all modes on one command”; it is “a supported route for terminal or non-claimable items.”
- **Alternatives considered**:
  - Permit `<item_id> + --stale` or `<item_id> + --homogeneous-reason`. Rejected because it blurs claimable-thread workflows with terminal-thread reconciliation and risks bypassing existing routing guards.
  - Introduce a separate low-level mutation command for historical items. Rejected because `agent evidence add` already serves that purpose with narrower semantics.

## Decision 3: Make lease conflict diagnostics first-class machine-readable recovery state

- **Decision**: When individual actions are blocked by active batch leases, return explicit lease-owner diagnostics and safe recovery guidance derived from `calculate_lease_recovery_state`, instead of exposing only `NO_ELIGIBLE_ITEM`.
- **Rationale**: `src/gh_address_cr/core/leases.py` already models recovery outcomes such as `reclaim`, `refresh_state`, `renew`, `stop`, and `already_completed`. Surfacing that state directly at the command boundary is lower-risk than inventing a second lease state machine.
- **Alternatives considered**:
  - Auto-release non-expired batch leases on every individual resolve attempt. Rejected because it would mutate authoritative runtime state without proving ownership or operator intent.
  - Leave leases opaque and tell users to inspect JSON files manually. Rejected because it violates the stable runtime recovery contract.

## Decision 4: Treat local `runtime-only` telemetry as advisory-by-context, not abnormal-by-default

- **Decision**: Preserve the `runtime-only` coverage label, but adjust final-gate guidance and attention-item wording so local runs without imported host telemetry are advisory unless another verified telemetry defect exists.
- **Rationale**: `runtime-only` is already a valid coverage label across docs and tests. The problem is severity projection and completion messaging, not the label itself. This keeps telemetry observed and fail-open while aligning the human guidance with the repo constitution.
- **Alternatives considered**:
  - Rename or remove `runtime-only`. Rejected because it is already part of the documented public telemetry vocabulary.
  - Treat all incomplete coverage as equally abnormal. Rejected because local-only runs and malformed telemetry are not equivalent operator situations.

## Decision 5: Split wrapped-`gh` permission mismatch from generic environment failures

- **Decision**: Add a dedicated diagnostic path for wrapped GitHub CLI permission mismatches so safeclis/runner permission drift can return a concrete remediation instead of being lumped into generic `GH_ENVIRONMENT_FAILED`.
- **Rationale**: Current preflight mapping in `src/gh_address_cr/cli.py` collapses sandbox/environment issues into one bucket. Issue `#200` needs a sharper distinction: “the runner is authorized, but the local wrapper permission view is stale or narrower” is operationally different from PATH, filesystem, or sandbox failure.
- **Alternatives considered**:
  - Keep the generic environment bucket and document the edge case in prose only. Rejected because it leaves no machine-readable route for skills or agent runners.
  - Treat wrapper permission mismatch as auth failure. Rejected because authentication and permission scope are different operator fixes.
