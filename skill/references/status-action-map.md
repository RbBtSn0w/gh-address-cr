# Status-Action Map

This document maps the `gh-address-cr` runtime `status` fields to the next safe action. As a thin adapter, the skill must follow this map without redefining the state machine.

## Active Work

If `status` is `WAITING_FOR_ACTION`:
- **Action**: Inspect the `item_id` and `item_kind`. Use `gh-address-cr agent next` and `gh-address-cr agent submit` to claim the item and submit your work.

If `status` is `BLOCKED`:
- **Action**: Inspect the `reason_code` and `waiting_on`. Handle the blocked item by applying a resolution (`fix`, `clarify`, `defer`, `reject`).

## External Interactions

If `status` is `WAITING_FOR_EXTERNAL_REVIEW`:
- **Action**: You must produce review findings. Emit a JSON findings file or a fixed `finding` block format. Do NOT wait for stdin.

## Stop Conditions

If `status` is `NO_WORK_AVAILABLE` or `PASSED`:
- **Action**: The orchestration is complete or paused. If `PASSED`, ensure `python3 scripts/cli.py final-gate` was executed and reported success.

## Error States

If `status` is `UNKNOWN`, `FAILED`, or the machine summary is malformed (missing required fields):
- **Action**: Fail loudly. Do NOT guess the next action. Request human intervention or refer to the audit logs.
