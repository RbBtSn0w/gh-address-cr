import subprocess
import sys
import re

MYPY_CMD = ["mypy", "src/gh_address_cr", "--check-untyped-defs", "--disallow-untyped-defs", "--show-error-codes"]
BASELINE = 0
TIMEOUT_SECONDS = 300

def main():
    print(f"Running: {' '.join(MYPY_CMD)}")
    try:
        result = subprocess.run(MYPY_CMD, capture_output=True, text=True, timeout=TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        print(f"FAILED: Mypy timed out after {TIMEOUT_SECONDS}s.")
        sys.exit(1)
    except Exception as exc:
        print(f"FAILED: Mypy execution failed: {type(exc).__name__}: {exc}")
        sys.exit(1)

    output = result.stdout + result.stderr
    print(output)

    match = re.search(r"Found (\d+) error", output)
    error_count = None

    if match:
        error_count = int(match.group(1))
    elif "Success: no issues found" in output:
        error_count = 0
    elif "error:" in output:
        error_count = output.count("error:")
    elif result.returncode == 0:
        error_count = 0

    if error_count is None:
        if result.returncode != 0:
            print(f"FAILED: Mypy exited with {result.returncode} but error count could not be parsed.")
            sys.exit(1)
        error_count = 0

    print(f"Current error count: {error_count}")
    print(f"Baseline: {BASELINE}")

    if error_count > BASELINE:
        print(f"FAILED: Mypy error count ({error_count}) exceeds baseline ({BASELINE}).")
        sys.exit(1)

    print("Mypy ratchet check passed.")

if __name__ == "__main__":
    main()
