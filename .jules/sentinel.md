## 2025-01-22 - Secret Leakage in Space-Separated CLI Arguments
**Vulnerability:** Telemetry command argument sanitization (`safe_command_args`) leaked sensitive values when they were provided as space-separated arguments (e.g., `--token secret_value`) rather than assignment syntax (e.g., `--token=secret_value`).
**Learning:** The sanitization loop only properly processed flags containing an `=` sign, treating the subsequent argument in space-separated pairs as a regular positional argument which evaded redaction.
**Prevention:** Implement stateful iteration when sanitizing command-line arguments. If an unsafe flag is detected, set a state variable to explicitly redact the next argument in the loop before reverting back to the standard checking behavior.
