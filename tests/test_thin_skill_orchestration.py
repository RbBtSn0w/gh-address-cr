import unittest
import json
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "thin_skill_orchestration"
SRC_CORE_DIR = Path(__file__).parent.parent / "src" / "gh_address_cr" / "core"

def load_status_summaries():
    with open(FIXTURES_DIR / "status_summaries.json", "r", encoding="utf-8") as f:
        return json.load(f)

def load_documentation_contracts():
    with open(FIXTURES_DIR / "documentation_contracts.json", "r", encoding="utf-8") as f:
        return json.load(f)

class ThinSkillOrchestrationTests(unittest.TestCase):
    def test_status_summaries_load(self):
        summaries = load_status_summaries()
        self.assertIn("WAITING_FOR_ACTION", summaries)
        
    def test_documentation_contracts_load(self):
        contracts = load_documentation_contracts()
        self.assertIn("public_commands", contracts)

    def test_no_runner_or_review_engine_exists(self):
        self.assertFalse((SRC_CORE_DIR / "runner.py").exists(), "Generic runner must not exist")
        self.assertFalse((SRC_CORE_DIR / "review_engine.py").exists(), "Built-in review engine must not exist")
        self.assertFalse((SRC_CORE_DIR / "scheduler.py").exists(), "Agent scheduler must not exist")


    def test_status_to_action_contract(self):
        summaries = load_status_summaries()
        waiting = summaries["WAITING_FOR_ACTION"]
        self.assertEqual(waiting["safe_next_action"], "agent_submit")
        self.assertFalse(waiting["stop_condition"])

    def test_malformed_and_unknown_summary_fails_loudly(self):
        summaries = load_status_summaries()
        malformed = summaries["MALFORMED"]
        self.assertTrue(malformed["stop_condition"])
        self.assertIsNone(malformed["safe_next_action"])
        self.assertIn("recovery_path", malformed)

    def test_stage_5_scope_guards(self):
        self.assertFalse((SRC_CORE_DIR / "autonomous_runner.py").exists(), "Autonomous runner must not be built in this stage")
        self.assertFalse((SRC_CORE_DIR / "review_generator.py").exists(), "Review generator must not be built in this stage")

if __name__ == "__main__":
    unittest.main()
