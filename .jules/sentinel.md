## 2024-05-18 - Sanitize Command Arguments in Diagnostics
**Vulnerability:** GitHub CLI commands were included verbatim in diagnostic exceptions, potentially leaking secrets passed as command-line arguments into logs or telemetry.
**Learning:** Diagnostic formatting often prioritizes verbosity and context over security, leading to accidental secret leakage if raw inputs are embedded without passing through a sanitization layer.
**Prevention:** Always ensure that diagnostic payloads that include command-line arguments are sanitized using the centralized telemetry safety functions (e.g., `safe_command_args` from `src/gh_address_cr/core/telemetry_safety.py`) before logging or exposing them.
