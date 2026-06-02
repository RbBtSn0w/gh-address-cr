# Feature Specification: Agent Efficiency Metrics

**Feature Branch**: `011-agent-efficiency-metrics`
**Created**: 2026-05-29
**Status**: In Review
**Input**: User description: "在ai agent的工作流程中，整个流程的高效性，如何评价和度量ai agent使用skill和cli工具，如果存在效率底下，就应该组织性能优化的工作了。"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Evaluate Workflow Efficiency (Priority: P1)

As an engineer or team lead, I want the system to automatically track and summarize the execution metrics of the AI agent's skills and CLI tools, so that I can evaluate the overall efficiency of the workflow at a glance.

**Why this priority**: Essential for understanding the baseline performance of the agent before any optimizations can be planned.

**Independent Test**: Execute an agent session and verify that a structured efficiency summary (e.g., tool invocations, duration, success rates) is generated at the end.

**Acceptance Scenarios**:

1. **Given** an active agent session processing a PR, **When** the agent invokes various skills and CLI commands, **Then** the system records the start time, end time, and exit status of each invocation.
2. **Given** a completed agent session, **When** the final gate concludes, **Then** an efficiency summary report is appended to the session output or logs.

---

### User Story 2 - Flag Inefficiencies (Priority: P1)

As an engineering manager, I want the system to detect and flag operations that fall below expected efficiency standards (e.g., excessive retries, timeouts, or extremely long tool executions), so that we can prioritize and organize performance optimization work for those specific bottlenecks.

**Why this priority**: Without automated flagging, inefficiencies hide in logs. Highlighting them is the trigger for optimization.

**Independent Test**: Can be tested by mocking a tool execution that exceeds the configured duration threshold and verifying that it is distinctly flagged in the summary report.

**Acceptance Scenarios**:

1. **Given** an agent session, **When** a CLI tool execution takes longer than the defined maximum threshold, **Then** the execution is flagged as "Inefficient" in the metrics.
2. **Given** an agent session, **When** the agent repeatedly fails and retries the same skill or tool multiple times, **Then** the system records an inefficiency alert for "High Retry Rate".

---

### User Story 3 - Export Metrics for Optimization Analysis (Priority: P2)

As a skill developer, I want to export structured workflow metrics (JSON format) across multiple agent sessions, so that I can perform aggregate analysis to pinpoint structural issues and design skill performance improvements.

**Why this priority**: Aggregate data provides long-term value for systemic improvements across the workspace.

**Independent Test**: Run a command to extract/export the metrics payload and verify it adheres to a standard JSON schema containing tool execution timings.

**Acceptance Scenarios**:

1. **Given** a completed session, **When** I request the machine-readable output, **Then** a JSON artifact containing detailed telemetry for tool/skill usage is provided.

### Edge Cases

- What happens when a tool execution hangs indefinitely? (System must timeout and log it as a critical inefficiency).
- How does system handle concurrent or parallel tool executions? (Metrics must track unique IDs or PIDs per execution to avoid cross-talk).
- What if the telemetry layer itself fails? (Must fail-open, preserving the core agent review loop without crashing).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST intercept and record start and end timestamps for all skill invocations and CLI tool executions.
- **FR-002**: System MUST capture the exit status (success/failure) of each tracked invocation.
- **FR-003**: System MUST define quantifiable thresholds for inefficiencies: execution time > 60 seconds OR error rate > 20%.
- **FR-004**: System MUST count the number of consecutive retries or failures for the same command context.
- **FR-005**: System MUST aggregate the recorded metrics and generate a human-readable efficiency summary at the end of the `gh-address-cr` session.
- **FR-006**: System MUST highlight or flag any metric that violates the defined efficiency thresholds within the report, signaling the need for optimization.
- **FR-007**: System MUST provide a mechanism to export the efficiency data by appending a human-readable text summary of the current efficiency status to the task completion reply.

### Constitution Alignment *(mandatory)*

- **Control Plane Impact**: This feature introduces a telemetry/metrics collection layer within the control plane's session state. The deterministic runtime will own the aggregation of these metrics to ensure accurate reporting.
- **CLI / Agent Contract Impact**: Adds a new output artifact (efficiency report) to the final gate and potentially a new command to query metrics. Preserves the existing Status-to-Action Map.
- **Evidence Requirements**: The efficiency metrics and any generated warnings serve as the evidence of workflow health.
- **Packaged Skill Boundary**: The tracking logic should reside in the core runtime (`src/gh_address_cr`), while the agent instructions might be updated to respect tracking context if necessary.
- **External Intake Replaceability**: Does not affect the Normalized Findings Contract.
- **Fail-Fast Behavior**: Metric collection MUST NOT block or crash the main execution loop; failures in telemetry should log silently without disrupting the PR review.

### Key Entities

- **Execution Metric**: Represents a single invocation of a skill or CLI tool, containing `command`, `start_time`, `end_time`, `duration`, `exit_code`, `is_retry`, `pid`, and `execution_id`.
- **Efficiency Report**: An aggregation of Execution Metrics for a specific PR session, containing overall statistics and a list of flagged inefficiencies.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: System captures execution metrics for 100% of skills and CLI tools invoked during the session.
- **SC-002**: Metric collection overhead adds less than 2% to the total session execution time.
- **SC-003**: The generated efficiency report clearly surfaces the top 3 slowest or most error-prone tool executions per session.
- **SC-004**: Users are able to trigger optimization discussions by directly sharing the structured JSON metrics artifact.

## Assumptions

- We assume the existing runtime environment (`gh_address_cr.core.cr_loop.run_cmd`, etc.) can be wrapped or augmented to emit execution events.
- We assume that "skill" and "CLI tool" invocations are distinguishable in the runtime context.
- We assume that the user's primary goal is visibility and reporting to drive manual optimization, not necessarily automatic self-healing by the agent.