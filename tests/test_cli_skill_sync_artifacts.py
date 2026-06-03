import unittest

from tests.helpers import ROOT


FEATURE_DIR = ROOT / "specs" / "012-cli-skill-sync"
SPEC_MD = FEATURE_DIR / "spec.md"
PLAN_MD = FEATURE_DIR / "plan.md"
TASKS_MD = FEATURE_DIR / "tasks.md"
EXTERNAL_TELEMETRY_PLAN_MD = ROOT / "specs" / "015-external-agent-telemetry" / "plan.md"
SUPERSEDED_MARKER = "Superseded by `specs/012-cli-skill-sync`"
CURRENT_DOC_PATHS = [
    ROOT / "README.md",
    *(ROOT / "docs").glob("*.md"),
    *ROOT.joinpath("skill").rglob("*"),
    *ROOT.joinpath("plugin", "gh-address-cr").rglob("*"),
]


class CliSkillSyncArtifactTest(unittest.TestCase):
    def test_012_artifacts_reflect_phase_3_closeout(self):
        spec = SPEC_MD.read_text(encoding="utf-8")
        plan = PLAN_MD.read_text(encoding="utf-8")
        tasks = TASKS_MD.read_text(encoding="utf-8")

        self.assertIn("**Feature Branch**: `012-skill2cli`", spec)
        self.assertIn("**Status**: Complete", spec)
        self.assertIn("Phase 3 - Complete", spec)
        self.assertIn("Phase 3 Closeout", plan)
        self.assertIn("Phase 7: Closeout Audit", tasks)

        combined = "\n".join([spec, plan, tasks])
        self.assertNotRegex(combined, r"\b544\s+(?:unit\s+)?tests?\b")
        self.assertNotIn("scripts/sync_scripts.py", plan)
        self.assertNotIn("python3 scripts/sync_scripts.py", spec)

    def test_legacy_skill_script_specs_are_marked_superseded(self):
        stale_files = []
        for path in sorted((ROOT / "specs").rglob("*.md")):
            if path.is_relative_to(FEATURE_DIR):
                continue
            text = path.read_text(encoding="utf-8")
            if "skill/scripts" in text or "scripts/cli.py" in text:
                if SUPERSEDED_MARKER not in text:
                    stale_files.append(str(path.relative_to(ROOT)))

        self.assertEqual(stale_files, [])

    def test_current_public_docs_do_not_reintroduce_removed_skill_script_commands(self):
        violations = []
        allowed_upgrade_docs = {
            ROOT / "docs" / "installation.md",
            ROOT / "docs" / "troubleshooting.md",
        }
        stale_patterns = ("skill/scripts", "scripts/cli.py")
        for path in sorted(path for path in CURRENT_DOC_PATHS if path.is_file()):
            if path.suffix not in {".md", ".yaml", ".json"}:
                continue
            for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if not any(pattern in line for pattern in stale_patterns):
                    continue
                if path in allowed_upgrade_docs and "removed" in line.lower():
                    continue
                violations.append(f"{path.relative_to(ROOT)}:{line_number}: {line}")

        self.assertEqual(violations, [])

    def test_external_telemetry_plan_keeps_publish_reply_boundary_clear(self):
        plan = EXTERNAL_TELEMETRY_PLAN_MD.read_text(encoding="utf-8")

        self.assertIn("workflow.py                # validation command telemetry capture for workflow execution", plan)
        self.assertNotIn("publish path continues to read runtime efficiency summary", plan)


if __name__ == "__main__":
    unittest.main()
