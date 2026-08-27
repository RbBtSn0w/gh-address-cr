## 2026-08-27 - [Avoid setdefault for Complex Fallbacks in Hot Paths]
**Learning:** Using `dict.setdefault(key, [])` in a hot loop (like telemetry event processing) causes the fallback object (`[]`) to be eagerly instantiated on every single iteration, leading to significant allocation overhead.
**Action:** Use an explicit `if key not in dict: dict[key] = []` check in performance-critical code paths when the default value requires instantiation.
