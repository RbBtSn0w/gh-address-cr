## 2024-07-03 - Avoid dict.setdefault with complex fallbacks in hot loops
**Learning:** In tight loops processing many objects (like telemetry events), `dict.setdefault(key, <default_object>)` eagerly instantiates the fallback object (e.g., a new dict, set, or list) on every iteration, causing massive allocation overhead.
**Action:** Use an explicit `if key not in dict: dict[key] = ...` instead for measurable speedups.
