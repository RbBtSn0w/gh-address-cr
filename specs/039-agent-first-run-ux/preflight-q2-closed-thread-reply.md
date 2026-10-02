# Architecture Preflight: runtime reply on a thread resolved without one (Spec 039 Q2)

Trigger: widens GitHub side effects (replies on remotely resolved threads) and adds an
agent protocol condition (AGENTS.md blast-radius list). Maintainer decision Q2: the runtime
posts the reply; agents must not post replies with `gh` directly (skill trust boundary).

## Problem

A review thread that the session saw open, then got resolved on GitHub (by the reviewer,
a bot, or a push) without a reply from this session, blocks `final-gate` with
`FINAL_GATE_MISSING_REPLY_EVIDENCE`. The only recovery was to post a reply out of band and
record it with `agent evidence add --reply-url`, which contradicts the skill rule and
bypasses the outbox (RbBtSn0w/app-store-creative#8; #308 finding 1).

## Decision

`agent resolve <item_id> --closed [fix evidence | --disposition clarify|reject|defer --why]`.
Deviation from the proposed `--disposition acknowledge`: reuse the existing `clarify`
disposition instead of adding a synonym (AGENTS.md compatibility policy: no aliases).

| Item | Answer |
|---|---|
| Authoritative state owner | Runtime store. `reopen_resolved_thread_for_reply` is one `transact_session` mutation that returns the item to its claimable state (`returned_claimable_state`), clears the resolved markers, and stamps `reopened_for_reply_at`. |
| Eligibility (decision function) | GitHub thread, resolved remotely, no `reply_evidence`, not `historical_remote_only`: exactly the threads final-gate blocks on. Otherwise `THREAD_NOT_RESOLVED` (open thread) or `CLOSED_THREAD_NEEDS_NO_REPLY`. No new state flag decides eligibility. |
| Side-effect plan | Unchanged machinery: classification, fixer lease, submit, and `agent publish` (outbox, idempotent reply then `resolveReviewThread`). `--closed` forces publish in the same call. Fix replies cite a commit checked by R3 (`COMMIT_NOT_IN_PR`). |
| Recovery / replay | If the call fails after the reopen, the next `address`/`final-gate` refresh merges the remote resolved state and closes the item again (`_determine_merged_thread_state`), so no stale open item survives. An accepted response not yet published at that point is covered by the existing publish/reconcile path. |
| Axis contract | `--closed` takes exactly one `item_id`; it is rejected with `RESOLVE_AXIS_CONFLICT` alongside `--stale`, `--input`, a files selection, or `--disposition trivial`. |
| Guidance | `THREAD_ALREADY_RESOLVED` (#320) and the `FINAL_GATE_MISSING_REPLY_EVIDENCE` reconcile next action now name the `--closed` commands; `evidence add --reply-url` remains for a reply that already exists. |
| Telemetry | OTel span event `gh_address_cr.thread.reopened_for_reply` (bounded attributes, no ids or paths). |
| Unverified external behavior | Whether GitHub accepts `addPullRequestReviewThreadReply` on a resolved thread was not exercised against GitHub in this change. If it is refused, publish fails fast with GitHub's error and the thread stays blocking; the journey fake accepts it. |
| Tests | `tests/contract/test_agent_journey_contract.py::ClosedThreadReplyContractTests` (fix and clarify replies pass the gate; open thread rejected; `THREAD_ALREADY_RESOLVED` and gate next actions name `--closed`), `tests/test_resolved_thread_validation_gap.py` (#320 guidance), `tests/test_agent_resolve_guards.py`. |
