import json
import unittest

from gh_address_cr.core.reply_templates import clarify_reply, defer_reply, fix_reply
from tests.helpers import ROOT

SKILL_MD = ROOT / "skill" / "SKILL.md"
README_MD = ROOT / "README.md"
DOCS_DIR = ROOT / "docs"
ARCHITECTURE_MD = DOCS_DIR / "architecture.md"
CLI_REFERENCE_MD = DOCS_DIR / "cli-reference.md"
COMPATIBILITY_INVENTORY_MD = DOCS_DIR / "compatibility-inventory.md"
DEVELOPMENT_MD = DOCS_DIR / "development.md"
INSTALLATION_MD = DOCS_DIR / "installation.md"
TROUBLESHOOTING_MD = DOCS_DIR / "troubleshooting.md"
WORKFLOWS_MD = DOCS_DIR / "workflows.md"
AGENTS_MD = ROOT / "AGENTS.md"
CONSTITUTION_MD = ROOT / ".specify" / "memory" / "constitution.md"
HANDOFF_PY = ROOT / "src" / "gh_address_cr" / "core" / "handoff.py"
MODE_PRODUCER_MATRIX_MD = ROOT / "skill" / "references" / "mode-producer-matrix.md"
LOCAL_REVIEW_ADAPTER_MD = ROOT / "skill" / "references" / "local-review-adapter.md"
OTEL_WORKER_BETTER_STACK_MD = ROOT / "skill" / "references" / "otel-worker-better-stack.md"
OTEL_TRACING_CONTRACT_MD = ROOT / "docs" / "contracts" / "otel-tracing-v1.md"
AGENT_PROTOCOL_MD = ROOT / "skill" / "references" / "agent-protocol.md"
COMPLETION_CONTRACT_MD = ROOT / "skill" / "references" / "completion-contract.md"
FEEDBACK_MD = ROOT / "skill" / "references" / "feedback.md"
STATUS_ACTION_MAP_MD = ROOT / "skill" / "references" / "status-action-map.md"
OTEL_WORKER_MJS = ROOT / "skill" / "references" / "otel-worker-better-stack" / "worker.mjs"
OTEL_WORKER_WRANGLER = ROOT / "skill" / "references" / "otel-worker-better-stack" / "wrangler.example.jsonc"
OPENAI_HINT_YAML = ROOT / "skill" / "agents" / "openai.yaml"
AGENT_FEEDBACK_ISSUE_TEMPLATE = ROOT / ".github" / "ISSUE_TEMPLATE" / "ai-agent-feedback.md"
REPLY_TEMPLATES_DIR = ROOT / "skill" / "assets" / "reply-templates"


def load_documentation_contracts():
    path = ROOT / "tests" / "fixtures" / "thin_skill_orchestration" / "documentation_contracts.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def read_repo_docs(*paths):
    return "\n".join(path.read_text(encoding="utf-8") for path in paths)


def cli_topology_section():
    text = CLI_REFERENCE_MD.read_text(encoding="utf-8")
    start = text.index("## Command Topology (ASCII)")
    end = text.index("Stable machine summary fields:", start)
    return text[start:end]


class SkillDocumentationContractTest(unittest.TestCase):
    def test_process_otel_has_versioned_contract_and_architecture_ownership(self):
        contract = OTEL_TRACING_CONTRACT_MD.read_text(encoding="utf-8")
        architecture = ARCHITECTURE_MD.read_text(encoding="utf-8")

        for phrase in (
            "otel-tracing.v1",
            "Process-level observability owner",
            "External inputs",
            "Span projection",
            "Export policy",
            "Side-effect boundary",
            "Artifact truth boundary",
            "Recovery and replay",
            "separate from PR-scoped workflow telemetry",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, contract)
        self.assertIn("docs/contracts/otel-tracing-v1.md", architecture)
        self.assertIn("separate from PR-scoped workflow telemetry", architecture)

    def test_handoff_module_documents_non_event_sourced_metadata_boundary(self):
        text = HANDOFF_PY.read_text(encoding="utf-8")

        self.assertIn("non-event-sourced metadata", text)
        self.assertIn("not authoritative runtime truth", text)
        self.assertIn("final-gate", text)

    def test_skill_declares_packaged_skill_root_scope(self):
        text = SKILL_MD.read_text(encoding="utf-8")
        self.assertIn("This file is part of the packaged `gh-address-cr` skill.", text)
        self.assertIn("All paths in this document are relative to the installed skill root.", text)
        self.assertIn("outside the packaged skill payload", text)

    def test_skill_is_concise_first_read_entrypoint(self):
        text = SKILL_MD.read_text(encoding="utf-8")
        word_count = len(text.split())
        self.assertGreater(word_count, 100)
        self.assertIn("## Primary Commands", text)
        self.assertIn("## Common Mistakes", text)
        self.assertNotIn("## Usage", text)
        self.assertNotIn("## Multi-Agent Protocol", text)
        self.assertNotIn("## Agent Feedback", text)

    def test_skill_description_has_trigger_keywords_without_workflow_summary(self):
        text = SKILL_MD.read_text(encoding="utf-8")
        self.assertIn("description: Use when", text)
        self.assertIn("unresolved review threads", text)
        self.assertIn("pending reviews", text)
        self.assertIn("stale/outdated threads", text)
        self.assertNotIn("description: Use when", text.split("---", 2)[2])

    def test_skill_examples_use_review_as_main_entrypoint_without_required_input(self):
        text = SKILL_MD.read_text(encoding="utf-8")
        self.assertIn("/gh-address-cr review <owner/repo> <pr_number> [--auto-simple]", text)
        self.assertIn("/gh-address-cr address <owner/repo> <pr_number> [--lean|--summary]", text)
        self.assertIn("/gh-address-cr threads <owner/repo> <pr_number> [--lean|--summary]", text)
        self.assertNotIn("/gh-address-cr review <owner/repo> <pr_number> --input <path>|-", text)
        self.assertIn("$gh-address-cr review <PR_URL>", text)
        self.assertNotIn("$gh-address-cr review <PR_URL> --input findings.json", text)
        self.assertIn("$gh-address-cr findings <PR_URL> --input - --sync --source <producer>", text)
        self.assertNotIn("$gh-address-cr findings <PR_URL> --input - --sync\n", text)
        self.assertIn("If `review` returns `BLOCKED`, inspect the loop request artifact,", text)
        self.assertIn("then rerun the same `review` command.", text)
        self.assertIn("Outdated / `STALE` GitHub threads are still unresolved until explicitly handled.", text)

    def test_skill_first_read_covers_runtime_agent_command_surface(self):
        text = SKILL_MD.read_text(encoding="utf-8")
        for command in (
            "/gh-address-cr review-to-findings <owner/repo> <pr_number> --input <finding-blocks.md>|-",
            "/gh-address-cr doctor [<owner/repo> [<pr_number>]]",
            "/gh-address-cr final-gate <owner/repo> <pr_number>",
            "/gh-address-cr submit-action <action-request.json>",
            "/gh-address-cr submit-feedback --category <category>",
            "/gh-address-cr agent manifest",
            "/gh-address-cr agent classify <owner/repo> <pr_number> <item_id>",
            "/gh-address-cr agent next <owner/repo> <pr_number>",
            "/gh-address-cr agent submit <owner/repo> <pr_number>",
            "/gh-address-cr agent resolve <owner/repo> <pr_number> <item_id>",
            "/gh-address-cr agent resolve <owner/repo> <pr_number> --batch --input <batch-response.json>",
            "/gh-address-cr agent resolve <owner/repo> <pr_number> --commit <sha> --files <paths> --validation <cmd=passed@<ms>ms> --stale --match-files",
            "/gh-address-cr agent evidence add <owner/repo> <pr_number>",
            "/gh-address-cr agent publish <owner/repo> <pr_number>",
            "/gh-address-cr agent leases <owner/repo> <pr_number>",
            "/gh-address-cr agent reclaim <owner/repo> <pr_number>",
            "/gh-address-cr agent orchestrate <start|step|status|stop|resume|submit|autopilot>",
        ):
            with self.subTest(command=command):
                self.assertIn(command, text)

    def test_skill_guides_cr_reply_comment_tasks_through_runtime_submission(self):
        skill_text = SKILL_MD.read_text(encoding="utf-8")
        status_text = STATUS_ACTION_MAP_MD.read_text(encoding="utf-8")
        hint_text = OPENAI_HINT_YAML.read_text(encoding="utf-8")
        combined = "\n".join([skill_text, status_text, hint_text])

        self.assertIn("GitHub review comment reply tasks", combined)
        self.assertIn("A reply draft is not a submitted task", combined)
        self.assertIn("`gh-address-cr agent resolve`", combined)
        self.assertIn("`gh-address-cr agent publish`", combined)
        self.assertIn("per-thread summary/why", combined)
        self.assertIn("homogeneous repeated", combined)

    def test_skill_documents_converter_input_contract(self):
        text = SKILL_MD.read_text(encoding="utf-8")
        self.assertIn("does not accept arbitrary Markdown", text)
        self.assertIn("fixed `finding` block format", text)
        self.assertIn("This converter rejects plain narrative Markdown review output.", text)

    def test_skill_documents_machine_summary_fields(self):
        text = SKILL_MD.read_text(encoding="utf-8")
        protocol_text = AGENT_PROTOCOL_MD.read_text(encoding="utf-8")
        combined = text + "\n" + protocol_text
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
            "commands",
            "exit_code",
        ):
            self.assertIn(f"`{field}`", combined)
        self.assertIn("Lean output keeps only", protocol_text)
        self.assertIn("agent resolve", protocol_text)
        self.assertIn("--input <batch-response.json>", protocol_text)
        self.assertIn("--homogeneous-reason <why>", protocol_text)
        self.assertIn("--stale --match-files", protocol_text)

    def test_cli_reference_ascii_topology_covers_public_command_surface(self):
        section = cli_topology_section()
        self.assertTrue(section.isascii())
        for command in (
            "active-pr",
            "review",
            "review [--auto-simple]",
            "address [--lean|--summary]",
            "threads [--lean|--summary]",
            "findings --input <json|->",
            "adapter <adapter_cmd...>",
            "doctor",
            "command-session --input <operations.json|->",
            "final-gate",
            "review-to-findings --input <finding-blocks.md|->",
            "submit-feedback",
            "submit-action <action-request.json>",
            "version / --version",
            "--machine",
            "--human",
        ):
            with self.subTest(command=command):
                self.assertIn(command, section)

    def test_cli_reference_ascii_topology_covers_agent_command_surface(self):
        section = cli_topology_section()
        for command in (
            "manifest",
            "classify",
            "next --role <role>",
            "next --batch",
            "submit",
            "resolve <item_id>",
            "resolve --trivial",
            "resolve --batch",
            "resolve --homogeneous-reason",
            "resolve --stale --match-files",
            "evidence add",
            "evidence list",
            "publish",
            "leases",
            "reclaim",
            "orchestrate start/status/step/resume/stop/submit/autopilot",
        ):
            with self.subTest(command=command):
                self.assertIn(command, section)

    def test_cli_reference_ascii_topology_covers_upstream_downstream_verification(self):
        section = cli_topology_section()
        for edge in (
            "WAITING_FOR_EXTERNAL_REVIEW",
            "WAITING_FOR_SIMPLE_ADDRESS",
            "PER_THREAD_EVIDENCE_REQUIRED -> next --batch",
            "producer output",
            "session items",
            "agent classify",
            "ActionResponse or BatchActionResponse",
            "agent submit or agent resolve --batch",
            "accepted evidence",
            "agent publish (GitHub thread side effects only)",
            "final-gate",
            "completion_summary_line",
            "runtime-owned leases + request_id values",
            "agent resolve --batch validates lease ownership and request context",
        ):
            with self.subTest(edge=edge):
                self.assertIn(edge, section)

    def test_skill_documents_runtime_complexity_additive_fields(self):
        skill_text = SKILL_MD.read_text(encoding="utf-8")
        protocol_text = AGENT_PROTOCOL_MD.read_text(encoding="utf-8")
        status_text = STATUS_ACTION_MAP_MD.read_text(encoding="utf-8")
        completion_text = COMPLETION_CONTRACT_MD.read_text(encoding="utf-8")
        combined = "\n".join([skill_text, protocol_text, status_text, completion_text])

        for term in (
            "handling_boundary",
            "lease_recovery",
            "TELEMETRY_OVERHEAD_EXCEEDED",
            "logic_validation_signals",
        ):
            with self.subTest(term=term):
                self.assertIn(term, combined)

    def test_skill_uses_references_for_advanced_dispatch_details(self):
        text = SKILL_MD.read_text(encoding="utf-8")
        self.assertNotIn("Advanced dispatch model:", text)
        self.assertIn("references/mode-producer-matrix.md", text)
        self.assertIn("references/otel-worker-better-stack.md", text)
        self.assertIn("references/agent-protocol.md", text)
        self.assertIn("references/completion-contract.md", text)
        self.assertIn("references/feedback.md", text)
        self.assertIn("references/status-action-map.md", text)
        self.assertIn("public main entrypoint", text)
        self.assertIn("reference surface", text)
        self.assertNotIn("## Prompt Patterns", text)
        self.assertNotIn("README.md", text)

    def test_skill_paths_are_relative_to_skill_root(self):
        text = SKILL_MD.read_text(encoding="utf-8")
        self.assertNotIn("skill/scripts/", text)
        self.assertNotIn("skill/references/", text)
        self.assertIn("gh-address-cr review <owner/repo> <pr_number>", text)
        self.assertIn("gh-address-cr final-gate <owner/repo> <pr_number>", text)
        self.assertNotIn("README.md", text)

    def test_skill_uses_runtime_cli_as_sole_execution_surface(self):
        text = SKILL_MD.read_text(encoding="utf-8")
        self.assertIn("Runtime public entrypoint: `gh-address-cr`", text)
        self.assertNotIn("scripts/cli.py", text)
        self.assertNotIn("Compatibility shim", text)
        self.assertIn("Start from the runtime dispatcher:\n  - `gh-address-cr review", text)

    def test_skill_completion_contract_does_not_require_current_run_summary(self):
        text = SKILL_MD.read_text(encoding="utf-8")
        completion_text = COMPLETION_CONTRACT_MD.read_text(encoding="utf-8")
        combined = text + "\n" + completion_text
        self.assertNotIn("readable current-run handling summary", text)
        self.assertNotIn("GitHub threads: total 2; new in this run 0; unresolved 0; handled in this run 0", text)
        self.assertNotIn("prefer the human-readable `Current Run Snapshot` block", text)
        self.assertIn("audit summary path + sha256", combined)

    def test_skill_completion_contract_requires_completion_summary_line(self):
        skill_text = SKILL_MD.read_text(encoding="utf-8")
        completion_text = COMPLETION_CONTRACT_MD.read_text(encoding="utf-8")
        status_text = STATUS_ACTION_MAP_MD.read_text(encoding="utf-8")
        hint_text = OPENAI_HINT_YAML.read_text(encoding="utf-8")
        combined = "\n".join([skill_text, completion_text, status_text, hint_text])

        self.assertIn("completion_summary_line", combined)
        self.assertIn("PR Completion Summary Guidance", combined)
        self.assertIn("first bracketed line", combined)
        self.assertIn("[gh-address-cr: PASSED | threads:", completion_text)
        self.assertIn("telemetry coverage, confidence, source scope, observed duration, slowest operation, and issue summary", combined)
        self.assertIn("abnormal coverage, diagnostics, success-rate drops, or inefficiency flags", combined)

    def test_skill_identifies_as_thin_adapter(self):
        text = SKILL_MD.read_text(encoding="utf-8")
        self.assertIn("thin adapter", text.lower())
        self.assertIn("adapter check-runtime", text)

    def test_openai_hint_identifies_as_thin_adapter(self):
        text = OPENAI_HINT_YAML.read_text(encoding="utf-8")
        self.assertIn("thin adapter", text.lower())
        self.assertNotIn("direct side effect", text.lower())

    def test_openai_hint_uses_runtime_cli_as_sole_execution_surface(self):
        text = OPENAI_HINT_YAML.read_text(encoding="utf-8")
        self.assertIn("Start with `gh-address-cr review <owner/repo> <pr_number>`", text)
        self.assertIn("run `gh-address-cr final-gate ...`", text)
        self.assertNotIn("scripts/cli.py", text)

    def test_openai_hint_does_not_require_natural_language_current_run_counts(self):
        text = OPENAI_HINT_YAML.read_text(encoding="utf-8")
        self.assertNotIn("summarize the current-run queue counts in natural language", text)
        self.assertNotIn("prefer the human-readable `Current Run Snapshot` block", text)

    def test_skill_documents_agent_feedback_command_and_trigger(self):
        text = SKILL_MD.read_text(encoding="utf-8")
        feedback_text = FEEDBACK_MD.read_text(encoding="utf-8")
        self.assertIn("references/feedback.md", text)
        self.assertIn("gh-address-cr submit-feedback", feedback_text)
        self.assertIn("When the skill itself blocks progress", feedback_text)
        self.assertIn("`RbBtSn0w/gh-address-cr`", feedback_text)
        self.assertIn("`--using-repo` and `--using-pr`", feedback_text)
        self.assertIn("Do not file feedback issues for normal PR findings", feedback_text)
        self.assertIn("--artifact <loop-request.json>", feedback_text)
        self.assertNotIn("--artifact /tmp/loop-request.json", feedback_text)

    def test_feedback_documents_auto_trigger_on_skill_exceptions_only(self):
        feedback_text = FEEDBACK_MD.read_text(encoding="utf-8")
        skill_text = SKILL_MD.read_text(encoding="utf-8")
        # The automatic trigger is documented and scoped to genuine skill exceptions.
        self.assertIn("Automatic feedback on skill exceptions", feedback_text)
        self.assertIn("--category tooling-bug", feedback_text)
        # Allowlist: crash, or a reason_code ending in _ERROR.
        self.assertIn("ends in `_ERROR`", feedback_text)
        self.assertIn("SYSTEM_ERROR", feedback_text)
        # Denylist keeps the scope to exceptions only (must not auto-file these).
        self.assertIn("`*_REJECTED`", feedback_text)
        self.assertIn("`WAITING_*`", feedback_text)
        # SKILL.md surfaces the auto-trigger without duplicating the full rule.
        self.assertIn("expected automatic step", skill_text)

    def test_skill_documents_structured_fix_reply_contract_for_github_threads(self):
        matrix_text = MODE_PRODUCER_MATRIX_MD.read_text(encoding="utf-8")
        cli_text = CLI_REFERENCE_MD.read_text(encoding="utf-8")
        workflow_text = WORKFLOWS_MD.read_text(encoding="utf-8")
        protocol_text = AGENT_PROTOCOL_MD.read_text(encoding="utf-8")
        skill_text = SKILL_MD.read_text(encoding="utf-8")
        self.assertIn("for GitHub thread `fix`: `fix_reply`", matrix_text)
        self.assertIn("`summary`", matrix_text)
        self.assertIn("`commit_hash`", matrix_text)
        self.assertIn("`files`", matrix_text)
        self.assertIn("for GitHub thread `clarify` or `defer`: `reply_markdown`", matrix_text)
        self.assertIn("for GitHub thread `fix`: `fix_reply`", workflow_text)
        self.assertIn("`summary`", workflow_text)
        self.assertIn("for GitHub thread `clarify` or `defer`: `reply_markdown`", workflow_text)
        self.assertIn("`fix_reply` **must be a JSON object**", protocol_text)
        self.assertIn("`commit_hash`", protocol_text)
        self.assertIn("`files`", protocol_text)
        self.assertIn("`test_command`", protocol_text)
        self.assertIn("`test_result`", protocol_text)
        self.assertIn("MISSING_PUBLISH_REPLY", protocol_text)
        self.assertIn("Review signal:", cli_text)
        self.assertIn("Review signal:", protocol_text)
        self.assertNotIn("Published fix replies should surface that signal as `Reviewer priority:`", skill_text)
        self.assertNotIn("shown in published fix replies as `Reviewer priority:`", protocol_text)

    def test_skill_reply_template_assets_match_runtime_renderer_contract(self):
        fix_cases = {
            "fixed.md": (
                None,
                [
                    "<commit_hash>",
                    "<file_path_1>,<file_path_2>",
                    "<test_command>",
                    "`<pass/fail + key output>`",
                    "`<technical reasoning tied to the comment>`",
                ],
                "`<brief fix summary>`",
            ),
            "fixed-p1.md": (
                "P1",
                [
                    "<commit_hash>",
                    "<file_path>",
                    "<targeted_test_command>",
                    "`<pass/fail + key signal>`",
                    "`<root cause and correction>`",
                ],
                "`<critical-path fix>`",
            ),
            "fixed-p2.md": (
                "P2",
                [
                    "<commit_hash>",
                    "<file_path>",
                    "<test_command>",
                    "`<pass/fail + key signal>`",
                    "`<behavioral correction>`",
                ],
                "`<fix summary>`",
            ),
            "fixed-p3.md": (
                "P3",
                [
                    "<commit_hash>",
                    "<file_path>",
                    "<test_command>",
                    "`<pass/fail + key signal>`",
                    "`<clarity/consistency improvement>`",
                ],
                "`<small/non-breaking improvement>`",
            ),
        }
        for filename, (severity, payload, summary) in fix_cases.items():
            with self.subTest(filename=filename):
                self.assertEqual((REPLY_TEMPLATES_DIR / filename).read_text(encoding="utf-8"), fix_reply(severity, payload, summary=summary))

        self.assertEqual(
            (REPLY_TEMPLATES_DIR / "clarify.md").read_text(encoding="utf-8"),
            clarify_reply(["`<detailed explanation of why the current logic is correct or answers the question>`"]),
        )
        self.assertEqual(
            (REPLY_TEMPLATES_DIR / "defer.md").read_text(encoding="utf-8"),
            defer_reply(["`<reason>`"]),
        )

    def test_fixed_reply_template_stays_evidence_focused_without_generic_offer(self):
        rendered = fix_reply(
            "P2",
            ["abc123", "src/example.py", "python3 -m unittest", "passed", "Targeted stale-thread fix."],
            summary="Updated stale thread handling.",
        )

        self.assertNotIn("If you want", rendered)
        self.assertNotIn("I can also", rendered)

    def test_openai_hint_requires_feedback_issue_when_skill_usage_is_blocked(self):
        text = OPENAI_HINT_YAML.read_text(encoding="utf-8")
        self.assertIn("run `gh-address-cr submit-feedback`", text)
        self.assertIn("`RbBtSn0w/gh-address-cr`", text)
        self.assertIn("contradictory instructions", text)
        self.assertIn("missing automation", text)
        self.assertIn("WAITING_FOR_EXTERNAL_REVIEW", text)
        self.assertIn("expected wait states", text)
        self.assertIn("Do not include usernames, emails, tokens, machine names, or absolute local paths", text)
        self.assertIn("Always provide `--using-repo` and `--using-pr`", text)

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
        for path in (MODE_PRODUCER_MATRIX_MD, LOCAL_REVIEW_ADAPTER_MD):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("skill/scripts/", text, msg=str(path))
            self.assertNotIn("skill/references/", text, msg=str(path))
            self.assertIn("gh-address-cr", text, msg=str(path))
            self.assertNotIn("python3 scripts/cli.py", text, msg=str(path))
        hint_text = OPENAI_HINT_YAML.read_text(encoding="utf-8")
        self.assertNotIn("skill/scripts/", hint_text)
        self.assertNotIn("skill/references/", hint_text)
        self.assertIn("gh-address-cr review", hint_text)

    def test_referenced_skill_owned_docs_exist(self):
        for path in (
            MODE_PRODUCER_MATRIX_MD,
            LOCAL_REVIEW_ADAPTER_MD,
            AGENT_PROTOCOL_MD,
            COMPLETION_CONTRACT_MD,
            FEEDBACK_MD,
            STATUS_ACTION_MAP_MD,
            OPENAI_HINT_YAML,
        ):
            self.assertTrue(path.exists(), msg=str(path))
        for path in (OTEL_WORKER_BETTER_STACK_MD, OTEL_WORKER_MJS, OTEL_WORKER_WRANGLER):
            self.assertTrue(path.exists(), msg=str(path))
        self.assertTrue(AGENT_FEEDBACK_ISSUE_TEMPLATE.exists(), msg=str(AGENT_FEEDBACK_ISSUE_TEMPLATE))

    def test_compatibility_inventory_documents_preserved_and_removed_surfaces(self):
        text = COMPATIBILITY_INVENTORY_MD.read_text(encoding="utf-8")
        self.assertIn("Preserved Public Contracts", text)
        self.assertIn("Unsupported historical root commands", text)
        self.assertIn("submit-action", text)
        self.assertIn("Removed Or Unsupported Surfaces", text)
        self.assertIn("legacy_scripts", text)
        self.assertIn("Internal Naming Rule", text)

    def test_readme_examples_use_single_review_main_entrypoint(self):
        text = read_repo_docs(README_MD, CLI_REFERENCE_MD)
        self.assertIn("Primary commands:", text)
        self.assertIn("Advanced/internal integration entrypoints:", text)
        self.assertNotIn("with these agent-safe public entrypoints:", text)
        self.assertIn("/gh-address-cr review <owner/repo> <pr_number>", text)
        self.assertIn("`final-gate`", text)
        self.assertNotIn("/gh-address-cr review <owner/repo> <pr_number> --input <path>|-", text)
        self.assertIn("$gh-address-cr review <PR_URL>", text)

    def test_readme_documents_repo_root_vs_skill_root_layout(self):
        text = read_repo_docs(README_MD, ARCHITECTURE_MD)
        self.assertIn("Published skill payload: the entire `skill/` directory", text)
        self.assertIn("Repo-level verification harness: `tests/`", text)
        self.assertIn(
            "If a rule or instruction must ship with the installed skill, it must live inside `skill/`", text
        )

    def test_agents_documents_skill_directory_without_renaming_product_identity(self):
        text = AGENTS_MD.read_text(encoding="utf-8")
        self.assertIn("The released skill payload is the entire `skill/` directory", text)
        self.assertIn("product/runtime identity remains", text)
        self.assertIn("`gh-address-cr`: the Python package, console entrypoint, repository URL", text)
        self.assertIn("with `--skill skill`", text)

    def test_project_governance_documents_architecture_preflight_kernel(self):
        text = read_repo_docs(CONSTITUTION_MD, AGENTS_MD, ARCHITECTURE_MD)
        for phrase in (
            "First-Principles Runtime Kernel",
            "Architecture Preflight",
            "external facts -> events -> projections -> policy -> command plan/outbox",
            "artifact truth boundary",
            "self-referential completion",
            "stop expanding conditionals",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

    def test_readme_and_skill_document_otlp_worker_tracing(self):
        readme_text = read_repo_docs(README_MD, DEVELOPMENT_MD)
        skill_text = SKILL_MD.read_text(encoding="utf-8")
        self.assertIn("Cloudflare Worker as the security relay", readme_text)
        self.assertIn("telemetry-gateway.hamiltonsnow.workers.dev/v1/traces", readme_text)
        self.assertIn("DISABLE_TELEMETRY=1", readme_text)
        self.assertIn("DO_NOT_TRACK=1", readme_text)
        self.assertNotIn("replace-with-worker-shared-secret", readme_text)
        self.assertIn("references/otel-worker-better-stack.md", skill_text)

    def test_readme_matches_adapter_public_semantics(self):
        text = read_repo_docs(README_MD, CLI_REFERENCE_MD)
        self.assertIn("adapter-produced findings plus PR orchestration", text)
        self.assertNotIn("adapter command prints findings JSON", text)
        self.assertIn("wrapper `--human` and `--machine` belong before `adapter`", text)
        self.assertIn("passed through to the adapter command unchanged", text)
        self.assertIn("handles both local findings and GitHub review threads in one run", text)
        self.assertIn("handles local findings only; it does not process GitHub review threads", text)

    def test_readme_documents_converter_input_contract(self):
        text = read_repo_docs(README_MD, CLI_REFERENCE_MD)
        self.assertIn("does not accept arbitrary Markdown", text)
        self.assertIn("fixed `finding` block format", text)

    def test_readme_documents_machine_summary_fields(self):
        text = read_repo_docs(README_MD, CLI_REFERENCE_MD, ARCHITECTURE_MD, TROUBLESHOOTING_MD)
        self.assertNotIn("The exact machine summary fields are documented in `skill/SKILL.md`.", text)
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
            "commands",
            "exit_code",
        ):
            self.assertIn(f"`{field}`", text)
        self.assertIn("current-login pending review count", text)
        self.assertIn("Use `--lean` or `--summary`", text)
        self.assertIn("agent resolve --stale --match-files", text)

    def test_status_action_map_documents_agent_friction_recovery(self):
        text = (ROOT / "skill" / "references" / "status-action-map.md").read_text(encoding="utf-8")
        self.assertIn("commands", text)
        self.assertIn("gh-address-cr address <owner/repo> <pr_number> --lean", text)
        self.assertIn("agent resolve --batch", text)
        self.assertIn("--homogeneous-reason", text)
        self.assertIn("--stale --match-files", text)
        self.assertIn("NO_ACTIVE_PR", text)
        self.assertIn("AMBIGUOUS_ACTIVE_PR", text)

    def test_readme_defers_advanced_dispatch_details_until_after_first_read_contract(self):
        cli_text = CLI_REFERENCE_MD.read_text(encoding="utf-8")
        workflow_text = WORKFLOWS_MD.read_text(encoding="utf-8")
        self.assertIn("docs/workflows.md", cli_text)
        self.assertNotIn("## Automatic Review Workflow", cli_text)
        self.assertLess(workflow_text.index("## Automatic Review Workflow"), workflow_text.index("Advanced producer categories:"))

    def test_readme_keeps_one_canonical_prompt_template_section(self):
        text = WORKFLOWS_MD.read_text(encoding="utf-8")
        self.assertEqual(text.count("Minimal user prompt:"), 1)
        self.assertEqual(text.count("Ready-to-use prompt variants:"), 1)
        self.assertNotIn("## Prompt Templates", text)

    def test_readme_documents_executable_adapter_flag_examples(self):
        text = CLI_REFERENCE_MD.read_text(encoding="utf-8")
        self.assertIn("$gh-address-cr --human adapter <owner/repo> <pr_number> <adapter_cmd...>", text)
        self.assertIn("$gh-address-cr adapter <owner/repo> <pr_number> <adapter_cmd...> --human --machine", text)
        self.assertIn(
            "gh-address-cr --human adapter owner/repo 123 python3 tools/review_adapter.py", text
        )
        self.assertIn(
            "gh-address-cr adapter owner/repo 123 python3 tools/review_adapter.py --base main --human",
            text,
        )

    def test_readme_uses_runtime_cli_as_primary_entrypoint(self):
        text = read_repo_docs(README_MD, WORKFLOWS_MD, ARCHITECTURE_MD)
        self.assertIn("`gh-address-cr` is the preferred and stable automation entrypoint", text)
        self.assertNotIn("`python3 skill/scripts/cli.py` is the only automation entrypoint", text)
        self.assertNotIn("`python3 skill/scripts/cli.py` remains the stable automation surface", text)
        self.assertNotIn("`cli.py` is the preferred Python entrypoint for automation", text)

    def test_active_docs_do_not_reintroduce_unsupported_legacy_commands(self):
        text = read_repo_docs(
            README_MD,
            AGENTS_MD,
            ARCHITECTURE_MD,
            CLI_REFERENCE_MD,
            DEVELOPMENT_MD,
            INSTALLATION_MD,
            TROUBLESHOOTING_MD,
            WORKFLOWS_MD,
            SKILL_MD,
            COMPLETION_CONTRACT_MD,
            FEEDBACK_MD,
            LOCAL_REVIEW_ADAPTER_MD,
            MODE_PRODUCER_MATRIX_MD,
            STATUS_ACTION_MAP_MD,
        )
        unsupported_commands = [
            "audit-report",
            "batch-resolve",
            "clean-state",
            "code-review-adapter",
            "control-plane",
            "cr-loop",
            "generate-reply",
            "ingest-findings",
            "list-threads",
            "mark-handled",
            "post-reply",
            "prepare-code-review",
            "publish-finding",
            "resolve-thread",
            "run-local-review",
            "run-once",
            "session-engine",
        ]
        for command in unsupported_commands:
            with self.subTest(command=command):
                self.assertNotIn(command, text)

    def test_readme_documents_external_review_handoff_contract(self):
        cli_text = CLI_REFERENCE_MD.read_text(encoding="utf-8")
        workflow_text = WORKFLOWS_MD.read_text(encoding="utf-8")
        self.assertIn("any external review producer may satisfy the handoff", cli_text)
        self.assertIn("producer-request.md", cli_text)
        self.assertIn("incoming-findings.json", cli_text)
        self.assertIn("incoming-findings.md", cli_text)
        self.assertIn("WAITING_FOR_EXTERNAL_REVIEW", cli_text)
        self.assertIn("source-scoped producer result", cli_text)
        self.assertIn("`[]` is a valid explicit producer result", cli_text)
        self.assertIn("如果你自己就是外部 review producer", workflow_text)
        self.assertIn("不要只输出普通 Markdown 审查报告", workflow_text)
        self.assertIn("Ready-to-use prompt variants:", workflow_text)
        self.assertIn("Short generic:", workflow_text)
        self.assertIn("Explicit `$code-review` producer:", workflow_text)
        self.assertIn("Any external review producer:", workflow_text)

    def test_readme_documents_feedback_target_repo_and_source_fields(self):
        readme_text = DEVELOPMENT_MD.read_text(encoding="utf-8")
        self.assertIn("`RbBtSn0w/gh-address-cr`", readme_text)
        self.assertIn("`--using-repo` and `--using-pr`", readme_text)

    def test_readme_moves_input_and_producer_routing_to_advanced_section(self):
        readme_text = read_repo_docs(README_MD, CLI_REFERENCE_MD, WORKFLOWS_MD)
        self.assertIn("## Advanced / Developer Integration", readme_text)
        self.assertIn(
            "The public user flow above does not require manual `--input`, producer selection, or mode routing.",
            readme_text,
        )
        self.assertIn("For explicit automation or repository-root invocation, the main command is:", readme_text)
        self.assertIn("`findings --sync` requires an explicit `--source`", readme_text)
        self.assertIn(
            "outdated / `STALE` GitHub threads still count as unresolved until explicitly handled", readme_text
        )

    def test_completion_summary_final_gate_evidence(self):
        completion_text = COMPLETION_CONTRACT_MD.read_text(encoding="utf-8")
        readme_text = README_MD.read_text(encoding="utf-8")
        cli_text = CLI_REFERENCE_MD.read_text(encoding="utf-8")
        combined = "\n".join([completion_text, readme_text, cli_text])
        self.assertIn("`gh-address-cr final-gate <owner/repo> <pr_number>` command invocation", completion_text)
        self.assertNotIn("`final_gate` command used", completion_text)
        self.assertIn("`Verified: 0 Unresolved Threads found`", completion_text)
        self.assertIn("`Verified: 0 Pending Reviews found`", completion_text)
        self.assertIn("unresolved GitHub threads = 0", completion_text)
        self.assertIn("session blocking items = 0", completion_text)
        self.assertIn("telemetry coverage label", combined)
        self.assertIn("efficiency report path", combined)
        self.assertIn("runtime-only", combined)
        self.assertIn("completion_summary_line", cli_text)
        self.assertIn("completion_summary_line", readme_text)
        self.assertIn("completion_summary", cli_text)
        self.assertIn("compact metrics line", readme_text)

    def test_skill_documents_runtime_telemetry_summary_contract(self):
        skill_text = SKILL_MD.read_text(encoding="utf-8")
        protocol_text = AGENT_PROTOCOL_MD.read_text(encoding="utf-8")
        openai_text = OPENAI_HINT_YAML.read_text(encoding="utf-8")
        readme_text = README_MD.read_text(encoding="utf-8")

        self.assertIn("complete", skill_text)
        self.assertIn("partial", skill_text)
        self.assertIn("runtime-only", skill_text)
        self.assertIn("unavailable", skill_text)
        self.assertIn("runtime telemetry", skill_text)
        self.assertIn("Coverage labels are `complete`, `partial`, `runtime-only`, and `unavailable`", protocol_text)
        self.assertNotIn("telemetry summary", readme_text)
        self.assertIn("Clarify, defer, and reject responses require `reply_markdown`.", protocol_text)
        self.assertNotIn("Clarify, defer, and reject responses require `reply_markdown` and validation evidence.", protocol_text)
        self.assertNotIn("GH_ADDRESS_CR_HOST_TELEMETRY_INPUT", openai_text)
