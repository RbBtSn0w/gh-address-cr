
## 2026-08-22 - Fix stateful argument parsing vulnerability
**Vulnerability:** Argument sanitization missed space-separated sensitive flags (e.g. `--token value`).
**Learning:** Command line argument parsing must be stateful to catch values of sensitive flags that are passed as separate arguments.
**Prevention:** Use a state flag during argument iteration to redact the argument immediately following a sensitive flag.
