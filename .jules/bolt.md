## 2024-10-24 - Avoid setdefault with complex defaults in tight loops
**Learning:** In tight loops processing many objects (like telemetry events), using `dict.setdefault(key, <default_object>)` eagerly instantiates the fallback object (e.g., a new dict or set) on every single iteration, even if the key already exists. This causes massive allocation overhead.
**Action:** Replace `setdefault` with an explicit `if key not in dict: dict[key] = ...` check to avoid allocating unneeded fallback objects.
