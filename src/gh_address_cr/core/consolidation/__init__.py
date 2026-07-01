"""Reversible runtime-consolidation framework (feature 024).

Public entities are re-exported here as they are implemented. The framework
provides a Runtime Authority Map (one owner per state axis), a side-effect-free
parity observer, migration-slice contracts, and a deterministic rollout gate so
that legacy paths migrate onto the event-sourced ``runtime_kernel`` in bounded,
reversible slices governed by feature-023 evidence.
"""

from __future__ import annotations

__all__: list[str] = []
