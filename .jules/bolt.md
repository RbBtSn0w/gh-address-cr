## 2024-08-15 - [Avoid setdefault in tight loops]
**Learning:** In tight loops processing many objects (like telemetry events), using `dict.setdefault(key, [])` or `dict.setdefault(key, {})` causes massive allocation overhead because the default list/dict is eagerly instantiated on every iteration.
**Action:** Use an explicit `if key not in dict: dict[key] = ...` instead.
