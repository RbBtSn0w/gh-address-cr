# Validation: O(changed) Runtime Transaction Hot Path

**Date**: 2026-09-28
**Baseline**: `develop` at `8269e40`

## Current Baseline

Command:

```text
.venv/bin/python scripts/benchmark_runtime_store.py --profile M --load-samples 3 --json
```

Environment: CPython 3.14.7.

| Profile | CRs | Evidence | p50 | p90 | Degradation | Load p50 before -> after |
|---|---:|---:|---:|---:|---:|---:|
| M | 300 | 3,000 | 48.101 ms | 68.111 ms | **2.801** | 1.712 -> 4.812 ms |

The degradation budget (`<= 1.5`) is reproduced as failing.

## First Prototype Checkpoint (reverted)

The initial tracked-mutation prototype was measured after the focused
contracts passed:

| Profile | p50 | p90 | Degradation | Load p50 before -> after |
|---|---:|---:|---:|---:|
| M | 36.406 ms | 49.643 ms | **2.386** | 2.091 -> 5.770 ms |

Compared with the baseline, p50 improved by about 24% and p90 by about 27%.
SC-001 is still red by a wide margin, so this result is not accepted as the
Spec 036 closeout.

These production changes and prototype-only tests were reverted after the
architecture review. The measurements remain research evidence; they do not
describe the current worktree implementation.

The implementation already removes repeated snapshot loading from the measured
save/action-request paths, normalizes and encodes only dirty entities, and
assembles a byte-identical compact projection from canonical fragments. The
remaining growth is therefore attributed to work still proportional to the
whole session: eager row decoding during the first load and full-file atomic
projection output. The next measurement must isolate those costs before more
production changes are accepted.

### Projection-write isolation

Profile M was rerun in a temporary benchmark process with
`RuntimeStore._write_session_projection` patched to a no-op. No repository or
runtime contract was changed by this experiment.

| Variant | p50 | p90 | Degradation |
|---|---:|---:|---:|
| Current checkpoint | 36.406 ms | 49.643 ms | 2.386 |
| Projection write skipped | 33.230 ms | 44.778 ms | 2.295 |

Skipping the complete atomic projection write saves about 3 ms at p50, but the
degradation ratio remains far above `1.5`. Artifact write cadence is therefore
not the primary next lever. Canonical eager entity decoding remains the next
research target.

## Second Prototype Checkpoint (reverted)

The experimental sequence removed the remaining full-session submit `replace`, avoided
enumerating tracked items through `get_session_items`, made item rows lazy, and
added an ASCII fast path for canonical fragments. Relevant contract suites,
ruff, and the zero-error mypy ratchet passed after these changes.

| Stage | p50 | p90 | Degradation |
|---|---:|---:|---:|
| Tracked submit | 34.300 ms | 48.355 ms | 2.245 |
| Tracked item helper | 29.424 ms | 41.995 ms | 2.389 |
| Lazy items | 28.606 ms | 39.315 ms | 2.320 |
| ASCII fragment fast path | 26.304 ms | 35.897 ms | **2.436** |

Absolute p50 is now about 45% below the original `48.101 ms` baseline and p90
about 47% below `68.111 ms`, but SC-001 remains red. Reducing fixed cost alone
can make the ratio numerically worse, so closeout continues to depend on the
last/first-decile slope rather than headline latency.

A full 300-CR cProfile after lazy items showed the remaining size-dependent
work concentrated in `_load_snapshot`, JSON decoding, lease datetime coercion,
and claim-projection inspection. The benchmark retains one terminal lease per
completed CR. The next contract must isolate terminal leases without changing
their public history or recovery semantics.

Later lazy-lease and active-index experiments observed a best degradation ratio
of `2.136`, still outside SC-001, while expanding the runtime store by more than
1,000 lines. The entire production prototype was reverted. Current runtime
behavior remains the `develop` baseline; only this research record and revised
planning artifacts remain.

## Historical Bounded Working-Set Checkpoint

The replacement prototype uses an explicit `runtime-working-set.v1` request,
loads only selected item and lease rows, writes only those rows, and assembles
the compatibility projection from canonical row fragments. Focused runtime,
agent-protocol, transaction, and outbox contracts pass (85 tests).

Command:

```text
.venv/bin/python scripts/benchmark_runtime_store.py --profile S --profile M --profile L --json
```

| Profile | CRs | p50 | p90 | Degradation | Classify | Next | Submit |
|---|---:|---:|---:|---:|---:|---:|---:|
| S | 50 | 11.548 ms | 12.664 ms | **1.376** | 1.241 | 1.305 | 1.354 |
| M | 300 | 20.723 ms | 27.853 ms | **2.057** | 2.021 | 2.029 | 2.128 |
| L | 1,000 | 48.586 ms | 73.851 ms | **3.452** | 3.586 | 3.398 | 3.450 |

The monotonic S/M/L slope contradicts SC-001 at both required profiles. It is
not accepted as a closeout even though absolute M latency is materially below
the original baseline.

### Materialization isolation at this checkpoint

Profile M was also run with only the post-commit compatibility materialization
temporarily disabled; the patch was restored immediately afterward.

| Variant | p50 | p90 | Degradation | Classify | Next | Submit |
|---|---:|---:|---:|---:|---:|---:|
| Materialization enabled | 21.047 ms | 27.720 ms | 2.159 | 2.098 | 2.137 | 2.227 |
| Materialization disabled | 25.057 ms | 34.046 ms | 2.398 | 1.805 | 2.408 | 2.485 |

The absolute numbers are noisy across independent runs, but the per-step
result is decisive: classification still grows after materialization is
removed, while next/submit retain their full-session preflight. Both the
preflight read boundary and artifact cadence must be resolved; changing only
one cannot prove SC-001.

Implementation was paused at this historical checkpoint because the planning
text contained mutually exclusive artifact-cadence requirements. Per-stage
attribution below resolved the decision, and ADR-001 now versions the accepted
contract.

## Corrected attribution checkpoint

The earlier pause was lifted after distinguishing transaction commit cost from
complete command cost. The benchmark now reports load, transaction,
materialization, and remaining command work independently. Explicit claim and
normal submit then moved to bounded preflight reads while malformed/rebound
compatibility paths retain their full fallback.

| Profile | p50 | p90 | Degradation | Load degradation |
|---|---:|---:|---:|---:|
| M | 16.387 ms | 21.630 ms | **2.044** | 0 for all stages |

The remaining stage degradation is:

| Stage | Transaction | Materialization | Other |
|---|---:|---:|---:|
| classify | 2.069 | 2.331 | 1.011 |
| next | 2.502 | 2.432 | 1.138 |
| submit | 2.595 | 2.515 | 1.164 |

Inspection found that bounded commits still append `lease_events` through
`json_insert` into the growing `sessions.payload_json`. This is a whole-history
rewrite inside SQLite and explains why a selected-row transaction still scales
with completed CR count. The next accepted experiment is runtime schema v3,
which normalizes that ordered event log while preserving immediate compatibility
materialization. Artifact cadence is not changed at this checkpoint.

## Final closeout

Runtime schema v3 normalizes ordered lease events, explicit claim and normal
submit use bounded preflight reads, and ADR-001 keeps incremental evidence
current while moving full `session.json` output to explicit compatibility
boundaries.

Final plain benchmark evidence on CPython 3.14.7:

| Profile | CRs | p50 | p90 | Degradation | Budget |
|---|---:|---:|---:|---:|---:|
| M | 300 | 8.323 ms | 9.291 ms | **0.991** | <= 1.5 |
| L | 1,000 | 8.283 ms | 8.892 ms | **1.011** | <= 1.5 |

The L attribution run reports transaction degradation `1.001` to `1.050`,
incremental evidence materialization `1.000` to `1.006`, and no full-session
load on any measured stage. Full compatibility loads remain intentionally
proportional to history and materialize the current revision before returning.

Three alternating profile-M runs produced:

| Run | Plain p50 / p90 | Traced p50 / p90 | Spans |
|---|---:|---:|---:|
| 1 | 8.325 / 9.077 ms | 8.652 / 9.291 ms | 2,733 |
| 2 | 8.358 / 9.086 ms | 8.577 / 9.270 ms | 2,733 |
| 3 | 8.237 / 8.877 ms | 8.848 / 9.385 ms | 2,733 |

Median tracing overhead is **3.93% at p50** and **2.36% at p90**, within the
5% budget. The third pair's p50 overhead was 7.42%, so the raw alternating
runs are retained here rather than treating a single noisy sample as the gate.

Correctness and repository gates:

- editable install succeeded;
- ruff passed;
- mypy ratchet passed with zero errors;
- `python -m unittest discover -s tests` passed 1,277 tests using an isolated
  writable state directory (one pre-existing lock `ResourceWarning` remains);
- CLI help and agent manifest smoke tests passed;
- plugin payload build and `--check` passed;
- randomized bounded add/update/delete sequences produced byte-identical
  row-fragment and full projections after every commit;
- v2-to-v3 migration preserved ordered lease history and executed exactly once.

Draft commit message: `perf: bound runtime transaction hot path`.
