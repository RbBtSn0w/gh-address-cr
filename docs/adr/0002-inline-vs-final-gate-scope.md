# ADR 0002: Distinguish inline pre-gate from the authoritative final gate

- Status: Accepted
- Date: 2026-06-13
- Issues: #119

## Context

Two distinct gate evaluations both surfaced a `PASSED` status:

- the inline pre-gate inside `review`/`address`/`threads`
  (`high_level.py` → `core_gate.evaluate_final_gate`), which folds only session
  items and remote threads; and
- the authoritative `final-gate` (`Gatekeeper.run`), which additionally fetches
  the current login's pending reviews and PR check runs.

Because both emitted `PASSED`, an agent reading a high-level `PASSED` could
reasonably but wrongly conclude the PR was complete while a pending review or red
check still existed. The completion contract already required a real `final-gate`
run, but the shared status token was a latent footgun.

## Decision

Tag every machine summary with a `gate_scope` field:

- `gate_scope: "inline"` on the pre-gate emitted by `review`/`address`/`threads`;
- `gate_scope: "final"` on `final-gate` output.

The completion contract is amended so that only `gate_scope: "final"` output is
valid completion proof. The inline result remains useful for fast iteration but is
explicitly non-authoritative.

## Consequences

- Agents and the completion contract can branch on `gate_scope` instead of
  inferring authority from the command name.
- No behavior change to the underlying gate logic; this is an additive,
  disambiguating field plus a documentation rule.
- Future work may rename the inline success status to `PRELIM_PASSED`; the
  `gate_scope` field already carries the distinction without that churn.
