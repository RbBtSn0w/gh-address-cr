# Status-Action Map

This document maps the `gh-address-cr` runtime `status` fields to the next safe action. As a thin adapter, the skill must follow this map without redefining the state machine.

## Active Work

If `status` is `WAITING_FOR_ACTION`:
- **Action**: Inspect the `item_id` and `item_kind`. Use `gh-address-cr agent next` and `gh-address-cr agent submit` to claim the item and submit your work.

If `status` is `ACTION_ACCEPTED`:
- **Action**: Run the returned `next_action` exactly. For accepted GitHub-thread fixes, this publishes through `gh-address-cr agent publish`.

If `status` is `BLOCKED`:
- **Action**: Inspect the `reason_code` and `waiting_on`. Handle the blocked item by applying a resolution (`fix`, `clarify`, `defer`, `reject`).

If `reason_code` is `WAITING_FOR_SIMPLE_ADDRESS`:
- **Action**: Inspect the `artifact_path` and `threads` array. Use per-thread `agent classify` and `agent next` to claim each actionable thread. Use `agent submit` for independent evidence, or `agent submit-batch` when one commit/files/validation set addresses multiple claimed GitHub threads, then run `agent publish`.

If `reason_code` is `AUTO_SIMPLE_NOT_ELIGIBLE`:
- **Action**: Stop the lightweight path and run the normal `review`, `findings`, or `adapter` workflow to handle local findings.

If `reason_code` is `GH_AUTH_FAILED` or `GITHUB_AUTH_FAILED`:
- **Action**: Inspect `diagnostics.command` and `diagnostics.stderr_category`. Fix GitHub CLI authentication with `gh auth status` / `gh auth login`, then rerun the same command.

If `reason_code` is `GH_NETWORK_FAILED`, `GITHUB_NETWORK_FAILED`, `GH_ENVIRONMENT_FAILED`, or `GITHUB_ENVIRONMENT_FAILED`:
- **Action**: Inspect `diagnostics.command`, `diagnostics.stderr_category`, and `diagnostics.stderr_excerpt`. Fix network, sandbox, PATH, or local permission issues before retrying; do not treat these as code-review findings.

## External Interactions

If `status` is `WAITING_FOR_EXTERNAL_REVIEW`:
- **Action**: You must produce review findings. Emit a JSON findings file or a fixed `finding` block format. Do NOT wait for stdin.

## Stop Conditions

If `status` is `NO_WORK_AVAILABLE` or `PASSED`:
- **Action**: The orchestration is complete or paused. If `PASSED`, ensure `python3 scripts/cli.py final-gate` was executed and reported success.

## Error States

If `status` is `UNKNOWN`, `FAILED`, or the machine summary is malformed (missing required fields):
- **Action**: Fail loudly. Do NOT guess the next action. Request human intervention or refer to the audit logs.
