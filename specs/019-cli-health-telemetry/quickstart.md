# Quickstart: CLI Health Telemetry

Run a health check for a PR-scoped session:

```bash
gh-address-cr telemetry doctor owner/repo 123
```

Inspect the current efficiency report:

```bash
gh-address-cr telemetry summary owner/repo 123 --format json
```

When final-gate reports `runtime-only`, run the doctor command to determine
whether the host feed was missing because no profile env was set, no transcript
matched, the PR session window was unavailable, or telemetry storage was
damaged.

