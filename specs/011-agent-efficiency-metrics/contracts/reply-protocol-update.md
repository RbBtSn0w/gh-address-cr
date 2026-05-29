# Contracts: Agent Efficiency Metrics

*No external interface contracts (like REST API endpoints or public JSON schemas) are introduced by this feature. The metrics are aggregated in-memory and printed directly into the Markdown reply body.*

However, the internal Python function signature for rendering the reply will be extended.

## Internal Python Contract Update

File: `src/gh_address_cr/core/reply_templates.py`

```python
def fix_reply(
    severity: str | None, 
    payload: list[str], 
    *, 
    summary: str | None = None,
    efficiency_summary: str | None = None  # NEW
) -> str:
    ...
```

The `efficiency_summary` string, if provided, will be appended to the bottom of the returned Markdown string.
