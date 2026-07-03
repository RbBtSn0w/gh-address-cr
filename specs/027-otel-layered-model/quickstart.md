# Quickstart: Validate Layered Workflow Telemetry

## Prerequisites

```bash
cd /Users/snow/Documents/GitHub/gh-address-cr-skill
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

Optional test-isolation environment:

```bash
export GH_ADDRESS_CR_TELEMETRY_ENVIRONMENT=test
```

## Scenario 1: Root span contract still holds

Goal: verify the feature preserves one root invocation span per CLI invocation.

```bash
.venv/bin/python -m unittest tests.test_cli_otel_execution tests.test_otel_telemetry
```

Expected outcome:

- Existing root span tests still pass
- No public CLI behavior changes are required to produce the root span

## Scenario 2: Promoted child operations are independently visible

Goal: verify adapter or command-session operations emit child spans while
checkpoint-only phases remain events.

```bash
.venv/bin/python -m unittest \
  tests.test_telemetry_acceptance_matrix \
  tests.test_cli_otel_context \
  tests.test_cli_otel_genai
```

Expected outcome:

- Promoted operations appear as child spans with stable names and expected
  attributes
- Root span still exists and remains the parent anchor
- Session correlation attributes remain optional/fail-open

## Scenario 3: High-level checkpoint phases stay event-shaped unless promoted

Goal: validate that preflight/session/ingest/gate style markers remain events
by default.

Validation path:

1. Add or update an in-memory span exporter test for the relevant high-level
   command path.
2. Assert checkpoint events remain on the correct active span.
3. Assert no redundant child span is emitted for a checkpoint-only phase.

## Scenario 4: No regressions in public CLI behavior

```bash
ruff check src tests scripts/build_plugin_payload.py
.venv/bin/python -m unittest discover -s tests
.venv/bin/python -m gh_address_cr --help
.venv/bin/python -m gh_address_cr agent manifest
.venv/bin/python scripts/build_plugin_payload.py --check
```

Expected outcome:

- Full test suite passes
- CLI smoke surfaces remain stable
- Packaged skill payload still validates

## References

- Contract: [workflow-layering-contract.md](./contracts/workflow-layering-contract.md)
- Data model: [data-model.md](./data-model.md)
- Research rationale: [research.md](./research.md)
