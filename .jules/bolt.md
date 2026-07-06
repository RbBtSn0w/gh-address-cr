## 2026-07-06 - Avoid Eager Allocation in dict.setdefault
**Learning:** In tight loops processing many objects (like telemetry events), using `dict.setdefault(key, <default_object>)` is a massive performance bottleneck if `<default_object>` is complex (like a new dictionary or set). The fallback object is eagerly instantiated on every single iteration, even if the key already exists, causing unnecessary allocation overhead.
**Action:** Use explicit `if key not in dict: dict[key] = <default_object>` checks instead to ensure the complex object is only allocated when strictly necessary.
