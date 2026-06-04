# Feature Spec: Reusable Command Session Mode

## Summary

Provide an optional command-session mode for repeated PR-scoped operations within one runtime process.

## Behavior

- `command-session --input <json>|-` accepts an `operations` array.
- Each operation has an `id` and `argv` string array.
- Every operation emits a discrete result with stdout, stderr, exit code, status, and reason code.
- Failed operations do not suppress later operations.
- Existing one-shot commands are unchanged.

## Owner Boundary

The CLI dispatch layer owns command-session execution. Individual command semantics remain with their existing handlers.

## Verification

- `python3 -m unittest tests.test_issue78_agent_experience.Issue78CommandSessionTests`
- `ruff check src tests`
- `python3 -m unittest discover -s tests`
- `python3 -m gh_address_cr --help`
