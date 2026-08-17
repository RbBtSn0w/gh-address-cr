## 2024-05-18 - Eager instantiation in dict.setdefault
**Learning:** In tight loops processing many objects like telemetry events, `dict.setdefault(key, [])` eagerly instantiates the fallback list on every iteration, causing massive allocation and garbage collection overhead.
**Action:** Use an explicit `if key not in dict: dict[key] = []` check to avoid allocating unneeded fallback objects.

## 2024-05-18 - Inline generators overhead
**Learning:** Inline generators (e.g., `any()` or `all()` with comprehensions) incur significant overhead in hot paths like telemetry validation/serialization.
**Action:** For measurable speedups, avoid them. Instead, use explicit `for` loops, precompile global regex patterns into lists, and utilize fast-fail substring checks.
