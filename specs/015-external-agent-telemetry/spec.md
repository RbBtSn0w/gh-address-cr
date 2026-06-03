# Feature Specification: External Agent Telemetry Ingestion

**Feature Branch**: `016-external-agent-telemetry`  
**Created**: 2026-06-03  
**Status**: Draft  
**Input**: User description: "External Agent Telemetry Ingestion，按照探究方案来构建spec"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Import Host Agent Telemetry (Priority: P1)

As an engineer using `gh-address-cr` to close pull request review work, I want to import telemetry from the surrounding AI agent host so the final efficiency report reflects both runtime-managed work and outer agent tool usage.

**Why this priority**: The existing efficiency metrics only cover runtime-visible commands and submitted validation evidence. Without host telemetry ingestion, the report misses the time and failures spent in agent tool calls, waiting, retries, and supporting investigation.

**Independent Test**: Complete a PR-scoped workflow with an external agent telemetry feed and verify that the final efficiency report includes both runtime and external agent observations with a clear coverage statement.

**Acceptance Scenarios**:

1. **Given** a PR session has runtime telemetry and an imported host-agent telemetry feed, **When** the user requests the final efficiency report, **Then** the report includes metrics from both sources and states that host telemetry was imported.
2. **Given** host-agent telemetry is unavailable, **When** the user requests the final efficiency report, **Then** the report still succeeds and clearly labels the coverage as runtime-only.
3. **Given** an imported host-agent feed contains tool calls, waits, failures, and retries, **When** the report is generated, **Then** the report summarizes counts, success rate, total observed duration, slowest operations, and inefficiency flags across the imported feed.

---

### User Story 2 - Support Generic AI Agent Reporting (Priority: P1)

As a maintainer of agent workflow tooling, I want any AI agent host to provide telemetry through a common event contract so `gh-address-cr` can evaluate workflow efficiency without being tied to one vendor or one log format.

**Why this priority**: Workflow efficiency should be comparable across Codex, other coding agents, CI agents, and future local or remote agent hosts. A generic contract prevents the feature from becoming a Codex-only integration.

**Independent Test**: Provide a telemetry feed from a generic agent source and verify that it is accepted, normalized, and included in the final report without requiring source-specific behavior.

**Acceptance Scenarios**:

1. **Given** a telemetry feed follows the generic agent event contract, **When** it is imported into a PR session, **Then** the system accepts the feed and records the source, session identifier, event types, durations, statuses, and optional metadata.
2. **Given** a telemetry feed comes from a known host-specific adapter, **When** it is imported, **Then** the system normalizes it to the same canonical event model used for generic feeds.
3. **Given** a telemetry feed uses a standard event or observability envelope, **When** it is imported, **Then** the system preserves enough source and coverage information for the final report to explain what was observed and what was not.

---

### User Story 3 - Repair Existing Metrics Summary Gap (Priority: P1)

As an engineer relying on the existing agent efficiency metrics feature, I want the current runtime metrics to appear in final-gate output, audit summaries, and shareable reports so the original efficiency-metrics promise is honored even when no external host telemetry is available.

**Why this priority**: The previous metrics feature can append efficiency data to published review-thread replies, but users also need the session completion summary and audit evidence to show the current metrics state. This repair is required before external telemetry ingestion can be trusted as an enhancement rather than another partial reporting surface.

**Independent Test**: Complete a PR-scoped workflow using only runtime telemetry and verify that final-gate output, audit summary, and structured report artifacts all include a runtime-only efficiency summary and coverage label.

**Acceptance Scenarios**:

1. **Given** a PR session has runtime telemetry but no external host telemetry, **When** final-gate passes, **Then** the final-gate output includes a runtime-only efficiency summary and a shareable structured report location.
2. **Given** a PR session has runtime telemetry, **When** the audit summary is written, **Then** the audit summary includes the current metrics status, coverage label, and top inefficiency signals.
3. **Given** no telemetry is available, **When** final-gate passes, **Then** the completion evidence explicitly reports telemetry coverage as unavailable instead of silently omitting metrics.

---

### User Story 4 - Diagnose Workflow Inefficiencies (Priority: P2)

As a team lead reviewing agent performance, I want the final report to identify the most expensive and error-prone parts of the workflow so I can decide whether to improve prompts, skills, adapters, validation steps, or runtime behavior.

**Why this priority**: Raw event logs are hard to act on. The report should convert telemetry into optimization signals that help prioritize workflow improvements.

**Independent Test**: Import telemetry with a mix of long-running operations, repeated failures, and successful commands, then verify that the report highlights the top bottlenecks and gives a clear confidence level.

**Acceptance Scenarios**:

1. **Given** imported telemetry contains long-running operations, **When** the efficiency report is generated, **Then** the report lists the slowest observed operations and flags those exceeding the configured threshold.
2. **Given** imported telemetry contains repeated failures or retries for the same operation, **When** the efficiency report is generated, **Then** the report flags high retry or error-rate patterns.
3. **Given** the report combines runtime and external telemetry, **When** the user reviews the summary, **Then** the report includes a confidence or coverage label that prevents partial telemetry from being mistaken for complete workflow evidence.

### Edge Cases

- What happens when an external telemetry feed is malformed? The import must fail loudly for that feed, identify the invalid record or missing required field, and preserve existing PR session state.
- What happens when an external telemetry feed contains sensitive paths, usernames, tokens, or raw prompts? The import must reject or sanitize unsafe fields before they can appear in public summaries.
- How does the system handle duplicate imports of the same telemetry feed? Duplicate events must not inflate counts, durations, retries, or slowest-operation rankings.
- How does the system handle overlapping runtime and external telemetry for the same command? The final report must preserve source attribution and avoid double-counting when events can be correlated.
- What happens when host telemetry is only partially available? The final report must label the coverage as partial and continue to provide runtime metrics.
- How does the system handle telemetry from multiple agent hosts for one PR? The report must group or attribute metrics by source while still producing an overall workflow summary.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST allow a PR session to accept external agent telemetry from generic agent sources and known host-specific adapters.
- **FR-002**: System MUST define a canonical event model for external agent telemetry that captures source, agent session identity, event type, operation name, start time, end time or duration, status, and safe metadata.
- **FR-003**: System MUST normalize all accepted external telemetry into the same reportable model used by the efficiency report.
- **FR-004**: System MUST preserve source attribution for each imported telemetry event so reports can distinguish runtime telemetry, generic agent telemetry, and host-specific adapter telemetry.
- **FR-005**: System MUST reject malformed external telemetry with actionable diagnostics and without mutating unrelated PR session state.
- **FR-006**: System MUST sanitize or reject sensitive telemetry fields, including tokens, credentials, raw prompts, usernames, private machine identifiers, and unnecessary absolute local paths.
- **FR-007**: System MUST detect duplicate imported events and prevent duplicate imports from inflating report metrics.
- **FR-008**: System MUST combine runtime telemetry and imported external agent telemetry into one human-readable efficiency summary for the active PR session.
- **FR-009**: System MUST produce a structured efficiency report artifact that includes source coverage, event counts, success rate, observed duration, slowest operations, error-prone operations, and inefficiency flags.
- **FR-010**: System MUST include a coverage label in every final efficiency summary: complete, partial, runtime-only, or unavailable.
- **FR-011**: System MUST include external telemetry status in final-gate evidence so users can tell whether host-agent metrics were imported before completion.
- **FR-012**: System MUST support generic AI agents without requiring vendor-specific behavior, while still allowing source-specific adapters to provide richer imports.
- **FR-013**: System MUST allow users to share the structured report for optimization discussions without exposing private or unsafe telemetry content.
- **FR-014**: System MUST keep telemetry failures fail-open for the core PR review workflow while failing loudly for the specific telemetry import or report request that could not be completed.
- **FR-015**: System MUST keep the existing runtime-owned review, reply, resolve, and final-gate behavior authoritative; imported telemetry must not change review item state by itself.
- **FR-016**: System MUST repair the existing efficiency-metrics summary gap by including runtime telemetry metrics in final-gate output, audit summaries, and structured efficiency report artifacts even when no external host telemetry has been imported.
- **FR-017**: System MUST treat `repair-telemetry-metrics` as part of this feature scope: existing runtime metrics must no longer be limited to published review-thread reply bodies.

### Constitution Alignment *(mandatory)*

- **Control Plane Impact**: This feature affects telemetry, audit artifacts, session evidence, and final-gate reporting. The deterministic runtime remains the owner of normalized telemetry state, source coverage calculation, report generation, and final-gate evidence.
- **CLI / Agent Contract Impact**: This feature adds a public telemetry ingestion and summary contract for PR-scoped sessions. Existing review, address, publish, and final-gate statuses and reason codes remain stable unless a telemetry-specific command is invoked.
- **Evidence Requirements**: A completed workflow must show whether runtime telemetry, external agent telemetry, both, or neither were available. Final evidence must include the efficiency summary, structured report location or identifier, source coverage label, and any rejected telemetry diagnostics.
- **Packaged Skill Boundary**: The packaged skill remains a thin behavioral policy layer. It may instruct agents to import host telemetry when available and to report coverage labels, but telemetry normalization, storage, safety checks, and reporting belong to the runtime.
- **External Intake Replaceability**: This feature preserves review producer replaceability. External telemetry intake is separate from findings intake and must not couple PR review resolution to any specific review producer or agent host.
- **Fail-Fast Behavior**: Malformed telemetry feeds, unsafe telemetry content, unsupported source formats, duplicate-only imports, and ambiguous session ownership must fail loudly for telemetry ingestion while preserving the core PR workflow.

### Key Entities *(include if feature involves data)*

- **External Telemetry Event**: A single observed agent-host event, such as a tool call, wait, retry, command execution, or validation step. Key attributes include source, session identity, event type, operation name, timing, status, and safe metadata.
- **Telemetry Source**: The origin of telemetry, such as runtime, generic agent, host-specific adapter, or manual report. It determines source attribution and coverage confidence.
- **Telemetry Import**: A PR-scoped batch of external telemetry events, including import status, source, deduplication identity, validation diagnostics, and safety results.
- **Coverage Report**: A statement describing which observation surfaces were available for the PR session, what was imported, what was missing, and how much confidence users should place in the efficiency summary.
- **Efficiency Report**: A combined runtime and external telemetry summary containing counts, success rate, duration, slowest operations, error-prone operations, inefficiency flags, and source coverage.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Users can import a valid generic agent telemetry feed for a PR session and see it reflected in the final efficiency summary in one workflow attempt.
- **SC-002**: Final efficiency summaries always include a coverage label, and users can distinguish runtime-only reports from reports that include host-agent telemetry.
- **SC-003**: Duplicate telemetry imports do not change total event counts, total observed duration, retry counts, or slowest-operation rankings.
- **SC-004**: Malformed or unsafe telemetry feeds produce actionable diagnostics without blocking review thread handling or final-gate evaluation.
- **SC-005**: Reports identify at least the top three slowest observed operations and any operation group exceeding the configured retry or error-rate threshold.
- **SC-006**: A generic agent source and at least one host-specific source can both be represented in the same report without losing source attribution.
- **SC-007**: Users can share the structured efficiency report for optimization review without exposing raw secrets, private prompts, or unnecessary local machine details.
- **SC-008**: A runtime-only PR session produces final-gate output, audit summary content, and a structured report that all include the current metrics state.

## Assumptions

- Existing runtime telemetry from `gh-address-cr` remains valuable and continues to be included in reports.
- External agent hosts may vary widely in what they expose; the feature treats imported telemetry as observed evidence with explicit coverage labels, not as guaranteed complete truth.
- A generic event contract is the baseline for broad AI agent support. Host-specific adapters are optional enrichment layers, not required for the feature to work.
- Standard observability or event envelopes may be accepted through adapters, but the feature's user-facing value is defined by normalized workflow efficiency reporting rather than by any single external standard.
- Imported telemetry is PR-scoped. Cross-PR or organization-wide aggregation is out of scope for this specification.
