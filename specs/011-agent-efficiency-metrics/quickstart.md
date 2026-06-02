# Quickstart: Agent Efficiency Metrics

The efficiency metrics layer is completely transparent to the user and runs automatically during any `gh-address-cr` session.

## Generating the Report

When the agent successfully resolves a GitHub thread via the `fix` action, the control plane will aggregate the telemetry gathered during the session.

You don't need to pass any new flags. Just run the agent loop normally:

```bash
gh-address-cr review RbBtSn0w/gh-address-cr 123
```

When the fix reply is generated and posted to GitHub, it will now automatically contain an efficiency appendix:

```markdown
Fixed in `abc1234`.

Severity: `P1` 🔴

What I changed:
...

Why this addresses the CR:
...

Validation:
...

---
> **Agent Efficiency Summary**: 12 tools invoked (85% success). Total tool duration: 45s.
> ⚠️ **Inefficiencies Detected**:
> - `pytest tests/core` ran 3 times consecutively (High Retry Rate).
> - `npm install` took 65s (Exceeds 60s threshold).
```
