"""Replay + guard tests for the side-effect-free ParityObserver (feature 024, US1)."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from gh_address_cr.core.consolidation.parity import ParityObserver
from gh_address_cr.core.consolidation.types import PARITY_REPORT_SCHEMA
from gh_address_cr.core.runtime_kernel.projections import ReviewProjection, project_review_threads

_FIXTURE = Path(__file__).parent / "fixtures" / "check_state_facts.json"


def _facts() -> list[dict]:
    return json.loads(_FIXTURE.read_text())["facts"]


class _ExplodingGitHubClient:
    """Any attribute access raises — proves the observer performs zero GitHub IO."""

    def __getattr__(self, name: str):  # noqa: ANN001
        raise AssertionError(f"ParityObserver must not perform GitHub IO (called {name!r})")


class TestParityDeterminismAndSideEffects(unittest.TestCase):
    def _observer(self, candidate=project_review_threads) -> ParityObserver:
        observer = ParityObserver()
        observer.register_candidate("slice-check-state", candidate)
        return observer

    def test_deterministic_and_side_effect_free(self) -> None:
        observer = self._observer()
        first = observer.observe("slice-check-state", _facts())
        second = observer.observe("slice-check-state", _facts())
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertEqual(first.to_dict()["schema"], PARITY_REPORT_SCHEMA)
        self.assertEqual(first.side_effects_executed, 0)
        # A matching candidate (identity of the legacy projection) has no differences.
        self.assertTrue(first.projection_match and first.decision_match and first.command_plan_match)
        self.assertEqual(first.differences, ())

    def test_candidate_divergence_is_reported(self) -> None:
        def _divergent_candidate(facts):  # noqa: ANN001, ANN202
            # Drop every work item so the candidate projection differs from legacy.
            base = project_review_threads(facts)
            return ReviewProjection(diagnostics=base.diagnostics)

        observer = self._observer(candidate=_divergent_candidate)
        observation = observer.observe("slice-check-state", _facts())
        self.assertFalse(observation.projection_match)
        self.assertTrue(observation.differences)
        self.assertEqual(observation.side_effects_executed, 0)

    def test_zero_github_calls(self) -> None:
        observer = ParityObserver(github_client=_ExplodingGitHubClient())
        observer.register_candidate("slice-check-state", project_review_threads)
        observation = observer.observe("slice-check-state", _facts())
        self.assertEqual(observation.side_effects_executed, 0)


if __name__ == "__main__":
    unittest.main()
