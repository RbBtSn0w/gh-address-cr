"""Reconcile immutable PyPI files and stage only missing verified archives."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from scripts.release.handoff import verify


def read_version(version: str) -> dict | None:
    if not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', version):
        raise ValueError('expected stable release version')
    try:
        with urlopen(f'https://pypi.org/pypi/gh-address-cr/{version}/json', timeout=20) as response:
            if response.status != 200:
                raise ValueError('unexpected PyPI response status')
            body = response.read(8 * 1024 * 1024 + 1)
            if len(body) > 8 * 1024 * 1024:
                raise ValueError('PyPI response exceeds size limit')
            payload = json.loads(body)
            if not isinstance(payload, dict):
                raise ValueError('malformed PyPI version response')
            return payload
    except HTTPError as error:
        error.close()
        if error.code == 404:
            return None
        raise


def published_files(response: dict | None, version: str) -> dict[str, str]:
    if response is None:
        return {}
    if (not isinstance(response, dict) or not isinstance(response.get('info'), dict)
            or response['info'].get('version') != version or not isinstance(response.get('urls'), list)):
        raise ValueError('malformed PyPI version response')
    files = {}
    for entry in response['urls']:
        if not isinstance(entry, dict):
            raise ValueError('malformed PyPI file')
        name = entry.get('filename')
        digests = entry.get('digests')
        digest = digests.get('sha256') if isinstance(digests, dict) else None
        if (not isinstance(name, str) or not name or Path(name).name != name or '/' in name or '\\' in name
                or name in files or not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest)):
            raise ValueError('malformed or ambiguous PyPI file identity')
        files[name] = digest
    return files


def reconcile(directory: Path, candidate: str, output: Path | None, receipt_path: Path) -> bool:
    # Every rerun revalidates the complete immutable handoff before any network read.
    plan = verify(directory, candidate)
    wheels = list(directory.glob('*.whl'))
    sdists = list(directory.glob('*.tar.gz'))
    if len(wheels) != 1 or len(sdists) != 1:
        raise ValueError('expected exactly one verified wheel and source archive')
    receipt = {'candidate': candidate, 'version': plan['version'], 'files': {}}
    for path in [*wheels, *sdists]:
        receipt['files'][path.name] = {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'status': 'unverified'}
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    try:
        remote = published_files(read_version(plan['version']), plan['version'])
    except (HTTPError, URLError, OSError, ValueError) as error:
        receipt['read_error'] = type(error).__name__
        receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
        raise
    missing = []
    conflicts = False
    for path in [*wheels, *sdists]:
        observed = remote.get(path.name)
        entry = receipt['files'][path.name]
        if observed is not None and observed != entry['sha256']:
            entry['status'] = 'conflict'
            conflicts = True
        else:
            entry['status'] = ('verified' if output is None else 'already-present') if observed else 'missing'
        if observed is None:
            missing.append(path)
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    if conflicts:
        raise ValueError('existing PyPI file has different bytes')
    if output is None:
        if missing:
            raise ValueError('PyPI publication remains missing files; inspect the per-file receipt')
    else:
        # A stale directory must never introduce a previously staged archive.
        output.mkdir(parents=True, exist_ok=False)
        for path in missing:
            shutil.copyfile(path, output / path.name)
    return bool(missing)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['stage', 'confirm'])
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--candidate', required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--receipt', type=Path, required=True)
    args = parser.parse_args()
    if (args.operation == 'stage') != (args.output is not None):
        parser.error('only stage requires --output')
    missing = reconcile(args.directory, args.candidate, args.output, args.receipt)
    if args.operation == 'stage' and os.environ.get('GITHUB_OUTPUT'):
        with Path(os.environ['GITHUB_OUTPUT']).open('a') as stream:
            stream.write(f'missing={str(missing).lower()}\n')


if __name__ == '__main__':
    main()
