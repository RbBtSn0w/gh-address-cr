import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


class ComplexityReductionConvergenceTests(unittest.TestCase):
    def test_removed_consolidation_package_is_fully_absent(self):
        self.assertFalse((REPO_ROOT / "src/gh_address_cr/core/consolidation").exists())

    def test_removed_evaluation_package_is_fully_absent(self):
        self.assertFalse((REPO_ROOT / "src/gh_address_cr/core/evaluation").exists())
