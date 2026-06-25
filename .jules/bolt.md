## 2024-05-18 - Type checking in heavily recursive functions
**Learning:** In heavily recursive functions (like `json_ready` and `_json_ready`), exact type checking (e.g., `type(value) is str`) is measurably faster than `isinstance()` or `is_dataclass()` checks. I observed ~50% speedup by fast-pathing primitive types and standard collections using `type()` before falling back to `isinstance()`.
**Action:** When optimizing recursive tree-traversal functions in Python, evaluate adding a fast-path for common types using exact type matching `type(val) is ...`.
