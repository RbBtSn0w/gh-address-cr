# Contract: CLI Legacy Compatibility Removal

## Supported Current Commands

The following runtime commands remain supported and must not depend on the
historical script-dispatch package:

- `gh-address-cr active-pr`
- `gh-address-cr address`
- `gh-address-cr review`
- `gh-address-cr threads`
- `gh-address-cr findings`
- `gh-address-cr adapter`
- `gh-address-cr doctor`
- `gh-address-cr review-to-findings`
- `gh-address-cr submit-feedback`
- `gh-address-cr submit-action`
- `gh-address-cr agent ...`
- `gh-address-cr final-gate`
- `gh-address-cr version`
- `python3 -m gh_address_cr --help`

## Unsupported Historical Commands

Historical low-level command names that were previously reachable through the
runtime script dispatcher are no longer supported as public commands. Attempts
to invoke them must return non-zero before session mutation or GitHub side
effects.

Examples include:

- `gh-address-cr cr-loop`
- `gh-address-cr control-plane`
- `gh-address-cr session-engine`
- `gh-address-cr run-once`
- `gh-address-cr list-threads`
- `gh-address-cr post-reply`
- `gh-address-cr resolve-thread`
- `gh-address-cr ingest-findings`
- `gh-address-cr publish-finding`
- `gh-address-cr mark-handled`
- `gh-address-cr audit-report`
- `gh-address-cr generate-reply`
- `gh-address-cr batch-resolve`
- `gh-address-cr clean-state`

## Rejection Requirements

Unsupported historical usage must:

1. Return a non-zero exit status.
2. Include "unsupported legacy command" or equivalent clear wording.
3. Name at least one current supported workflow.
4. Avoid creating or modifying PR session files.
5. Avoid GitHub write operations.

## Documentation Requirements

Active user-facing docs and packaged skill guidance must not instruct users to
run removed script paths or unsupported historical commands. Historical specs
may retain old examples only when marked as superseded or archival.
