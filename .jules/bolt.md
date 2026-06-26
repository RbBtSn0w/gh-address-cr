
## 2024-05-18 - Exact type checking vs isinstance/is_dataclass in recursive traversals
**Learning:** In heavily recursive functions (like `json_ready` and `_json_ready`), using exact type checking (e.g., `t = type(value); if t is str:`) is measurably faster (~40% improvement in benchmarks) than `isinstance()` or `is_dataclass()` checks.
**Action:** When implementing heavily recursive data traversal in this Python codebase, prefer exact type matching over `isinstance()` for common base types and collections to reduce overhead.
## 2024-05-18 - Exact type checks can break subclasses
**Learning:** Using exact type checking (`type(x) is dict`) as a performance optimization breaks support for standard library types and subclasses like `collections.defaultdict` and `collections.OrderedDict`.
**Action:** When implementing exact type checks for performance, ALWAYS keep the slower `isinstance()` checks as a fallback after the fast-path exactly-matched types, to ensure correctness for polymorphic objects and subclasses.
