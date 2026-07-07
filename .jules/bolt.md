## 2024-05-17 - Eager default instantiation in hot paths
**Learning:** In tight loops processing many objects (like telemetry events), `dict.setdefault(key, <default_object>)` eagerly instantiates the fallback object on every iteration, causing massive allocation overhead if the default object is complex (e.g., a new dict or set).
**Action:** Use an explicit `if key not in dict: dict[key] = ...` instead.

## 2024-05-17 - Inline generator overhead
**Learning:** Inline generators (e.g., `any()` or `all()` with comprehensions) incur significant overhead in hot paths like telemetry validation/serialization.
**Action:** For measurable speedups, avoid them. Instead, use explicit `for` loops and fast-fail substring checks.
