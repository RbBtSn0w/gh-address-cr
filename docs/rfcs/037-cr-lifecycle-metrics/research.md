> Archived design reference. Current code, tests, and `AGENTS.md` govern
> execution; historical delivery status and commands are not active instructions.

# Research: CR Lifecycle Decision Metrics

## Current baseline

Inspection of `develop@907be6bc` establishes:

- `src/gh_address_cr/core/cr_metrics.py` reads the incrementally maintained
  evidence projection, selects the latest session, groups by `item_id`, and
  treats `thread_resolved` as its only terminal event;
- it reports one coarse span plus classification mix, incomplete items,
  wall-clock time, active time, and compactness;
- `response_accepted`, `response_rejected`, `verification_rejected`,
  `reply_posted`, `reply_reconciled`, `thread_resolved`,
  `response_published`, and `publish_blocked` are already produced;
- there is no uniform `finding_observed` event, so historical origin time is
  only an estimate from the earliest item-scoped record;
- `final-gate` owns efficiency-report generation, completion guidance, archive
  copying, and archived artifact-path rewriting, but it does not currently make
  `cr-metrics.json` a first-class result;
- Spec 036 keeps `evidence.jsonl` incrementally current while deferring full
  `session.json` materialization to explicit compatibility boundaries.

## Rejected directions

### Treat first evidence as exact finding creation

Rejected because classification or request issuance may be the first recorded
event. Reporting that timestamp as exact finding creation would create a false
precision bias in lead-time comparisons.

### Infer verification from final session state alone

Rejected because a mutable snapshot does not establish when or through which
workflow the item became verified. Terminal time must come from explicit
evidence and a deterministic item-kind policy.

### Make lifecycle performance a final-gate predicate

Rejected because correctness and efficiency answer different questions.
Sample size, item mix, model choice, reviewer behavior, and working hours make
early thresholds unsuitable as truth conditions.

### Rebuild an evaluation subsystem

Rejected because one per-session derived artifact answers the immediate
maintainer question without a new database, catalog, cohort engine, or daemon.

## Resolved validation questions

1. Native-finding intake and GitHub-thread discovery emit `finding_observed`
   when an item identifier first enters the session. Repeated discovery does
   not emit another observation.
2. Local-finding verification is the first verifier-role `response_accepted`
   after the last `verification_rejected`. A fixer acceptance is an address
   attempt, not verification; no new terminal event is required for v1.
3. Existing coarse `cr_metrics` fields are preserved. Lifecycle fields are
   additive inside the artifact and bounded completion summary; the strict
   top-level final-gate machine contract is unchanged.
4. Stack final-gate reports the selected PR lifecycle and archives that report.
   A cross-member aggregate remains out of scope until separately specified.
