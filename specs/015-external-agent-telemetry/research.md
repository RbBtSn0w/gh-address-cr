# Research: External Agent Telemetry Ingestion

## 1. Repair Existing Runtime Metrics Summary Gap

- **Decision**: Treat `repair-telemetry-metrics` as the first implementation slice. Runtime-only metrics must appear in final-gate stdout, `audit_summary.md`, and a structured efficiency report artifact even when no external telemetry has been imported.
- **Rationale**: The previous 011 implementation appends efficiency data to published review-thread replies, but users also need completion evidence and audit artifacts to summarize the current metrics state. External ingestion should extend a complete runtime reporting path, not compensate for a partial one.
- **Alternatives considered**: Only add external ingestion and leave final-gate/audit output unchanged. Rejected because it preserves the original user-visible gap and makes coverage labels less trustworthy.

## 2. Canonical External Event Contract

- **Decision**: Define a runtime-owned canonical event model with source, source session id, event id, event kind, operation name, timing, status, optional duration, and sanitized metadata.
- **Rationale**: There is no universal AI-agent telemetry protocol that all hosts already emit. A small canonical model lets generic agents provide useful telemetry while host-specific adapters can enrich the same report surface.
- **Alternatives considered**: Make one host-specific log format the public contract. Rejected because it would make the feature vendor-specific and conflict with replaceability goals.

## 3. Standard Envelope Compatibility

- **Decision**: Accept standard observability or event envelopes through adapters that normalize into the canonical model; do not make any external standard the only accepted format.
- **Rationale**: General observability/event standards can carry telemetry data, but they do not define this product's workflow-efficiency semantics. The runtime should preserve source attribution while reporting product-specific efficiency signals.
- **Alternatives considered**: Require a single standard event envelope for every agent. Rejected because it raises adoption cost for simple agents and does not solve product-specific coverage reporting.

## 4. Coverage Labels

- **Decision**: Every report uses one of four coverage labels: `complete`, `partial`, `runtime-only`, or `unavailable`.
- **Rationale**: Users must not mistake missing host telemetry for a complete workflow measurement. Labels make the report honest even when only runtime telemetry exists.
- **Alternatives considered**: Omit coverage when data is missing. Rejected because silent omission caused the original confusion around 011 metrics.

## 5. Safety And Privacy

- **Decision**: External telemetry imports must reject or sanitize unsafe fields before storage and reporting. Public summaries must avoid tokens, raw prompts, usernames, private machine identifiers, and unnecessary absolute local paths.
- **Rationale**: Agent-host telemetry can contain shell commands, prompt fragments, local paths, environment variables, and user identifiers. These are unsafe to place in PR comments, audit summaries, or shareable reports without filtering.
- **Alternatives considered**: Store raw telemetry and sanitize only in summaries. Rejected because unsafe raw artifacts can still leak through feedback packets, archives, or future tooling.

## 6. Duplicate And Overlap Handling

- **Decision**: Compute deterministic event identities from stable source fields and reject or ignore duplicate events during import. Preserve source attribution and avoid double-counting correlated runtime and external events when a correlation id is available.
- **Rationale**: Agents may retry ingestion or import the same session log more than once. Counts, durations, and retry rates must remain stable across repeated imports.
- **Alternatives considered**: Allow duplicate imports and rely on users to notice inflated metrics. Rejected because it undermines the report's credibility.

## 7. Failure Semantics

- **Decision**: Telemetry command failures fail loudly for the telemetry action, but they do not block review handling, publish, or final-gate unless the user explicitly requires external telemetry coverage.
- **Rationale**: The core product is PR review resolution. Metrics are important evidence, but telemetry availability should not make review closure impossible by default.
- **Alternatives considered**: Make host telemetry mandatory for final-gate. Rejected because many agents cannot export host telemetry yet.
