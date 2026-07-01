"""Contract tests for the Runtime Authority Map (feature 024, US1)."""

from __future__ import annotations

import unittest

from gh_address_cr.core.consolidation.authority_map import (
    AuthorityEntry,
    RuntimeAuthorityMap,
    derive_authority_map,
)
from gh_address_cr.core.consolidation.types import (
    AUTHORITY_MAP_SCHEMA,
    CompatibilityDirection,
    ConsolidationError,
    Owner,
    StateAxis,
)
from gh_address_cr.core.protocol_codes import DUPLICATE_STATE_OWNER


class TestRuntimeAuthorityMap(unittest.TestCase):
    def _entry(self, axis: StateAxis, owner: Owner = Owner.LEGACY) -> AuthorityEntry:
        return AuthorityEntry(
            axis=axis,
            authoritative_owner=owner,
            compatibility_direction=CompatibilityDirection.NONE,
        )

    def test_single_owner_per_axis(self) -> None:
        amap = RuntimeAuthorityMap.from_entries(
            "3.2.2",
            [self._entry(StateAxis.CHECK, Owner.KERNEL), self._entry(StateAxis.LEASE)],
        )
        self.assertEqual(amap.owner_for(StateAxis.CHECK), Owner.KERNEL)
        self.assertEqual(amap.owner_for(StateAxis.LEASE), Owner.LEGACY)

    def test_duplicate_axis_fails_loud(self) -> None:
        with self.assertRaises(ConsolidationError) as ctx:
            RuntimeAuthorityMap.from_entries(
                "3.2.2",
                [
                    AuthorityEntry(
                        axis=StateAxis.CHECK,
                        authoritative_owner=Owner.LEGACY,
                        compatibility_direction=CompatibilityDirection.NONE,
                    ),
                    AuthorityEntry(
                        axis=StateAxis.CHECK,
                        authoritative_owner=Owner.KERNEL,
                        compatibility_direction=CompatibilityDirection.LEGACY_FROM_KERNEL,
                    ),
                ],
            )
        self.assertEqual(ctx.exception.reason_code, DUPLICATE_STATE_OWNER)

    def test_serializes_to_authority_map_v1(self) -> None:
        amap = derive_authority_map("3.2.2", {})
        body = amap.to_dict()
        self.assertEqual(body["schema"], AUTHORITY_MAP_SCHEMA)
        self.assertEqual(body["runtime_version"], "3.2.2")
        self.assertTrue(all("axis" in row and "authoritative_owner" in row for row in body["axes"]))


class TestPartialMigrationCompleteness(unittest.TestCase):
    def test_derive_covers_every_axis(self) -> None:
        # FR-019: a partially consolidated runtime must expose every axis.
        amap = derive_authority_map(
            "3.2.2",
            {StateAxis.CHECK: (Owner.KERNEL, CompatibilityDirection.LEGACY_FROM_KERNEL, "slice-check-state")},
        )
        covered = {entry.axis for entry in amap.entries}
        self.assertEqual(covered, set(StateAxis))
        self.assertEqual(amap.missing_axes(), ())
        self.assertEqual(amap.owner_for(StateAxis.CHECK), Owner.KERNEL)
        # Unlisted axes default to the legacy owner during partial migration.
        self.assertEqual(amap.owner_for(StateAxis.REVIEW_ITEM), Owner.LEGACY)

    def test_incomplete_map_reports_missing_axes(self) -> None:
        amap = RuntimeAuthorityMap.from_entries(
            "3.2.2",
            [
                AuthorityEntry(
                    axis=StateAxis.CHECK,
                    authoritative_owner=Owner.LEGACY,
                    compatibility_direction=CompatibilityDirection.NONE,
                )
            ],
        )
        self.assertIn(StateAxis.LEASE, amap.missing_axes())


if __name__ == "__main__":
    unittest.main()
