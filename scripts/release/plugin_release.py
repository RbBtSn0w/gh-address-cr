"""Prepare, publish and recover immutable stable Codex marketplace snapshots."""
from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from packaging.version import Version

from scripts import build_plugin_payload as builder
from scripts.release import homebrew_support as shared
from scripts.release.plugin_bundle import (
    SCHEMA,
    Bundle,
    asset_names,
    catalog,
    encoded,
    git_files,
    load_bundle,
    readme,
    sha,
    validate_receipt,
    verify_source,
)

ROOT = Path(__file__).resolve().parents[2]
BRANCH = 'marketplace'
REMOTE = 'https://github.com/RbBtSn0w/gh-address-cr.git'


def phase(name: str) -> None:
    shared.add_current_span_event('release.plugin.phase', {'release.phase': name})


def prepare(directory: Path, version: str, *, source: Path = ROOT, run_url: str | None = None) -> None:
    shared.stable_version(version)
    phase('prepare')
    commit = shared.command(['git', 'rev-parse', 'HEAD'], cwd=source).stdout.strip()
    if shared.command(['git', 'rev-parse', f'v{version}^{{commit}}'], cwd=source).stdout.strip() != commit:
        raise ValueError('plugin build must run at the exact stable source tag')
    if shared.command(['git', 'status', '--porcelain', '--untracked-files=no'], cwd=source).stdout.strip():
        raise ValueError('plugin build requires clean tracked source')
    directory.mkdir(parents=True, exist_ok=True)
    archive_name, checksum_name, _ = asset_names(version)
    with tempfile.TemporaryDirectory() as temporary:
        payload = Path(temporary) / 'gh-address-cr'
        builder.build_payload(payload, source_root=source / "skill", pyproject_path=source / "pyproject.toml", assets_root=source / "assets/plugin")
        builder.validate_payload(payload, pyproject_path=source / "pyproject.toml")
        builder.write_archive(payload, directory / archive_name, pyproject_path=source / "pyproject.toml")
        files = {path.relative_to(payload).as_posix(): sha(path.read_bytes()) for path in sorted(payload.rglob('*')) if path.is_file()}
    archive_hash = shared.digest(directory / archive_name)
    receipt = {'schema_version': SCHEMA, 'version': version, 'source_tag': 'v' + version,
               'source_commit': commit, 'archive': {'name': archive_name, 'sha256': archive_hash},
               'files': files, 'build_run_url': run_url or f'https://github.com/{shared.REPOSITORY}/actions/runs/{os.environ.get("GITHUB_RUN_ID", "")}',
               'snapshot': {'catalog': catalog(), 'readme': readme(version), 'license': (source / 'LICENSE').read_text()}}
    validate_receipt(receipt)
    (directory / checksum_name).write_text(f'{archive_hash}  {archive_name}\n')
    (directory / 'publication.json').write_bytes(encoded(receipt))
    verify_source(load_bundle(directory, version), source)
    phase('validated')


def publication_policy(current: dict | None, candidate: dict) -> str:
    validate_receipt(candidate)
    if current is None:
        return 'publish'
    validate_receipt(current)
    comparison = (Version(candidate['version']) > Version(current['version'])) - (Version(candidate['version']) < Version(current['version']))
    if comparison > 0:
        return 'publish'
    if comparison < 0:
        return 'superseded'
    if current != candidate:
        raise ValueError('same-version publication diverges; publish a new version')
    return 'unchanged'


def require_release(version: str) -> dict:
    shared.stable_version(version)
    result = shared.github_json(f'repos/{shared.REPOSITORY}/releases/tags/v{version}')
    if result['tag_name'] != f'v{version}' or result['draft'] or result['prerelease']:
        raise ValueError('expected a published stable GitHub Release')
    return result


class PluginAssets(shared.ReleaseAssets):
    def __init__(self, version: str):
        super().__init__('v' + shared.stable_version(version))

    def upload_verified(self, path: Path) -> None:
        if path.name not in self.names():
            try:
                shared.command(['gh', 'release', 'upload', self.tag, str(path), '--repo', shared.REPOSITORY])
            except (ValueError, OSError, subprocess.SubprocessError):
                # A lost response is not permission to replay a write blindly.
                if path.name not in self.names():
                    raise
        self.verify(path)


def git_environment(env: dict | None = None) -> dict:
    result = dict(os.environ if env is None else env)
    token = result.get('GH_TOKEN') or result.get('GITHUB_TOKEN')
    if token:
        count = int(result.get('GIT_CONFIG_COUNT', '0'))
        result[f'GIT_CONFIG_KEY_{count}'] = 'http.https://github.com/.extraheader'
        result[f'GIT_CONFIG_VALUE_{count}'] = 'AUTHORIZATION: basic ' + base64.b64encode(('x-access-token:' + token).encode()).decode()
        result['GIT_CONFIG_COUNT'] = str(count + 1)
    return result


def _git(work: Path, *args: str, check: bool = True, env: dict | None = None) -> str:
    return shared.command(['git', '-c', 'core.fsmonitor=false', *args], cwd=work, check=check, env=git_environment(env)).stdout.strip()


def _fetch(work: Path, remote: str) -> str | None:
    result = shared.command(['git', 'ls-remote', '--exit-code', remote, f'refs/heads/{BRANCH}'], cwd=work, check=False, env=git_environment())
    if result.returncode == 2:
        return None
    if result.returncode:
        raise ValueError('cannot inspect remote marketplace ref')
    _git(work, 'fetch', '--quiet', remote, f'refs/heads/{BRANCH}')
    return _git(work, 'rev-parse', 'FETCH_HEAD')


def _tree(work: Path, commit: str) -> dict[str, bytes]:
    return git_files(work, commit)


def _validate_remote_tree(files: dict[str, bytes]) -> dict:
    try:
        receipt = json.loads(files['publication.json'])
        validate_receipt(receipt)
        expected_names = {f'dist/plugin/gh-address-cr/{name}' for name in receipt['files']}
        expected_names |= {'.agents/plugins/marketplace.json', 'README.md', 'LICENSE', 'publication.json'}
        if set(files) != expected_names:
            raise ValueError('remote snapshot has missing or unexpected files')
        for name, digest in receipt['files'].items():
            if sha(files[f'dist/plugin/gh-address-cr/{name}']) != digest:
                raise ValueError('remote payload diverges from its receipt')
        snapshot = receipt['snapshot']
        if (files['.agents/plugins/marketplace.json'] != encoded(snapshot['catalog'])
                or files['README.md'] != snapshot['readme'].encode()
                or files['LICENSE'] != snapshot['license'].encode()):
            raise ValueError('remote metadata diverges from its receipt')
        return receipt
    except (KeyError, TypeError) as exc:
        raise ValueError('malformed remote snapshot') from exc


def verify_remote(bundle: Bundle, remote: str, commit: str) -> None:
    phase('verify')
    with tempfile.TemporaryDirectory() as temporary:
        work = Path(temporary)
        _git(work, 'init', '-q')
        _git(work, 'fetch', '--quiet', remote, f'refs/heads/{BRANCH}')
        observed = _git(work, 'rev-parse', 'FETCH_HEAD')
        if observed != commit or _tree(work, observed) != bundle.snapshot():
            raise ValueError('remote verification mismatch; publication is not proven')


def publish_git(bundle: Bundle, remote: str = REMOTE) -> dict:
    phase('git')
    with tempfile.TemporaryDirectory() as temporary:
        work = Path(temporary)
        _git(work, 'init', '-q')
        _git(work, 'config', 'user.name', 'github-actions[bot]')
        _git(work, 'config', 'user.email', '41898282+github-actions[bot]@users.noreply.github.com')
        for _ in range(3):
            parent = _fetch(work, remote)
            current = _validate_remote_tree(_tree(work, parent)) if parent else None
            decision = publication_policy(current, bundle.receipt)
            if decision == 'superseded':
                return {'status': decision, 'commit': parent, 'version': bundle.receipt['version']}
            if decision == 'unchanged':
                verify_remote(bundle, remote, parent)
                return {'status': decision, 'commit': parent, 'version': bundle.receipt['version']}
            snapshot = work / 'snapshot'
            if snapshot.exists():
                shutil.rmtree(snapshot)
            snapshot.mkdir()
            for name, data in bundle.snapshot().items():
                path = snapshot / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            env = dict(os.environ, GIT_INDEX_FILE=str(work / 'publication-index'), GIT_WORK_TREE=str(snapshot))
            _git(work, 'read-tree', '--empty', env=env)
            _git(work, 'add', '--all', env=env)
            tree = _git(work, 'write-tree', env=env)
            args = ['commit-tree', tree]
            if parent:
                args += ['-p', parent]
            args += ['-m', f'chore(plugin): publish {bundle.receipt["version"]} from {bundle.receipt["source_commit"]}']
            commit = _git(work, *args)
            result = shared.command(['git', 'push', '--quiet', remote, f'{commit}:refs/heads/{BRANCH}'], cwd=work, check=False, env=git_environment())
            if result.returncode == 0:
                verify_remote(bundle, remote, commit)
                return {'status': 'published', 'commit': commit, 'version': bundle.receipt['version']}
            # Includes uncertain push responses: re-read before another write.
        raise ValueError('marketplace publication failed after three reconciled attempts')


def publish(directory: Path, version: str, *, source: Path = ROOT) -> dict:
    bundle = load_bundle(directory, version)
    verify_source(bundle, source)
    require_release(version)
    phase('assets')
    assets = PluginAssets(version)
    for name in asset_names(version):
        assets.upload_verified(directory / name)
    result = publish_git(bundle)
    phase('completed')
    return result


def recover(directory: Path, version: str) -> dict:
    require_release(version)
    phase('recover')
    assets = PluginAssets(version)
    names = asset_names(version)
    if not set(names) <= assets.names():
        raise ValueError('missing immutable plugin assets; recovery never rebuilds source')
    for name in names:
        assets.download(name, directory)
    return publish(directory, version)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['prepare', 'publish', 'recover'])
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--version', required=True)
    args = parser.parse_args()
    try:
        if args.operation == 'prepare':
            prepare(args.directory, args.version)
            result = {'status': 'prepared', 'version': args.version}
        elif args.operation == 'recover':
            result = recover(args.directory, args.version)
        else:
            result = publish(args.directory, args.version)
        print(json.dumps(result, sort_keys=True))
        summary = os.environ.get('GITHUB_STEP_SUMMARY')
        if summary:
            receipt = load_bundle(args.directory, args.version).receipt
            with Path(summary).open('a') as output:
                output.write(f'### Plugin distribution: {result["status"]}\n\nVersion: {args.version}\n\n'
                             f'Source: `{receipt["source_commit"]}`\n\nZIP SHA-256: `{receipt["archive"]["sha256"]}`\n\n'
                             f'Marketplace commit: `{result.get("commit", "not published")}`\n\n'
                             'Recovery: run **Recover Plugin Marketplace** with this stable version.\n')
        return 0
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print(f'Plugin distribution failed: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(shared.traced_main(main))
