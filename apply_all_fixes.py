import os
import re

def fix_telemetry():
    path = 'src/gh_address_cr/core/telemetry.py'
    with open(path, 'r') as f: content = f.read()
    content = content.replace('from typing import Any, ClassVar', 'from typing import Any, ClassVar, TypedDict, cast')

    old_report_class = """@dataclass
class EfficiencyReport:
    total_invocations: int
    total_duration: float
    success_rate: float
    flagged_inefficiencies: list[str]
    metrics: list[ExecutionMetric]

    def to_dict(self) -> dict:
        return {
            "total_invocations": self.total_invocations,
            "total_duration": self.total_duration,
            "success_rate": self.success_rate,
            "flagged_inefficiencies": self.flagged_inefficiencies,
            "metrics": [m.to_dict() for m in self.metrics],
        }"""
    new_report_class = """class EfficiencyReport(TypedDict):
    total_invocations: int
    total_duration: float
    success_rate: float
    flagged_inefficiencies: list[str]
    metrics: list[dict[str, Any]]


class SlowestOperation(TypedDict):
    source: str
    operation: str
    duration_ms: float
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
    total_observed_duration_ms: float
    duration_observed: bool
    telemetry_overhead_budget_ms: int
    telemetry_overhead_ms: float | None
    host_metrics: dict[str, int]
    slowest_operations: list[SlowestOperation]
    error_prone_operations: list[dict[str, Any]]
    inefficiency_flags: list[str]
    cli_health_issues: list[dict[str, Any]]
    diagnostics: list[str]
    confidence: float
    report_generated_at: str
    report_artifact: str"""
    content = content.replace(old_report_class, new_report_class)
    content = content.replace('def to_dict(self) -> dict:', 'def to_dict(self) -> dict[str, Any]:')
    content = content.replace('def __init__(self):', 'def __init__(self) -> None:')
    content = content.replace('def build_efficiency_report(repo: str, pr_number: str) -> dict[str, Any]:',
                              'def build_efficiency_report(repo: str, pr_number: str) -> EfficiencyReportPayload:')
    content = content.replace('report: dict[str, Any] = {', 'report: EfficiencyReportPayload = {')
    content = content.replace('def _failed_import_summary(\n    paths,', 'def _failed_import_summary(\n    paths: core_paths.SessionPaths,')
    content = content.replace('def _load_import_state(paths, *, source: str, fmt: str):',
                              'def _load_import_state(paths: core_paths.SessionPaths, *, source: str, fmt: str) -> tuple[list[ExternalTelemetryEvent], set[str], None] | tuple[None, None, dict[str, Any]]:')
    content = re.sub(r'def _resolve_import_status\(\s+\*,\s+accepted: list,', 'def _resolve_import_status(\n    *,\n    accepted: list[ExternalTelemetryEvent],', content)

    old_get_report = """    def get_report(self) -> EfficiencyReport:
        total_inv = len(self.metrics)
        if total_inv == 0:
            return EfficiencyReport(0, 0.0, 0.0, [], [])

        total_dur = sum(m.duration for m in self.metrics)
        successes = sum(1 for m in self.metrics if m.is_success)
        success_rate = (successes / total_inv) * 100.0

        flags = self.evaluate_efficiency()

        return EfficiencyReport(
            total_invocations=total_inv,
            total_duration=total_dur,
            success_rate=success_rate,
            flagged_inefficiencies=flags,
            metrics=list(self.metrics),
        )"""
    new_get_report = """    def get_report(self) -> EfficiencyReport:
        total_inv = len(self.metrics)
        if total_inv == 0:
            return {
                "total_invocations": 0,
                "total_duration": 0.0,
                "success_rate": 0.0,
                "flagged_inefficiencies": [],
                "metrics": [],
            }

        total_dur = sum(m.duration for m in self.metrics)
        successes = sum(1 for m in self.metrics if m.is_success)
        success_rate = (successes / total_inv) * 100.0

        flags = self.evaluate_efficiency()

        return {
            "total_invocations": total_inv,
            "total_duration": total_dur,
            "success_rate": success_rate,
            "flagged_inefficiencies": flags,
            "metrics": [m.to_dict() for m in self.metrics],
        }"""
    content = content.replace(old_get_report, new_get_report)

    content = content.replace('report.total_invocations', 'report["total_invocations"]')
    content = content.replace('report.success_rate', 'report["success_rate"]')
    content = content.replace('report.total_duration', 'report["total_duration"]')
    content = content.replace('report.flagged_inefficiencies', 'report["flagged_inefficiencies"]')

    content = content.replace('def _extract_stored_required_strings(payload: dict, source: str) -> dict[str, str]:',
                              'def _extract_stored_required_strings(payload: dict[str, Any], source: str) -> dict[str, str]:')
    content = content.replace('"confidence": _confidence_for_coverage(coverage_label),',
                              '"confidence": float(_confidence_for_coverage(coverage_label)),')
    content = content.replace('duration_ms = _event_duration_ms(payload)', 'duration_ms = _event_duration_ms(cast(dict[str, Any], payload))')
    content = content.replace('values = _extract_stored_required_strings(payload, source)', 'values = _extract_stored_required_strings(cast(dict[str, Any], payload), source)')

    old_call = """    existing, existing_fingerprints, load_failure = _load_import_state(paths, source=source, fmt=fmt)
    if load_failure is not None:
        return load_failure"""
    new_call = """    existing, existing_fingerprints, load_failure = _load_import_state(paths, source=source, fmt=fmt)
    if load_failure is not None or existing_fingerprints is None:
        return load_failure or {}"""
    content = content.replace(old_call, new_call)

    content = content.replace('summary = f"{report.total_invocations} tools invoked ({report.success_rate:.0f}% success). Total tool duration: {report.total_duration:.1f}s."',
                              'summary = f"{report[\'total_invocations\']} tools invoked ({report[\'success_rate\']:.0f}% success). Total tool duration: {report[\'total_duration\']:.1f}s."')
    content = content.replace('for f in report.flagged_inefficiencies', 'for f in report["flagged_inefficiencies"]')

    with open(path, 'w') as f: f.write(content)

def fix_feedback():
    path = 'src/gh_address_cr/commands/submit_feedback.py'
    with open(path, 'r') as f: content = f.read()
    content = re.sub(r': dict([ \),])', r': dict[str, Any]\1', content)
    content = content.replace('-> dict:', '-> dict[str, Any]:')
    content = content.replace('-> dict\n', '-> dict[str, Any]\n')
    content = content.replace('list[dict]', 'list[dict[str, Any]]')
    content = content.replace('dict | None', 'dict[str, Any] | None')
    content = content.replace('-> subprocess.CompletedProcess:', '-> subprocess.CompletedProcess[str]:')
    with open(path, 'w') as f: f.write(content)

def fix_high_level():
    path = 'src/gh_address_cr/commands/high_level.py'
    with open(path, 'r') as f: content = f.read()
    content = re.sub(r': dict([ \),])', r': dict[str, Any]\1', content)
    content = content.replace('-> dict:', '-> dict[str, Any]:')
    content = content.replace('-> dict\n', '-> dict[str, Any]\n')
    content = content.replace('list[dict]', 'list[dict[str, Any]]')
    content = content.replace('dict | None', 'dict[str, Any] | None')
    with open(path, 'w') as f: f.write(content)

def fix_batch():
    path = 'src/gh_address_cr/core/agent_batch.py'
    with open(path, 'r') as f: content = f.read()
    content = 'from datetime import datetime\n' + content
    content = content.replace('def _select_batch_target_items(session, *, agent_id: str, files: list[str] | None):',
                              'def _select_batch_target_items(session: dict[str, Any], *, agent_id: str, files: list[str] | None) -> list[tuple[str, dict[str, Any]]]:')
    content = content.replace('def _ensure_batch_classification_evidence(session, item, *, item_id, agent_id, ledger) -> None:',
                              'def _ensure_batch_classification_evidence(session: dict[str, Any], item: dict[str, Any], *, item_id: str, agent_id: str, ledger: Any) -> None:')
    content = content.replace('def _build_fixer_action_request(session, repo, pr_number, *, item, lease_id, request_id) -> dict[str, Any]:',
                              'def _build_fixer_action_request(session: dict[str, Any], repo: str, pr_number: str, *, item: dict[str, Any], lease_id: str, request_id: str) -> dict[str, Any]:')
    content = content.replace('def _reconcile_existing_lease(session, repo, pr_number, *, item, item_id, existing_lease, agent_id, ledger) -> dict[str, Any]:',
                              'def _reconcile_existing_lease(session: dict[str, Any], repo: str, pr_number: str, *, item: dict[str, Any], item_id: str, existing_lease: dict[str, Any], agent_id: str, ledger: Any) -> dict[str, Any]:')
    old_lease = """def _lease_new_github_thread(
    session, repo, pr_number, *, item, item_id, agent_id, ledger, current_time, newly_leased_items
) -> dict[str, Any] | None:"""
    new_lease = """def _lease_new_github_thread(
    session: dict[str, Any], repo: str, pr_number: str, *, item: dict[str, Any], item_id: str, agent_id: str, ledger: Any, current_time: datetime, newly_leased_items: list[tuple[str, dict[str, Any]]]
) -> dict[str, Any] | None:"""
    content = content.replace(old_lease, new_lease)
    content = content.replace('def _rollback_newly_leased_items(session, newly_leased_items) -> None:',
                              'def _rollback_newly_leased_items(session: dict[str, Any], newly_leased_items: list[tuple[str, dict[str, Any]]]) -> None:')
    content = content.replace('def _load_existing_batch_skeleton(batch_skeleton_path) -> tuple[dict, dict]:',
                              'def _load_existing_batch_skeleton(batch_skeleton_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:')
    content = content.replace('def _build_batch_skeleton(agent_id, leased_items, existing_items_replies, existing_common) -> dict[str, Any]:',
                              'def _build_batch_skeleton(agent_id: str, leased_items: list[dict[str, Any]], existing_items_replies: dict[str, Any], existing_common: dict[str, Any]) -> dict[str, Any]:')
    with open(path, 'w') as f: f.write(content)

def fix_cli():
    path = 'src/gh_address_cr/cli.py'
    with open(path, 'r') as f: content = f.read()
    content = content.replace('from __future__ import annotations', 'from __future__ import annotations\n\nfrom typing import Any')
    content = content.replace('def _legacy_module(name: str):', 'def _legacy_module(name: str) -> Any:')
    content = content.replace('_dispatch_management_commands(args) -> int | None:', '_dispatch_management_commands(args: argparse.Namespace) -> int | None:')
    content = content.replace('_expand_target_args(args) -> None:', '_expand_target_args(args: argparse.Namespace) -> None:')
    content = content.replace('_dispatch_passthrough_commands(args) -> int | None:', '_dispatch_passthrough_commands(args: argparse.Namespace) -> int | None:')
    content = content.replace('_dispatch_high_level_commands(args) -> int:', '_dispatch_high_level_commands(args: argparse.Namespace) -> int:')
    with open(path, 'w') as f: f.write(content)

def fix_harness():
    path = 'src/gh_address_cr/orchestrator/harness.py'
    with open(path, 'r') as f: content = f.read()
    content = content.replace('def _parse_common_args(args: List[str]):', 'def _parse_common_args(args: List[str]) -> tuple[argparse.Namespace, list[str]]:')
    with open(path, 'w') as f: f.write(content)

def fix_final_gate():
    path = 'src/gh_address_cr/commands/final_gate.py'
    with open(path, 'r') as f: content = f.read()
    content = content.replace('from typing import Any, cast', 'from typing import Any, cast, TYPE_CHECKING\nif TYPE_CHECKING:\n    from gh_address_cr.core.telemetry import EfficiencyReportPayload')
    content = content.replace('def telemetry_sources_summary(telemetry_report: dict) -> str:', 'def telemetry_sources_summary(telemetry_report: dict[str, Any]) -> str:')
    content = content.replace('def telemetry_diagnostics_summary(telemetry_report: dict) -> str:', 'def telemetry_diagnostics_summary(telemetry_report: dict[str, Any]) -> str:')
    content = content.replace('telemetry_report: dict)', 'telemetry_report: EfficiencyReportPayload | dict[str, Any])')
    content = content.replace('-> tuple[Path, dict]:', '-> tuple[Path, dict[str, Any]]:')
    content = content.replace('telemetry_report: dict = None,', 'telemetry_report: EfficiencyReportPayload | dict[str, Any] | None = None,')
    content = content.replace('def build_completion_summary_guidance(result, telemetry_report, summary_path=None, include_sha256=False):',
                              'def build_completion_summary_guidance(result: core_gate.GateResult, telemetry_report: EfficiencyReportPayload | dict[str, Any], summary_path: Path | None = None, include_sha256: bool = False) -> str:')
    old_fetch = """    if telemetry_report is None:
        telemetry_report = core_telemetry.build_efficiency_report(result.repo, result.pr_number)"""
    new_fetch = """    if telemetry_report is None:
        telemetry_report = cast('EfficiencyReportPayload', core_telemetry.build_efficiency_report(result.repo, result.pr_number))"""
    content = content.replace(old_fetch, new_fetch)
    content = content.replace('print(f"telemetry_coverage_label={telemetry_report[', 'assert telemetry_report is not None\n    print(f"telemetry_coverage_label={telemetry_report[')
    content = content.replace('return _issue_summary(telemetry_report)', 'return _issue_summary(cast(dict[str, Any], telemetry_report))')
    with open(path, 'w') as f: f.write(content)

def fix_telemetry_cmd():
    path = 'src/gh_address_cr/commands/telemetry.py'
    with open(path, 'r') as f: content = f.read()
    content = content.replace('import sys\nfrom pathlib import Path', 'import sys\nfrom pathlib import Path\nfrom typing import Any, cast')
    content = content.replace('def telemetry_report_has_storage_diagnostics(report: dict) -> bool:',
                              'def telemetry_report_has_storage_diagnostics(report: dict[str, Any]) -> bool:')
    content = content.replace('core_telemetry.efficiency_report_markdown(report)',
                              'core_telemetry.efficiency_report_markdown(cast(dict[str, Any], report))')
    with open(path, 'w') as f: f.write(content)

fix_telemetry()
fix_feedback()
fix_high_level()
fix_batch()
fix_cli()
fix_harness()
fix_final_gate()
fix_telemetry_cmd()
