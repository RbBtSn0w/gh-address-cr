# Contract: Environment Diagnostics

## Purpose

Define how local-environment telemetry coverage and wrapped GitHub CLI
permission failures are classified and surfaced without conflating them with
review-resolution truth.

## Telemetry Coverage Guidance

### `runtime-only`

- **Meaning**: Runtime command events exist, but host-side telemetry was not imported.
- **Default treatment**:
  - Advisory for local development loops when no other telemetry defect is present.
  - Report explicitly in completion output, but do not treat it as review-resolution failure.
- **Still blocking when**:
  - Telemetry artifacts are malformed or unsafe.
  - The command explicitly requires telemetry ingestion that failed.

### `partial`

- **Meaning**: Some telemetry sources were present but incomplete.
- **Treatment**:
  - Advisory by default, unless the missing portion invalidates a requested proof surface.

### `unavailable`

- **Meaning**: No usable telemetry evidence exists.
- **Treatment**:
  - Explicitly reported.
  - Fail-open for core review completion unless a telemetry-specific command or contract requires telemetry.

## GitHub Preflight Permission Diagnostics

### Wrapper permission mismatch

- **Meaning**: The runner or host has been granted permission for the intended GitHub action, but the wrapped local `gh` execution surface still denies the operation.
- **Required behavior**:
  - Return a distinct machine-readable reason code or diagnostic discriminator such as `GH_PERMISSION_MISMATCH`.
  - Mark the diagnostic as `severity=blocking`.
  - Expose a wrapper-scoped source marker such as `source_scope=github_wrapper`.
  - Provide a remediation that points to permission synchronization or wrapper configuration, not only generic auth or sandbox repair.

### Generic environment failure

- **Meaning**: PATH, filesystem, sandbox, or local execution conditions prevent `gh` from running correctly.
- **Required behavior**:
  - Remain distinct from auth, network, rate-limit, and permission-mismatch cases.
  - Continue to fail fast before side effects.

## Reporting Rules

- Diagnostics must not mutate review state.
- Machine summaries must expose:
  - `reason_code`
  - `waiting_on`
  - `next_action`
  - targeted `diagnostics`
  - diagnostic `severity`
  - diagnostic `source_scope`
- Skill and completion guidance may explain advisory implications, but runtime
  code remains the source of truth for severity and recovery.
