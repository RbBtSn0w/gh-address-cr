import unittest

from tests.helpers import ROOT

CURRENT_DOC_PATHS = [
    ROOT / "README.md",
    *ROOT.joinpath("skill").rglob("*"),
    *ROOT.joinpath("plugin", "gh-address-cr").rglob("*"),
]


class CliSkillSyncArtifactTest(unittest.TestCase):
    def test_current_repo_contract_no_longer_requires_archived_docs_or_specs(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertNotIn("docs/cli-reference.md", readme)
        self.assertNotIn("docs/workflows.md", readme)
        self.assertNotIn("docs/architecture.md", readme)
        self.assertNotIn("docs/troubleshooting.md", readme)
        self.assertNotIn("docs/contracts/otel-tracing-v1.md", readme)
        self.assertNotIn("specs/012-cli-skill-sync", readme)
        self.assertNotIn("specs/015-external-agent-telemetry", readme)

    def test_current_public_docs_do_not_reintroduce_removed_skill_script_commands(self):
        violations = []
        stale_patterns = ("skill/scripts", "scripts/cli.py")
        for path in sorted(path for path in CURRENT_DOC_PATHS if path.is_file()):
            if path.suffix not in {".md", ".yaml", ".json"}:
                continue
            for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if not any(pattern in line for pattern in stale_patterns):
                    continue
                violations.append(f"{path.relative_to(ROOT)}:{line_number}: {line}")

        self.assertEqual(violations, [])

    def test_runtime_completion_contract_keeps_publish_reply_boundary_clear(self):
        completion = (ROOT / "skill" / "references" / "completion-contract.md").read_text(encoding="utf-8")
        self.assertIn("final-gate", completion)
        self.assertNotIn("publish path continues to read runtime efficiency summary", completion)


if __name__ == "__main__":
    unittest.main()
