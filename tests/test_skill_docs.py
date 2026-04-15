import unittest

from tests.helpers import ROOT


SKILL_MD = ROOT / "gh-address-cr" / "SKILL.md"


class SkillDocumentationContractTest(unittest.TestCase):
    def test_skill_examples_do_not_show_bare_review_entrypoint(self):
        text = SKILL_MD.read_text(encoding="utf-8")
        self.assertNotIn("$gh-address-cr review <PR_URL>\n", text)
        self.assertIn("$gh-address-cr review <PR_URL> --input findings.json", text)
        self.assertIn("$gh-address-cr review <PR_URL> --input -", text)

    def test_skill_documents_converter_input_contract(self):
        text = SKILL_MD.read_text(encoding="utf-8")
        self.assertIn("does not accept arbitrary Markdown", text)
        self.assertIn("fixed `finding` block format", text)
        self.assertIn("This converter rejects plain narrative Markdown review output.", text)

    def test_skill_documents_machine_summary_fields(self):
        text = SKILL_MD.read_text(encoding="utf-8")
        for field in (
            "status",
            "repo",
            "pr_number",
            "item_id",
            "item_kind",
            "counts",
            "artifact_path",
            "reason_code",
            "waiting_on",
            "next_action",
            "exit_code",
        ):
            self.assertIn(f"`{field}`", text)

    def test_skill_uses_references_for_advanced_dispatch_details(self):
        text = SKILL_MD.read_text(encoding="utf-8")
        self.assertNotIn("Advanced dispatch model:", text)
        self.assertIn("references/mode-producer-matrix.md", text)
        self.assertIn("adapter-produced findings plus PR orchestration", text)
