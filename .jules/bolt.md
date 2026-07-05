## 2024-05-24 - Avoid dict.setdefault with complex defaults in tight loops
**Learning:** In tight loops processing many objects (like telemetry events), `dict.setdefault(key, <default_object>)` eagerness causes massive allocation overhead when the default object is complex (e.g., a new dict, set, or list).
**Action:** Use an explicit `if key not in dict: dict[key] = ...` check instead to avoid eager allocation in telemetry processing or hot paths.
