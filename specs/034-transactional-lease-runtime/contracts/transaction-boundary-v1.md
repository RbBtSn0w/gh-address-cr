# Contract: Transactional Persistence Boundary v1

This contract is the executable policy source for transaction outcomes, recovery,
outbox evidence, and compatibility artifacts. Phase A/B tests must parse or mirror
these tables with a drift assertion.

## Transaction outcome table

| Condition inside reserved write transaction | Commit | Revision | Evidence / outbox | Stable outcome |
|---|---:|---:|---|---|
| Policy accepts transition | all canonical rows | N+1 | committed in same transaction | success |
| Expected revision differs | none | N | none | stale revision |
| Lease/item policy rejects | none | N | none | existing deterministic conflict/rejection |
| Writer wait exceeds bound | none | unchanged | none | retryable persistence busy |
| Schema/integrity invalid | none | unchanged | none | non-retryable persistence invalid |
| Unexpected error before commit | none | N | none | internal failure |
| Process terminates before commit | none after recovery | N | none | old revision |
| Process terminates after commit | all visible after recovery | N+1 | all visible | committed revision |

No row permits state without its event or an event without its state.

## Artifact materialization table

| Database revision | Artifact revision/status | Runtime read | Required action |
|---:|---|---|---|
| N | N / current | database | none |
| N | less than N / current | database | mark dirty and rebuild N |
| N | N / failed | database | retry rebuild; surface diagnostic |
| N | missing | database | build N |
| N | greater than N | database | fail integrity check; never import artifact |
| no database | valid legacy files | legacy migration input only | import once |
| no database | malformed/divergent legacy files | none | fail loudly; preserve files |

## Outbox evidence table

| Outbox status | External effect may have happened | Completion evidence | Recovery |
|---|---:|---:|---|
| `planned` | no | no | execute |
| `in_flight` | yes | no | on restart classify `unknown` |
| `unknown` | yes | no | reobserve external system; retry only if idempotent |
| `failed` | no or known failed | no | policy-defined retry/stop |
| `succeeded` with recorded result | yes | yes, subject to existing evidence policy | none |

## Claim acquisition result

Every successful claim API result includes internal provenance:

| Result | Meaning | Rollback ownership |
|---|---|---|
| `created` | This transaction inserted the active lease | This call may release on its modeled pre-handoff failure |
| `reentered` | A qualifying lease already belonged to the caller | This call must not release it as newly created |

Provenance is derived and returned from the transaction; it is not inferred from
artifact diffs or a separately mutable flag.

## Recovery order

1. Open SQLite and allow native journal recovery.
2. Validate schema version, foreign keys, and integrity contract.
3. Complete or verify a once-only legacy migration.
4. Classify stale `in_flight` outbox work as `unknown` in one transaction.
5. Reconcile required external effects under their idempotency contracts.
6. Rebuild dirty/missing compatibility artifacts from the latest committed revision.
7. Project status and next action; never read an artifact back as truth.

## Privacy and telemetry

Allowed bounded attributes:

- persistence operation category;
- outcome/reason category;
- schema version;
- contention duration bucket;
- migration/recovery/materialization outcome;
- outbox effect category and attempt-count bucket.

Forbidden attributes include repository/PR identity, paths, database filename,
item/lease/request/transaction IDs, agent identity, conflict keys, SQL, payloads,
GitHub bodies/titles/URLs, and artifact contents/hashes.
