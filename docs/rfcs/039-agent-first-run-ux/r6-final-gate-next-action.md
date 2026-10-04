> Archived design reference. Current code, tests, and `AGENTS.md` govern
> execution; historical delivery status and commands are not active instructions.

# Spec 039 addendum: R6 / I6 — blocked final-gate prints its next action

Source: issue #308, finding 1 (runtime 3.16.0, `RbBtSn0w/app-store-creative#4`).

## Finding F8

A review thread was open when the session started and was later resolved on
GitHub without a reply from the agent. `final-gate` blocked with
`FINAL_GATE_MISSING_REPLY_EVIDENCE`, and the agent had to discover
`agent evidence add` on its own.

Verification:
- The runtime did compute the exact remediation. The archived
  `last-machine-summary.json` for that session holds
  `next_action: Record terminal-thread reply evidence with gh-address-cr agent evidence add RbBtSn0w/app-store-creative 4 --item-id github-thread:PRRT_… --reply-url <reply_url> --author-login <login> …`.
- The default single-PR report (`emit_final_gate_result`) never printed it; only
  the stack report (`emit_stack_final_gate_result`) printed `Next action:`.
  Agents reading the terminal report therefore saw the reason code without the
  command. `--machine` output already carried `next_action`.

## R6

Print `Next action: <next_action>` under `== Gate Result ==` for every blocked
single-PR `final-gate`, matching the stack report. Output-only: the gate verdict,
exit code, reason codes, and machine summary are unchanged, so no Architecture
Preflight trigger applies.

## I6 (L1 journey invariant)

A blocked `final-gate` prints its next action in the terminal report.
`tests/contract/test_agent_journey_contract.py::FinalGateNextActionContractTests`
covers the #308 scenario (thread resolved remotely without a reply → the line
names `agent evidence add … --item-id github-thread:…`) and an ordinary
unresolved thread (→ `address … --lean`).

## Out of scope (tracked on #308, need separate decisions)

- Whether a thread closed remotely without any reply should still require reply
  evidence. `agent evidence add` needs a reply URL that does not exist in that
  case; changing it alters final-gate truth semantics and needs a preflight.
- Normalizing a bare `PRRT_…` id to `github-thread:PRRT_…` (input contract).
  Partly mitigated by R2: `primary_action` now carries the full item id.
- A `--reason` alias for `--why`: AGENTS.md prefers a clean contract over aliases.
