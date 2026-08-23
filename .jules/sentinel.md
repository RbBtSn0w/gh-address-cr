## 2024-05-24 - Space-Separated CLI Secrets Telemetry Leak
**Vulnerability:** Telemetry command line argument sanitization failed to redact secrets passed via space-separated values (e.g., `--token mysecret`), leading to potential sensitive credential leakage in telemetry.
**Learning:** The sanitization logic only accounted for the assignment syntax (`--token=mysecret`). Parsing CLI arguments without proper context of the preceding flag leaves alternative passing patterns exposed.
**Prevention:** Implement stateful iteration over CLI arguments to securely sanitize space-separated values when the preceding token is identified as an unsafe metadata key, taking care not to aggressively redact subsequent flags.
