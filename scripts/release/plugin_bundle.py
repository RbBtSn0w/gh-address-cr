"""Immutable, source-bound plugin bundles; no GitHub writes or session state."""
from __future__ import annotations

import hashlib
import json
import re
import stat
import sys
import tarfile
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from scripts import build_plugin_payload as builder
from scripts.release import homebrew_support as shared

SCHEMA = 'plugin-publication.v1'
PAYLOAD = 'dist/plugin/gh-address-cr'
CATALOG = '.agents/plugins/marketplace.json'


def encoded(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def asset_names(version: str) -> tuple[str, str, str]:
    shared.stable_version(version)
    if not re.fullmatch(r'(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)', version):
        raise ValueError('expected a canonical stable version')
    archive = f'gh-address-cr-{version}.zip'
    return archive, archive + '.sha256', 'publication.json'


def catalog() -> dict:
    return {'name': 'gh-address-cr-community', 'interface': {'displayName': 'GH Address CR Community'},
            'plugins': [{'name': 'gh-address-cr', 'source': {'source': 'local', 'path': './' + PAYLOAD},
                         'policy': {'installation': 'AVAILABLE', 'authentication': 'ON_INSTALL'},
                         'category': 'Developer Tools'}]}


def readme(version: str) -> str:
    return (f'# GH Address CR Marketplace\n\nStable plugin version: {version}.\n\n'
            'Install the gh-address-cr runtime separately using pipx or Homebrew.\n'
            'Register this Git source with an explicit marketplace ref:\n\n'
            '```bash\ncodex plugin marketplace add RbBtSn0w/gh-address-cr --ref marketplace\n'
            'codex plugin add gh-address-cr@gh-address-cr-community\n```\n\n'
            'See the source repository documentation for update and recovery instructions.\n')


def validate_receipt(value: dict) -> None:
    required = {'schema_version', 'version', 'source_tag', 'source_commit', 'archive', 'files', 'snapshot', 'build_run_url'}
    if not isinstance(value, dict) or set(value) != required or value['schema_version'] != SCHEMA:
        raise ValueError('unsupported publication receipt')
    version = shared.stable_version(value['version'])
    if value['source_tag'] != 'v' + version or not re.fullmatch('[a-f0-9]{40}', value['source_commit']):
        raise ValueError('invalid source identity')
    archive = value['archive']
    if set(archive) != {'name', 'sha256'} or archive['name'] != asset_names(version)[0] or not re.fullmatch('[a-f0-9]{64}', archive['sha256']):
        raise ValueError('invalid archive identity')
    if not re.fullmatch(r'https://github.com/RbBtSn0w/gh-address-cr/actions/runs/[0-9]+', value['build_run_url']):
        raise ValueError('invalid build run URL')
    snapshot = value['snapshot']
    if set(snapshot) != {'catalog', 'readme', 'license'} or snapshot['catalog'] != catalog():
        raise ValueError('invalid marketplace catalog')
    for name in ['readme', 'license']:
        text = snapshot[name]
        if not isinstance(text, str) or not text.strip() or len(text) > 65536:
            raise ValueError('invalid snapshot text')
    files = value['files']
    if not isinstance(files, dict) or not files or len(files) > 1000:
        raise ValueError('invalid file inventory')
    for name, digest in files.items():
        path = PurePosixPath(name)
        if (not isinstance(name, str) or path.is_absolute() or '..' in path.parts or '\\' in name
                or path.as_posix() != name or not re.fullmatch('[a-f0-9]{64}', digest)):
            raise ValueError('invalid file inventory entry')


@dataclass
class Bundle:
    directory: Path
    receipt: dict
    payload: dict[str, bytes]

    def snapshot(self) -> dict[str, bytes]:
        projection = {f'{PAYLOAD}/{name}': data for name, data in self.payload.items()}
        source = self.receipt['snapshot']
        projection.update({CATALOG: encoded(source['catalog']), 'README.md': source['readme'].encode(),
                           'LICENSE': source['license'].encode(), 'publication.json': encoded(self.receipt)})
        return projection


def load_bundle(directory: Path, version: str) -> Bundle:
    try:
        return _load_bundle(directory, version)
    except (KeyError, TypeError, AttributeError, zipfile.BadZipFile) as exc:
        raise ValueError('malformed plugin bundle') from exc


def _load_bundle(directory: Path, version: str) -> Bundle:
    archive_name, checksum_name, receipt_name = asset_names(version)
    receipt_path = directory / receipt_name
    if receipt_path.stat().st_size > 1024 * 1024:
        raise ValueError('publication receipt exceeds size limit')
    receipt = json.loads(receipt_path.read_text())
    validate_receipt(receipt)
    if receipt['version'] != version:
        raise ValueError('bundle version mismatch')
    archive = directory / archive_name
    digest = shared.digest(archive)
    if digest != receipt['archive']['sha256'] or (directory / checksum_name).read_text() != f'{digest}  {archive_name}\n':
        raise ValueError('archive checksum mismatch')
    payload = {}
    with zipfile.ZipFile(archive) as zipped:
        entries = zipped.infolist()
        if len(entries) > 1000 or sum(item.file_size for item in entries) > 32 * 1024 * 1024:
            raise ValueError('archive exceeds payload budget')
        for item in entries:
            path = PurePosixPath(item.filename)
            mode = item.external_attr >> 16
            if (path.is_absolute() or '..' in path.parts or '\\' in item.filename
                    or path.as_posix() != item.filename or len(path.parts) < 2
                    or path.parts[0] != 'gh-address-cr' or item.is_dir()
                    or stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in (0, stat.S_IFREG))):
                raise ValueError('unsafe archive entry')
            relative = '/'.join(path.parts[1:])
            if relative in payload:
                raise ValueError('duplicate archive entry')
            payload[relative] = zipped.read(item)
    if {name: sha(data) for name, data in payload.items()} != receipt['files']:
        raise ValueError('payload inventory mismatch')
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        for name, data in payload.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        builder.validate_payload(root, expected_version=version)
    manifest = json.loads(payload['plugin.json'])
    if manifest['name'] != 'gh-address-cr' or manifest['version'] != version:
        raise ValueError('plugin identity mismatch')
    return Bundle(directory, receipt, payload)


def verify_source(bundle: Bundle, source: Path, *, candidate: str | None = None, verify_generated_payload: bool = False) -> None:
    receipt = bundle.receipt
    commit = candidate or shared.command(['git', 'rev-parse', receipt['source_tag'] + '^{commit}'], cwd=source).stdout.strip()
    if commit != receipt['source_commit']:
        raise ValueError('source tag changed or bundle source mismatch')
    source_files = git_files(source, commit, ['skill', 'LICENSE', 'pyproject.toml', CATALOG, 'scripts/build_plugin_payload.py', 'assets/plugin'])
    expected = {'skills/gh-address-cr/' + path.removeprefix('skill/'): data for path, data in source_files.items()
                if path.startswith('skill/') and not builder.should_exclude(Path(path).relative_to('skill'))}
    actual = {name: data for name, data in bundle.payload.items() if name.startswith('skills/')}
    if actual != expected:
        raise ValueError('skill content or inventory differs from source tag')
    if (source_files['LICENSE'].decode() != receipt['snapshot']['license']
            or json.loads(source_files[CATALOG]) != receipt['snapshot']['catalog']):
        raise ValueError('snapshot differs from source tag')
    expected_assets = {name.removeprefix('assets/plugin/'): data for name, data in source_files.items()
                       if name.startswith('assets/plugin/')}
    actual_assets = {name.removeprefix('assets/'): data for name, data in bundle.payload.items()
                     if name.startswith('assets/')}
    if expected_assets != actual_assets:
        raise ValueError('generated assets differ from source tag')
    if receipt['snapshot']['readme'] != readme(receipt['version']):
        raise ValueError('distribution README differs from its sealed contract')
    if verify_generated_payload:
        verify_generated(bundle, source_files)


def verify_generated(bundle: Bundle, source_files: dict[str, bytes]) -> None:
    # Read-only preparation only: never execute source generators in publish/recover.
    # The resulting bytes are sealed by the receipt and immutable CI artifact.
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        for name, data in source_files.items():
            target = root / 'source' / name
            target.parent.mkdir(parents=True, exist_ok=True)
            if name == 'pyproject.toml':
                import re
                data, count = re.subn(rb'^version = "[^"]+"$', ('version = "' + bundle.receipt['version'] + '"').encode(), data, count=1, flags=re.MULTILINE)
                if count != 1:
                    raise ValueError('missing source package version metadata')
            target.write_bytes(data)
        output = root / 'expected'
        shared.command([sys.executable, '-I', str(root / 'source/scripts/build_plugin_payload.py'),
                        '--output', str(output)], cwd=root)
        generated = {path.relative_to(output).as_posix(): path.read_bytes() for path in output.rglob('*') if path.is_file()}
        if generated != bundle.payload:
            raise ValueError('generated payload differs from the tagged build contract')
        if bundle.receipt['snapshot']['readme'] != readme(bundle.receipt['version']):
            raise ValueError('generated distribution README differs from its contract')


def git_files(source: Path, commit: str, paths: list[str] | None = None) -> dict[str, bytes]:
    with tempfile.TemporaryDirectory() as temporary:
        archive = Path(temporary) / 'tree.tar'
        shared.command(['git', 'archive', '--format=tar', '--output', str(archive), commit, *(paths or [])], cwd=source)
        files = {}
        with tarfile.open(archive) as packed:
            for item in packed:
                if item.isdir():
                    continue
                if not item.isfile() or item.size > 5 * 1024 * 1024:
                    raise ValueError('unsafe source tree member')
                stream = packed.extractfile(item)
                if stream is None:
                    raise ValueError('missing source tree member')
                files[item.name] = stream.read()
        return files
