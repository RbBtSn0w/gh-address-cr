import json
import re
import unittest

from gh_address_cr.commands.agent import build_agent_manifest
from gh_address_cr.commands.high_level import _parse_native_high_level_args
from gh_address_cr.core.reply_templates import fix_reply
from tests.helpers import ROOT

SKILL_MD = ROOT / "skill" / "SKILL.md"
README_MD = ROOT / "README.md"
DOCS_DIR = ROOT / "docs"
ARCHITECTURE_MD = README_MD
CLI_REFERENCE_MD = README_MD
COMPATIBILITY_INVENTORY_MD = README_MD
DEVELOPMENT_MD = README_MD
INSTALLATION_MD = README_MD
TROUBLESHOOTING_MD = README_MD
WORKFLOWS_MD = README_MD
AGENTS_MD = ROOT / "AGENTS.md"
CONSTITUTION_MD = ROOT / ".specify" / "memory" / "constitution.md"
HANDOFF_PY = ROOT / "src" / "gh_address_cr" / "core" / "handoff.py"
MODE_PRODUCER_MATRIX_MD = ROOT / "skill" / "references" / "mode-producer-matrix.md"
OTEL_TRACING_CONTRACT_MD = README_MD
AGENT_PROTOCOL_MD = ROOT / "skill" / "references" / "agent-protocol.md"
COMPLETION_CONTRACT_MD = ROOT / "skill" / "references" / "completion-contract.md"
FEEDBACK_MD = ROOT / "skill" / "references" / "feedback.md"
STATUS_ACTION_MAP_MD = ROOT / "skill" / "references" / "status-action-map.md"
STACKED_PR_WORKFLOW_MD = ROOT / "skill" / "references" / "stacked-pr-workflow.md"
OPENAI_HINT_YAML = ROOT / "skill" / "agents" / "openai.yaml"
RUNTIME_REQUIREMENTS_JSON = ROOT / "skill" / "runtime-requirements.json"
AGENT_FEEDBACK_ISSUE_TEMPLATE = ROOT / ".github" / "ISSUE_TEMPLATE" / "ai-agent-feedback.md"


def load_documentation_contracts():
    path = ROOT / "tests" / "fixtures" / "thin_skill_orchestration" / "documentation_contracts.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def read_repo_docs(*paths):
    return "\n".join(path.read_text(encoding="utf-8") for path in paths)


STATUS_TOKEN_PATTERN = r"[A-Z][A-Z0-9_]{3,}"


def emitted_status_tokens(source: str) -> set[str]:
    """Extract ALLCAPS tokens that plausibly appear as an emitted status/reason_code.

    Used to guard status-action-map.md against phantom entries: a documented token
    that the runtime never actually produces. Excludes the three contexts that read
    as "emitted" under a naive word-boundary scan but are not: prose in a triple-
    quoted docstring, prose in a full-line comment, and an `x or 'TOKEN'` /
    `x or "TOKEN"` read-side fallback default (a stand-in for a *missing* value, not
    something the runtime writes) -- both quote styles occur in this codebase
    (final_gate.py uses single quotes inside f-strings).
    """
    source = re.sub(r'"""[\s\S]*?"""', "", source)
    source = re.sub(r"'''[\s\S]*?'''", "", source)
    source = "\n".join(line for line in source.splitlines() if not line.strip().startswith("#"))
    source = re.sub(rf"""\bor\s+['"]({STATUS_TOKEN_PATTERN})['"]""", "", source)
    return set(re.findall(STATUS_TOKEN_PATTERN, source))


def unreferenced_protocol_codes(protocol_codes_source: str, rest_of_source: str) -> set[str]:
    """protocol_codes.py constants that are declared but never referenced anywhere else.

    protocol_codes.py's own docstring calls it "the single source of truth" for
    reason/status tokens, but declaring a constant there is not evidence the runtime
    ever emits it -- six constants (UNKNOWN_SLICE among them) are declared and never
    referenced again. Scoped to this one module: the same "declare but never use"
    pattern isn't verified for constant families defined elsewhere (e.g. FINAL_GATE_*
    in final_gate.py), where treating a bare declaration as insufficient evidence
    produced false negatives against genuinely emitted codes (PER_THREAD_EVIDENCE_REQUIRED
    is assigned to a differently-named constant and would vanish under a blanket rule).
    """
    declared = set(
        re.findall(rf"^\s*({STATUS_TOKEN_PATTERN})\s*=\s*\"\1\"\s*$", protocol_codes_source, re.M)
    )
    return declared - emitted_status_tokens(rest_of_source)


def cli_topology_section():
    text = CLI_REFERENCE_MD.read_text(encoding="utf-8")
    start = text.index("## Command Topology (ASCII)")
    end = text.index("Stable machine summary fields:", start)
    return text[start:end]


class SkillDocumentationContractTest(unittest.TestCase):
    def test_skill_frontmatter_uses_supported_keys_only(self):
        text = SKILL_MD.read_text(encoding="utf-8")
        frontmatter = text.split("---", 2)[1]
        keys = {
            match.group(1)
            for line in frontmatter.splitlines()
            if (match := re.match(r"^([a-z][a-z0-9_-]*):", line))
        }

        self.assertEqual(keys, {"name", "description"})

    def test_openai_metadata_is_a_thin_generated_interface(self):
        text = OPENAI_HINT_YAML.read_text(encoding="utf-8")
        self.assertEqual(
            text,
            'interface:\n'
            '  display_name: "GH Address CR"\n'
            '  short_description: "Resolve GitHub PR review feedback safely"\n'
            '  default_prompt: "Use $gh-address-cr to handle this pull request through the runtime CLI and verify completion with final-gate."\n',
        )

    def test_skill_cli_examples_use_runtime_command_spelling(self):
        text = SKILL_MD.read_text(encoding="utf-8")
        self.assertNotIn("/gh-address-cr", text)
        self.assertNotRegex(text, r"(?m)^\$gh-address-cr ")
        self.assertIn("Use $gh-address-cr review", text)

    def test_dispatch_matrix_matches_current_cli_intake_contract(self):
        text = MODE_PRODUCER_MATRIX_MD.read_text(encoding="utf-8")
        expected_commands = (
            "gh-address-cr address <owner/repo> <pr_number> --lean",
            "gh-address-cr findings <owner/repo> <pr_number> --input - --sync --source <producer>",
            "gh-address-cr adapter <owner/repo> <pr_number> <adapter_cmd...>",
            "gh-address-cr review <owner/repo> <pr_number> --input <path>|-",
            "gh-address-cr review-to-findings <owner/repo> <pr_number> --input - --output -",
        )
        for command in expected_commands:
            with self.subTest(command=command):
                self.assertIn(command, text)

        self.assertNotIn(" --repo ", text)
        self.assertNotIn(" --pr ", text)
        self.assertNotIn("adapter --repo", text)
        self.assertNotIn("adapter <owner/repo> <pr_number> --source", text)
        self.assertIn("`finding` code fences", text)

    def test_documented_intake_shapes_parse_as_current_cli_arguments(self):
        cases = (
            ("address", ["owner/repo", "123", "--lean"], None),
            (
                "findings",
                ["owner/repo", "123", "--input", "-", "--sync", "--source", "producer"],
                None,
            ),
            ("adapter", ["owner/repo", "123", "python3", "review.py"], ["python3", "review.py"]),
            ("review", ["owner/repo", "123", "--input", "-"], None),
        )
        for command, argv, adapter_cmd in cases:
            with self.subTest(command=command):
                parsed = _parse_native_high_level_args(command, argv)
                self.assertEqual((parsed.repo, parsed.pr_number), ("owner/repo", "123"))
                if adapter_cmd is not None:
                    self.assertEqual(parsed.adapter_cmd, adapter_cmd)

    def test_skill_root_commands_are_exposed_by_runtime_manifest(self):
        manifest_commands = set(build_agent_manifest()["public_commands"])
        skill_text = read_repo_docs(SKILL_MD, *sorted((ROOT / "skill" / "references").glob("*.md")))
        documented_commands = set(re.findall(r"`gh-address-cr ([a-z][a-z0-9-]*)(?:\s|`)", skill_text))
        documented_commands.update(
            re.findall(r"(?m)^(?:[/\\$])?gh-address-cr ([a-z][a-z0-9-]*)", skill_text)
        )

        self.assertEqual(documented_commands - manifest_commands, set())

    def test_skill_runtime_floor_covers_resolve_axis_contract(self):
        requirements = json.loads(RUNTIME_REQUIREMENTS_JSON.read_text(encoding="utf-8"))
        self.assertEqual(requirements["minimum_runtime_version"], "3.5.7")

    def test_process_otel_has_versioned_contract_and_architecture_ownership(self):
        contract = OTEL_TRACING_CONTRACT_MD.read_text(encoding="utf-8")
        architecture = ARCHITECTURE_MD.read_text(encoding="utf-8")

        for phrase in (
            "otel-tracing.v2",
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
        self.assertIn("separate from PR-scoped workflow telemetry", architecture)
        self.assertIn("Subprocess arguments are never exported", contract)
        self.assertIn("does not claim a hosted `deployment.environment.name`", contract)

    def test_gateway_profile_contract_is_reviewable_without_secrets(self):
        profile = (ROOT / "specs" / "030-otel-gateway-hardening" / "contracts" / "ingest-profile.md")
        text = profile.read_text(encoding="utf-8")

        for phrase in (
            "anonymous-client-v1",
            "trustClass: anonymous",
            "allowedSignals: [traces]",
            "maxBodyBytes",
            "Staging acceptance",
            "Production switch gate",
            "Rollback",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)
        self.assertNotIn("x-honeycomb-team", text)

    def test_handoff_module_documents_non_event_sourced_metadata_boundary(self):
        text = HANDOFF_PY.read_text(encoding="utf-8")

        self.assertIn("non-event-sourced metadata", text)
        self.assertIn("not authoritative runtime truth", text)
        self.assertIn("final-gate", text)

    def test_skill_declares_packaged_skill_root_scope(self):
        text = SKILL_MD.read_text(encoding="utf-8")
        self.assertIn("This file is part of the packaged `gh-address-cr` skill.", text)
        self.assertIn("All paths in this document are relative to the installed skill root.", text)
        self.assertIn("outside the packaged skill", text)

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
        self.assertIn("gh-address-cr review <owner/repo> <pr_number>", text)
        self.assertIn("gh-address-cr address <owner/repo> <pr_number> --lean", text)
        self.assertNotIn("gh-address-cr review <owner/repo> <pr_number> --input", text)
        self.assertIn("Use $gh-address-cr review PR #123", text)
        self.assertIn("references/mode-producer-matrix.md", text)
        self.assertIn("If `review` returns `BLOCKED`, inspect the loop request artifact,", text)
        self.assertIn("then rerun the same", text)
        self.assertIn("`review` command.", text)
        self.assertIn("Do not treat `STALE` or outdated threads as clean.", text)

    def test_skill_first_read_covers_runtime_agent_command_surface(self):
        skill_text = SKILL_MD.read_text(encoding="utf-8")
        protocol_text = AGENT_PROTOCOL_MD.read_text(encoding="utf-8")
        self.assertIn("gh-address-cr --help", skill_text)
        self.assertIn("gh-address-cr agent manifest", skill_text)
        self.assertIn("gh-address-cr agent resolve", skill_text)
        self.assertIn("gh-address-cr agent publish", skill_text)
        self.assertIn("references/agent-protocol.md", skill_text)
        for command in ("agent classify", "agent next", "agent submit", "agent evidence add", "agent leases", "agent reclaim"):
            with self.subTest(command=command):
                self.assertIn(command, protocol_text)

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
        self.assertIn("fenced\n`finding` blocks", text)
        self.assertIn("rejects plain narrative Markdown review output", text)

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
            "remediation",
            "exit_code",
        ):
            self.assertIn(f"`{field}`", combined)
        self.assertIn("Lean output keeps only", protocol_text)
        self.assertIn("agent resolve", protocol_text)
        self.assertIn("--input <batch-response.json>", protocol_text)
        self.assertIn("--why <why>", protocol_text)
        self.assertIn("--stale", protocol_text)

    def test_status_action_map_documents_only_codes_the_runtime_emits(self):
        # One-directional doc ⊆ runtime, mirroring
        # test_skill_root_commands_are_exposed_by_runtime_manifest. The reverse is not
        # assertable: agent_protocol_submission.required_response_field mints codes via
        # f"MISSING_{field.upper()}", so the emitted set is open by construction.
        # Guards against phantom entries like the former NO_WORK_AVAILABLE /
        # WAITING_FOR_ACTION, which sent agents looking for a status never produced.
        documented = set(re.findall(rf"`({STATUS_TOKEN_PATTERN})`", STATUS_ACTION_MAP_MD.read_text(encoding="utf-8")))
        src_files = sorted((ROOT / "src").rglob("*.py"))
        protocol_codes_path = ROOT / "src" / "gh_address_cr" / "core" / "protocol_codes.py"
        protocol_codes_source = protocol_codes_path.read_text(encoding="utf-8")
        other_source = "\n".join(
            path.read_text(encoding="utf-8") for path in src_files if path != protocol_codes_path
        )
        runtime_source = protocol_codes_source + "\n" + other_source

        emitted = emitted_status_tokens(runtime_source) - unreferenced_protocol_codes(
            protocol_codes_source, other_source
        )

        phantom = sorted(token for token in documented if token not in emitted)

        self.assertEqual(phantom, [], f"status-action-map.md documents codes the runtime never emits: {phantom}")

    def test_emitted_status_tokens_rejects_fallback_defaults_and_comments(self):
        # Regression for a guard that read too permissively: a plain word-boundary scan
        # counts `UNKNOWN` as emitted because of code shaped exactly like this, even
        # though the runtime never actually produces `status: "UNKNOWN"` anywhere -- the
        # `or` branch only fires when a value is already missing.
        source = (
            '# UNKNOWN is only ever a display fallback here, never a real emission.\n'
            'status = str(payload.get("status") or "UNKNOWN")\n'
            # final_gate.py uses this single-quoted shape inside f-strings.
            'print(f"reason_code={result.reason_code or \'STACK_MEMBER_BLOCKED\'}")\n'
        )

        emitted = emitted_status_tokens(source)
        self.assertNotIn("UNKNOWN", emitted)
        self.assertNotIn("STACK_MEMBER_BLOCKED", emitted)

    def test_emitted_status_tokens_rejects_docstring_prose(self):
        # Regression: workflow.py's docstring mentions FINAL_GATE_MISSING_REPLY_EVIDENCE
        # in a ".. note::"-style explanation, not as an emission. A token that appeared
        # ONLY in prose like this would incorrectly read as emitted without this strip.
        source = (
            'def f():\n'
            '    """See ``final-gate``, which reports ``TOTALLY_FAKE_DOCSTRING_ONLY_CODE``\n'
            '    even though this function never raises it."""\n'
            '    pass\n'
        )

        self.assertNotIn("TOTALLY_FAKE_DOCSTRING_ONLY_CODE", emitted_status_tokens(source))

    def test_emitted_status_tokens_still_counts_a_code_alongside_its_own_docstring(self):
        # Stripping docstrings must not blind the scan to a real emission that happens
        # to sit near documentation in the same file.
        source = (
            'def f():\n'
            '    """Raises MISSING_THREAD_ID when the thread id is absent."""\n'
            '    raise WorkflowError(reason_code="MISSING_THREAD_ID")\n'
        )

        self.assertIn("MISSING_THREAD_ID", emitted_status_tokens(source))

    def test_emitted_status_tokens_still_counts_real_emission_shapes(self):
        source = (
            'FINAL_GATE_UNRESOLVED_REMOTE_THREADS = "FINAL_GATE_UNRESOLVED_REMOTE_THREADS"\n'
            'raise WorkflowError(status="BLOCKED", reason_code="MISSING_THREAD_ID", ...)\n'
            '"reason_code": protocol_codes.NO_ELIGIBLE_ITEM,\n'
        )

        emitted = emitted_status_tokens(source)
        for token in ("FINAL_GATE_UNRESOLVED_REMOTE_THREADS", "BLOCKED", "MISSING_THREAD_ID", "NO_ELIGIBLE_ITEM"):
            with self.subTest(token=token):
                self.assertIn(token, emitted)

    def test_unreferenced_protocol_codes_excludes_declared_but_unused_constants(self):
        # Regression: UNKNOWN_SLICE is declared in protocol_codes.py and never
        # referenced anywhere else. A plain word-boundary scan over all of src/ counts
        # its own declaration line as "emitted", which would let a genuinely phantom
        # `UNKNOWN_SLICE` status slip past the doc guard undetected.
        protocol_codes_source = 'UNKNOWN_SLICE = "UNKNOWN_SLICE"\nNO_ELIGIBLE_ITEM = "NO_ELIGIBLE_ITEM"\n'
        rest_of_source = 'raise WorkflowError(reason_code=protocol_codes.NO_ELIGIBLE_ITEM)\n'

        dead = unreferenced_protocol_codes(protocol_codes_source, rest_of_source)

        self.assertIn("UNKNOWN_SLICE", dead)
        self.assertNotIn("NO_ELIGIBLE_ITEM", dead)

    def test_unreferenced_protocol_codes_does_not_penalize_differently_named_aliases(self):
        # A constant defined elsewhere under a different variable name than its own
        # value (FIX_ALL_PER_THREAD_EVIDENCE_REASON = "PER_THREAD_EVIDENCE_REQUIRED" in
        # workflow_matching.py) must still count as emitted -- this guard only tightens
        # protocol_codes.py's own self-referential declarations, not every constant in
        # the codebase.
        rest_of_source = 'FIX_ALL_PER_THREAD_EVIDENCE_REASON = "PER_THREAD_EVIDENCE_REQUIRED"\n'

        self.assertIn("PER_THREAD_EVIDENCE_REQUIRED", emitted_status_tokens(rest_of_source))

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
            "resolve <item_id> --disposition trivial",
            "resolve --input <batch-response.json>",
            "resolve --why <why>",
            "resolve --stale",
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
            "agent submit or agent resolve --input <batch-response.json>",
            "accepted evidence",
            "agent publish (GitHub thread side effects only)",
            "final-gate",
            "completion_summary_line",
            "runtime-owned leases + request_id values",
            "agent resolve --input <batch-response.json> validates lease ownership and request context",
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
            "logic_validation_signals",
        ):
            with self.subTest(term=term):
                self.assertIn(term, combined)

    def test_skill_uses_references_for_advanced_dispatch_details(self):
        text = SKILL_MD.read_text(encoding="utf-8")
        self.assertNotIn("Advanced dispatch model:", text)
        self.assertIn("references/mode-producer-matrix.md", text)
        self.assertIn("references/agent-protocol.md", text)
        self.assertIn("references/completion-contract.md", text)
        self.assertIn("references/feedback.md", text)
        self.assertIn("references/status-action-map.md", text)
        self.assertIn("public main entrypoint", text)
        self.assertIn("Reference Surface", text)
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
        self.assertIn("Runtime entrypoints: `gh-address-cr` and `python3 -m gh_address_cr`", text)
        self.assertNotIn("scripts/cli.py", text)
        self.assertNotIn("Compatibility shim", text)
        self.assertIn("Use the runtime help and manifest as the authoritative command inventory", text)

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
        cli_text = CLI_REFERENCE_MD.read_text(encoding="utf-8")
        workflow_text = WORKFLOWS_MD.read_text(encoding="utf-8")
        protocol_text = AGENT_PROTOCOL_MD.read_text(encoding="utf-8")
        skill_text = SKILL_MD.read_text(encoding="utf-8")
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

    def test_fixed_reply_template_stays_evidence_focused_without_generic_offer(self):
        rendered = fix_reply(
            "P2",
            ["abc123", "src/example.py", "python3 -m unittest", "passed", "Targeted stale-thread fix."],
            summary="Updated stale thread handling.",
        )

        self.assertNotIn("If you want", rendered)
        self.assertNotIn("I can also", rendered)

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
        for path in (MODE_PRODUCER_MATRIX_MD,):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("skill/scripts/", text, msg=str(path))
            self.assertNotIn("skill/references/", text, msg=str(path))
            self.assertIn("gh-address-cr", text, msg=str(path))
            self.assertNotIn("python3 scripts/cli.py", text, msg=str(path))
        hint_text = OPENAI_HINT_YAML.read_text(encoding="utf-8")
        self.assertNotIn("skill/scripts/", hint_text)
        self.assertNotIn("skill/references/", hint_text)
        self.assertIn("$gh-address-cr", hint_text)

    def test_referenced_skill_owned_docs_exist(self):
        for path in (
            MODE_PRODUCER_MATRIX_MD,
            AGENT_PROTOCOL_MD,
            COMPLETION_CONTRACT_MD,
            FEEDBACK_MD,
            STATUS_ACTION_MAP_MD,
            OPENAI_HINT_YAML,
        ):
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
        self.assertIn("review", text)
        self.assertIn("final-gate", text)
        self.assertIn("`final-gate`", text)
        self.assertIn("gh-address-cr review", text)

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
        self.assertIn("exported by the runtime through its configured Honeycomb", skill_text)
        self.assertIn("fail-open", skill_text)
        self.assertIn("DISABLE_TELEMETRY=1", skill_text)
        self.assertIn("DO_NOT_TRACK=1", skill_text)

    def test_readme_matches_adapter_public_semantics(self):
        text = read_repo_docs(README_MD, CLI_REFERENCE_MD)
        self.assertIn("adapter", text)
        self.assertNotIn("adapter command prints findings JSON", text)
        self.assertIn("`--human`", text)
        self.assertIn("`--machine`", text)
        self.assertIn("GitHub review threads", text)
        self.assertIn("local findings", text)

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
        self.assertIn("agent resolve --stale", text)

    def test_status_action_map_documents_agent_friction_recovery(self):
        text = (ROOT / "skill" / "references" / "status-action-map.md").read_text(encoding="utf-8")
        self.assertIn("commands", text)
        self.assertIn("gh-address-cr address <owner/repo> <pr_number> --lean", text)
        self.assertIn("agent resolve --input <batch-response.json>", text)
        self.assertIn("--why", text)
        self.assertIn("--stale", text)
        self.assertIn("NO_ACTIVE_PR", text)
        self.assertIn("AMBIGUOUS_ACTIVE_PR", text)

    def test_readme_defers_advanced_dispatch_details_until_after_first_read_contract(self):
        cli_text = CLI_REFERENCE_MD.read_text(encoding="utf-8")
        workflow_text = WORKFLOWS_MD.read_text(encoding="utf-8")
        self.assertIn("Workflow Patterns", cli_text)
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
        self.assertIn("external review producer", cli_text)
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
        feedback_text = FEEDBACK_MD.read_text(encoding="utf-8")
        self.assertIn("`RbBtSn0w/gh-address-cr`", feedback_text)
        self.assertIn("`--using-repo` and `--using-pr`", feedback_text)

    def test_readme_moves_input_and_producer_routing_to_advanced_section(self):
        readme_text = read_repo_docs(README_MD, CLI_REFERENCE_MD, WORKFLOWS_MD)
        self.assertIn("## Advanced / Developer Integration", readme_text)
        self.assertIn("producer", readme_text)
        self.assertIn("`--source`", readme_text)
        self.assertIn("STALE", readme_text)

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
        self.assertIn("Telemetry degradation", skill_text)
        self.assertIn("Coverage labels are `complete`, `partial`, `runtime-only`, and `unavailable`", protocol_text)
        self.assertNotIn("telemetry summary", readme_text)
        self.assertIn("Clarify, defer, and reject responses require `reply_markdown`.", protocol_text)
        self.assertNotIn("Clarify, defer, and reject responses require `reply_markdown` and validation evidence.", protocol_text)
        self.assertNotIn("GH_ADDRESS_CR_HOST_TELEMETRY_INPUT", openai_text)

    def test_stacked_pr_layer_and_management_boundaries_are_published(self):
        skill_text = SKILL_MD.read_text(encoding="utf-8")
        protocol_text = AGENT_PROTOCOL_MD.read_text(encoding="utf-8")
        completion_text = COMPLETION_CONTRACT_MD.read_text(encoding="utf-8")
        status_text = STATUS_ACTION_MAP_MD.read_text(encoding="utf-8")

        self.assertIn("selected PR layer", skill_text)
        self.assertIn("GitHub's `gh stack`", skill_text)
        self.assertIn("revision_binding", protocol_text)
        self.assertIn("already-terminal GitHub thread or local finding", protocol_text)
        self.assertIn("item-scoped `agent evidence add`", status_text)
        self.assertIn("completion_scope: \"stack_segment\"", completion_text)
        self.assertIn("FINAL_GATE_STALE_REVISION_EVIDENCE", status_text)
        self.assertTrue(STACKED_PR_WORKFLOW_MD.is_file())
        workflow_text = STACKED_PR_WORKFLOW_MD.read_text(encoding="utf-8")
        normalized_workflow = " ".join(workflow_text.split())
        self.assertIn("owning branch", normalized_workflow)
        self.assertIn("Do not implement a lower-layer fix on an upper branch", normalized_workflow)
        self.assertIn("separately authorized stack-management workflow", normalized_workflow)
        self.assertIn("Discard the old ActionRequest", normalized_workflow)
