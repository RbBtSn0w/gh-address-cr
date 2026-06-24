"""Mypy ratchet gate: fail CI if the error count exceeds the baseline.

The mypy invocation is intentionally flag-free so that pyproject.toml's
[tool.mypy] section (files + strict flags) stays the single source of truth.
"""
import re
import subprocess
import sys

# Config-driven: flags and target files come from [tool.mypy] in pyproject.toml.
MYPY_CMD = ["mypy", "--show-error-codes"]
BASELINE = 0


def main() -> None:
    print(f"Running: {' '.join(MYPY_CMD)}")
    try:
        result = subprocess.run(MYPY_CMD, capture_output=True, text=True, timeout=300)
    except Exception as exc:  # includes subprocess.TimeoutExpired
        print(f"FAILED: mypy execution failed or timed out: {exc}")
        sys.exit(1)
    output = result.stdout + result.stderr
    print(output)

    match = re.search(r"Found (\d+) error", output)
    if match:
        error_count = int(match.group(1))
    elif "Success: no issues found" in output:
        error_count = 0
    elif "error:" in output:
        error_count = output.count("error:")
    elif result.returncode == 0:
        error_count = 0
    else:
        # mypy failed without a parseable count (e.g. crash/config error).
        print(f"FAILED: mypy exited with code {result.returncode} and no parseable result.")
        sys.exit(1)

    print(f"Current error count: {error_count}")
    print(f"Baseline: {BASELINE}")
    if error_count > BASELINE:
        print(f"FAILED: Mypy error count ({error_count}) exceeds baseline ({BASELINE}).")
        sys.exit(1)
    print("Mypy ratchet check passed.")


if __name__ == "__main__":
    main()
