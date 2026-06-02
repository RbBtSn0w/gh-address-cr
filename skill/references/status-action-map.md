# Status-Action Map

This document maps the `gh-address-cr` runtime `status` fields to the next safe action. As a thin adapter, the skill must follow this map without redefining the state machine.

## Active Work

If `status` is `WAITING_FOR_ACTION`:
- **Action**: Inspect the `item_id` and `item_kind`. Use `gh-address-cr agent next` and `gh-address-cr agent submit` to claim the item and submit your work.

If `status` is `ACTION_ACCEPTED`:
- **Action**: Run the returned `next_action` exactly. For accepted GitHub-thread fixes, this publishes through `gh-address-cr agent publish`.

If `status` is `BLOCKED`:
- **Action**: Inspect the `reason_code` and `waiting_on`. Handle the blocked item by applying a resolution (`fix`, `clarify`, `defer`, `reject`).
- **Command discipline**: If the machine summary includes `commands`, prefer those templates. They are the authoritative low-token route for agent recovery.

If `reason_code` is `WAITING_FOR_SIMPLE_ADDRESS`:
- **Action**: Inspect the `artifact_path`, `threads`, `claimable_item_ids`, and `batch_response_skeleton`. Use per-thread `agent classify` and `agent next` to claim each actionable thread. Use `agent submit` for independent evidence, or `agent submit-batch` when one commit/files/validation set addresses multiple matching GitHub threads; keep per-thread summary/why entries. Use `agent fix-all --homogeneous-reason <why>` only for a homogeneous repeated concern, then run `agent publish`.
- **GitHub review comment reply tasks**: A reply draft is not a submitted task. Fill the issued `response_skeleton_path` or `batch_response_skeleton`, then run `gh-address-cr agent submit <owner/repo> <pr_number> --input <response.json>` or `gh-address-cr agent submit-batch <owner/repo> <pr_number> --input <batch-response.json>` before `gh-address-cr agent publish <owner/repo> <pr_number>`.
- **Lean path**: Re-run `gh-address-cr address <owner/repo> <pr_number> --lean` or `gh-address-cr threads <owner/repo> <pr_number> --lean` when only item IDs, claimability, and evidence presence are needed.

If `reason_code` is `FINAL_GATE_UNRESOLVED_REMOTE_THREADS` or `FINAL_GATE_BLOCKING_GITHUB_ITEMS`:
- **Action**: Run the returned `next_action` exactly. The normal recovery is `gh-address-cr address <owner/repo> <pr_number> --lean`, then `gh-address-cr agent submit-batch <owner/repo> <pr_number> --input <batch-response.json>` or per-thread `agent fix`. Use `gh-address-cr agent fix-all ... --homogeneous-reason <why>` only for a homogeneous repeated concern. Follow with `gh-address-cr agent publish <owner/repo> <pr_number>` and `gh-address-cr final-gate <owner/repo> <pr_number>`.

If `reason_code` is `FINAL_GATE_MISSING_REPLY_EVIDENCE`:
- **Action**: Run `gh-address-cr agent publish <owner/repo> <pr_number>` when accepted evidence is present, then rerun `gh-address-cr final-gate <owner/repo> <pr_number>`.

If a GitHub thread has `state=stale` or `status=STALE`:
- **Action**: Do not mark it resolved directly. Use `gh-address-cr agent resolve-stale <owner/repo> <pr_number> --commit <sha> --files <paths> --validation <cmd=passed> --match-files`, then publish and rerun final-gate.

If `reason_code` is `AUTO_SIMPLE_NOT_ELIGIBLE`:
- **Action**: Stop the lightweight path and run the normal `review`, `findings`, or `adapter` workflow to handle local findings.

If `reason_code` is `GH_AUTH_FAILED` or `GITHUB_AUTH_FAILED`:
- **Action**: Inspect `diagnostics.command` and `diagnostics.stderr_category`. Fix GitHub CLI authentication with `gh auth status` / `gh auth login`, then rerun the same command.

If `reason_code` is `GH_NETWORK_FAILED`, `GITHUB_NETWORK_FAILED`, `GH_ENVIRONMENT_FAILED`, or `GITHUB_ENVIRONMENT_FAILED`:
- **Action**: Inspect `diagnostics.command`, `diagnostics.stderr_category`, and `diagnostics.stderr_excerpt`. Fix network, sandbox, PATH, or local permission issues before retrying; do not treat these as code-review findings.

If `reason_code` is `DOCTOR_FAILED`:
- **Action**: Inspect each failed `checks[]` row. Fix GitHub CLI, auth, repository access, or state/cache writeability, then rerun `gh-address-cr doctor` before retrying the blocked command.

## External Interactions

If `status` is `WAITING_FOR_EXTERNAL_REVIEW`:
- **Action**: You must produce review findings. Emit a JSON findings file or a fixed `finding` block format. Do NOT wait for stdin.

## Stop Conditions

If `status` is `NO_WORK_AVAILABLE` or `PASSED`:
- **Action**: The orchestration is complete or paused. If `PASSED`, ensure `gh-address-cr final-gate` was executed and reported success.

If `status` is `NO_ACTIVE_PR`:
- **Action**: No OPEN PR matches the branch. Open a PR or pass an explicit PR number; do not fall back to MERGED/CLOSED PRs.

If `status` is `AMBIGUOUS_ACTIVE_PR`:
- **Action**: Choose the intended OPEN PR explicitly before running `review`, `address`, or `threads`.

## Error States

If `status` is `UNKNOWN`, `FAILED`, or the machine summary is malformed (missing required fields):
- **Action**: Fail loudly. Do NOT guess the next action. Request human intervention or refer to the audit logs.
