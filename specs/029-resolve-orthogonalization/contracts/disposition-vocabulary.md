# Contract: Canonical Disposition Vocabulary

Enforced by `tests/test_disposition_vocabulary.py`. Implements FR-006b and
SC-004a: `agent resolve` and `submit-action` **share one disposition
vocabulary**, drawn from 5 sites (see C-V2). `agent evidence add` has **no**
disposition/resolution surface and is **excluded by construction**, not a
third party to this sharing (E1 correction, `/speckit-analyze` — an earlier
draft of this file, plan.md, and quickstart.md Scenario 6 incorrectly said
"all three commands"/"`agent evidence add` adopts/accepts/shares"; verified
against `handle_agent_evidence` and the evidence functions it calls, none of
which reference any resolution/disposition value — see spec.md FR-006a/
SC-004a and data-model.md Entity 2, the authoritative statement of this
scope).

## C-V1 One canonical set

- Two distinct sets, to avoid conflating the surface with the constant (N1):
  - **Shared source-of-truth constant** = `TERMINAL_RESOLUTIONS =
    {fix, clarify, defer, reject}`. Every command that exposes or validates a
    resolution value draws from it; no command hard-codes a divergent synonym
    set.
  - **`agent resolve`'s `--disposition` axis surface set** =
    `{fix, trivial, reject, clarify}` — it adds `trivial` (a fix sub-mode, not
    a terminal resolution) and omits `defer` (a `submit-action`-only loop
    action). Cross-command equality is therefore checked **modulo `trivial`
    and `defer`** (SC-004a / T025), not as a raw set-equality of every site.
- `trivial` is a documentation/typo fast path within the fix disposition, not a
  separate terminal resolution.

## C-V2 Cross-command identity (2 commands, 5 sites — `agent evidence add` excluded)

- The disposition names accepted by `agent resolve` (its `--disposition` axis)
  and by `submit-action --resolution` MUST be drawn from the same canonical
  constant, with no divergent synonyms — verified by a test that imports
  **5 sites** and asserts equality (modulo `defer` where applicable and
  `trivial` as a fix sub-mode): `agent resolve`'s parser, `submit_action.
  parse_args`'s choices, `agent.roles.TERMINAL_RESOLUTIONS`,
  `core.agent_protocol_evidence.TERMINAL_RESOLUTIONS`, and
  `agent.responses.WORKFLOW_DECISIONS`.
- `agent evidence add` (`handle_agent_evidence` and the evidence functions it
  calls) is **not** one of the 5 sites and is **not** checked here — it has no
  disposition/resolution value to compare. Its selection shape
  (`--item-id`/`--thread-id`/`--files`) matches `agent resolve`'s selection
  axis (FR-006a), which is the extent of its alignment to this feature.

## C-V3 No capability loss

- Aligning vocabulary MUST NOT drop capabilities: `submit-action`'s file-based
  single-action submission, and `agent evidence add`'s reusable evidence
  recording and reply-evidence reconciliation, remain expressible unchanged
  (FR-006c).

## C-V4 No behavioral change to submit-action's payload

- `submit-action`'s structured action-request/response schema is unchanged; only
  the *vocabulary source* is unified. Existing `--resolution {fix,clarify,defer,
  reject}` values keep their meaning and output.

## Verification

`python3 -m unittest tests.test_disposition_vocabulary` +
`python3 -m gh_address_cr submit-action --help` +
`python3 -m gh_address_cr agent resolve --help`.
