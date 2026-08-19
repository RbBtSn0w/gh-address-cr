## 2024-05-19 - [Avoid setdefault with mutable defaults in tight loops]
**Learning:** Using `dict.setdefault(key, [])` in a hot loop eagerly instantiates a new empty list on *every* single iteration, causing significant allocation overhead, especially when iterating over many objects like telemetry events.
**Action:** Use an explicit `if key not in dict: dict[key] = []` check to avoid allocating unneeded fallback objects.
