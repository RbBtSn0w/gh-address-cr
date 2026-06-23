import sys
import re

path = 'src/gh_address_cr/core/telemetry.py'
with open(path, 'r') as f:
    content = f.read()

content = content.replace('from typing import Any, ClassVar', 'from typing import Any, ClassVar, TypedDict, cast')

# Keep EfficiencyReport as dataclass, add EfficiencyReportPayload as TypedDict
typed_dicts = """
class SlowestOperation(TypedDict):
    source: str
    operation: str
    duration_ms: int
    status: str


class EfficiencyReportPayload(TypedDict):
    status: str
    reason_code: str
    repo: str
    pr_number: str
    coverage_label: str
    sources: list[dict[str, Any]]
    total_events: int
    success_rate: float
    total_observed_duration_ms: int
    duration_observed: bool
    telemetry_overhead_budget_ms: int
    telemetry_overhead_ms: float | None
    host_metrics: dict[str, int]
    slowest_operations: list[SlowestOperation]
    error_prone_operations: list[dict[str, Any]]
    inefficiency_flags: list[str]
    cli_health_issues: list[dict[str, Any]]
    diagnostics: list[str]
    confidence: str
    report_generated_at: str
    report_artifact: str
"""

# Insert TypedDicts after external event or something stable
content = content.replace('SAFE_KINDS = {"tool_call", "command", "wait", "retry", "validation", "agent_step"}',
                          'SAFE_KINDS = {"tool_call", "command", "wait", "retry", "validation", "agent_step"}' + typed_dicts)

content = content.replace('def to_dict(self) -> dict:', 'def to_dict(self) -> dict[str, Any]:')
content = content.replace('def __init__(self):', 'def __init__(self) -> None:')
content = content.replace('def build_efficiency_report(repo: str, pr_number: str) -> dict[str, Any]:',
                          'def build_efficiency_report(repo: str, pr_number: str) -> EfficiencyReportPayload:')
content = content.replace('report: dict[str, Any] = {', 'report: EfficiencyReportPayload = {')
content = content.replace('def _failed_import_summary(\n    paths,', 'def _failed_import_summary(\n    paths: core_paths.SessionPaths,')
content = content.replace('def _load_import_state(paths, *, source: str, fmt: str):',
                          'def _load_import_state(paths: core_paths.SessionPaths, *, source: str, fmt: str) -> tuple[list[ExternalTelemetryEvent], set[str], None] | tuple[None, None, dict[str, Any]]:')
content = re.sub(r'def _resolve_import_status\(\s+\*,\s+accepted: list,', 'def _resolve_import_status(\n    *,\n    accepted: list[ExternalTelemetryEvent],', content)

content = content.replace('duration_ms = _event_duration_ms(payload)', 'duration_ms = _event_duration_ms(cast(dict[str, Any], payload))')
content = content.replace('values = _extract_stored_required_strings(payload, source)', 'values = _extract_stored_required_strings(cast(dict[str, Any], payload), source)')
content = content.replace('def _extract_stored_required_strings(payload: dict, source: str) -> dict[str, str]:',
                          'def _extract_stored_required_strings(payload: dict[str, Any], source: str) -> dict[str, str]:')

old_call = """    existing, existing_fingerprints, load_failure = _load_import_state(paths, source=source, fmt=fmt)
    if load_failure is not None:
        return load_failure"""
new_call = """    existing, existing_fingerprints, load_failure = _load_import_state(paths, source=source, fmt=fmt)
    if load_failure is not None or existing_fingerprints is None:
        return load_failure or {}"""
content = content.replace(old_call, new_call)

with open(path, 'w') as f: f.write(content)
