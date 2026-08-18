## 2024-05-24 - Avoid setdefault with eager instantiations
**Learning:** In tight loops, `dict.setdefault(key, [])` or `dict.setdefault(key, {})` eagerly instantiates the default object (like a list or dict) on every iteration, leading to significant allocation overhead.
**Action:** Use an explicit `if key not in dict: dict[key] = ...` instead of `setdefault` when the default value requires instantiation or expensive computation.
