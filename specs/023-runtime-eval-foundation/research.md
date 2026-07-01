# Research: Read-Only Evaluation Plane

## 1. Evaluation Ownership And Module Boundary

- **Decision**: Create a focused `core/evaluation/` package and keep `commands/evaluation.py` as a thin public adapter. Final-gate calls only the archive-manifest boundary.
- **Rationale**: Existing `telemetry.py`, `telemetry_reporting.py`, and `cr_metrics.py` already have distinct contracts. Extending them with verification, catalog, and cohort policy would recreate a god module and mix operational health with product outcomes.
- **Alternatives considered**: Extend `core/telemetry.py` (rejected because evaluation is not telemetry truth); replace `cr_metrics.py` in place (rejected because its current artifact is a narrow latest-session summary and remains a compatibility surface).

## 2. Catalog Storage

- **Decision**: Use Python's standard-library SQLite as a rebuildable local catalog. Build into a temporary database, validate it, then atomically replace the prior catalog.
- **Rationale**: Comparisons need indexed queries across runs, runtime versions, concerns, coverage, and cohort dimensions. SQLite adds no service or package dependency and supports transactional rebuilds.
- **Alternatives considered**: JSONL-only (simple but requires repeated full scans and weak multi-entity constraints); DuckDB (strong analytics but adds a new dependency and packaging burden); make SQLite authoritative (rejected because the catalog must remain disposable).

## 3. Source Evidence And Run Manifest

- **Decision**: Preserve existing archived runtime artifacts and add a small versioned `run-manifest.v1.json` containing stable run, runtime, PR, source, final-gate, and complexity metadata.
- **Rationale**: Existing archives contain the necessary evidence but lack one stable correlation envelope. A manifest avoids inferring runtime version and cohort identity from filenames or narrative summaries.
- **Alternatives considered**: Rewrite archives into a new canonical event log (rejected as a risky migration); infer all metadata during every rebuild (rejected because some values are unavailable after the run); treat `efficiency-report.json` as the manifest (rejected because it is telemetry-specific and not completion truth).

The manifest is persisted only after its target artifacts are stable. Auto-clean currently rewrites archived paths after copying the workspace, so computing digests before that rewrite would create an immediately invalid manifest. Auto-clean therefore finalizes the manifest in the archive after rewrites; `--no-auto-clean` finalizes it in the stable workspace.

## 4. Hybrid Verification Semantics

- **Decision**: Derive `provisionally_verified` from current-cycle runtime evidence and `durably_verified` only from a later supported GitHub reviewer observation. The initial supported observation is either an approval on the same or a later head revision, or a submitted later review from the original concern author with no correlated reopen/recurrence. Merge, PR closure, elapsed time, or an unrelated review comment alone does not establish durability.
- **Rationale**: Current-cycle evidence proves the agent completed the required protocol. A later reviewer round is the first supported signal that the concern stayed resolved.
- **Alternatives considered**: Current-cycle evidence only (overstates quality); wait for durable evidence before reporting any success (makes evaluation unusable for recent runs); use merge as durable proof (merge can occur without a reviewer re-validating the concern); treat every later submitted review as validation (an unrelated comment does not prove the original concern was re-observed).

## 5. Recurrence Correlation

- **Decision**: Support deterministic correlation by original thread/item identity, explicit `related_item_id`, or an existing normalized finding fingerprint. Leave unmatched new comments unlinked and durable outcome unknown.
- **Rationale**: Semantic similarity over raw review text would be non-deterministic, privacy-sensitive, and difficult to contract-test.
- **Alternatives considered**: AI semantic matching (rejected for determinism, privacy, and cost); path-and-line-only matching (rejected because unrelated concerns often share locations); treat every later comment as recurrence (rejected due to false negatives).

## 6. Dimensional Coverage

- **Decision**: Compute workflow, timing, token, and outcome coverage independently, each with status, evidence count, source attribution, and deficits. Keep the existing aggregate telemetry coverage label as a compatibility field only.
- **Rationale**: Runtime-only telemetry can be sufficient for command health while being insufficient for token or durable-outcome claims.
- **Alternatives considered**: Reuse `complete|partial|runtime-only|unavailable` as evaluation confidence (rejected because it overloads unrelated dimensions); one weighted confidence score (rejected because it hides evidence gaps).

## 7. Active Wall Time

- **Decision**: Compute active wall time as the union of valid measured intervals. Report summed resource time separately. Duration-only events without intervals contribute to resource time but not active wall time.
- **Rationale**: Summing nested or concurrent spans overstates elapsed handling time. Interval union is deterministic and handles overlap directly.
- **Alternatives considered**: Sum all durations (incorrect under concurrency); use first-to-last event span (includes unrelated idle time); require agents to annotate timing (unreliable and token-expensive).

Current runtime metrics already persist epoch start/end values, but `_runtime_events` drops those values when producing canonical telemetry events, and the default `GitHubClient` runner is not measured through `core.command_runner`. The implementation must preserve normalized UTC start/end timestamps and add measured spans at the centralized GitHub runner boundary. The evaluator must not reconstruct missing intervals from report generation time.

## 8. Cohort Matching And Minimum Evidence

- **Decision**: Match initial cohorts using buckets for review-item count, changed-file count, diff size, and classification mix; include language/toolchain and required-check duration when material and available. Require at least 10 eligible runs per compared cohort.
- **Rationale**: Exact-value matching fragments a small corpus, while unqualified global averages confound PR complexity. Ten runs is an explicit initial floor that prevents single-run claims without pretending to establish universal statistical significance.
- **Alternatives considered**: No minimum (too easy to overclaim); 30+ per cohort (credible but blocks initial dogfood learning); learned propensity matching (too complex and opaque for the initial local evaluator).

## 9. Distribution And Uncertainty Reporting

- **Decision**: Report sample count, median, and p90 when sample size supports the percentile, plus deterministic confidence bounds for quality rates. Never return one composite score.
- **Rationale**: Medians resist outliers; upper-tail values expose expensive runs; explicit bounds reveal uncertainty. Quality guardrails remain independent of cost improvements.
- **Alternatives considered**: Mean only (outlier-sensitive); p95 on very small cohorts (false precision); opaque weighted score (hides regressions).

## 10. Protocol Rejection Taxonomy

- **Decision**: Classify known wait/coordination/control-flow outcomes separately from actionable request, response, lease, validation, publish, GitHub, or storage failures. Unknown rejection codes remain actionable until classified.
- **Rationale**: Raw `response_rejected` counts currently mix expected control flow with product friction. Defaulting unknown codes to actionable avoids optimistic undercounting.
- **Alternatives considered**: Count every rejection as failure (overstates friction); ignore every rejection (hides real protocol cost); infer from exit code alone (insufficient context).

## 11. Failure And Privacy Boundaries

- **Decision**: Reuse runtime telemetry safety primitives for evaluation input. Explicit evaluation commands fail non-zero on unsafe, malformed, ambiguous, or unsupported evidence. Final-gate remains fail-open and records diagnostics when optional manifest/evaluation preparation fails.
- **Rationale**: Evaluation must not make review completion impossible, but direct evaluation requests must not silently produce incomplete or unsafe conclusions.
- **Alternatives considered**: Fail final-gate on evaluation capture (violates telemetry boundary); sanitize only at report time (unsafe raw archives/catalog); silently skip invalid rows (creates false confidence).

## 12. Public Command Surface

- **Decision**: Add an advanced top-level `evaluation` command family: `observe`, `rebuild`, `show`, and `compare`. JSON is the default; Markdown is optional presentation.
- **Rationale**: Evaluation is a separate plane, not a review orchestration step or telemetry synonym. A dedicated namespace keeps `review` as the default product path and allows versioned reason codes.
- **Alternatives considered**: Add commands under `telemetry` (blurs operational and outcome truth); auto-run all comparisons in final-gate (adds latency and self-reference); expose only Python APIs (not a stable public interface).

## 13. Performance And Self-Reference

- **Decision**: Keep added final-gate capture within the existing 250 ms normal-path telemetry budget. Measure validation/projection/report construction and exclude the final artifact persistence write from its own timing field.
- **Rationale**: The repository already uses a 250 ms telemetry-overhead boundary and explicitly avoids self-rewriting artifacts to measure their own write.
- **Alternatives considered**: Introduce a second unrelated budget (harder to interpret); include the report's final write in its own stored timing (requires recursive rewrite); leave overhead unmeasured (cannot detect evaluation regressions).
