## 2024-05-01 - Stateful CLI argument sanitization
**Vulnerability:** Command-line argument sanitization failed to redact sensitive space-separated values (e.g., `--token value`), exposing secrets in telemetry.
**Learning:** Checking arguments independently without state fails to map values to their corresponding keys in CLI space-separated formatting.
**Prevention:** Implement stateful iteration in `safe_command_args` to set a flag when an unsafe key is encountered and redact the subsequent value.
