# Contract: Review Producer Intake

## Purpose

Keep external review production replaceable while preserving deterministic PR review resolution.

## Accepted Inputs

The workflow accepts:

- Normalized findings JSON.
- Fixed `finding` blocks that can be converted to normalized findings.

The workflow rejects:

- Narrative-only review prose.
- Mixed prose that does not contain fixed `finding` blocks.
- Producer output that lacks required finding fields.
- Producer output that asks agents to bypass runtime-mediated session handling.

## Required Finding Semantics

Each accepted finding must provide enough information to become a session item:

- Title or summary.
- Body or rationale.
- Source or producer identity.
- Location when applicable.
- Severity when available.
- Stable identity or enough fields to derive one.

## Producer Independence Rules

- Producer identity must not change session handling semantics.
- Producer identity must not change completion semantics.
- Producers do not own GitHub replies, resolves, session mutation, or final-gate decisions.
- Invalid producer output is a fail-loud intake error, not an agent interpretation task.

## Adapter Guidance

When producer output is unsupported, the adapter should direct the operator to provide normalized findings or fixed `finding` blocks and rerun the high-level review command.

## Test Expectations

- Valid normalized findings are accepted from at least two producer identities.
- Fixed `finding` blocks are accepted through the documented conversion path.
- Narrative-only Markdown is rejected.
- Producer replacement does not change reply, resolve, evidence, or final-gate behavior.
