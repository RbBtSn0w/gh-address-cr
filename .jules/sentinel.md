## 2026-08-27 - Space-separated arguments in telemetry leak secrets
**Vulnerability:** `safe_command_args` function in `src/gh_address_cr/core/telemetry_safety.py` failed to redact secrets when passed as space-separated arguments (e.g., `--token value`), though it did redact `--token=value`. This leads to credential exposure in telemetry and logs.
**Learning:** Argument sanitization logic must use stateful iteration to account for both space-separated values (where a flag indicates the subsequent argument is sensitive) and assigned values (flag=value).
**Prevention:** When parsing CLI arguments for sanitization, use an iterator or keep track of the previous flag to correctly identify and redact the value associated with a sensitive flag, regardless of syntax.
