# Contract: CLI Health Telemetry

## Command

```bash
gh-address-cr telemetry doctor <owner/repo> <pr_number> [--format json|markdown]
```

JSON output:

```json
{
  "status": "PASSED",
  "reason_code": "TELEMETRY_DOCTOR_PASSED",
  "repo": "owner/repo",
  "pr_number": "123",
  "coverage_label": "runtime-only",
  "profile_checks": [
    {
      "profile": "codex",
      "status": "skipped",
      "reason_code": "TELEMETRY_PROFILE_ENV_MISSING",
      "detail": "No configured session id environment variable is set.",
      "next_action": "Run from an active supported agent session or set the profile session id environment variable."
    }
  ],
  "cli_health_issues": [],
  "telemetry_report_artifact": ".../efficiency-report.json",
  "next_action": "Inspect failed checks and rerun telemetry doctor."
}
```

## Fail-Open Diagnostic Import Summary

When final-gate cannot autodiscover host telemetry, it may append an import
summary:

```json
{
  "status": "FAILED",
  "reason_code": "TELEMETRY_AUTODISCOVERY_MISS",
  "source": "host-autodiscovery",
  "format": "agent-jsonl",
  "diagnostics": [
    "host telemetry autodiscovery codex: TELEMETRY_PROFILE_ENV_MISSING"
  ]
}
```

This diagnostic affects telemetry coverage and reporting only. It MUST NOT
change final-gate completion truth.

