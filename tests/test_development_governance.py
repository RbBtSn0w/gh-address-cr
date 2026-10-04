"""Development governance must work without retired scaffolding."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class DevelopmentGovernanceTests(unittest.TestCase):
    def test_governance_is_self_contained_and_uses_current_persistence_owner(self):
        text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("`runtime.sqlite3` is the current authoritative store", text)
        self.assertIn("## Autonomous Development", text)
        self.assertNotIn(".specify/", text)
        self.assertNotIn("SPECKIT START", text)
        self.assertFalse((ROOT / ".specify").exists())
        self.assertFalse((ROOT / "specs").exists())

    def test_execution_surfaces_do_not_depend_on_retired_scripts(self):
        for directory in ("src", "scripts", ".github"):
            for path in (ROOT / directory).rglob("*"):
                if path.is_file() and path.suffix in (".py", ".sh", ".yml", ".yaml", ".json"):
                    with self.subTest(path=path.relative_to(ROOT)):
                        self.assertNotIn(".specify/", path.read_text(encoding="utf-8"))

    def test_autonomous_development_preserves_specialized_verification_gates(self):
        text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        verification = text.split("### Risk-Matched Verification", 1)[1]
        for requirement in (
            "CLI or packaging changes MUST include CLI smoke tests",
            "resolve, or final-gate changes MUST include behavior tests",
            "Telemetry changes crossing the telemetry blast-radius threshold MUST include",
            "safety filtering",
            "deterministic fingerprints",
            "duplicate or overlapping",
            "coverage labels",
            "report artifacts",
            "final-gate/audit integration",
            "fail-loud telemetry-command versus fail-open core-workflow boundary",
            "Runtime-kernel changes crossing the kernel blast-radius threshold MUST include",
            "replay or contract tests",
            "event inputs, projections, policy decisions",
            "side-effect plans, artifact boundaries, and final-gate outcomes agree",
        ):
            with self.subTest(requirement=requirement):
                self.assertIn(requirement, verification)

    def test_archived_design_links_resolve_without_task_lists(self):
        archive = ROOT / "docs" / "rfcs"
        self.assertFalse(list(archive.rglob("tasks.md")))
        for path in archive.rglob("*.md"):
            for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
                if ":" in target or target.startswith("#"):
                    continue
                with self.subTest(path=path.relative_to(ROOT), target=target):
                    self.assertTrue((path.parent / target.split("#")[0]).exists())
