## 2024-08-12 - dict.setdefault in Loops

**Learning:** `dict.setdefault(key, [])` creates a new list (or dict) on every single loop iteration, even if the key already exists. In tight loops processing many telemetry events, this adds unnecessary allocation overhead.
**Action:** Replace `dict.setdefault(key, default_complex_object)` inside loops with an explicit `if key not in dict: dict[key] = default_complex_object` pattern to avoid object creation overhead.
