# Data Model: Agent Efficiency Metrics

## Entities

### `ExecutionMetric` (Data Class)
Represents a single invocation of a shell command or skill.

**Fields**:
- `command` (str): The raw command executed (or a truncated/sanitized version).
- `start_time` (float): Epoch timestamp (e.g., from `time.time()`).
- `end_time` (float): Epoch timestamp.
- `duration` (float): `end_time - start_time`.
- `exit_code` (int): The return code of the subprocess (0 usually indicates success).
- `is_success` (bool): Derived from `exit_code == 0`.
- `is_retry` (bool): True if this command is identical to the immediately preceding command and the preceding command failed.

### `EfficiencyReport` (Data Class)
Represents the aggregated statistics for the entire session.

**Fields**:
- `total_invocations` (int): Total commands run.
- `total_duration` (float): Sum of all `duration` fields.
- `success_rate` (float): `(successful_invocations / total_invocations) * 100`.
- `flagged_inefficiencies` (list[str]): A list of formatted strings describing executions that breached the thresholds.

## Threshold Constants

- `MAX_DURATION_SECONDS`: `60.0`
- `MAX_ERROR_RATE_PERCENT`: `20.0`
