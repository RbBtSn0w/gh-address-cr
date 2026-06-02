# Research: Fix-All Thread Replies

## Decision: Make per-thread batch evidence the default multi-thread path

**Rationale**: The existing batch contract already separates shared fix evidence
from item-specific `summary` and `why`. Restoring this path as the default keeps
the low-overhead workflow while preserving the reviewer expectation that each
thread receives a direct answer.

**Alternatives considered**:

- Keep `fix-all` as the default and improve docs only. Rejected because generic
  shortcut replies remain accepted runtime behavior.
- Require only single-thread `agent fix` for every comment. Rejected because it
  removes useful shared evidence and lease batching for ordinary small PRs.

## Decision: Narrow `fix-all` to explicit homogeneous repeated concerns

**Rationale**: `fix-all` remains useful for repeated mechanical nits, such as
the same typo, style correction, or identical guard repeated across equivalent
locations. It should not infer semantic equivalence from matching files alone.

**Alternatives considered**:

- Remove `fix-all` entirely. Rejected because the user explicitly allowed
  keeping it as a narrow shortcut and the workflow benefits from a low-friction
  path for true repeated nits.
- Treat matching file paths as enough to prove homogeneity. Rejected because
  multiple distinct reviewer questions often occur on the same file.

## Decision: Require per-item evidence for mixed or uncertain fix-all matches

**Rationale**: When homogeneity is not explicit, the runtime needs structured
per-item evidence so acceptance and publishing can preserve one-to-one reviewer
answers. A per-item evidence file is the clearest way to keep `fix-all` useful
without relying on generated boilerplate.

**Alternatives considered**:

- Generate targeted answers automatically from thread bodies. Rejected as the
  primary design because deterministic runtime code should not invent reviewer
  rationale, and missing bodies would force unsafe guesses.
- Accept generic replies but add thread URLs. Rejected because a URL reference
  does not answer the reviewer's question.

## Decision: Fail fast when mixed threads lack per-item rationale

**Rationale**: A refusal with a concrete next action is safer than accepting
generic replies and letting final-gate pass with weak evidence. The failure
should direct agents back to the per-thread batch skeleton.

**Alternatives considered**:

- Let publishing detect duplicate reply bodies. Rejected because evidence would
  already be accepted into the session, making recovery noisier.
- Let final-gate detect generic replies. Rejected because final-gate should
  prove completion, not repair accepted evidence quality.

## Decision: Test published reply body distinctness and targeted rationale

**Rationale**: The previous regression was not caught because tests verified
state transitions and commit evidence but not reply content quality. Tests must
prove that mixed review questions either produce distinct targeted replies or
are rejected before publishing.

**Alternatives considered**:

- Test only accepted response JSON. Rejected because publishing is the user
  visible contract and can still render duplicate bodies from accepted data.
- Test only documentation wording. Rejected because the runtime must enforce
  the contract, not merely suggest it.
