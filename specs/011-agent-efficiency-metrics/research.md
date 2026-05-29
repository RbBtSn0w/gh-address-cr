# Research: Agent Efficiency Metrics

## 1. Interception Point for CLI Tools
- **Decision**: Wrap the existing `run_cmd` function in `src/gh_address_cr/core/cr_loop.py` to record start and end timestamps.
- **Rationale**: `run_cmd` is the unified bottleneck through which the agent control plane executes external shell commands. Wrapping it guarantees 100% capture of CLI tool executions without needing to scatter tracking logic across the codebase.
- **Alternatives considered**: Modifying the agent's prompt to force the agent to emit timestamps (rejected because it's unreliable, wastes tokens, and violates the "deterministic runtime owns state" rule).

## 2. Tracking Context and State Storage
- **Decision**: Introduce a `SessionTelemetry` singleton or context object instantiated at the start of the `gh-address-cr` invocation to hold in-memory `ExecutionMetric` records.
- **Rationale**: The metrics only need to live for the duration of the process to generate the final summary appended to the reply. In-memory storage adds effectively zero overhead.
- **Alternatives considered**: Writing each metric immediately to a JSON file (rejected due to I/O overhead and synchronization complexity, though it could be added later if cross-process persistence is needed).

## 3. Threshold and Efficiency Calculation
- **Decision**: Implement a pure function `evaluate_efficiency(metrics: list[ExecutionMetric]) -> EfficiencyReport` in `src/gh_address_cr/core/telemetry.py`. The threshold logic (time > 60s OR error rate > 20%) will be constants within this module.
- **Rationale**: Isolates business logic for testability. Makes it trivial to write unit tests with mocked timestamps and exit codes.
- **Alternatives considered**: Calculating metrics inline during `run_cmd` (rejected due to mixing concerns and making the summary phase difficult).

## 4. Appending Summary to the Completion Reply
- **Decision**: Update `fix_reply` (and potentially `clarify_reply`/`defer_reply`) in `src/gh_address_cr/core/reply_templates.py` to accept an optional `efficiency_summary` string parameter, which will be formatted into a markdown blockquote or expandable `<details>` section at the bottom of the reply.
- **Rationale**: Ensures the metrics are highly visible at the exact moment of task completion (resolving FR-007) while maintaining the structured, deterministic formatting of the reply templates.
- **Alternatives considered**: Posting a separate GitHub comment (rejected due to PR noise).
