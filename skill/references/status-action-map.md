# Status-Action Map

This document maps the `gh-address-cr` runtime `status` fields to the next safe action. As a thin adapter, the skill must follow this map without redefining the state machine.

## Active Work

If `status` is `WAITING_FOR_ACTION`:
- **Action**: Inspect the `item_id` and `item_kind`. Use `gh-address-cr agent next` and `gh-address-cr agent submit` to claim the item and submit your work.

If `status` is `ACTION_ACCEPTED`:
- **Action**: Run the returned `next_action` exactly. For accepted GitHub-thread fixes, this publishes through `gh-address-cr agent publish`.

If `status` is `ACTION_REJECTED` or `BATCH_ACTION_REJECTED` and the payload includes `lease_recovery`:
- **Action**: Follow `lease_recovery.recovery_outcome`, not a blind retry. `renew` means request a fresh action request for the same item. `reclaim` means run `gh-address-cr agent reclaim <owner/repo> <pr_number>` and then request work again. `refresh_state` means discard the stale response/request file and rerun `agent next` or `address --lean` to get current runtime truth. `stop` means another actor or newer state owns the item; do not resubmit. `already_completed` means the work was accepted or completed; move to publish/final-gate as appropriate.
- **Command discipline**: Prefer `lease_recovery.resume_command` when present. It is a machine-generated safe next command, not a guarantee that the previous response can be reused.

If `status` is `LEASES_READY` and a lease row includes `lease_recovery`:
- **Action**: Use the row as pre-submit guidance. A stale or expired row should be refreshed before submitting evidence. Do not infer permission to overwrite accepted, transferred, or changed work from an old lease file.

If `status` is `BLOCKED`:
- **Action**: Inspect the `reason_code` and `waiting_on`. Handle the blocked item by applying a resolution (`fix`, `clarify`, `defer`, `reject`).
- **Command discipline**: If the machine summary includes `commands`, prefer those templates. They are the authoritative low-token route for agent recovery.

If `reason_code` is `WAITING_FOR_SIMPLE_ADDRESS`:
- **Action**: Inspect the `artifact_path`, `threads`, `claimable_item_ids`, and `batch_response_skeleton`. Use per-thread `agent classify` and `agent next` to claim each actionable thread. Use `agent submit` for independent evidence, or `agent submit-batch` when one set of files/validation evidence addresses multiple matching GitHub threads; keep per-thread summary/why entries. Commit evidence is hydrated during publish. Use `agent fix-all --homogeneous-reason <why>` only for a homogeneous repeated concern, then run `agent publish`.
- **GitHub review comment reply tasks**: A reply draft is not a submitted task. Fill the issued `response_skeleton_path` or `batch_response_skeleton`, then run `gh-address-cr agent submit <owner/repo> <pr_number> --input <response.json>` or `gh-address-cr agent submit-batch <owner/repo> <pr_number> --input <batch-response.json>` before `gh-address-cr agent publish <owner/repo> <pr_number>`.
- **Lean path**: Re-run `gh-address-cr address <owner/repo> <pr_number> --lean` or `gh-address-cr threads <owner/repo> <pr_number> --lean` when only item IDs, claimability, and evidence presence are needed.

If `reason_code` is `PER_THREAD_EVIDENCE_REQUIRED`:
- **Action**: Run the returned `commands.batch_next` or `gh-address-cr agent next <owner/repo> <pr_number> --batch --agent-id <id>` to claim eligible GitHub review threads and write `batch-response-skeleton.json`. Fill common files/validation plus per-thread summary/why, then run the returned `submit_batch` command and publish.

If `reason_code` is `FINAL_GATE_UNRESOLVED_REMOTE_THREADS` or `FINAL_GATE_BLOCKING_GITHUB_ITEMS`:
- **Action**: Run the returned `next_action` exactly. The normal recovery is `gh-address-cr address <owner/repo> <pr_number> --lean`, then `gh-address-cr agent next <owner/repo> <pr_number> --batch --agent-id <id>` for shared batch evidence or per-thread `agent fix`. Use `gh-address-cr agent fix-all ... --homogeneous-reason <why>` only for a homogeneous repeated concern. Follow with `gh-address-cr agent publish <owner/repo> <pr_number>` and `gh-address-cr final-gate <owner/repo> <pr_number>`.

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
- **Action**: The orchestration is complete or paused. If `PASSED`, ensure `gh-address-cr final-gate` was executed and reported success. The final response must include the exact `completion_summary_line` from `final-gate --machine` or the first bracketed line from `PR Completion Summary Guidance`; explain abnormal coverage, diagnostics, success-rate drops, or inefficiency flags when present.

If `status` is `NO_ACTIVE_PR`:
- **Action**: No OPEN PR matches the branch. Open a PR or pass an explicit PR number; do not fall back to MERGED/CLOSED PRs.

If `status` is `AMBIGUOUS_ACTIVE_PR`:
- **Action**: Choose the intended OPEN PR explicitly before running `review`, `address`, or `threads`.

## Error States

If `status` is `UNKNOWN`, `FAILED`, or the machine summary is malformed (missing required fields):
- **Action**: Fail loudly. Do NOT guess the next action. Request human intervention or refer to the audit logs.
