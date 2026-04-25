#!/usr/bin/env python3
from __future__ import annotations

import sys

from gh_address_cr.cli import handle_final_gate


def main() -> int:
    return handle_final_gate(None, None, sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
