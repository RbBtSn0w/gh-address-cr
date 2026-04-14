#!/usr/bin/env sh
set -e
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 "$script_dir/cli.py" review-to-findings "$@"
