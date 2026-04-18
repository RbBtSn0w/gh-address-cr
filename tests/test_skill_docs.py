import unittest

from tests.helpers import ROOT


SKILL_MD = ROOT / "gh-address-cr" / "SKILL.md"
README_MD = ROOT / "README.md"
MODE_PRODUCER_MATRIX_MD = ROOT / "gh-address-cr" / "references" / "mode-producer-matrix.md"
LOCAL_REVIEW_ADAPTER_MD = ROOT / "gh-address-cr" / "references" / "local-review-adapter.md"
OPENAI_HINT_YAML = ROOT / "gh-address-cr" / "agents" / "openai.yaml"
AGENT_FEEDBACK_ISSUE_TEMPLATE = ROOT / ".github" / "ISSUE_TEMPLATE" / "ai-agent-feedback.md"


class SkillDocumentationContractTest(unittest.TestCase):
    def test_skill_declares_packaged_skill_root_scope(self):
        text = SKILL_MD.read_text(encoding="utf-8")
        self.assertIn("This file is part of the packaged `gh-address-cr` skill.", text)
        self.assertIn("All paths in this document are relative to the installed skill root.", text)
        self.assertIn("outside the packaged skill payload", text)

    def test_skill_examples_use_review_as_main_entrypoint_without_required_input(self):
        text = SKILL_MD.read_text(encoding="utf-8")
        self.assertIn("/gh-address-cr review <owner/repo> <pr_number>", text)
        self.assertNotIn("/gh-address-cr review <owner/repo> <pr_number> --input <path>|-", text)
        self.assertIn("$gh-address-cr review <PR_URL>", text)
        self.assertNotIn("$gh-address-cr review <PR_URL> --input findings.json", text)
        self.assertIn("If `review` returns `BLOCKED`, inspect the loop request artifact,", text)
        self.assertIn("then rerun the same `review` command.", text)
        self.assertIn("Outdated / `STALE` GitHub threads are still unresolved until explicitly handled.", text)

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

    def test_skill_completion_contract_does_not_require_current_run_summary(self):
        text = SKILL_MD.read_text(encoding="utf-8")
        self.assertNotIn("readable current-run handling summary", text)
        self.assertNotIn("GitHub threads: total 2; new in this run 0; unresolved 0; handled in this run 0", text)
        self.assertNotIn("prefer the human-readable `Current Run Snapshot` block", text)

    def test_openai_hint_does_not_require_natural_language_current_run_counts(self):
        text = OPENAI_HINT_YAML.read_text(encoding="utf-8")
        self.assertNotIn("summarize the current-run queue counts in natural language", text)
        self.assertNotIn("prefer the human-readable `Current Run Snapshot` block", text)

    def test_skill_documents_agent_feedback_command_and_trigger(self):
        text = SKILL_MD.read_text(encoding="utf-8")
        self.assertIn("python3 scripts/submit_feedback.py", text)
        self.assertIn("When the skill itself blocks progress", text)
        self.assertIn("Do not file feedback issues for normal PR findings", text)
        self.assertNotIn("- when the skill itself blocks progress", text)

    def test_skill_documents_structured_fix_reply_contract_for_github_threads(self):
        skill_text = SKILL_MD.read_text(encoding="utf-8")
        readme_text = README_MD.read_text(encoding="utf-8")
        self.assertIn("for GitHub thread `fix`: `fix_reply`", skill_text)
        self.assertIn("`commit_hash`", skill_text)
        self.assertIn("`files`", skill_text)
        self.assertIn("for GitHub thread `clarify` or `defer`: `reply_markdown`", skill_text)
        self.assertIn("for GitHub thread `fix`: `fix_reply`", readme_text)
        self.assertIn("for GitHub thread `clarify` or `defer`: `reply_markdown`", readme_text)

    def test_openai_hint_requires_feedback_issue_when_skill_usage_is_blocked(self):
        text = OPENAI_HINT_YAML.read_text(encoding="utf-8")
        self.assertIn("run `python3 scripts/submit_feedback.py`", text)
        self.assertIn("contradictory instructions", text)
        self.assertIn("missing automation", text)
        self.assertIn("WAITING_FOR_EXTERNAL_REVIEW", text)
        self.assertIn("expected wait states", text)
        self.assertIn("Do not include usernames, emails, tokens, machine names, or absolute local paths", text)

    def test_repo_issue_template_documents_ai_agent_feedback_fields(self):
        text = AGENT_FEEDBACK_ISSUE_TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("name: AI Agent Feedback", text)
        self.assertIn("## Summary", text)
        self.assertIn("## Category", text)
        self.assertIn("## Expected Workflow", text)
        self.assertIn("## Actual Behavior", text)
        self.assertIn("## Reproduction Context", text)
        self.assertIn("## Technical Diagnostics", text)
        self.assertIn("## Additional Notes", text)
        self.assertIn("Do not include usernames, emails, tokens, machine names, or absolute local paths", text)

    def test_skill_owned_references_and_agent_hints_use_skill_relative_paths(self):
        for path in (MODE_PRODUCER_MATRIX_MD, LOCAL_REVIEW_ADAPTER_MD, OPENAI_HINT_YAML):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("gh-address-cr/scripts/", text, msg=str(path))
            self.assertNotIn("gh-address-cr/references/", text, msg=str(path))
            self.assertIn("scripts/cli.py", text, msg=str(path))

    def test_referenced_skill_owned_docs_exist(self):
        for path in (MODE_PRODUCER_MATRIX_MD, LOCAL_REVIEW_ADAPTER_MD, OPENAI_HINT_YAML):
            self.assertTrue(path.exists(), msg=str(path))
        self.assertTrue(AGENT_FEEDBACK_ISSUE_TEMPLATE.exists(), msg=str(AGENT_FEEDBACK_ISSUE_TEMPLATE))

    def test_readme_examples_use_single_review_main_entrypoint(self):
        text = README_MD.read_text(encoding="utf-8")
        self.assertIn("one public main entrypoint", text)
        self.assertIn("Advanced/internal integration entrypoints:", text)
        self.assertNotIn("with these agent-safe public entrypoints:", text)
        self.assertIn("/gh-address-cr review <owner/repo> <pr_number>", text)
        self.assertNotIn("/gh-address-cr review <owner/repo> <pr_number> --input <path>|-", text)
        self.assertIn("$gh-address-cr review <PR_URL>", text)

    def test_readme_documents_repo_root_vs_skill_root_layout(self):
        text = README_MD.read_text(encoding="utf-8")
        self.assertIn("Published skill payload: the entire `gh-address-cr/` directory", text)
        self.assertIn("Repo-level verification harness: `tests/`", text)
        self.assertIn("If a rule or instruction must ship with the installed skill, it must live inside `gh-address-cr/`", text)

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
        self.assertIn("current-login pending review count", text)

    def test_readme_defers_advanced_dispatch_details_until_after_first_read_contract(self):
        text = README_MD.read_text(encoding="utf-8")
        self.assertLess(text.index("## Public Interface"), text.index("## Automatic Review Workflow"))
        self.assertLess(text.index("## Automatic Review Workflow"), text.index("Advanced producer categories:"))

    def test_readme_keeps_one_canonical_prompt_template_section(self):
        text = README_MD.read_text(encoding="utf-8")
        self.assertEqual(text.count("Minimal user prompt:"), 1)
        self.assertEqual(text.count("Ready-to-use prompt variants:"), 1)
        self.assertNotIn("## Prompt Templates", text)

    def test_readme_documents_executable_adapter_flag_examples(self):
        text = README_MD.read_text(encoding="utf-8")
        self.assertIn("$gh-address-cr --human adapter <owner/repo> <pr_number> <adapter_cmd...>", text)
        self.assertIn("$gh-address-cr adapter <owner/repo> <pr_number> <adapter_cmd...> --human --machine", text)
        self.assertIn("python3 gh-address-cr/scripts/cli.py --human adapter owner/repo 123 python3 tools/review_adapter.py", text)
        self.assertIn("python3 gh-address-cr/scripts/cli.py adapter owner/repo 123 python3 tools/review_adapter.py --base main --human", text)

    def test_readme_documents_external_review_handoff_contract(self):
        readme_text = README_MD.read_text(encoding="utf-8")
        self.assertIn("any external review producer may satisfy the handoff", readme_text)
        self.assertIn("producer-request.md", readme_text)
        self.assertIn("incoming-findings.json", readme_text)
        self.assertIn("incoming-findings.md", readme_text)
        self.assertIn("WAITING_FOR_EXTERNAL_REVIEW", readme_text)
        self.assertIn("如果你自己就是外部 review producer", readme_text)
        self.assertIn("不要只输出普通 Markdown 审查报告", readme_text)
        self.assertIn("Ready-to-use prompt variants:", readme_text)
        self.assertIn("Short generic:", readme_text)
        self.assertIn("Explicit `$code-review` producer:", readme_text)
        self.assertIn("Any external review producer:", readme_text)

    def test_readme_moves_input_and_producer_routing_to_advanced_section(self):
        readme_text = README_MD.read_text(encoding="utf-8")
        self.assertIn("## Advanced / Developer Integration", readme_text)
        self.assertIn(
            "The public user flow above does not require manual `--input`, producer selection, or mode routing.",
            readme_text,
        )
        self.assertIn("For explicit automation or repository-root invocation, the main command is:", readme_text)
        self.assertIn("`findings --sync` requires an explicit `--source`", readme_text)
        self.assertIn("outdated / `STALE` GitHub threads still count as unresolved until explicitly handled", readme_text)
