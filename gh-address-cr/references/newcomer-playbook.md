# Newcomer Playbook

Use this playbook when you are new to `gh-address-cr` and need one repeatable way to run PR review work.

## What Each Tool Owns

- Review producer:
  - finds issues
  - emits findings JSON
- `gh-address-cr`:
  - owns the PR session
  - ingests findings
  - handles GitHub review threads
  - enforces the final gate

Do not treat `gh-address-cr` as the review engine itself. Treat it as the control plane.

## Producer Meaning

`producer=code-review` is a category label, not one fixed skill name.

Examples:

- `/code-review`
- `/code-review-aa`
- `/code-review-bb`
- an agent-native review command

If the upstream review step emits valid findings JSON, `gh-address-cr` can consume it through the `code-review` path.

Use this mapping:

| If your upstream source is... | Use this producer |
| --- | --- |
| only GitHub review threads | no producer; use `remote` |
| an existing findings JSON file | `json` |
| a review skill or review command that emits findings JSON | `code-review` |
| a command whose interface is "print findings JSON" | `adapter` |

Do not put the upstream tool name itself in the producer slot.

- correct advanced form: `$gh-address-cr loop mixed code-review <PR_URL>`
- incorrect: `$gh-address-cr loop mixed code-review-aa <PR_URL>`

## Pick The Right Mode

- `remote`
  - use when you only need to process GitHub review threads
- `local`
  - use when you only need to process local findings
- `mixed`
  - use when you want GitHub review threads and local findings in the same PR session
- `loop`
  - use when you want repeated intake + processing + gate evaluation until the run exits `PASSED`, `BLOCKED`, or `NEEDS_HUMAN`

Default for most real work:

```text
$gh-address-cr review <PR_URL>
```

If you omit the producer:

- `remote`
  - fine; there is no local findings source
- `ingest`
  - defaults to `json`
- `local` and `mixed`
  - fail, because `gh-address-cr` cannot infer whether your source is `json`, `code-review`, or `adapter`

## Findings Input Rule

Use `--input <path>` only when a real JSON file already exists.

Use `--input -` with `stdin` when findings are being produced in the current step.

Do not create ad-hoc temporary files like `dummy.json` or `empty.json` in the project workspace just to drive the workflow.

Accepted findings shapes:

- JSON array of finding objects
- JSON object with `findings`, `issues`, or `results`
- NDJSON

Minimum fields per finding:

- `title`
- `body`
- `path`
- `line`

## Recommended Prompt: `gh-address-cr` First

Use this when `gh-address-cr` is the main entrypoint:

```text
使用 $gh-address-cr 处理这个 PR：<PR_URL>

先让上游 review producer 输出 findings JSON，不要只给 Markdown。
如果 findings 是当前步骤现产出的，优先通过 stdin 传入；只有在已经存在真实 JSON 文件时才使用 --input <path>。
然后由 $gh-address-cr 接管 session、GitHub threads、loop 和 final-gate，直到通过。
```

## Recommended Prompt: Review Command First

Use this when the upstream review command must run first and `gh-address-cr` can only come second:

```text
先运行 <review-command> 审查这个 PR：<PR_URL>，并输出 findings JSON，不要只给 Markdown。
然后把这些 findings 交给 $gh-address-cr，使用 `review` 入口接管。
如果 findings 已经是现成文件，用 --input <path>；如果是当前步骤现产出的，优先用 --input - 通过 stdin 传入。
最后由 $gh-address-cr 负责 intake、session、reply/resolve 和 final-gate。
```

## What Completion Means

Do not stop at "looks fixed".

Completion requires:

- `Verified: 0 Unresolved Threads found`
- `SESSION GATE PASS`
- `REMOTE GATE PASS`

If gate fails, continue iteration.

## Common Mistakes

- Running a review producer but only collecting Markdown
- Treating `producer=code-review` as one mandatory skill name
- Creating temporary findings files in the repo root
- Forgetting that GitHub review threads require both reply and resolve
- Declaring success before the final gate passes
