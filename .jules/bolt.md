## 2024-05-24 - Avoid setdefault in hot loops

**Learning:** `dict.setdefault(key, <default_object>)` evaluates and instantiates `<default_object>` on every single iteration, even if the key already exists in the dict. In hot loops processing many items (like telemetry events), instantiating a new list or dict on every iteration causes massive memory allocation overhead.
**Action:** Use explicit `if key not in dict: dict[key] = ...` instead of `setdefault` when the default object is complex, to prevent eager instantiation.