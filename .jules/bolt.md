## 2024-05-23 - Avoid setdefault with complex fallback objects in tight loops
**Learning:** `dict.setdefault(key, <default_object>)` eagerly instantiates the fallback object on every iteration. In tight loops processing many objects (like telemetry events), this causes massive allocation overhead when the fallback is complex (like a new dictionary or set).
**Action:** Use an explicit `if key not in dict: dict[key] = ...` instead for complex default objects.
