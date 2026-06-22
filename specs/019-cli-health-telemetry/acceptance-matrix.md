# Acceptance Matrix: CLI Health Telemetry

| ID | Area | Contract | Verification |
| --- | --- | --- | --- |
| HT-001 | autodiscovery | Missing host profile/env/transcript facts are diagnose-loud but final-gate remains fail-open. | `test_final_gate_autodiscovery_miss_is_diagnose_loud_fail_open` |
| HT-002 | doctor | `telemetry doctor` emits stable profile checks and CLI health issues. | `test_cli_telemetry_doctor_reports_profile_and_health_checks` |
| HT-003 | reporting | Efficiency report exposes `cli_health_issues` separately from inefficiency flags. | `test_cli_telemetry_doctor_reports_profile_and_health_checks` |
| HT-004 | abstraction | Codex and Claude Code are loaded from profiles, not hard-coded final-gate branches. | `test_cli_telemetry_doctor_reports_profile_and_health_checks` |
| HT-005 | safety | Diagnostic details remain public-safe and do not include transcript contents. | Existing telemetry safety tests plus doctor output assertions |
| HT-006 | feedback | The latest CLI machine `reason_code` and `next_action` feed health issues so telemetry can guide repair. | `test_cli_telemetry_doctor_projects_last_machine_summary_reason_code` |
