## 2024-05-15 - Telemetry Credential Leak via Space-Separated Arguments
**Vulnerability:** Telemetry argument sanitization (`safe_command_args`) only correctly handled `--token=value` (assignment syntax), allowing space-separated credentials like `--token <secret>` to be logged unredacted.
**Learning:** Argument sanitization must always account for both `key=value` assignment and positional state machines (`key` followed by `value` as separate arguments) for flags. Simple substring/equals checks are insufficient to capture all CLI parsing edge cases.
**Prevention:** Implement stateful iteration over argument lists to redact the subsequent element when a sensitive flag is encountered without an `=` sign.
