import subprocess
import sys
import re

MYPY_CMD = ["mypy", "src/gh_address_cr", "--check-untyped-defs", "--disallow-untyped-defs", "--show-error-codes"]
BASELINE = 0

def main():
    print(f"Running: {' '.join(MYPY_CMD)}")
    result = subprocess.run(MYPY_CMD, capture_output=True, text=True)
    output = result.stdout + result.stderr
    print(output)
    match = re.search(r"Found (\d+) error", output)
    error_count = 0
    if match: error_count = int(match.group(1))
    elif "Success: no issues found" in output: error_count = 0
    else:
        if "error:" in output: error_count = output.count("error:")
        elif result.returncode == 0: error_count = 0
    print(f"Current error count: {error_count}")
    print(f"Baseline: {BASELINE}")
    if error_count > BASELINE:
        print(f"FAILED: Mypy error count ({error_count}) exceeds baseline ({BASELINE}).")
        sys.exit(1)
    print("Mypy ratchet check passed.")

if __name__ == "__main__":
    main()
