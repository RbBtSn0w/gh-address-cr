# Research: CLI Version Query

## Unknowns & Research Tasks

- **Decision**: Use `argparse`'s built-in `action='version'` for the flag and manual routing for the subcommand.
- **Rationale**: `action='version'` is the standard way to handle version flags in Python. It automatically prints the version and exits. For the `version` subcommand, we need to handle it in `main` or via a dedicated handler to maintain consistency.
- **Alternatives considered**: 
    - Manual flag parsing: Rejected. `argparse` is already used and provides standard support.
    - Only flag, no subcommand: Rejected. Requirements specify both.

## Findings

### 1. argparse Version Action
Standard usage:
```python
parser.add_argument('--version', action='version', version=f'%(prog)s {__version__}')
```
This handles printing and exiting automatically.

### 2. Subcommand Routing
In `gh_address_cr/cli.py`, the `main` function dispatches based on `args.command`. Adding `version` to the supported commands list and handling it in `main` is straightforward.

### 3. Source of Truth
`src/gh_address_cr/__init__.py` already exports `__version__`. This will be imported in `cli.py`.
