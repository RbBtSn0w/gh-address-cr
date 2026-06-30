# Data Model: Read-Only Evaluation Plane

## Truth Classes

| Class | Examples | Authority |
|---|---|---|
| Runtime truth | `session.json`, evidence ledger, final-gate result, recorded GitHub side effects | Authoritative for review completion |
| Evaluation input fact | Archived runtime artifacts, `run-manifest.v1`, later GitHub observation rows | Authoritative only as observed evaluation input |
| Evaluation projection | Concern/run records, dimensional coverage, SQLite rows | Derived and rebuildable |
| Evaluation report | Comparison JSON/Markdown, insufficiency diagnostics | Derived and rebuildable |

Evaluation projections and reports MUST never be accepted as runtime events.

## RunManifestV1

Stable correlation envelope written during final-gate artifact generation.

Fields:

- `schema_version`: exactly `run-manifest.v1`.
- `run_id`: archive/final-gate run identifier.
- `session_id`: runtime session identifier.
- `repo`: `owner/repo` scope.
- `pr_number`: string PR number.
- `runtime_version`: installed `gh-address-cr` version.
- `runtime_commit`: optional public-safe source revision when available.
- `skill_version`: optional installed skill contract version.
- `head_sha`: PR head revision observed by final-gate when available.
- `started_at`: earliest supported run evidence timestamp.
- `final_gate_observed_at`: final-gate observation timestamp.
- `final_gate_status`: `PASSED` or `FAILED`.
- `final_gate_counts`: existing machine count map.
- `workflow_variant`: supported high-level route such as `review` or `address`, otherwise `unknown`.
- `telemetry_sources`: public-safe attributed source labels.
- `complexity`: `ComplexityProfile`.
- `artifacts`: relative final-target filenames and optional SHA-256 digests computed after path rewrites.
- `diagnostics`: public-safe capture limitations.

Validation:

- Identity fields are required and normalized.
- Artifact references are relative paths inside the run directory; absolute paths are forbidden.
- The manifest does not list or hash itself.
- A manifest cannot claim `PASSED` when archived final-gate evidence reports failure.
- Missing optional complexity or version fields reduce coverage; they are not synthesized.

## ComplexityProfile

Fields:

- `review_item_count`: non-negative integer.
- `changed_file_count`: optional non-negative integer.
- `diff_line_count`: optional non-negative integer using additions plus deletions.
- `classification_mix`: counts keyed by `fix`, `clarify`, `defer`, and `reject`.
- `language_toolchain`: optional normalized public label list.
- `required_check_duration_ms`: optional non-negative integer.
- `bucket_key`: derived cohort key.

Initial buckets:

- Review items: `1`, `2-5`, `6+`.
- Changed files: `1-3`, `4-10`, `11+`, or `unknown`.
- Diff lines: `1-100`, `101-500`, `501+`, or `unknown`.
- Classification mix: `fix-only`, `non-fix-only`, `mixed`, or `unknown`.

Unknown required dimensions prevent cross-version improvement claims for that run.

## EvaluationObservationV1

Append-only evaluation input fact captured by a read-only GitHub query.

Fields:

- `schema_version`: exactly `evaluation-observation.v1`.
- `observation_id`: deterministic fingerprint.
- `repo`, `pr_number`: scope.
- `run_id`: provisional run being observed.
- `observed_at`: UTC observation time.
- `observed_head_sha`: PR head at observation time.
- `review_round_id`: stable GitHub review identifier.
- `review_state`: submitted review state.
- `reviewer_relation`: `original_concern_author`, `other_reviewer`, or `unknown`; raw reviewer identity is not persisted.
- `item_id`: original item when direct correlation exists.
- `observed_thread_id`: observed thread identity.
- `related_item_id`: explicit recurrence correlation when available.
- `finding_fingerprint`: normalized producer fingerprint when available.
- `outcome_kind`: `no_reopen`, `reopened`, `equivalent_recurrence`, `manual_recovery`, or `final_gate_regression`.
- `correlation_method`: `thread_id`, `related_item_id`, or `finding_fingerprint`.
- `source`: `github`.
- `source_url`: optional public GitHub URL.

Validation:

- Observation must be later than the provisional final-gate timestamp.
- Observation must reference the same PR and the same or a later head revision.
- Durable verification requires a supported correlation method plus either an `APPROVED` later review or `reviewer_relation=original_concern_author`.
- Unmatched comments are retained diagnostically but cannot change a concern's durable state.
- Duplicate `observation_id` rows do not increase counts.

## EvidencePointer

Fields:

- `artifact`: relative run artifact name.
- `record_id`: stable source record ID when available.
- `event_type`: source event type.
- `observed_at`: source timestamp.
- `source`: runtime, GitHub, host profile, or generic telemetry label.
- `fingerprint`: deterministic source/evaluation fingerprint.

Pointers provide traceability without copying raw prompts or review bodies into the catalog.

## ConcernEvaluationV1

Fields:

- `schema_version`: exactly `evaluation.v1`.
- `evaluation_id`: deterministic fingerprint of run, item, and source evidence.
- `run_id`, `session_id`, `repo`, `pr_number`, `item_id`.
- `classification`: `fix`, `clarify`, `defer`, or `reject`.
- `provisional_state`: `verified` or `not_verified`.
- `provisional_deficits`: missing classification/reply/resolve/publish/final-gate evidence.
- `durable_state`: `verified`, `negative`, or `unknown`.
- `durable_reason`: stable reason code.
- `first_pass`: boolean derived from absence of reopen/retry/manual recovery before provisional completion.
- `manual_recovery_count`, `reopen_count`, `actionable_rejection_count`, `expected_control_flow_rejection_count`.
- `cost`: `WorkflowCost`.
- `coverage`: `CoverageDimensionSet`.
- `evidence`: list of `EvidencePointer`.

Derived state rules:

1. `provisional_state=verified` only when classification, required reply, required resolve/publish, and passing final-gate evidence all correlate to the concern/run.
2. Missing any required current-cycle evidence yields `not_verified` with deficits.
3. A later correlated reopen, equivalent recurrence, manual recovery, or final-gate regression yields `durable_state=negative`.
4. A supported later reviewer round with no negative observation yields `durable_state=verified`.
5. No supported later observation yields `durable_state=unknown`.

## WorkflowCost

Fields:

- `input_tokens`, `output_tokens`, `total_tokens`: optional attributed counts.
- `active_wall_time_ms`: interval union of supported timestamped spans.
- `summed_resource_time_ms`: sum of supported deduplicated durations.
- `invocation_count`, `github_api_round_trip_count`, `tool_call_count`, `retry_count`.
- `actionable_rejection_count`, `expected_control_flow_rejection_count`.
- `manual_recovery_count`.
- `measurement_overhead_ms`: projection/report construction cost excluding final persistence.

Validation:

- Counts and durations are non-negative.
- `active_wall_time_ms <= summed_resource_time_ms` when both are available for the same span set.
- Duration-only events do not contribute to active wall time.
- Runtime metric normalization preserves measured start/end timestamps; missing intervals are never synthesized from evaluation time.
- Duplicate/correlated overlaps are removed before aggregation.

## CoverageDimension

Fields:

- `status`: `complete`, `partial`, `unavailable`, or `invalid`.
- `evidence_count`: non-negative integer.
- `sources`: sorted source labels.
- `deficits`: stable reason codes.

## CoverageDimensionSet

Fields:

- `workflow`: evidence for classifications, protocol decisions, retries, and tool/API counts.
- `timing`: measured interval/duration evidence and active-time eligibility.
- `token`: attributable host token deltas.
- `outcome`: provisional and later durable observations.
- `legacy_coverage_label`: optional compatibility field from the current efficiency report.

No aggregate field may override a dimension's deficits.

## RunEvaluationV1

Fields:

- Run identity and runtime version from `RunManifestV1`.
- `concerns`: concern evaluation IDs.
- `verified_concern_count`, `durably_verified_concern_count`, `durable_negative_count`, `durable_unknown_count`.
- `first_pass_resolution_rate`, `reopen_rate`, `manual_recovery_rate`, `actionable_protocol_rejection_rate`.
- Aggregated `WorkflowCost`.
- `CoverageDimensionSet`.
- `complexity`: `ComplexityProfile`.
- `projection_fingerprint`: deterministic replay fingerprint.
- `diagnostics`: public-safe input limitations.

## EvaluationCatalog

Derived SQLite tables:

- `catalog_meta(schema_version, rebuilt_at, source_fingerprint)`.
- `runs(run_id, repo, pr_number, runtime_version, final_gate_status, cohort_key, projection_fingerprint, ...)`.
- `concerns(evaluation_id, run_id, item_id, provisional_state, durable_state, classification, ...)`.
- `coverage(owner_type, owner_id, dimension, status, deficits_json, ...)`.
- `costs(owner_type, owner_id, metric_name, metric_value, source_count)`.
- `observations(observation_id, run_id, item_id, outcome_kind, correlation_method, observed_at, ...)`.
- `evidence_pointers(owner_id, artifact, record_id, event_type, fingerprint)`.

Uniqueness constraints on run, evaluation, observation, and evidence fingerprints make replay idempotent.

## ComparisonRequestV1

Fields:

- `baseline_runtime_version`, `candidate_runtime_version`.
- Optional repo and cohort filters.
- Required coverage dimensions.
- `minimum_runs_per_cohort`, fixed to at least 10 in `comparison.v1`.
- Requested quality and cost metrics.

## ComparisonResultV1

Fields:

- `status`: `SUPPORTED`, `INSUFFICIENT_EVIDENCE`, or `REGRESSED`.
- `reason_code` and `evidence_deficits`.
- Baseline/candidate runtime versions and matched cohort keys.
- Per-side sample counts and coverage summaries.
- Independent `quality`, `economics`, and `operational_health` result vectors.
- Distribution fields: median and p90 where supported.
- Quality-rate confidence bounds.
- `guardrail_failures`.
- `report_fingerprint` and optional report artifact.

Policy:

- Any required missing dimension, fewer than 10 eligible runs per cohort, or unmatched required complexity dimension yields `INSUFFICIENT_EVIDENCE`.
- Any supported quality regression yields `REGRESSED` even when cost improves.
- `SUPPORTED` describes evidence support; each metric states improved, unchanged, or worse independently.
- No composite score is generated.
