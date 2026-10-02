# Spec 039: Agent First-Run UX Fixes and Pre-Release Dogfooding

Status: Draft (plan only; nothing implemented)
Trigger: first real `address` session with runtime 3.16.0 (PR #305).
Verification method: code reading, executable reproduction against the installed
checkout (`gh_address_cr.__file__` = this repo), and cross-session triangulation over
local archived session artifacts (`~/Library/Caches/gh-address-cr/archive/*/efficiency-report.json`).

## 1. Verified findings

| # | Claim | Verdict | Evidence | Introduced |
|---|---|---|---|---|
| F4 | Expected "needs action" exits are reported as failures in telemetry | **Confirmed, 3.16.0 regression** | `cli._record_command_metric` (new in 3.16.0) records the raw exit code; `ExecutionMetric.is_success` is `exit_code == 0`; exit 5 is the documented blocked/needs-action code (41 call sites; `scripts/e2e_stacked_pr_sandbox.py` accepts `(0, 5)` as normal). Tag snapshots: `_record_command_metric` is absent in `v3.15.3` and present in `v3.16.0`. Existing tests pin exit 1 as failure (subprocess semantics); no test covers `_record_command_metric` or pins exit 5 as failure, so this is not an intended contract. Triangulation (20 of 50 local reports sampled; runtime version inferred from date because reports do not record it): no pre-3.16 session shows exit-5 command failures (pr-91/pr-100/pr-101 flags are genuine `github.graphql` failures or duration thresholds); 3 of 3 sessions from 3.16.0 onward do, and every flagged call is exit 5 (`address`, `threads`, `agent.next`, `agent.resolve`, `final-gate`). | v3.16.0 |
| F1 | `primary_action` recommends a command that is deterministically rejected | **Confirmed** | Repro: unclassified thread -> `kind=claim`, command `agent next --role fixer ...`; `agent_protocol` rejects mutating roles without `classification_evidence` (`MISSING_CLASSIFICATION`). It also contradicts `SKILL.md` step 5, which routes threads to `agent resolve` (classification recorded internally). Tests in `tests/test_primary_action.py` assert the projection only, never execute it. Tag snapshots: the classification gate already exists in `v3.11.0`; the `claim` projection was added in `v3.12.1` without checking that gate. | v3.12.1 |
| F7 (+F6) | Published fix reply can cite a commit that is not the fix | **Confirmed (latent)** | When the response has no `commit_hash` and the item has no commit evidence, `publisher._default_commit_hash_for_publish` falls back to local `git rev-parse HEAD` with no check against the PR head. Repro with the real archived PR #305 `session.json` (no `commit_evidence` on the session, the item, or the accepted response) while on branch `docs/039-agent-first-run-ux`: fallback returns `6583c8d` (develop tip, older than the PR #305 fix `876a911`). The response skeleton does not advertise `fix_reply.commit_hash`, so a skeleton-filled submit relies on this fallback unless the agent knows the undocumented field. The original F6 ("no commit binding") is **retracted**: the PR #305 reply correctly says "Addressed in `876a911`" because the checkout happened to be on the head branch. | v2.10.8 |
| F5 | Completion line repeats each failure twice | **Confirmed** | `final_gate._issue_summary` renders `inefficiency_flags` (derived from `error_prone_operations`) and then renders `error_prone_operations` again. Repro output: `flags: X had 1 failures...; X failures=1 timeouts=0 retries=0`. Amplified by F4. | v2.10.6 |
| F2 | Lean path hides the review body needed to classify | **Narrowed, low impact** | Original "body missing" claim **retracted**: `context.selected_item.comment_excerpt` exists. Residual: `--lean` thread rows drop `body`; the excerpt is cut at 500 chars with no truncation marker; the full untrusted body arrives in the action request only after classification. PR #305: the core claim (char 231) survived, the reviewer's suggested fix (char 841) did not. | v3.12.1 |
| F3 | Transient `GH_NETWORK_FAILED` lacks a retry signal | **Not reproducible; no product defect established** | The failure path has no `retryable` field (confirmed), but the single failure could not be reproduced and may be environmental. The "mixed stdout/stderr" observation was an artifact of my own `2>&1`. | n/a |

## 2. Escape analysis (why these reached a release)

1. Tests verify each surface in isolation: the projection returns `claim`, the
   recorder stores an exit code, the summary renders its parts. No test executes
   the runtime's own recommendation or asserts on the telemetry a clean session produces.
2. The two end-to-end tools do not behave like an agent:
   `scripts/validate_cr_lifecycle_dogfood.py` writes ledger events directly, and
   `scripts/e2e_stacked_pr_sandbox.py` runs a hard-coded `agent resolve` sequence,
   never follows `primary_action`, and never inspects telemetry or the completion line.
3. The release train promotes `develop` weekly behind unit tests only, so the
   first agent-shaped run is a post-release run.

## 3. Requirements (fixes)

### P0
- **R1 (F4)**: classify exit 5 outcomes that carry a documented `reason_code` as
  "needs action", not failure, in `success_rate`, `error_prone_operations` and
  `inefficiency_flags`. Real failures (non-zero exits other than documented blocked/rejected states, timeouts, crashes) stay flagged.
  AC: a session that reaches `final-gate PASSED` through the documented path reports 100% and no flags; a fixture with one genuine failure is still flagged.
- **R2 (F1)**: `primary_action` for an unresolved GitHub thread must be executable as-is.
  Either recommend `agent resolve` (matches `SKILL.md`) or emit classification first.
  AC: executing `primary_action.command` on a fresh session never yields `MISSING_CLASSIFICATION`.
  Any placeholder left in the command must be one an agent can fill from its own fix
  (`<agent_id>`, `<sha>`, `<paths>`, `<text>`, `<why>`, `<cmd=passed>`); the L1 literal
  follower (`tests/contract/test_agent_journey_contract.py`) fails on any other placeholder.

### P1
- **R3 (F7)**: before publishing, verify the cited commit is reachable from the PR head
  (`head_oid` already in session metadata) and is not an ancestor of the base; otherwise
  fail fast with a remediation that names `fix_reply.commit_hash`. Advertise
  `commit_hash` in the response skeleton.
- **R4 (F5)**: render each operation's problem once in the completion line; update the
  contract test for `completion_summary_line` in the same change.

### P2
- **R5 (F2)**: add `comment_excerpt_truncated` and name the command that returns the full body before classification.
- F3: no change until reproduced.

Architecture Preflight (AGENTS.md) is required for R1 (telemetry reporting contract),
R2 (Status-to-Action Map) and R3 (publish side-effect precondition).

## 4. Dogfooding: catch these before release

| Layer | When | What | Would have caught |
|---|---|---|---|
| L1 Agent journey contract tests | every PR, offline, seconds | Drive the CLI with the existing fake GitHub clients by **only** following `primary_action.command` (literal follower) and, separately, by following `SKILL.md` routing (skill follower), across a scenario matrix (fix, reject, clarify, batch, local finding, stale, stack member, wrong-branch checkout). Assert invariants I1-I5 below. | F1, F4, F5, F7 |
| L2 Wheel journey | every PR, CI | Run L1 against the built wheel in an isolated venv (CI already builds it for pr-preview). | packaging and skill-payload drift |
| L3 Sandbox journey | pre-promotion gate in `scheduled-release-pr.yml` | Extend `e2e_stacked_pr_sandbox.py exercise` to follow `primary_action` and assert I2/I3 on the real `final-gate` output against the sandbox repo. | real GitHub behaviour, F1-F5 |
| L4 Self-hosting + telemetry diff | continuous on this repo | Handle this repo's own bot review threads with the develop build; a script groups archived `efficiency-report.json` by runtime version and fails on a shift in success rate or new flag kinds (the manual triangulation in section 1, automated). | F4 within the first dogfood session |
| L5 Agent smoke | weekly, before promotion | Headless agent with the pr-preview skill on a seeded sandbox PR; its friction goes through `submit-feedback`. | unknown unknowns |

Journey invariants:
- **I1** Every executed `primary_action.command` is accepted (no precondition rejection whose remediation names a different command).
- **I2** A session completed through the documented path reports `success_rate == 100` and no `inefficiency_flags`.
- **I3** `completion_summary_line` mentions each operation at most once and stays under a length budget.
- **I4** Any commit cited in a published reply is reachable from the PR head and newer than the base; a wrong-branch checkout fails fast.
- **I5** Before classification, the agent can obtain the full review body through a documented command.

Order: L1 first (cheapest, deterministic, covers 4 of 5 confirmed items), then L4's telemetry diff script, then L3 as a promotion gate. L2 and L5 follow.

## 5. Open questions

- Q1: R2 — recommend `agent resolve` directly, or add a classification step to the action vocabulary?
- Q2: R1 — exclude needs-action exits from `success_rate`, or report them as a separate counter?
- Q3: L3 — is a required pre-promotion sandbox run acceptable for the weekly train (needs sandbox token in Actions)?
