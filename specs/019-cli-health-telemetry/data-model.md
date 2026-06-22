# Data Model: CLI Health Telemetry

## `CliHealthIssue`

- `reason_code`: stable machine-readable taxonomy value.
- `severity`: `info`, `warning`, or `blocking`.
- `source`: `runtime`, `host-autodiscovery`, `telemetry-store`, or `profile`.
- `retryable`: boolean.
- `detail`: public-safe human-readable detail.
- `next_action`: concrete recovery action.

## `HostAutodiscoveryCheck`

- `profile`: host profile source, for example `codex` or `claude-code`.
- `status`: `passed`, `skipped`, or `failed`.
- `reason_code`: stable taxonomy value.
- `detail`: public-safe diagnostic detail.
- `next_action`: recovery action.

## `TelemetryDoctorReport`

- `status`: `PASSED` or `FAILED`.
- `reason_code`: `TELEMETRY_DOCTOR_PASSED` or `TELEMETRY_DOCTOR_ISSUES`.
- `coverage_label`: current efficiency telemetry coverage label.
- `profile_checks`: list of `HostAutodiscoveryCheck`.
- `cli_health_issues`: list of `CliHealthIssue`.
- `telemetry_report_artifact`: path to the efficiency report artifact.

## Initial Taxonomy

- `TELEMETRY_AUTODISCOVERY_DISABLED`
- `TELEMETRY_AUTODISCOVERY_MISS`
- `TELEMETRY_PROFILE_INVALID`
- `TELEMETRY_PROFILE_ENV_MISSING`
- `TELEMETRY_TRANSCRIPT_NOT_FOUND`
- `TELEMETRY_SESSION_WINDOW_MISSING`
- `TELEMETRY_TRANSCRIPT_OUT_OF_WINDOW`
- `TELEMETRY_STORE_UNAVAILABLE`
- `TELEMETRY_TIMING_UNAVAILABLE`
- `CLI_COMMAND_FAILURE`
- `CLI_COMMAND_TIMEOUT`
- `CLI_RETRY_LOOP`
- `CLI_WAIT_STATE`
- `CLI_REASON_CODE_OBSERVED`
