import json
import sys
import unittest

from tests.helpers import ROOT, SRC_ROOT


sys.path.insert(0, str(SRC_ROOT))

from gh_address_cr.agent.manifests import (  # noqa: E402
    ManifestValidationError,
    is_manifest_eligible,
    load_capability_manifest,
    validate_capability_manifest,
)
from gh_address_cr.agent.requests import (  # noqa: E402
    RequestValidationError,
    build_action_request,
    reject_request_without_classification,
    validate_action_request,
)
from gh_address_cr.agent.responses import (  # noqa: E402
    ResponseValidationError,
    validate_action_response,
    validate_response_for_request,
)
from gh_address_cr.agent.roles import AgentRole  # noqa: E402
from gh_address_cr.core.models import (  # noqa: E402
    ActionRequest,
    CapabilityManifest,
    ClaimLease,
    EvidenceRecord,
    ReviewSession,
    WorkItem,
)


FIXTURES_DIR = ROOT / "tests" / "fixtures" / "action_protocol"


class ActionProtocolTestCase(unittest.TestCase):
    def work_item(self, **overrides):
        payload = {
            "item_id": "github-thread:abc",
            "item_kind": "github_thread",
            "source": "github",
            "title": "Missing validation",
            "body": "The input is not checked before use.",
            "path": "src/example.py",
            "line": 42,
            "allowed_actions": ["fix", "clarify", "defer", "reject"],
            "classification_evidence": {
                "event_type": "classification_recorded",
                "classification": "fix",
                "record_id": "ev_classified",
            },
        }
        payload.update(overrides)
        return WorkItem.from_dict(payload)

    def manifest(self, **overrides):
        payload = {
            "schema_version": "1.0",
            "agent_id": "codex-fixer-1",
            "roles": ["fixer", "verifier"],
            "actions": ["fix", "clarify", "defer", "reject", "verify"],
            "input_formats": ["action_request.v1"],
            "output_formats": ["action_response.v1"],
            "protocol_versions": ["1.0"],
            "constraints": {"max_parallel_claims": 2},
        }
        payload.update(overrides)
        return CapabilityManifest.from_dict(payload)

    def request_payload(self, **overrides):
        payload = {
            "schema_version": "1.0",
            "request_id": "req_123",
            "session_id": "session_123",
            "lease_id": "lease_123",
            "agent_role": "fixer",
            "item": self.work_item().to_dict(),
            "allowed_actions": ["fix", "clarify", "defer", "reject"],
            "required_evidence": ["note", "files", "validation_commands"],
            "repository_context": {"repo": "octo/example", "pr_number": "42"},
            "forbidden_actions": ["post_github_reply", "resolve_github_thread"],
            "resume_command": "python3 -m gh_address_cr agent submit octo/example 42 --input response.json",
        }
        payload.update(overrides)
        return payload

    def response_payload(self, resolution="fix", **overrides):
        payload = {
            "schema_version": "1.0",
            "request_id": "req_123",
            "lease_id": "lease_123",
            "agent_id": "codex-fixer-1",
            "resolution": resolution,
            "note": "Fixed input validation and verified with unit tests.",
            "files": ["src/example.py", "tests/test_example.py"],
            "validation_commands": [
                {
                    "command": "python3 -m unittest tests.test_example",
                    "result": "passed",
                    "summary": "1 test passed",
                }
            ],
            "fix_reply": {
                "summary": "Fixed input validation.",
                "commit_hash": "abc123",
                "files": ["src/example.py", "tests/test_example.py"],
            },
        }
        if resolution in {"clarify", "defer", "reject"}:
            payload.pop("files")
            payload.pop("fix_reply")
            payload["reply_markdown"] = "This is the terminal handling rationale."
        payload.update(overrides)
        return payload


class ActionRequestSchemaTests(ActionProtocolTestCase):
    def test_action_request_rejects_missing_required_fields(self):
        required_fields = {
            "request_id",
            "session_id",
            "lease_id",
            "agent_role",
            "item",
            "allowed_actions",
            "required_evidence",
        }

        for field in sorted(required_fields):
            with self.subTest(field=field):
                payload = self.request_payload()
                payload.pop(field)
                with self.assertRaises(RequestValidationError) as caught:
                    validate_action_request(payload)
                self.assertEqual(caught.exception.code, f"missing_{field}")

    def test_action_request_rejects_item_without_item_id(self):
        payload = self.request_payload()
        payload["item"].pop("item_id")

        with self.assertRaises(RequestValidationError) as caught:
            validate_action_request(payload)

        self.assertEqual(caught.exception.code, "missing_item_id")

    def test_action_request_rejects_unknown_role(self):
        payload = self.request_payload(agent_role="commenter")

        with self.assertRaises(RequestValidationError) as caught:
            validate_action_request(payload)

        self.assertEqual(caught.exception.code, "unsupported_agent_role")

    def test_action_request_requires_non_empty_allowed_actions_and_required_evidence(self):
        for field in ("allowed_actions", "required_evidence"):
            with self.subTest(field=field):
                payload = self.request_payload(**{field: []})
                with self.assertRaises(RequestValidationError) as caught:
                    validate_action_request(payload)
                self.assertEqual(caught.exception.code, f"empty_{field}")

    def test_build_action_request_for_pr_thread_includes_required_forbidden_actions(self):
        request = build_action_request(
            request_id="req_thread",
            session_id="session_123",
            lease_id="lease_thread",
            agent_role=AgentRole.FIXER,
            item=self.work_item(item_id="github-thread:abc", item_kind="github_thread"),
            allowed_actions=["fix", "clarify", "defer", "reject"],
            required_evidence=["note", "files", "validation_commands", "fix_reply"],
            repository_context={"repo": "octo/example", "pr_number": "42"},
            resume_command="python3 -m gh_address_cr agent submit octo/example 42 --input response.json",
            manifest=self.manifest(),
            active_claims_for_agent=1,
        )

        self.assertEqual(request.item.item_id, "github-thread:abc")
        self.assertEqual(request.agent_role, AgentRole.FIXER)
        self.assertIn("post_github_reply", request.forbidden_actions)
        self.assertIn("resolve_github_thread", request.forbidden_actions)
        self.assertIn("fix_reply", request.required_evidence)

    def test_build_action_request_for_local_finding_keeps_single_normalized_item(self):
        request = build_action_request(
            request_id="req_local",
            session_id="session_123",
            lease_id="lease_local",
            agent_role="triage",
            item=self.work_item(item_id="local:finding-1", item_kind="local_finding", source="code-review"),
            allowed_actions=["clarify", "defer", "reject"],
            required_evidence=["note", "reply_markdown"],
            repository_context={"repo": "octo/example", "pr_number": "42"},
            resume_command="python3 -m gh_address_cr agent submit octo/example 42 --input response.json",
            manifest=self.manifest(roles=["triage"], actions=["clarify", "defer", "reject"]),
        )

        self.assertEqual(request.item.item_id, "local:finding-1")
        self.assertEqual(request.item.item_kind, "local_finding")
        self.assertEqual(request.allowed_actions, ("clarify", "defer", "reject"))

    def test_build_action_request_rejects_ineligible_role(self):
        with self.assertRaises(RequestValidationError) as caught:
            build_action_request(
                request_id="req_bad_role",
                session_id="session_123",
                lease_id="lease_123",
                agent_role="fixer",
                item=self.work_item(),
                allowed_actions=["fix"],
                required_evidence=["note", "files", "validation_commands"],
                repository_context={"repo": "octo/example", "pr_number": "42"},
                resume_command="python3 -m gh_address_cr agent submit octo/example 42 --input response.json",
                manifest=self.manifest(roles=["triage"], actions=["fix"]),
            )

        self.assertEqual(caught.exception.code, "manifest_role_not_declared")


class ActionResponseSchemaTests(ActionProtocolTestCase):
    def test_fix_response_requires_changed_files_validation_summary_and_lease(self):
        response = validate_action_response(self.response_payload("fix"))

        self.assertEqual(response.resolution, "fix")
        self.assertEqual(response.lease_id, "lease_123")
        self.assertEqual(response.files, ("src/example.py", "tests/test_example.py"))
        self.assertEqual(response.validation_commands[0]["result"], "passed")
        self.assertEqual(response.validation_commands[0]["summary"], "1 test passed")
        self.assertEqual(response.fix_reply["summary"], "Fixed input validation.")

    def test_fix_response_missing_evidence_has_machine_readable_error_codes(self):
        cases = {
            "files": "missing_files",
            "validation_commands": "missing_validation_commands",
            "fix_reply": "missing_fix_reply",
            "lease_id": "missing_lease_id",
        }
        for field, code in cases.items():
            with self.subTest(field=field):
                payload = self.response_payload("fix")
                payload.pop(field)
                with self.assertRaises(ResponseValidationError) as caught:
                    validate_action_response(payload, item_kind="github_thread")
                self.assertEqual(caught.exception.code, code)

    def test_clarify_defer_reject_require_reply_markdown_and_validation_evidence(self):
        for resolution in ("clarify", "defer", "reject"):
            with self.subTest(resolution=resolution):
                response = validate_action_response(self.response_payload(resolution))
                self.assertEqual(response.resolution, resolution)
                self.assertIn("terminal handling rationale", response.reply_markdown)
                self.assertEqual(response.validation_commands[0]["result"], "passed")

    def test_terminal_response_missing_reply_markdown_is_rejected_by_resolution(self):
        for resolution in ("clarify", "defer", "reject"):
            with self.subTest(resolution=resolution):
                payload = self.response_payload(resolution)
                payload.pop("reply_markdown")
                with self.assertRaises(ResponseValidationError) as caught:
                    validate_action_response(payload)
                self.assertEqual(caught.exception.code, f"missing_{resolution}_reply_markdown")

    def test_response_rejects_direct_github_side_effect_claims(self):
        payload = self.response_payload("fix", github_side_effects=["posted_reply"])

        with self.assertRaises(ResponseValidationError) as caught:
            validate_action_response(payload)

        self.assertEqual(caught.exception.code, "direct_github_side_effect_claimed")


class CapabilityManifestTests(ActionProtocolTestCase):
    def test_manifest_declares_role_action_formats_and_protocol_version(self):
        manifest = validate_capability_manifest(self.manifest().to_dict())

        self.assertTrue(is_manifest_eligible(manifest, "fixer", "fix", "action_request.v1", "1.0", 1))
        self.assertTrue(is_manifest_eligible(manifest, AgentRole.VERIFIER, "verify", "action_request.v1", "1.0", 1))
        self.assertFalse(is_manifest_eligible(manifest, "triage", "fix", "action_request.v1", "1.0", 1))
        self.assertFalse(is_manifest_eligible(manifest, "fixer", "publish", "action_request.v1", "1.0", 1))
        self.assertFalse(is_manifest_eligible(manifest, "fixer", "fix", "legacy_request", "1.0", 1))
        self.assertFalse(is_manifest_eligible(manifest, "fixer", "fix", "action_request.v1", "2.0", 1))
        self.assertFalse(is_manifest_eligible(manifest, "fixer", "fix", "action_request.v1", "1.0", 2))

    def test_manifest_rejects_missing_or_malformed_mutating_work_capabilities(self):
        for field in ("agent_id", "roles", "actions", "input_formats", "output_formats", "protocol_versions"):
            with self.subTest(field=field):
                payload = self.manifest().to_dict()
                payload.pop(field)
                with self.assertRaises(ManifestValidationError) as caught:
                    validate_capability_manifest(payload)
                self.assertEqual(caught.exception.code, f"missing_{field}")

    def test_load_capability_manifest_from_json_file(self):
        manifest = load_capability_manifest(FIXTURES_DIR / "codex_fixer_manifest.json")

        self.assertEqual(manifest.agent_id, "codex-fixer-1")
        self.assertIn(AgentRole.FIXER, manifest.roles)
        self.assertIn("action_response.v1", manifest.output_formats)


class PreFixClassificationGateTests(ActionProtocolTestCase):
    def test_fixer_request_without_classification_is_rejected_and_appends_evidence(self):
        session = ReviewSession(session_id="session_123", repo="octo/example", pr_number="42")
        item = self.work_item(classification_evidence=None)

        with self.assertRaises(RequestValidationError) as caught:
            build_action_request(
                request_id="req_unclassified",
                session_id=session.session_id,
                lease_id="lease_unclassified",
                agent_role="fixer",
                item=item,
                allowed_actions=["fix"],
                required_evidence=["note", "files", "validation_commands"],
                repository_context={"repo": "octo/example", "pr_number": "42"},
                resume_command="python3 -m gh_address_cr agent submit octo/example 42 --input response.json",
                manifest=self.manifest(),
                evidence_sink=session.append_evidence,
            )

        self.assertEqual(caught.exception.code, "missing_classification_evidence")
        self.assertEqual(session.evidence[-1].event_type, "request_rejected")
        self.assertEqual(session.evidence[-1].payload["reason_code"], "missing_classification_evidence")
        self.assertEqual(session.leases, {})

    def test_response_with_code_modifications_without_classification_is_rejected_and_appends_evidence(self):
        session = ReviewSession(session_id="session_123", repo="octo/example", pr_number="42")
        item = self.work_item(classification_evidence=None)
        request = ActionRequest.from_dict(self.request_payload(item=item.to_dict()))
        lease = ClaimLease(
            lease_id="lease_123",
            item_id=item.item_id,
            agent_id="codex-fixer-1",
            role=AgentRole.FIXER,
            status="active",
            request_hash=request.stable_hash(),
        )

        with self.assertRaises(ResponseValidationError) as caught:
            validate_response_for_request(
                self.response_payload("fix"),
                request=request,
                item=item,
                lease=lease,
                evidence_sink=session.append_evidence,
            )

        self.assertEqual(caught.exception.code, "missing_classification_evidence")
        self.assertEqual(session.evidence[-1].event_type, "response_rejected")
        self.assertEqual(session.evidence[-1].payload["reason_code"], "missing_classification_evidence")

    def test_explicit_reject_helper_appends_request_rejected_evidence(self):
        session = ReviewSession(session_id="session_123", repo="octo/example", pr_number="42")
        item = self.work_item(classification_evidence=None)

        evidence = reject_request_without_classification(
            session_id=session.session_id,
            item=item,
            lease_id="lease_123",
            agent_id="codex-fixer-1",
            evidence_sink=session.append_evidence,
        )

        self.assertIsInstance(evidence, EvidenceRecord)
        self.assertEqual(evidence.event_type, "request_rejected")
        self.assertEqual(evidence.payload["reason_code"], "missing_classification_evidence")


class ActionProtocolFixtureCorpusTests(ActionProtocolTestCase):
    def load_corpus(self):
        records = []
        with (FIXTURES_DIR / "corpus.jsonl").open(encoding="utf-8") as handle:
            for line in handle:
                records.append(json.loads(line))
        return records

    def test_fixture_corpus_has_twenty_representative_pairs(self):
        records = self.load_corpus()
        resolutions = [record["response"]["resolution"] for record in records]

        self.assertGreaterEqual(len(records), 20)
        for resolution in ("fix", "clarify", "defer", "reject"):
            self.assertGreaterEqual(resolutions.count(resolution), 5)

    def test_fixture_corpus_parses_at_least_95_percent_schema_valid_responses(self):
        records = self.load_corpus()
        valid = 0

        for record in records:
            validate_action_request(record["request"])
            try:
                validate_response_for_request(
                    record["response"],
                    request=ActionRequest.from_dict(record["request"]),
                    item=WorkItem.from_dict(record["request"]["item"]),
                    lease=ClaimLease(
                        lease_id=record["request"]["lease_id"],
                        item_id=record["request"]["item"]["item_id"],
                        agent_id=record["response"]["agent_id"],
                        role=record["request"]["agent_role"],
                        status="active",
                        request_hash=ActionRequest.from_dict(record["request"]).stable_hash(),
                    ),
                )
            except ResponseValidationError:
                continue
            valid += 1

        self.assertGreaterEqual(valid / len(records), 0.95)


if __name__ == "__main__":
    unittest.main()
