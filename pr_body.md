## Summary
Implement a telemetry tracking layer to automatically record execution metrics (start/end time, exit status) for all skill and CLI tool invocations. The system flags inefficiencies based on thresholds (>60s execution or >20% error rate) and appends a human-readable summary to GitHub PR replies.

## Spec Coverage
- [x] FR-001: Intercept/record timestamps — verified by `tests/core/test_telemetry.py`
- [x] FR-002: Capture exit status — verified by `tests/core/test_telemetry.py`
- [x] FR-003: Quantifiable thresholds — verified by `tests/core/test_telemetry.py`
- [x] FR-004: Count consecutive retries — verified by `tests/core/test_telemetry.py`
- [x] FR-005: Generate efficiency summary — verified by `tests/core/test_telemetry.py`
- [x] FR-006: Flag threshold violations — verified by `tests/core/test_telemetry.py`
- [x] FR-007: Export via completion reply — verified by `tests/core/test_reply_templates.py`

## Verification Evidence
- Test suite: 540 tests, 540 passing, 0 failing
- Spec coverage: 7/7 requirements verified
- Ruff: All checks passed

## Review
Consider running `/speckit.superb.critique` for spec-aligned review.
