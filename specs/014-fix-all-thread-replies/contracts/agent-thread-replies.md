# Contract: Agent Thread Replies

## Purpose

This contract governs multi-thread GitHub review handling where one commit or
validation set may cover several review threads, but each reviewer question must
still receive item-specific reply evidence.

## Default Addressing Guidance

When a PR has multiple actionable GitHub review threads, machine summaries and
skill guidance must present per-thread `BatchActionResponse` evidence as the
ordinary path.

Required guidance:

- Inspect the review thread bodies before answering.
- Claim each actionable thread through runtime-issued leases.
- Use shared commit, file, and validation evidence only for fields that are
  genuinely common.
- Fill each batch item with its own `summary` and `why`.
- Run `agent submit-batch`, then `agent publish`, then `final-gate`.

`agent fix-all` must be described as a shortcut only for explicitly homogeneous
repeated nits or equivalent repeated concerns.

## BatchActionResponse Requirements

Accepted multi-thread batch evidence must preserve:

- `agent_id`
- `resolution: fix`
- common files and validation evidence
- common or item-level commit evidence
- per-item `item_id`
- per-item `request_id`
- per-item `lease_id`
- per-item `summary`
- per-item `why` for mixed or uncertain thread sets

Shared `common.fix_reply` fields must not overwrite item-specific `summary` or
`why` when an item supplies its own evidence.

## Fix-All Requirements

`agent fix-all` may accept a multi-thread set without per-item evidence only
when the request explicitly identifies the matched threads as homogeneous
repeated concerns. The accepted evidence must make the homogeneous concern
visible in the final reply rationale.

If homogeneity is absent, unknown, or contradicted by distinct thread bodies,
`agent fix-all` must either:

- accept a per-item evidence input and preserve each item-specific answer; or
- fail before evidence acceptance with a next action that points to the
  per-thread `BatchActionResponse` skeleton.

Matching file paths alone is not proof of homogeneity.

## Publishing Requirements

Publishing must render replies from accepted per-thread evidence.

For materially different review questions:

- reply bodies must not be identical;
- each reply must include the relevant item-specific rationale;
- shared commit, file, and validation evidence may be repeated;
- severity and reviewer-priority evidence must remain evidence-backed.

For homogeneous repeated nits:

- reply bodies may share the same core rationale;
- each reply must still identify the repeated concern and preserve runtime
  reply evidence for the corresponding thread.

## Rejection Requirements

The workflow must reject before acceptance or publication when:

- per-item evidence is missing for mixed or uncertain thread sets;
- an item lacks active lease ownership;
- a batch includes duplicate item or lease identities;
- validation evidence is missing;
- a reply would be generic boilerplate for a distinct reviewer question;
- stale/outdated threads are routed through ordinary fix-all without the
  explicit stale-thread evidence path.

## Documentation Requirements

The following surfaces must remain consistent:

- runtime CLI help and machine summary command hints;
- `README.md`;
- `skill/SKILL.md`;
- `skill/agents/openai.yaml`;
- `skill/references/agent-protocol.md`;
- `skill/references/status-action-map.md`;
- repo-root tests that assert the documentation contract.
