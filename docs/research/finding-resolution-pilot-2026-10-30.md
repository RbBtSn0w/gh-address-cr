# Finding-resolution guidance pilot — 2026-10-30

## Result and decision

Both skill versions passed all three grading criteria in the matched five-task
pilot. The observed evidence-format difference is one baseline validation
command wrapped by `pyenv` that the fixed grader does not recognize, versus a
candidate command using its supported Python syntax. This is not evidence that
the baseline skipped validation or produced a worse fix.

| Primary metric | Baseline | PR #374 candidate |
| --- | --- | --- |
| Legal state | 5/5 | 5/5 |
| Effective fix | 5/5 | 5/5 |
| Consistent evidence | 5/5 | 5/5 |
| Grader-recognized replayable validation, fix items | 4/5 | 5/5 |
| Fix-attempt success, fix-expecting runs | 3/4 | 4/4 |

The last two metrics reflect the grader's supported replay grammar, not a
separate finding about functional correctness. Keep the small guidance change
for clearer, portable command records; do not claim stable or causal quality
improvement. The owner stopped additional repetitions to balance ROI. No more
model evaluations or capacity retries are planned for this work.

## Selection and per-sample evidence

The primary pilot uses repeat 1 of each of the same five samples in both arms,
selected by sample and execution order rather than pass/fail outcome. Stopping
and reducing the original plan were post-hoc decisions. There is one
false-positive sample with no expected fix; the two-finding sample contributes
two fix items, so fix-item and fix-expecting-run denominators differ.

| Sample | Baseline pass | Candidate pass | Baseline recognized validation | Candidate recognized validation |
| --- | --- | --- | --- | --- |
| malformed-report-fields | 1/1 | 1/1 | 2/2 | 2/2 |
| nonfinite-shutdown-wait | 1/1 | 1/1 | 1/1 | 1/1 |
| preflight-timeout-claim | 1/1 | 1/1 | n/a | n/a |
| stale-unused-parameter | 1/1 | 1/1 | 0/1 | 1/1 |
| windows-gh-matcher | 1/1 | 1/1 | 1/1 | 1/1 |

For `stale-unused-parameter`, the baseline recorded an absolute executable path
to a `pyenv exec python3 -B -m unittest discover -v` wrapper. It actually ran
validation. The grader's `runnable_validation` parser does not unwrap that
form. The candidate recorded `python3 -m unittest discover -s tests -v`, which
the same parser recognizes. Private absolute paths are deliberately omitted
from this public report. The frozen grader was not changed after measurement.

## Retained attempts

| Group | Primary complete | Supplement complete | Valid complete | User-cancelled partial |
| --- | --- | --- | --- | --- |
| Baseline | 5 | 4 | 9 | 1 |
| Candidate | 5 | 3 | 8 | 1 |

All 17 completed valid runs passed their independent grades. Supplementary
baseline results are 4/4 passed, 4/4 recognized fix-item validations and 3/3
fix-attempt success; candidate results are 3/3, 3/3 and 2/2 respectively. These
unequal supplementary groups are descriptive only.

The final dataset started 20 attempts: 17 valid completions, two user-cancelled
partials and one provider-capacity refusal before any tool execution. The
capacity retry was cancelled by the ROI stop. Earlier setup attempts comprise
two local host-start failures and one environment-invalid model run; all are
retained separately. No completed task-quality failure was retried or removed.
The planned 25+25 valid comparison was not completed.

Both primary arms report five `RUNTIME_COMPATIBLE` observations. These are
successful compatibility checks, not workflow failures; the current summary's
deviation list includes them because its expected-code set does not name them.

## Reproducibility and boundaries

- Runtime: `0d4a794a8fbc269fbbf4af845e82bd4dce51aeec`; #365 persistence changes excluded.
- Baseline skill: `0ad7eefe8b6f5c3b088791170d02ba0a8a394727`, content digest `d16d0c6d3ae5`.
- Candidate skill: `0d4a794a8fbc269fbbf4af845e82bd4dce51aeec`, content digest `77d540d0eb1f`.
- Neutral harness SHA-256: `8d0d91698b7e675f61a805afa3e536f2f1304e1e65eb27b4b2e942e81e34f4c1`.
- Fake GitHub SHA-256: `746a37251acdfed80d3237aac8ca3a573171559e6a0e58541a6b7ea90a4eb8d0`.
- Explicit runner-config SHA-256: `890f384ee3a10170647ba61f86bbebd42557f1992f9e8c51c96e2613bac4157e`.
- Executor for this measurement only: Codex CLI 0.165.0 requesting `gpt-6.1-sol`, medium effort; Homebrew Python 3.14.8; timeout 600 seconds per attempt.

The executor adapter and its host-specific OS compatibility code stayed outside
the repository. The harness has no default host, vendor, model or account.
Login and nonlogin shells used the isolated runtime and fake GitHub. A local
argv reader supplied real process metadata for attribution and was checked
against native `ps`; it did not manufacture caller labels. Controls refused
reads of hidden oracle/solution source, the original repository and other runs.

Every completed fixture matched its skill snapshot; runtime, harness, samples,
oracles and runner inputs remained frozen. Raw host events reconstruct the
stored normalized steps. All completed runs include `handling_session_gated`
and have no `checkout_changed` warning. Grading remained independent of the
executor's self-reported result. Raw transcripts, fixtures, source hashes,
attempt mappings and token usage remain local; they are not committed here.
The retained machine-readable comparison has SHA-256
`b26d8fdf3b44784a59c3b04b0e853cb70c651b5ef786bef496276d70bdec71bc`.

The candidate group began after five baseline completions; groups then
overlapped while each group stayed serial. Shared provider capacity, account,
caches and built-in host context are uncontrolled boundaries. Dollar cost is
unavailable rather than zero. No latency, cache-efficiency, production-success,
statistical-superiority or cross-agent claim follows from this pilot.
