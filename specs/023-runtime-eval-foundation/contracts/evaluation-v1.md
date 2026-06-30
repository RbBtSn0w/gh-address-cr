# Contract: `evaluation.v1` And `comparison.v1`

## Concern Evaluation

```json
{
  "schema_version": "evaluation.v1",
  "evaluation_id": "eval_...",
  "run_id": "default",
  "session_id": "owner/repo#123",
  "repo": "owner/repo",
  "pr_number": "123",
  "item_id": "github-thread:PRRT_123",
  "classification": "fix",
  "provisional_state": "verified",
  "provisional_deficits": [],
  "durable_state": "unknown",
  "durable_reason": "DURABLE_OBSERVATION_MISSING",
  "first_pass": true,
  "manual_recovery_count": 0,
  "reopen_count": 0,
  "actionable_rejection_count": 0,
  "expected_control_flow_rejection_count": 1,
  "cost": {
    "input_tokens": 1200,
    "output_tokens": 350,
    "total_tokens": 1550,
    "active_wall_time_ms": 42000,
    "summed_resource_time_ms": 47000,
    "invocation_count": 8,
    "github_api_round_trip_count": 3,
    "tool_call_count": 6,
    "retry_count": 0,
    "actionable_rejection_count": 0,
    "expected_control_flow_rejection_count": 1,
    "manual_recovery_count": 0,
    "measurement_overhead_ms": 18.2
  },
  "coverage": {
    "workflow": {"status": "complete", "evidence_count": 8, "sources": ["runtime"], "deficits": []},
    "timing": {"status": "complete", "evidence_count": 6, "sources": ["runtime", "codex"], "deficits": []},
    "token": {"status": "complete", "evidence_count": 2, "sources": ["codex"], "deficits": []},
    "outcome": {"status": "partial", "evidence_count": 1, "sources": ["runtime"], "deficits": ["DURABLE_OBSERVATION_MISSING"]},
    "legacy_coverage_label": "complete"
  },
  "evidence": []
}
```

## Verification Reason Codes

- `PROVISIONAL_VERIFIED`
- `CLASSIFICATION_EVIDENCE_MISSING`
- `REPLY_EVIDENCE_MISSING`
- `RESOLVE_EVIDENCE_MISSING`
- `PUBLISH_EVIDENCE_MISSING`
- `FINAL_GATE_NOT_PASSED`
- `DURABLE_VERIFIED`
- `DURABLE_OBSERVATION_MISSING`
- `DURABLE_OBSERVATION_UNSUPPORTED`
- `DURABLE_REOPENED`
- `DURABLE_EQUIVALENT_RECURRENCE`
- `DURABLE_MANUAL_RECOVERY`
- `DURABLE_FINAL_GATE_REGRESSION`

## Coverage Deficit Codes

- `WORKFLOW_EVIDENCE_MISSING`
- `TIMING_INTERVALS_MISSING`
- `TIMING_SOURCE_UNATTRIBUTED`
- `TOKEN_EVIDENCE_MISSING`
- `TOKEN_SOURCE_UNSUPPORTED`
- `OUTCOME_CORRELATION_MISSING`
- `DURABLE_OBSERVATION_MISSING`
- `COHORT_DIMENSION_MISSING`
- `SAMPLE_SIZE_INSUFFICIENT`
- `ARCHIVE_MANIFEST_MISSING`
- `ARCHIVE_INTEGRITY_FAILED`

## Comparison Result

```json
{
  "schema_version": "comparison.v1",
  "status": "INSUFFICIENT_EVIDENCE",
  "reason_code": "SAMPLE_SIZE_INSUFFICIENT",
  "baseline_runtime_version": "3.1.10",
  "candidate_runtime_version": "3.2.0",
  "matched_cohort_keys": [],
  "sample_size": {"baseline": 4, "candidate": 3},
  "evidence_deficits": ["SAMPLE_SIZE_INSUFFICIENT"],
  "quality": {},
  "economics": {},
  "operational_health": {},
  "guardrail_failures": [],
  "report_fingerprint": "comparison_...",
  "report_artifact": null
}
```

Supported reports populate three independent vectors:

- `quality`: provisional rate, durable rate, reopen/recurrence rate, final-gate regression rate, manual-recovery rate.
- `economics`: tokens per provisionally/durably verified concern, active time, resource time, invocations, API/tool calls, retries, actionable rejection friction.
- `operational_health`: operation latency distributions, timeout/error rates, dimensional coverage, capture/report overhead.

## Comparison Policy

- At least 10 eligible runs per compared cohort are required by `comparison.v1`.
- Required complexity dimensions must be known and compatible.
- Required workflow, timing, token, and outcome dimensions depend on requested metrics and are evaluated independently.
- Cost improvement cannot override a supported quality regression.
- A missing durable observation is unknown, not success.
- An approval or a later review by the original concern author can satisfy the first supported durable observation boundary; unrelated review comments cannot.
- Unknown protocol rejection reason codes count as actionable until explicitly classified.
- No weighted or composite score is allowed.

## Determinism

- Record and report fingerprints exclude generation timestamps and absolute artifact locations.
- Replaying identical source facts produces identical semantic records and fingerprints.
- Duplicate source fingerprints do not increase samples, outcomes, durations, retries, or cost.
