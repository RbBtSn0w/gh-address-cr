"""Contract tests for deprecation inventory (feature 024, US2)."""

from __future__ import annotations

import unittest

from gh_address_cr.core.consolidation.deprecations import DeprecationEntry, DeprecationInventory
from gh_address_cr.core.consolidation.types import DEPRECATION_INVENTORY_SCHEMA, RolloutStage


class DeprecationInventoryTests(unittest.TestCase):
    def test_serializes_to_deprecation_inventory_v1(self) -> None:
        inventory = DeprecationInventory(
            entries=(
                DeprecationEntry(
                    kind="duplicate_model",
                    target="core.workflow_matching",
                    replaced_by="core.runtime_kernel.projections",
                    slice_id="slice-check-state",
                    contract_boundary="kernel projection is authoritative",
                    removable=False,
                ),
            )
        )
        self.assertEqual(inventory.to_dict()["schema"], DEPRECATION_INVENTORY_SCHEMA)

    def test_removable_entries_require_deprecating_or_later(self) -> None:
        inventory = DeprecationInventory(
            entries=(
                DeprecationEntry(
                    kind="compatibility_shim",
                    target="workflow.py legacy branch",
                    replaced_by="core.consolidation.rollout",
                    slice_id="slice-check-state",
                    contract_boundary="replacement proven by parity",
                    removable=True,
                ),
            )
        )
        with self.assertRaises(ValueError):
            inventory.validate(slice_stage=RolloutStage.OPT_IN, deprecation_window_complete=False)


if __name__ == "__main__":
    unittest.main()
