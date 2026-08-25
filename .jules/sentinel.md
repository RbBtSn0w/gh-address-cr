## 2024-05-18 - Fix CLI Argument Sanitization for Space-Separated Secrets
**Vulnerability:** Command-line argument sanitization failed to redact sensitive secrets (e.g., tokens) when they were passed as space-separated values (e.g., `--token mysecret`).
**Learning:** `safe_command_args` only checked for assignment syntax (`--token=mysecret`) or global redacting of standalone tokens, leaving space-separated sensitive flags completely exposed in telemetry.
**Prevention:** Implement stateful iteration in CLI argument sanitizers to track when the previous argument was a sensitive flag, so the subsequent value can be redacted correctly.
