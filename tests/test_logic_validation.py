import copy
import unittest

from gh_address_cr.core.logic_validation import generate_logic_validation_signals


class LogicValidationSignalTest(unittest.TestCase):
    def test_missing_required_evidence_generates_blocking_signal(self):
        session = {
            "items": {
                "local-finding:fixed": {
                    "item_id": "local-finding:fixed",
                    "item_kind": "local_finding",
                    "state": "fixed",
                    "blocking": False,
                }
            }
        }

        signals = generate_logic_validation_signals(session)

        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].signal_type, "missing_required_evidence")
        self.assertEqual(signals[0].gate_effect, "blocking")

    def test_terminal_github_thread_missing_validation_generates_blocking_signal(self):
        session = {
            "items": {
                "github-thread:fixed": {
                    "item_id": "github-thread:fixed",
                    "item_kind": "github_thread",
                    "state": "published",
                    "reply_evidence": {"reply_url": "https://example.test/reply"},
                    "blocking": False,
                }
            }
        }

        signals = generate_logic_validation_signals(session)

        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].signal_type, "missing_required_evidence")
        self.assertEqual(signals[0].gate_effect, "blocking")

    def test_state_contradiction_generates_blocking_signal(self):
        session = {
            "items": {
                "github-thread:open": {
                    "item_id": "github-thread:open",
                    "item_kind": "github_thread",
                    "state": "open",
                    "completion_claim": "ready_to_publish",
                }
            }
        }

        signals = generate_logic_validation_signals(session)

        self.assertEqual(signals[0].signal_type, "state_contradiction")
        self.assertEqual(signals[0].gate_effect, "blocking")

    def test_low_confidence_signal_is_advisory(self):
        session = {
            "items": {
                "github-thread:thin": {
                    "item_id": "github-thread:thin",
                    "item_kind": "github_thread",
                    "state": "closed",
                    "reply_evidence": {"reply_url": "https://example.test/reply"},
                    "validation_evidence": [{"command": "python3 -m unittest", "exit_code": 0}],
                    "logic_confidence": "low",
                }
            }
        }

        signals = generate_logic_validation_signals(session)

        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].signal_type, "low_confidence_advisory")
        self.assertEqual(signals[0].gate_effect, "advisory")

    def test_validation_signals_do_not_mutate_session_state(self):
        session = {
            "items": {
                "local-finding:fixed": {
                    "item_id": "local-finding:fixed",
                    "item_kind": "local_finding",
                    "state": "fixed",
                }
            }
        }
        original = copy.deepcopy(session)

        generate_logic_validation_signals(session)

        self.assertEqual(session, original)


if __name__ == "__main__":
    unittest.main()
