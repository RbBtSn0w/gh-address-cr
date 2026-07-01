"""Performance-budget assertions for feature 024."""

from __future__ import annotations

import json
import time
import unittest
from pathlib import Path

from gh_address_cr.core.consolidation.migration_slice import registered_slices
from gh_address_cr.core.consolidation.parity import ParityObserver
from gh_address_cr.core.runtime_kernel.projections import project_review_threads

_FIXTURE = Path(__file__).parent / "fixtures" / "check_state_facts.json"


class PerformanceBudgetTests(unittest.TestCase):
    def test_parity_replay_stays_within_budget(self) -> None:
        facts = json.loads(_FIXTURE.read_text(encoding="utf-8"))["facts"]
        observer = ParityObserver()
        observer.register_candidate("slice-check-state", project_review_threads)

        started = time.perf_counter()
        observation = observer.observe("slice-check-state", facts)
        elapsed_ms = (time.perf_counter() - started) * 1000

        self.assertEqual(observation.side_effects_executed, 0)
        self.assertLessEqual(elapsed_ms, 250.0, f"parity replay exceeded budget: {elapsed_ms:.2f} ms")

    def test_slice_enablement_lookup_scales_with_slice_count(self) -> None:
        started = time.perf_counter()
        slice_ids = [slice_.slice_id for slice_ in registered_slices()]
        elapsed_ms = (time.perf_counter() - started) * 1000

        self.assertEqual(slice_ids, ["slice-check-state"])
        self.assertLessEqual(elapsed_ms, max(5.0, len(slice_ids) * 5.0))


if __name__ == "__main__":
    unittest.main()
