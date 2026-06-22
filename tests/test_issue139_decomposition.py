import inspect
import unittest

from gh_address_cr.core import agent_batch, agent_protocol, workflow, workflow_matching


class Issue139DecompositionTestCase(unittest.TestCase):
    def test_agent_protocol_keeps_batch_facade_while_batch_module_owns_response_logic(self):
        self.assertTrue(callable(agent_protocol.issue_batch_action_request))
        self.assertTrue(callable(agent_protocol.submit_batch_action_response))
        self.assertTrue(callable(agent_batch.issue_batch_action_request))
        self.assertTrue(callable(agent_batch.submit_batch_action_response))

        protocol_source = inspect.getsource(agent_protocol)
        batch_source = inspect.getsource(agent_batch)
        moved_symbols = [
            "def _batch_action_responses",
            "def _validate_batch_fix_contract",
            "def _augment_batch_recovery_error",
            "def _batch_recovery_payload",
            "def _batch_acceptance_payload",
        ]
        for symbol in moved_symbols:
            with self.subTest(symbol=symbol):
                self.assertNotIn(symbol, protocol_source)
                self.assertIn(symbol, batch_source)

    def test_workflow_keeps_matching_facade_while_matching_module_owns_implementation(self):
        self.assertTrue(callable(workflow.fast_fix_matching_threads))
        self.assertTrue(callable(workflow.decline_matching_threads))
        self.assertTrue(callable(workflow_matching.fast_fix_matching_threads))
        self.assertTrue(callable(workflow_matching.decline_matching_threads))

        workflow_source = inspect.getsource(workflow)
        matching_source = inspect.getsource(workflow_matching)
        moved_symbols = [
            "class _FastFixContext",
            "def _resolve_fast_fix_matches",
            "def _enforce_fast_fix_routing",
            "def _process_fast_fix_matches",
            "def _finalize_matching_threads",
            "def _process_decline_matches",
        ]
        for symbol in moved_symbols:
            with self.subTest(symbol=symbol):
                self.assertNotIn(symbol, workflow_source)
                self.assertIn(symbol, matching_source)


if __name__ == "__main__":
    unittest.main()
