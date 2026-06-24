import re
path = 'src/gh_address_cr/commands/final_gate.py'
content = open(path).read()
if 'TYPE_CHECKING' not in content:
    content = content.replace('from typing import Any, cast', 'from typing import Any, cast, TYPE_CHECKING\nif TYPE_CHECKING:\n    from gh_address_cr.core.telemetry import EfficiencyReportPayload')
content = content.replace('def telemetry_sources_summary(telemetry_report: dict) -> str:', 'def telemetry_sources_summary(telemetry_report: Any) -> str:')
content = content.replace('def telemetry_diagnostics_summary(telemetry_report: dict) -> str:', 'def telemetry_diagnostics_summary(telemetry_report: Any) -> str:')
content = content.replace('telemetry_report: dict)', 'telemetry_report: Any)')
content = content.replace('-> tuple[Path, dict]:', '-> tuple[Path, Any]:')
content = content.replace('telemetry_report: dict = None,', 'telemetry_report: Any = None,')
content = content.replace('def build_completion_summary_guidance(result, telemetry_report, summary_path=None, include_sha256=False):',
                          'def build_completion_summary_guidance(result: core_gate.GateResult, telemetry_report: Any, summary_path: Path | None = None, include_sha256: bool = False) -> str:')
old_fetch = """    if telemetry_report is None:
        telemetry_report = core_telemetry.build_efficiency_report(result.repo, result.pr_number)"""
new_fetch = """    if telemetry_report is None:
        from typing import cast
        telemetry_report = cast(dict, core_telemetry.build_efficiency_report(result.repo, result.pr_number))"""
content = content.replace(old_fetch, new_fetch)
content = content.replace('return _issue_summary(telemetry_report)', 'return _issue_summary(cast(dict[str, Any], telemetry_report))')
open(path, 'w').write(content)
