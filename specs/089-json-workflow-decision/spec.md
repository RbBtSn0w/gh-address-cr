# Feature Spec: JSON Workflow Decision Contract

## Summary

Add a schema-defined JSON workflow decision path so agents are not forced to rely on whitespace-sensitive Markdown decision blocks.

## Behavior

- `workflow_decision.v1` requires `schema_version`, `request_id`, `item_id`, `decision`, and `reason`.
- Valid decisions are `fix`, `clarify`, `defer`, and `reject`.
- Invalid JSON decision payloads fail fast before session mutation.
- Markdown decision blocks remain compatibility guidance, not the preferred machine contract.

## Owner Boundary

Runtime response validation owns the schema and reason codes. Skill docs describe the contract after tests define it.

## Verification

- `python3 -m unittest tests.test_issue78_agent_experience.Issue78WorkflowDecisionTests`
- `ruff check src tests`
- `python3 -m unittest discover -s tests`
- `python3 -m gh_address_cr --help`
