"""Runtime Authority Map — one authoritative owner per state axis (feature 024).

The map is the deterministic source of truth for *which* path owns each runtime
state axis during a partial migration. Duplicate or ambiguous ownership fails
loud (FR-005). The map is a side-effect-free projection over declared ownership;
it never mutates runtime state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from gh_address_cr.core.consolidation.types import (
    AUTHORITY_MAP_SCHEMA,
    CompatibilityDirection,
    ConsolidationError,
    Owner,
    StateAxis,
)
from gh_address_cr.core.protocol_codes import DUPLICATE_STATE_OWNER

JsonDict = dict[str, Any]


@dataclass(frozen=True)
class AuthorityEntry:
    """One state axis, its authoritative owner, and its compatibility direction."""

    axis: StateAxis
    authoritative_owner: Owner
    compatibility_direction: CompatibilityDirection
    slice_id: str | None = None

    def to_dict(self) -> JsonDict:
        return {
            "axis": self.axis.value,
            "authoritative_owner": self.authoritative_owner.value,
            "compatibility_direction": self.compatibility_direction.value,
            "slice_id": self.slice_id,
        }


@dataclass(frozen=True)
class RuntimeAuthorityMap:
    """A validated set of authority entries for one runtime version."""

    runtime_version: str
    entries: tuple[AuthorityEntry, ...]

    @classmethod
    def from_entries(cls, runtime_version: str, entries: list[AuthorityEntry] | tuple[AuthorityEntry, ...]) -> "RuntimeAuthorityMap":
        seen: dict[StateAxis, AuthorityEntry] = {}
        for entry in entries:
            existing = seen.get(entry.axis)
            if existing is not None:
                raise ConsolidationError(
                    DUPLICATE_STATE_OWNER,
                    f"axis {entry.axis.value!r} has duplicate ownership: "
                    f"{existing.authoritative_owner.value} vs {entry.authoritative_owner.value}",
                )
            seen[entry.axis] = entry
        ordered = tuple(seen[axis] for axis in StateAxis if axis in seen)
        return cls(runtime_version=runtime_version, entries=ordered)

    def owner_for(self, axis: StateAxis) -> Owner | None:
        for entry in self.entries:
            if entry.axis == axis:
                return entry.authoritative_owner
        return None

    def missing_axes(self) -> tuple[StateAxis, ...]:
        present = {entry.axis for entry in self.entries}
        return tuple(axis for axis in StateAxis if axis not in present)

    def to_dict(self) -> JsonDict:
        return {
            "schema": AUTHORITY_MAP_SCHEMA,
            "runtime_version": self.runtime_version,
            "axes": [entry.to_dict() for entry in self.entries],
        }


def derive_authority_map(
    runtime_version: str,
    slice_owners: dict[StateAxis, tuple[Owner, CompatibilityDirection, str | None]],
) -> RuntimeAuthorityMap:
    """Project a *complete* authority map for the active runtime (FR-019).

    Axes claimed by a migration slice adopt the declared owner and compatibility
    direction; every unlisted axis defaults to the legacy owner so a partially
    consolidated runtime still exposes exactly one owner per axis. Fails loud if
    a caller declares the same axis twice with conflicting owners.
    """

    entries: list[AuthorityEntry] = []
    for axis in StateAxis:
        if axis in slice_owners:
            owner, direction, slice_id = slice_owners[axis]
            entries.append(
                AuthorityEntry(
                    axis=axis,
                    authoritative_owner=owner,
                    compatibility_direction=direction,
                    slice_id=slice_id,
                )
            )
        else:
            entries.append(
                AuthorityEntry(
                    axis=axis,
                    authoritative_owner=Owner.LEGACY,
                    compatibility_direction=CompatibilityDirection.NONE,
                )
            )
    return RuntimeAuthorityMap.from_entries(runtime_version, entries)
