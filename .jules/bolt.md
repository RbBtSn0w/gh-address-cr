## 2026-08-13 - Eager Instantiation in setdefault
**Learning:** In tight loops processing many objects (like telemetry events), `dict.setdefault(key, [])` eagerly instantiates a new empty list on every iteration before throwing it away if the key exists. This causes massive unnecessary allocation overhead.
**Action:** Use an explicit `if key not in dict: dict[key] = []` block to lazily create default objects in hot paths.
