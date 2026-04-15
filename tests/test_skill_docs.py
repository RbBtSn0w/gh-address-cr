import unittest

from tests.helpers import ROOT


SKILL_MD = ROOT / "gh-address-cr" / "SKILL.md"
README_MD = ROOT / "README.md"


class SkillDocumentationContractTest(unittest.TestCase):
    def test_skill_examples_do_not_show_bare_review_entrypoint(self):
        text = SKILL_MD.read_text(encoding="utf-8")
        self.assertNotIn("$gh-address-cr review <PR_URL>\n", text)
        self.assertIn("/gh-address-cr review <owner/repo> <pr_number> --input <path>|-", text)
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
        self.assertIn("handles both local findings and GitHub review threads in one run", text)
        self.assertIn("handles local findings only; it does not process GitHub review threads", text)
        self.assertNotIn("## Prompt Patterns", text)
        self.assertIn("README.md", text)

    def test_readme_examples_do_not_show_bare_review_entrypoint(self):
        text = README_MD.read_text(encoding="utf-8")
        self.assertNotIn("$gh-address-cr review <PR_URL>\n", text)
        self.assertIn("/gh-address-cr review <owner/repo> <pr_number> --input <path>|-", text)
        self.assertIn("$gh-address-cr review <PR_URL> --input findings.json", text)
        self.assertIn("$gh-address-cr review <PR_URL> --input -", text)

    def test_readme_matches_adapter_public_semantics(self):
        text = README_MD.read_text(encoding="utf-8")
        self.assertIn("adapter-produced findings plus PR orchestration", text)
        self.assertNotIn("adapter command prints findings JSON", text)
        self.assertIn("wrapper `--human` and `--machine` belong before `adapter`", text)
        self.assertIn("passed through to the adapter command unchanged", text)
        self.assertIn("handles both local findings and GitHub review threads in one run", text)
        self.assertIn("handles local findings only; it does not process GitHub review threads", text)

    def test_readme_documents_converter_input_contract(self):
        text = README_MD.read_text(encoding="utf-8")
        self.assertIn("does not accept arbitrary Markdown", text)
        self.assertIn("fixed `finding` block format", text)

    def test_readme_documents_machine_summary_fields(self):
        text = README_MD.read_text(encoding="utf-8")
        self.assertNotIn("The exact machine summary fields are documented in `gh-address-cr/SKILL.md`.", text)
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

    def test_readme_defers_advanced_dispatch_details_until_after_first_read_contract(self):
        text = README_MD.read_text(encoding="utf-8")
        self.assertLess(text.index("## Public Interface"), text.index("## Automatic Review Workflow"))
        self.assertLess(text.index("## Automatic Review Workflow"), text.index("Advanced producer categories:"))

    def test_readme_keeps_one_canonical_prompt_template_section(self):
        text = README_MD.read_text(encoding="utf-8")
        self.assertEqual(text.count("When `gh-address-cr` is the main entrypoint:"), 1)
        self.assertEqual(text.count("When the upstream review command must run first and `gh-address-cr` can only come second:"), 1)
        self.assertNotIn("## Prompt Templates", text)

    def test_readme_documents_executable_adapter_flag_examples(self):
        text = README_MD.read_text(encoding="utf-8")
        self.assertIn("$gh-address-cr --human adapter <owner/repo> <pr_number> <adapter_cmd...>", text)
        self.assertIn("$gh-address-cr adapter <owner/repo> <pr_number> <adapter_cmd...> --human --machine", text)
        self.assertIn("python3 gh-address-cr/scripts/cli.py --human adapter owner/repo 123 python3 tools/review_adapter.py", text)
        self.assertIn("python3 gh-address-cr/scripts/cli.py adapter owner/repo 123 python3 tools/review_adapter.py --base main --human", text)

    def test_prompt_patterns_distinguish_review_vs_findings_scope(self):
        readme_text = README_MD.read_text(encoding="utf-8")
        self.assertIn("如果你要同时处理 GitHub review threads 和 local findings，请使用 `review` 入口。", readme_text)
        self.assertIn("如果你只想接管 local findings JSON，请使用 `findings` 入口。", readme_text)
