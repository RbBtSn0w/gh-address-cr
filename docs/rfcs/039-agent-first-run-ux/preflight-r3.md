> Archived design reference. Current code, tests, and `AGENTS.md` govern
> execution; historical delivery status and commands are not active instructions.

# Architecture Preflight: Spec 039 R3 (fix replies cite only PR commits)

Trigger: adds a publish side-effect precondition and a submission rejection
(AGENTS.md blast-radius list: widens GitHub reads on the side-effect path and
changes when evidence is accepted). Fixes F7.

## Design change from the spec

Spec 039 R3 proposed blocking at publish with a remediation naming
`fix_reply.commit_hash`. Verification showed that would deadlock: once a response
is accepted its commit cannot be changed (`agent resolve` on a `publish_ready`
item returns `NO_ELIGIBLE_ITEM`, and `agent evidence add` only accepts terminal
items). Each check therefore sits where its recovery exists:

| Commit source | Checked at | Recovery |
|---|---|---|
| Explicit (`agent resolve --commit`, `fix_reply.commit_hash`, batch `common.commit_hash`) | submission, before acceptance | resubmit with the right commit; the one-shot lease is released on rejection |
| None given (local `HEAD` fallback, #111) | publish, before posting | push the fix, check out the PR head branch, rerun publish (the fallback is recomputed each run) |

The response skeleton still omits `commit_hash`, keeping #111's contract that a
fix can be submitted before its commit exists.

| Item | Answer |
|---|---|
| Authoritative state owner | Unchanged: runtime store for responses and publish state. Membership is a GitHub fact read at check time, not stored. |
| External facts | `GET repos/{repo}/pulls/{n}/commits` (paginated; `GitHubClient.list_pr_commit_shas`). Read fresh because the session's cached `head_oid` can predate the push of the fix. One read per publish; one per batch via `_CoherentStackContextClient`. |
| Decision function | `core/commit_membership.commit_in_pr`: a full SHA or an abbreviation of at least four characters (git's minimum) that prefixes a PR commit. |
| Side-effect plan | A failing check posts nothing and resolves nothing. Publish records `publish_blocked` with `COMMIT_NOT_IN_PR` and leaves the item `publish_ready`. |
| Reason code | New `COMMIT_NOT_IN_PR`: `ACTION_REJECTED` / `BATCH_ACTION_REJECTED` at submission, `PUBLISH_BLOCKED` with `waiting_on=commit_evidence` at publish. Documented in `skill/references/status-action-map.md`. Not in the R1 needs-action allowlist, so it counts as a failure in telemetry. |
| Failure of the read | Fails fast like any GitHub read on these paths (no silent pass). |
| Known limit | GitHub lists at most 250 commits per PR; a fix beyond that is reported as not in the PR. |
| Recovery / replay | Responses accepted before this change are only checked at publish when they relied on the fallback. |
| Executable contract tests | Journey I4 (`test_i4_publish_blocks_a_fallback_commit_outside_the_pr_and_recovers`, `test_i4_explicit_commit_outside_the_pr_is_rejected_before_acceptance`); batch rejection in `tests/contract/test_batch_claim_and_submit_contract.py`; matching rules in `tests/core/test_commit_membership.py`. |

## Test hermeticity found on the way

Several CLI and batch test suites never installed a fake `gh` and called the real
GitHub API for stack context, where the failure was swallowed. The new fail-fast
read exposed this. Those suites now use `PythonScriptTestCase.install_fake_pr_commits`
or a patched `list_pr_commit_shas`, so they no longer depend on the network for
this read.
