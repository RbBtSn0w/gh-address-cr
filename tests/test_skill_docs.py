import unittest

from tests.helpers import ROOT


SKILL_MD = ROOT / "gh-address-cr" / "SKILL.md"
README_MD = ROOT / "README.md"
MODE_PRODUCER_MATRIX_MD = ROOT / "gh-address-cr" / "references" / "mode-producer-matrix.md"
LOCAL_REVIEW_ADAPTER_MD = ROOT / "gh-address-cr" / "references" / "local-review-adapter.md"
OPENAI_HINT_YAML = ROOT / "gh-address-cr" / "agents" / "openai.yaml"


class SkillDocumentationContractTest(unittest.TestCase):
    def test_skill_examples_use_review_as_main_entrypoint_without_required_input(self):
        text = SKILL_MD.read_text(encoding="utf-8")
        self.assertIn("/gh-address-cr review <owner/repo> <pr_number>", text)
        self.assertNotIn("/gh-address-cr review <owner/repo> <pr_number> --input <path>|-", text)
        self.assertIn("$gh-address-cr review <PR_URL>", text)
        self.assertNotIn("$gh-address-cr review <PR_URL> --input findings.json", text)

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
        self.assertIn("public main entrypoint", text)
        self.assertIn("advanced/internal", text)
        self.assertNotIn("## Prompt Patterns", text)
        self.assertNotIn("README.md", text)

    def test_skill_paths_are_relative_to_skill_root(self):
        text = SKILL_MD.read_text(encoding="utf-8")
        self.assertNotIn("gh-address-cr/scripts/", text)
        self.assertNotIn("gh-address-cr/references/", text)
        self.assertIn("python3 scripts/cli.py review <owner/repo> <pr_number>", text)
        self.assertIn("python3 scripts/cli.py final-gate <owner/repo> <pr_number>", text)
        self.assertNotIn("README.md", text)

    def test_skill_owned_references_and_agent_hints_use_skill_relative_paths(self):
        for path in (MODE_PRODUCER_MATRIX_MD, LOCAL_REVIEW_ADAPTER_MD, OPENAI_HINT_YAML):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("gh-address-cr/scripts/", text, msg=str(path))
            self.assertNotIn("gh-address-cr/references/", text, msg=str(path))
            self.assertIn("scripts/cli.py", text, msg=str(path))

    def test_readme_examples_use_single_review_main_entrypoint(self):
        text = README_MD.read_text(encoding="utf-8")
        self.assertIn("/gh-address-cr review <owner/repo> <pr_number>", text)
        self.assertNotIn("/gh-address-cr review <owner/repo> <pr_number> --input <path>|-", text)
        self.assertIn("$gh-address-cr review <PR_URL>", text)

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
        self.assertEqual(text.count("使用 $gh-address-cr 完整处理这个 PR：<PR_URL>"), 1)
        self.assertNotIn("## Prompt Templates", text)

    def test_readme_documents_executable_adapter_flag_examples(self):
        text = README_MD.read_text(encoding="utf-8")
        self.assertIn("$gh-address-cr --human adapter <owner/repo> <pr_number> <adapter_cmd...>", text)
        self.assertIn("$gh-address-cr adapter <owner/repo> <pr_number> <adapter_cmd...> --human --machine", text)
        self.assertIn("python3 gh-address-cr/scripts/cli.py --human adapter owner/repo 123 python3 tools/review_adapter.py", text)
        self.assertIn("python3 gh-address-cr/scripts/cli.py adapter owner/repo 123 python3 tools/review_adapter.py --base main --human", text)

    def test_readme_documents_external_review_handoff_contract(self):
        readme_text = README_MD.read_text(encoding="utf-8")
        self.assertIn("任意外部 review producer", readme_text)
        self.assertIn("producer-request.md", readme_text)
        self.assertIn("incoming-findings.json", readme_text)
        self.assertIn("incoming-findings.md", readme_text)
        self.assertIn("WAITING_FOR_EXTERNAL_REVIEW", readme_text)
