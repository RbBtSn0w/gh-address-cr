# Quickstart: Fix-All Thread Replies

## 1. Reproduce the current generic shortcut problem

Create or use a test session with two actionable GitHub review threads on the
same file but with different reviewer questions.

Expected current risk:

- `agent fix-all` can accept both items using only commit, file, and validation
  evidence.
- Accepted responses contain generic shortcut rationale rather than targeted
  answers for each question.

This scenario should become a failing regression test before implementation.

## 2. Verify default addressing prefers per-thread batch evidence

Run the high-level addressing path for a PR with multiple actionable review
threads.

Expected result:

- The machine summary includes the thread list and batch skeleton.
- The primary next action points agents to per-thread `BatchActionResponse`
  evidence.
- Any `fix-all` hint is narrow and explicitly limited to homogeneous repeated
  concerns.

## 3. Verify mixed-question fix-all rejection

Attempt `agent fix-all` on two same-file threads with different bodies and no
per-item evidence.

Expected result:

- The command exits before accepting evidence.
- No item moves to publish-ready.
- The machine summary explains that generic fix-all is unsafe for mixed or
  uncertain threads.
- The next action points to the per-thread batch skeleton.

## 4. Verify per-item evidence acceptance

Submit or route per-item evidence for the same mixed threads.

Expected result:

- Each item preserves its own `summary` and `why`.
- Shared commit, files, and validation are reused.
- Accepted responses move to publish-ready without duplicate lease or item
  errors.

## 5. Verify published replies are targeted

Publish the accepted mixed-thread evidence using a fake GitHub client in tests.

Expected result:

- Two reply bodies are posted.
- The bodies are not identical.
- Each body includes the item-specific rationale matching the corresponding
  reviewer question.
- Shared validation evidence is still present in both replies.

## 6. Verify homogeneous repeated-nit shortcut still works

Run `agent fix-all` on repeated low-risk nits that share the same concern and
same rationale.

Expected result:

- The shortcut can accept the batch when homogeneity is explicit.
- Runtime lease, validation, reply evidence, publish, and final-gate rules are
  unchanged.

## 7. Verify documentation and full checks

Run the relevant focused tests first:

```bash
python3 -m unittest tests.test_control_plane_workflow tests.test_native_workflow tests.test_skill_docs tests.test_python_wrappers
```

Then run repository checks before completion:

```bash
ruff check src tests
python3 -m unittest discover -s tests
python3 -m gh_address_cr --help
```

For real PR-session handling work, finish with:

```bash
gh-address-cr final-gate <owner/repo> <pr_number>
```
