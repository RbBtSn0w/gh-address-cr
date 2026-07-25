# Feature Specification: OTel Gateway Hardening

## Objective

Publish `otel-tracing.v2` without changing CLI, workflow-state, final-gate, or
Status-to-Action behavior. The release removes subprocess argv from exported
telemetry, standardizes resource/error/exporter behavior, and defines the
operator-controlled gateway profile and Honeycomb acceptance boundary.

## Requirements

- Preserve one `gh-address-cr.cli` root span per invocation and the existing
  child-span/event promotion rule.
- Never export subprocess argv, request/response bodies, standard streams,
  thread identities, paths, or hashes derived from subprocess values. Preserve
  the existing root-span VCS contract: repository names remain one-way hashed
  and plain repository identities remain prohibited.
- Keep root CLI argv position-preserving while exporting only the executable
  basename, bounded command name, and fixed redaction placeholders.
- Emit stable Resource identity: service name, namespace, and version. Omit
  `deployment.environment.name` because this is distributable software, not a
  hosted deployment.
- Classify final subprocess failures with bounded error type, category, and
  expectedness; retries that finish successfully carry no error residue.
- Use traces only, bounded batching/timeout/shutdown, gzip, always-on sampling,
  standard endpoint precedence, and fail-open export.
- Send the backend-neutral `anonymous-client-v1` admission profile only to the
  exact approved HTTPS gateway origin on effective port 443.

## Success Criteria

- Automated privacy fixtures find no forbidden subprocess content anywhere in
  exported span/event attributes.
- In-memory traces prove resource identity, parentage, span kinds, success,
  failure, retry, and exception ownership.
- Offline or rejected export does not change the CLI exit result.
- The checked-in profile contract is complete without credentials and records
  its production switch and rollback gates.

## Non-Goals

- OTel Logs API, metrics, availability SLOs, tail sampling, workflow telemetry
  JSONL changes, or telemetry-owned runtime decisions.
