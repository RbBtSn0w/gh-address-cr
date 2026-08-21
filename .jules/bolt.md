## 2024-05-19 - Avoid dict.setdefault for complex objects in tight loops
**Learning:** In hot paths processing many objects (like `session_events` in `cr_metrics.py`), using `dict.setdefault(key, [])` eagerly instantiates the fallback object (a new list) on every single iteration, even if the key already exists. This causes unnecessary allocation overhead and garbage collection pressure when processing large numbers of events.
**Action:** Use an explicit `if key not in dict: dict[key] = []` check instead of `setdefault` when the default object requires instantiation.

## 2024-05-19 - Inline generators in hot paths cause overhead
**Learning:** Inline generators with `any()` (e.g., `any(event.duration_ms > 0 for event in events)`) incur significant generator instantiation overhead in hot paths like telemetry processing.
**Action:** Replace inline generators inside `any()` or `all()` with explicit `for` loops for measurable speedups in telemetry validation and serialization.
