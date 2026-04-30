# Quickstart: Action Request Friction Repair

## 1. Verify helper accepts runtime ActionRequest

1. Create a PR-session fixture with one classified item.
2. Run:

```bash
python3 -m gh_address_cr agent next owner/repo 123 --role fixer --agent-id codex-1
```

3. Pass the emitted request path to:

```bash
python3 skill/scripts/submit_action.py <request-path> \
  --agent-id codex-1 \
  --resolution fix \
  --note "Fixed validation." \
  --files src/example.py \
  --validation-cmd "python3 -m unittest tests.test_example=passed"
```

4. Submit the generated response with:

```bash
python3 -m gh_address_cr agent submit owner/repo 123 --input <generated-response>
```

Expected result: `ACTION_ACCEPTED`.

## 2. Verify classification and resolution guidance

Trigger missing classification:

```bash
python3 -m gh_address_cr agent next owner/repo 123 --role fixer
```

Expected result: the summary explains that triage classification evidence is missing and points to `agent classify`.

Trigger missing resolution:

```bash
python3 -m gh_address_cr agent submit owner/repo 123 --input response-without-resolution.json
```

Expected result: the summary explains that fixer response field `resolution` is missing and points to `agent submit` payload requirements.

## 3. Verify batch evidence path

1. Claim two GitHub-thread fixer leases.
2. Create a `BatchActionResponse` with common commit/files/validation evidence and per-thread summaries.
3. Run:

```bash
python3 -m gh_address_cr agent submit-batch owner/repo 123 --input batch-response.json
```

Expected result: `BATCH_ACTION_ACCEPTED`, with `accepted_count` matching the number of items.

4. Mutate one item to use a stale lease and rerun the batch command.

Expected result: `BATCH_ACTION_REJECTED`, with no item accepted.
