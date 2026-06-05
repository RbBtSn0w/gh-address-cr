import sys
import unittest

from tests.helpers import SRC_ROOT


sys.path.insert(0, str(SRC_ROOT))


class RuntimeKernelTestIntent:
    risk = "Review-resolution state can drift when stale, reopened, resolved, evidence, and reporting facts are handled by scattered branches."
    why_automation = "The behavior is deterministic state transformation and must be replayable without live GitHub or artifact writes."
    why_existing_tests_insufficient = "Existing tests cover current workflow paths, but not a standalone facts-to-projection-to-policy-to-plan kernel boundary."
    chosen_layer = "Unit Test - pure runtime logic is the smallest effective layer."
    fragility_analysis = "Tests assert public kernel dictionaries and reason codes, not private helper call order."
    if_omitted = "Final-gate or agent routing could regress into partial-evidence or self-referential artifact completion."


def review_fact(thread_id, *, fact_id=None, observed_at="2026-06-05T00:00:00Z", sequence=0, **payload):
    body = {
        "schema_version": "1.0",
        "fact_kind": "review_thread_observed",
        "fact_id": fact_id or f"thread-{thread_id}-{sequence}",
        "observed_at": observed_at,
        "sequence": sequence,
        "payload": {"thread_id": thread_id, **payload},
    }
    return body


def command_fact(
    command,
    *,
    observed_at="2026-06-05T00:01:00Z",
    sequence=0,
    status="succeeded",
    include_result_url=True,
):
    payload = {
        "command_id": command.command_id,
        "command_kind": command.command_kind,
        "item_id": command.item_id,
        "status": status,
        "recorded_at": observed_at,
        **command.payload,
    }
    if include_result_url:
        payload["result_url"] = f"https://github.example/{command.command_id}"
    return {
        "schema_version": "1.0",
        "fact_kind": "command_executed",
        "fact_id": f"exec-{command.command_id}-{sequence}",
        "observed_at": observed_at,
        "sequence": sequence,
        "payload": payload,
    }


def raw_command_fact(command_id, command_kind, item_id, *, observed_at="2026-06-05T00:01:00Z", status="succeeded"):
    return {
        "schema_version": "1.0",
        "fact_kind": "command_executed",
        "fact_id": f"exec-{command_id}",
        "observed_at": observed_at,
        "payload": {
            "command_id": command_id,
            "command_kind": command_kind,
            "item_id": item_id,
            "status": status,
            "result_url": f"https://github.example/{command_id}",
            "recorded_at": observed_at,
        },
    }


def reporting_fact(*, fact_id="report-1", observed_at="2026-06-05T00:02:00Z", write_status="failed"):
    return {
        "schema_version": "1.0",
        "fact_kind": "reporting_observed",
        "fact_id": fact_id,
        "observed_at": observed_at,
        "payload": {
            "coverage_label": "runtime-only",
            "diagnostics": ["REPORT_WRITE_EXCLUDED_FROM_COMPLETION"],
            "overhead_ms": 12,
            "report_path": "efficiency_report.json",
            "write_status": write_status,
        },
    }


class RuntimeKernelProjectionTests(unittest.TestCase):
    def test_runtime_fact_validation_and_stable_ordering(self):
        from gh_address_cr.core.runtime_kernel.events import RuntimeFact, sort_runtime_facts

        late = RuntimeFact.from_dict(review_fact("B", fact_id="b", observed_at="2026-06-05T00:00:02Z"))
        early = RuntimeFact.from_dict(review_fact("A", fact_id="a", observed_at="2026-06-05T00:00:01Z"))

        self.assertEqual([fact.fact_id for fact in sort_runtime_facts([late, early])], ["a", "b"])
        with self.assertRaises(ValueError):
            RuntimeFact.from_dict({"schema_version": "9.9", "fact_kind": "review_thread_observed"})

    def test_runtime_fact_instances_are_revalidated(self):
        from gh_address_cr.core.runtime_kernel.events import RuntimeFact, sort_runtime_facts

        malformed = RuntimeFact(
            schema_version="1.0",
            fact_kind="unknown_fact",
            fact_id="bad",
            observed_at="2026-06-05T00:00:00Z",
        )

        with self.assertRaisesRegex(ValueError, "unsupported runtime fact kind"):
            sort_runtime_facts([malformed])

    def test_runtime_fact_ordering_normalizes_rfc3339_offsets(self):
        from gh_address_cr.core.runtime_kernel.events import RuntimeFact, sort_runtime_facts

        earlier = RuntimeFact.from_dict(
            review_fact("OFFSET", fact_id="offset", observed_at="2026-06-05T01:00:00+01:00")
        )
        later = RuntimeFact.from_dict(review_fact("Z", fact_id="z", observed_at="2026-06-05T00:30:00Z"))

        self.assertEqual([fact.fact_id for fact in sort_runtime_facts([later, earlier])], ["offset", "z"])

    def test_runtime_fact_rejects_malformed_observed_at(self):
        from gh_address_cr.core.runtime_kernel.events import RuntimeFact

        with self.assertRaisesRegex(ValueError, "observed_at"):
            RuntimeFact.from_dict(review_fact("BAD_TIME", observed_at="2026-06-05T00:00:00"))

    def test_runtime_fact_sequence_must_be_an_integer(self):
        from gh_address_cr.core.runtime_kernel.events import RuntimeFact

        invalid_sequences = ("1", True)
        for sequence in invalid_sequences:
            with self.subTest(sequence=sequence):
                payload = review_fact("BAD_SEQUENCE")
                payload["sequence"] = sequence
                with self.assertRaisesRegex(ValueError, "sequence must be an integer"):
                    RuntimeFact.from_dict(payload)

    def test_ambiguous_review_thread_item_identity_fails_loudly(self):
        from gh_address_cr.core.runtime_kernel.projections import project_review_threads

        with self.assertRaisesRegex(ValueError, "ambiguous item_id"):
            project_review_threads(
                [
                    review_fact(
                        "THREAD_A",
                        fact_id="ambiguous",
                        item_id="github-thread:THREAD_B",
                    )
                ]
            )

    def test_review_thread_boolean_payloads_must_be_booleans(self):
        from gh_address_cr.core.runtime_kernel.projections import project_review_threads

        invalid_payloads = (
            {"is_resolved": "false"},
            {"isResolved": "false"},
            {"is_outdated": "false"},
            {"isOutdated": "false"},
            {"reply_evidence_present": "false"},
            {"external_wait": "false"},
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                with self.assertRaisesRegex(ValueError, "must be a boolean"):
                    project_review_threads([review_fact("BAD_BOOL", **payload)])

    def test_command_execution_kind_must_be_supported(self):
        from gh_address_cr.core.runtime_kernel.projections import project_review_threads

        with self.assertRaisesRegex(ValueError, "unsupported command execution kind"):
            project_review_threads(
                [
                    review_fact("OPEN", is_resolved=False),
                    raw_command_fact("unknown", "made_up_command", "github-thread:OPEN"),
                ]
            )

    def test_same_and_reordered_facts_project_identically(self):
        from gh_address_cr.core.runtime_kernel.projections import project_review_threads

        facts = [
            review_fact("THREAD_2", fact_id="2", observed_at="2026-06-05T00:00:02Z", is_resolved=False),
            review_fact(
                "THREAD_1",
                fact_id="1",
                observed_at="2026-06-05T00:00:01Z",
                is_resolved=True,
                state="closed",
                reply_evidence_present=True,
            ),
        ]

        first = project_review_threads(facts).to_dict()
        second = project_review_threads(list(reversed(facts))).to_dict()

        self.assertEqual(first, second)

    def test_unresolved_stale_reopened_and_resolved_projection_states(self):
        from gh_address_cr.core.runtime_kernel.projections import project_review_threads

        facts = [
            review_fact("OPEN", fact_id="open", is_resolved=False),
            review_fact("STALE", fact_id="stale", is_resolved=False, is_outdated=True, status="STALE"),
            review_fact(
                "DONE",
                fact_id="done",
                is_resolved=True,
                state="closed",
                reply_evidence_present=True,
            ),
            review_fact(
                "REOPENED",
                fact_id="reopened-1",
                observed_at="2026-06-05T00:00:01Z",
                is_resolved=True,
                state="closed",
                reply_evidence_present=True,
            ),
            review_fact(
                "REOPENED",
                fact_id="reopened-2",
                observed_at="2026-06-05T00:00:02Z",
                is_resolved=False,
                state="open",
            ),
        ]

        projection = project_review_threads(facts).to_dict()
        items = {item["item_id"]: item for item in projection["work_items"]}

        self.assertEqual(items["github-thread:OPEN"]["state"], "active")
        self.assertEqual(items["github-thread:STALE"]["state"], "stale")
        self.assertEqual(items["github-thread:DONE"]["state"], "terminal")
        self.assertEqual(items["github-thread:REOPENED"]["state"], "reopened")
        self.assertIn("github-thread:STALE", projection["stale_item_ids"])
        self.assertIn("github-thread:REOPENED", projection["reopened_item_ids"])
        self.assertIn("github-thread:OPEN", projection["final_gate_blocker_ids"])
        self.assertNotIn("github-thread:DONE", projection["final_gate_blocker_ids"])

    def test_external_wait_overrides_reopened_and_stale_action_states(self):
        from gh_address_cr.core.runtime_kernel.policies import evaluate_review_policy
        from gh_address_cr.core.runtime_kernel.projections import project_review_threads

        reopened_wait = project_review_threads(
            [
                review_fact(
                    "REOPENED_WAIT",
                    fact_id="done",
                    observed_at="2026-06-05T00:00:00Z",
                    is_resolved=True,
                    state="closed",
                    reply_evidence_present=True,
                ),
                review_fact(
                    "REOPENED_WAIT",
                    fact_id="wait",
                    observed_at="2026-06-05T00:00:01Z",
                    is_resolved=False,
                    state="open",
                    external_wait=True,
                ),
            ]
        )
        stale_wait = project_review_threads(
            [review_fact("STALE_WAIT", is_resolved=False, is_outdated=True, external_wait=True)]
        )

        self.assertEqual(reopened_wait.to_dict()["work_items"][0]["state"], "waiting")
        self.assertEqual(stale_wait.to_dict()["work_items"][0]["state"], "waiting")
        self.assertEqual(evaluate_review_policy(reopened_wait).to_dict()["status"], "waiting_for_external_input")
        self.assertEqual(evaluate_review_policy(stale_wait).to_dict()["status"], "waiting_for_external_input")


class RuntimeKernelPolicyTests(unittest.TestCase):
    def test_policy_decision_table(self):
        from gh_address_cr.core.runtime_kernel.policies import evaluate_review_policy
        from gh_address_cr.core.runtime_kernel.projections import ReviewProjection, project_review_threads

        blocked = evaluate_review_policy(
            ReviewProjection(diagnostics=({"severity": "blocking", "reason_code": "KERNEL_FACT_INVALID"},))
        ).to_dict()
        ready = evaluate_review_policy(project_review_threads([review_fact("OPEN", is_resolved=False)])).to_dict()
        waiting = evaluate_review_policy(
            project_review_threads([review_fact("WAIT", is_resolved=False, external_wait=True)])
        ).to_dict()
        eligible = evaluate_review_policy(
            project_review_threads(
                [review_fact("DONE", is_resolved=True, state="closed", reply_evidence_present=True)]
            )
        ).to_dict()

        self.assertEqual(blocked["status"], "blocked")
        self.assertEqual(ready["status"], "ready_for_action")
        self.assertEqual(waiting["status"], "waiting_for_external_input")
        self.assertEqual(eligible["status"], "final_gate_eligible")

    def test_final_gate_cannot_be_eligible_with_unresolved_or_evidence_pending_work(self):
        from gh_address_cr.core.runtime_kernel.policies import evaluate_review_policy
        from gh_address_cr.core.runtime_kernel.projections import project_review_threads

        unresolved = evaluate_review_policy(project_review_threads([review_fact("OPEN", is_resolved=False)])).to_dict()
        missing_reply = evaluate_review_policy(
            project_review_threads([review_fact("DONE", is_resolved=True, state="closed")])
        ).to_dict()

        self.assertNotEqual(unresolved["status"], "final_gate_eligible")
        self.assertNotEqual(missing_reply["status"], "final_gate_eligible")
        self.assertIn("github-thread:DONE", missing_reply["item_ids"])


class RuntimeKernelCommandPlanTests(unittest.TestCase):
    def test_command_plans_are_idempotent_and_non_executing(self):
        from gh_address_cr.core.runtime_kernel.commands import plan_review_commands
        from gh_address_cr.core.runtime_kernel.policies import evaluate_review_policy
        from gh_address_cr.core.runtime_kernel.projections import project_review_threads

        projection = project_review_threads([review_fact("OPEN", is_resolved=False)])
        decision = evaluate_review_policy(projection)

        first = [command.to_dict() for command in plan_review_commands(projection, decision)]
        second = [command.to_dict() for command in plan_review_commands(projection, decision)]

        self.assertEqual(first, second)
        self.assertEqual([command["command_kind"] for command in first], ["reply_thread", "resolve_thread"])
        self.assertTrue(all(command["idempotency_key"] for command in first))

    def test_planned_commands_do_not_complete_work_until_execution_evidence_is_recorded(self):
        from gh_address_cr.core.runtime_kernel.commands import plan_review_commands
        from gh_address_cr.core.runtime_kernel.policies import evaluate_review_policy
        from gh_address_cr.core.runtime_kernel.projections import project_review_threads

        review = review_fact("OPEN", is_resolved=False)
        projection = project_review_threads([review])
        decision = evaluate_review_policy(projection)
        plan = plan_review_commands(projection, decision)

        without_execution = evaluate_review_policy(project_review_threads([review])).to_dict()
        with_execution_projection = project_review_threads([review, *[command_fact(command) for command in plan]])
        with_execution = evaluate_review_policy(with_execution_projection).to_dict()

        self.assertEqual(without_execution["status"], "ready_for_action")
        self.assertEqual(with_execution["status"], "final_gate_eligible")
        self.assertEqual(with_execution_projection.to_dict()["final_gate_blocker_ids"], [])

    def test_unknown_execution_facts_do_not_complete_work(self):
        from gh_address_cr.core.runtime_kernel.policies import evaluate_review_policy
        from gh_address_cr.core.runtime_kernel.projections import project_review_threads

        projection = project_review_threads(
            [
                review_fact("OPEN", fact_id="open", is_resolved=False),
                raw_command_fact("unknown-reply", "reply_thread", "github-thread:OPEN"),
                raw_command_fact("unknown-resolve", "resolve_thread", "github-thread:OPEN"),
            ]
        )
        decision = evaluate_review_policy(projection).to_dict()

        self.assertEqual(projection.to_dict()["work_items"][0]["state"], "active")
        self.assertEqual(decision["status"], "ready_for_action")
        self.assertIn("github-thread:OPEN", projection.to_dict()["final_gate_blocker_ids"])

    def test_succeeded_execution_without_durable_evidence_does_not_complete_work(self):
        from gh_address_cr.core.runtime_kernel.commands import plan_review_commands
        from gh_address_cr.core.runtime_kernel.policies import evaluate_review_policy
        from gh_address_cr.core.runtime_kernel.projections import project_review_threads

        review = review_fact("OPEN", is_resolved=False)
        projection = project_review_threads([review])
        plan = plan_review_commands(projection, evaluate_review_policy(projection))

        unproven_projection = project_review_threads(
            [review, *[command_fact(command, include_result_url=False) for command in plan]]
        )
        decision = evaluate_review_policy(unproven_projection).to_dict()

        self.assertEqual(unproven_projection.to_dict()["work_items"][0]["state"], "active")
        self.assertEqual(decision["status"], "ready_for_action")
        self.assertIn("github-thread:OPEN", unproven_projection.to_dict()["final_gate_blocker_ids"])

    def test_succeeded_execution_with_blank_result_url_does_not_complete_work(self):
        from gh_address_cr.core.runtime_kernel.commands import plan_review_commands
        from gh_address_cr.core.runtime_kernel.policies import evaluate_review_policy
        from gh_address_cr.core.runtime_kernel.projections import project_review_threads

        review = review_fact("OPEN", is_resolved=False)
        projection = project_review_threads([review])
        plan = plan_review_commands(projection, evaluate_review_policy(projection))
        command_facts = [command_fact(command) for command in plan]
        for fact in command_facts:
            fact["payload"]["result_url"] = "   "

        unproven_projection = project_review_threads([review, *command_facts])
        decision = evaluate_review_policy(unproven_projection).to_dict()

        self.assertEqual(unproven_projection.to_dict()["work_items"][0]["state"], "active")
        self.assertEqual(decision["status"], "ready_for_action")
        self.assertIn("github-thread:OPEN", unproven_projection.to_dict()["final_gate_blocker_ids"])

    def test_reopened_thread_invalidates_old_execution_evidence(self):
        from gh_address_cr.core.runtime_kernel.commands import plan_review_commands
        from gh_address_cr.core.runtime_kernel.policies import evaluate_review_policy
        from gh_address_cr.core.runtime_kernel.projections import project_review_threads

        first_generation = review_fact(
            "REOPENED",
            fact_id="generation-1",
            observed_at="2026-06-05T00:00:00Z",
            is_resolved=False,
        )
        first_projection = project_review_threads([first_generation])
        first_plan = plan_review_commands(first_projection, evaluate_review_policy(first_projection))
        reopened_generation = review_fact(
            "REOPENED",
            fact_id="generation-2",
            observed_at="2026-06-05T00:00:03Z",
            is_resolved=False,
            state="open",
        )

        reopened_projection = project_review_threads(
            [
                first_generation,
                *[command_fact(command, observed_at="2026-06-05T00:00:01Z") for command in first_plan],
                reopened_generation,
            ]
        )
        decision = evaluate_review_policy(reopened_projection).to_dict()

        self.assertEqual(reopened_projection.to_dict()["work_items"][0]["state"], "reopened")
        self.assertEqual(decision["status"], "ready_for_action")
        self.assertIn("github-thread:REOPENED", reopened_projection.to_dict()["final_gate_blocker_ids"])

    def test_failed_execution_results_plan_retry_without_completing_work(self):
        from gh_address_cr.core.runtime_kernel.commands import plan_review_commands
        from gh_address_cr.core.runtime_kernel.policies import evaluate_review_policy
        from gh_address_cr.core.runtime_kernel.projections import project_review_threads

        review = review_fact("OPEN", is_resolved=False)
        initial_projection = project_review_threads([review])
        initial_plan = plan_review_commands(initial_projection, evaluate_review_policy(initial_projection))
        failed_reply = next(command for command in initial_plan if command.command_kind == "reply_thread")

        retry_projection = project_review_threads([review, command_fact(failed_reply, status="failed")])
        retry_decision = evaluate_review_policy(retry_projection)
        retry_plan = [command.to_dict() for command in plan_review_commands(retry_projection, retry_decision)]

        self.assertEqual(retry_decision.to_dict()["status"], "ready_for_action")
        self.assertIn("retry_command", [command["command_kind"] for command in retry_plan])
        self.assertIn("github-thread:OPEN", retry_projection.to_dict()["final_gate_blocker_ids"])

    def test_successful_retry_execution_satisfies_original_required_command(self):
        from gh_address_cr.core.runtime_kernel.commands import plan_review_commands
        from gh_address_cr.core.runtime_kernel.policies import evaluate_review_policy
        from gh_address_cr.core.runtime_kernel.projections import project_review_threads

        review = review_fact("OPEN", is_resolved=False)
        initial_projection = project_review_threads([review])
        initial_plan = plan_review_commands(initial_projection, evaluate_review_policy(initial_projection))
        failed_reply = next(command for command in initial_plan if command.command_kind == "reply_thread")
        successful_resolve = next(command for command in initial_plan if command.command_kind == "resolve_thread")
        retry_projection = project_review_threads(
            [
                review,
                command_fact(failed_reply, status="failed"),
                command_fact(successful_resolve),
            ]
        )
        retry_plan = plan_review_commands(retry_projection, evaluate_review_policy(retry_projection))
        retry_reply = next(command for command in retry_plan if command.command_kind == "retry_command")

        completed_projection = project_review_threads(
            [
                review,
                command_fact(failed_reply, status="failed"),
                command_fact(successful_resolve),
                command_fact(retry_reply),
            ]
        )
        completed_decision = evaluate_review_policy(completed_projection).to_dict()

        self.assertEqual(completed_decision["status"], "final_gate_eligible")
        self.assertEqual(completed_projection.to_dict()["final_gate_blocker_ids"], [])

    def test_retry_execution_requires_durable_evidence_for_original_required_command(self):
        from gh_address_cr.core.runtime_kernel.commands import plan_review_commands
        from gh_address_cr.core.runtime_kernel.policies import evaluate_review_policy
        from gh_address_cr.core.runtime_kernel.projections import project_review_threads

        review = review_fact("OPEN", is_resolved=False)
        initial_projection = project_review_threads([review])
        initial_plan = plan_review_commands(initial_projection, evaluate_review_policy(initial_projection))
        failed_reply = next(command for command in initial_plan if command.command_kind == "reply_thread")
        successful_resolve = next(command for command in initial_plan if command.command_kind == "resolve_thread")
        retry_projection = project_review_threads(
            [
                review,
                command_fact(failed_reply, status="failed"),
                command_fact(successful_resolve),
            ]
        )
        retry_plan = plan_review_commands(retry_projection, evaluate_review_policy(retry_projection))
        retry_reply = next(command for command in retry_plan if command.command_kind == "retry_command")

        unproven_projection = project_review_threads(
            [
                review,
                command_fact(failed_reply, status="failed"),
                command_fact(successful_resolve),
                command_fact(retry_reply, include_result_url=False),
            ]
        )
        unproven_decision = evaluate_review_policy(unproven_projection).to_dict()

        self.assertEqual(unproven_decision["status"], "ready_for_action")
        self.assertIn("github-thread:OPEN", unproven_projection.to_dict()["final_gate_blocker_ids"])

    def test_reporting_facts_do_not_complete_work_or_create_recursive_blockers(self):
        from gh_address_cr.core.runtime_kernel.policies import evaluate_review_policy
        from gh_address_cr.core.runtime_kernel.projections import project_review_threads

        open_projection = project_review_threads([review_fact("OPEN", is_resolved=False), reporting_fact()])
        done_projection = project_review_threads(
            [
                review_fact("DONE", is_resolved=True, state="closed", reply_evidence_present=True),
                reporting_fact(),
            ]
        )

        self.assertEqual(evaluate_review_policy(open_projection).to_dict()["status"], "ready_for_action")
        self.assertEqual(evaluate_review_policy(done_projection).to_dict()["status"], "final_gate_eligible")
        self.assertEqual(done_projection.to_dict()["final_gate_blocker_ids"], [])


if __name__ == "__main__":
    unittest.main()
