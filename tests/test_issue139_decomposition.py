import inspect
import unittest

from gh_address_cr.commands import agent as agent_commands
from gh_address_cr.core import agent_batch, agent_protocol, workflow, workflow_matching


class Issue139DecompositionTestCase(unittest.TestCase):
    def test_agent_batch_module_is_the_only_batch_entrypoint_owner(self):
        self.assertFalse(hasattr(agent_protocol, "issue_batch_action_request"))
        self.assertFalse(hasattr(agent_protocol, "submit_batch_action_response"))
        self.assertTrue(callable(agent_batch.issue_batch_action_request))
        self.assertTrue(callable(agent_batch.submit_batch_action_response))

        protocol_source = inspect.getsource(agent_protocol)
        command_source = inspect.getsource(agent_commands)
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
        self.assertNotIn("agent_protocol.issue_batch_action_request", command_source)
        self.assertIn("agent_batch.issue_batch_action_request", command_source)

    def test_workflow_matching_module_is_the_only_matching_entrypoint_owner(self):
        self.assertFalse(hasattr(workflow, "fast_fix_matching_threads"))
        self.assertFalse(hasattr(workflow, "decline_matching_threads"))
        self.assertTrue(callable(workflow_matching.fast_fix_matching_threads))
        self.assertTrue(callable(workflow_matching.decline_matching_threads))

        workflow_source = inspect.getsource(workflow)
        command_source = inspect.getsource(agent_commands)
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
        self.assertNotIn("workflow.fast_fix_matching_threads", command_source)
        self.assertIn("workflow_matching.fast_fix_matching_threads", command_source)


if __name__ == "__main__":
    unittest.main()
