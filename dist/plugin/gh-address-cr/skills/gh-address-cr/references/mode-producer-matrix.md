# Mode and Producer Dispatch

`gh-address-cr` has two canonical workflow modes:

- `address`: handle unresolved GitHub review threads.
- `review`: ingest explicit review findings, then use the same resolution and
  publication workflow.

The runtime CLI owns persistence, GitHub side effects, and completion truth.
Review producers only emit structured findings.

## Intake Routes

| Input | Command |
| --- | --- |
| GitHub review threads | `gh-address-cr address <owner/repo> <pr_number> --lean` |
| Structured findings JSON | `gh-address-cr findings <owner/repo> <pr_number> --input - --sync --source <producer>` |
| Executable producer | `gh-address-cr adapter <owner/repo> <pr_number> <adapter_cmd...>` |
| `finding` code fences | `gh-address-cr review-to-findings <owner/repo> <pr_number> --input - --output -`, then pipe its JSON to `findings` |
| GitHub threads plus structured findings | `gh-address-cr review <owner/repo> <pr_number> --input <path>` |

`review` also accepts stdin as
`gh-address-cr review <owner/repo> <pr_number> --input <path>|-`.

Do not invent alternate modes or hidden producer fallbacks. A requested
producer must be invoked explicitly and must fail fast when unavailable.

## Structured Findings Contract

A producer returns one JSON array. `[]` means that the review found no issues.
Empty output, narrative Markdown, malformed JSON, or a non-zero producer exit
is an error.

Each finding requires:

- `title`
- `body`
- `path`
- `line`

Optional fields include `start_line`, `end_line`, `severity`, `category`,
`confidence`, and `head_sha`. Paths must be repository-relative. Finding text
must not contain secrets, raw local paths, or unrelated user data.

## Workflow Boundary

After ingestion:

1. Run `gh-address-cr review` or `gh-address-cr address` to obtain the current
   deterministic work item.
2. Submit decisions through `gh-address-cr agent resolve`.
3. Apply GitHub mutations through `gh-address-cr agent publish`.
4. Finish with `gh-address-cr final-gate`.

See `references/agent-protocol.md` for the structured worker protocol and
`references/completion-contract.md` for completion evidence.
