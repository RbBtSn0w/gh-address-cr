path = 'src/gh_address_cr/commands/final_gate.py'
content = open(path).read()
content = content.replace('telemetry_sources_summary(telemetry_report: dict[str, Any])', 'telemetry_sources_summary(telemetry_report: Any)')
content = content.replace('telemetry_diagnostics_summary(telemetry_report: dict[str, Any])', 'telemetry_diagnostics_summary(telemetry_report: Any)')
content = content.replace('build_completion_summary_guidance(result: core_gate.GateResult, telemetry_report: Any,', 'build_completion_summary_guidance(result: core_gate.GateResult, telemetry_report: Any,')
content = content.replace('build_completion_summary_guidance(result, cast(dict, telemetry_report),', 'build_completion_summary_guidance(result, telemetry_report,')
open(path, 'w').write(content)
