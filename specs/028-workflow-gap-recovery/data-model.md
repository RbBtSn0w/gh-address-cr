# Data Model: Workflow Gap Recovery

## FinalGateBlocker

- **Purpose**: Represents the projected reason a PR session cannot complete.
- **Key fields**:
  - `reason_code`: stable failure code chosen by policy ordering
  - `waiting_on`: operator-facing blocker category such as `reply_evidence`, `validation_evidence`, `lease_recovery`, `github_environment`, or `telemetry`
  - `failure_codes`: all active failure classes in policy order
  - `next_action`: deterministic recovery instruction derived from runtime truth
  - `commands`: optional command templates for the active PR scope
  - `recoverability`: whether the blocker is claimable, reconcilable, advisory, or terminal stop
- **Relationships**:
  - May reference one or more `ReplyEvidenceRecord`, `LeaseRecoveryState`, or `EnvironmentDiagnostic` instances.

## ReplyEvidenceRecord

- **Purpose**: Durable evidence that a GitHub review thread received a reply from the current authenticated actor.
- **Key fields**:
  - `item_id`
  - `thread_id`
  - `reply_url`
  - `author_login`
  - `source` (`publish` or reconcile path)
  - `idempotency_key`
  - `terminal_thread_state` at reconciliation time
- **Validation rules**:
  - `reply_url` must be non-empty.
  - `author_login` must be non-empty.
  - The referenced item must exist and be a `github_thread`.
- **State transitions**:
  - `missing` → `recorded`
  - `recorded` → `counted_by_final_gate` when login and terminal-state rules are satisfied

## ValidationEvidenceRecord

- **Purpose**: Durable validation proof for a terminal GitHub-thread item that was fixed but resolved out-of-band.
- **Key fields**:
  - `item_id`
  - `thread_id`
  - `commit_hash`
  - `files`
  - `validation_commands`
  - `summary`
  - `why`
  - `source`
- **Validation rules**:
  - Only terminal `github_thread` items are eligible for reconcile.
  - Validation result must be success-like.
  - Commit hash, file set, and validation commands are all required.
- **State transitions**:
  - `missing` → `recorded`
  - `recorded` → `counted_by_logic_validation`

## LeaseRecoveryState

- **Purpose**: Authoritative runtime projection of whether a lease-blocked item can be resumed, reclaimed, renewed, refreshed, or must stop.
- **Key fields**:
  - `lease_id`
  - `item_id`
  - `agent_id`
  - `role`
  - `lease_status`
  - `item_state`
  - `recovery_outcome` (`renew`, `reclaim`, `refresh_state`, `stop`, `already_completed`)
  - `reason_code`
  - `resume_command`
- **Validation rules**:
  - Must be derived from runtime session state, never from stale local response files alone.
  - A `stop` outcome means another actor or newer authoritative state owns the item.
- **State transitions**:
  - `active lease` + matching request → `stop`
  - `expired lease` + open/claimed item → `reclaim`
  - `released/rejected lease` + open item → `reclaim`
  - `handled/accepted item` → `already_completed`

## EnvironmentDiagnostic

- **Purpose**: Runtime classification for non-review blockers or advisories that shape operator recovery.
- **Key fields**:
  - `kind` (`telemetry_coverage`, `gh_permission`, `gh_auth`, `gh_network`, `gh_environment`)
  - `severity` (`advisory`, `blocking`)
  - `reason_code`
  - `diagnostics`
  - `next_action`
  - `source_scope`
- **Relationships**:
  - Can attach to `FinalGateBlocker` or preflight machine summaries.
- **State transitions**:
  - `observed` → `advisory` when local context makes the condition expected
  - `observed` → `blocking` when the condition prevents safe execution or completion evidence

## Relationships Summary

- `FinalGateBlocker` consumes `ReplyEvidenceRecord`, `ValidationEvidenceRecord`,
  `LeaseRecoveryState`, and `EnvironmentDiagnostic` projections.
- `LeaseRecoveryState` influences command-level next actions before submission.
- `EnvironmentDiagnostic` changes operator guidance but does not own review-item truth.
