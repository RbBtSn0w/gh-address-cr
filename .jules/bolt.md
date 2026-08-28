## 2025-02-23 - Inline Generator Overhead in Telemetry Hot Paths
**Learning:** Generator expressions passed to functions like `any()` or `sum()` incur significant overhead (generator instantiation, context switching, function calls) in telemetry processing loops. Doing multiple passes over the same event list using comprehensions and generators multiplies this overhead.
**Action:** Use single-pass explicit `for` loops to compute multiple metrics at once (duration, success counts, subsets) to avoid generator overhead and redundant iterations.
