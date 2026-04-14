Fixed in d753b03.

Updated the `review` alias help text to show `--input` as required (`--input <path>|-`) instead of optional (`[--input <path>|-]`), and updated the description line to say "Provide findings JSON via --input \<path\> or --input - with stdin."

This accurately reflects the runtime behavior: `review` dispatches to `cr_loop.py mixed code-review`, which requires findings JSON input.

**Validation:**
- All 88 tests pass with `pytest tests/ -v`
- Help text now matches: `usage: cli.py review <owner/repo> <pr_number> --input <path>|- [--machine]`
