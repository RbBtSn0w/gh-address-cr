## $(date +%Y-%m-%d) - Expensive Default Object Instantiation in `setdefault`
**Learning:** Using `dict.setdefault` in tight loops with complex fallback objects (like new dictionaries with sets) eagerly instantiates the fallback on every iteration, leading to significant allocation overhead. Benchmark showed `if key not in dict:` is ~3.7x faster than `setdefault` for 100k events.
**Action:** Replace `dict.setdefault` with explicit `if key not in dict:` checks in tight loops across the codebase, particularly in telemetry processing.
