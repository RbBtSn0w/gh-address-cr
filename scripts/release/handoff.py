"""Bind verified release bytes to one candidate and reject changed handoffs."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


def inventory(directory: Path) -> dict[str, str]:
    files = {}
    for path in sorted(directory.rglob('*')):
        if path.is_symlink():
            raise ValueError('symlink in release handoff')
        if path.is_file() and path != directory / 'handoff.json':
            files[path.relative_to(directory).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    if not files or not any(name.endswith('.whl') for name in files) or not any(name.endswith('.tar.gz') for name in files):
        raise ValueError('missing release archives')
    return files


def verify(directory: Path, candidate: str) -> dict:
    receipt = json.loads((directory / 'handoff.json').read_text())
    plan = json.loads((directory / 'plan.json').read_text())
    if receipt['candidate'] != candidate or plan['candidate'] != candidate or not plan['completed'] or not plan['version']:
        raise ValueError('candidate mismatch or incomplete release analysis')
    if receipt['files'] != inventory(directory):
        raise ValueError('release artifact checksum or inventory mismatch')
    return plan


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['record', 'verify'])
    parser.add_argument('--directory', type=Path, default=Path('dist'))
    parser.add_argument('--candidate', required=True)
    args = parser.parse_args()
    if subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip() != args.candidate:
        raise ValueError('checkout candidate mismatch')
    if args.operation == 'record':
        (args.directory / 'handoff.json').write_text(json.dumps({'candidate': args.candidate, 'files': inventory(args.directory)}, sort_keys=True))
    verify(args.directory, args.candidate)


if __name__ == '__main__':
    main()
