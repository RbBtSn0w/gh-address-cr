## 2024-05-24 - Avoid eager allocation in telemetry loops
**Learning:** In tight loops processing many objects (like telemetry events), `dict.setdefault(key, <default_object>)` eagerly instantiates the fallback object on every iteration. When the fallback object is complex (like a new dict or set), this causes massive allocation overhead.
**Action:** Use an explicit `if key not in dict: dict[key] = ...` instead of `setdefault` when the default object requires a complex allocation.
