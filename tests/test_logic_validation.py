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
                    "classification_evidence": {"classification": "fix"},
                    "blocking": False,
                }
            }
        }

        signals = generate_logic_validation_signals(session)

        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].signal_type, "missing_required_evidence")
        self.assertEqual(signals[0].gate_effect, "blocking")

    def test_legacy_closed_github_thread_with_reply_evidence_does_not_require_validation(self):
        session = {
            "items": {
                "github-thread:legacy": {
                    "item_id": "github-thread:legacy",
                    "item_kind": "github_thread",
                    "state": "closed",
                    "reply_evidence": {"reply_url": "https://example.test/reply"},
                    "blocking": False,
                }
            }
        }

        signals = generate_logic_validation_signals(session)

        self.assertEqual(signals, [])

    def test_terminal_github_thread_accepts_final_gate_validation_shapes(self):
        for key, value in (
            ("validation_results", [{"command": "python3 -m unittest", "result": "passed"}]),
            ("evidence", {"validation": {"command": "python3 -m unittest", "result": "passed"}}),
            ("evidence", {"validation_evidence": [{"command": "python3 -m unittest", "result": "passed"}]}),
        ):
            with self.subTest(key=key, value=value):
                session = {
                    "items": {
                        "github-thread:fixed": {
                            "item_id": "github-thread:fixed",
                            "item_kind": "github_thread",
                            "state": "published",
                            "reply_evidence": {"reply_url": "https://example.test/reply"},
                            key: value,
                        }
                    }
                }

                signals = generate_logic_validation_signals(session)

                self.assertEqual(signals, [])

    def test_terminal_github_thread_accepts_published_accepted_response_validation(self):
        session = {
            "items": {
                "github-thread:fixed": {
                    "item_id": "github-thread:fixed",
                    "item_kind": "github_thread",
                    "state": "published",
                    "reply_evidence": {"reply_url": "https://example.test/reply"},
                    "accepted_response": {
                        "resolution": "fix",
                        "validation_commands": [
                            {"command": "python3 -m unittest", "result": "passed"},
                        ],
                    },
                }
            }
        }

        signals = generate_logic_validation_signals(session)

        self.assertEqual(signals, [])

    def test_non_mutating_github_thread_responses_do_not_require_validation(self):
        for resolution, state in (("clarify", "clarified"), ("defer", "deferred"), ("reject", "rejected")):
            with self.subTest(resolution=resolution, state=state):
                session = {
                    "items": {
                        f"github-thread:{resolution}": {
                            "item_id": f"github-thread:{resolution}",
                            "item_kind": "github_thread",
                            "state": state,
                            "reply_evidence": {"reply_url": "https://example.test/reply"},
                            "accepted_response": {
                                "resolution": resolution,
                                "reply_markdown": f"{resolution} response",
                            },
                        }
                    }
                }

                signals = generate_logic_validation_signals(session)

                self.assertEqual(signals, [])

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

    def test_terminal_github_thread_states_do_not_contradict_handled_claims(self):
        for state in ("resolved", "clarified", "deferred", "rejected"):
            with self.subTest(state=state):
                session = {
                    "items": {
                        f"github-thread:{state}": {
                            "item_id": f"github-thread:{state}",
                            "item_kind": "github_thread",
                            "state": state,
                            "completion_claim": "handled",
                            "validation_evidence": [{"command": "python3 -m unittest", "result": "passed"}],
                        }
                    }
                }

                signals = generate_logic_validation_signals(session)

                self.assertEqual(signals, [])

    def test_terminal_local_states_do_not_contradict_handled_claims(self):
        for state in ("clarified", "deferred", "rejected"):
            with self.subTest(state=state):
                session = {
                    "items": {
                        f"local-finding:{state}": {
                            "item_id": f"local-finding:{state}",
                            "item_kind": "local_finding",
                            "state": state,
                            "completion_claim": "handled",
                            "validation_evidence": [{"command": "python3 -m unittest", "result": "passed"}],
                        }
                    }
                }

                signals = generate_logic_validation_signals(session)

                self.assertEqual(signals, [])

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
