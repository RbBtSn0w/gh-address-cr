"""Exercise real Codex Git marketplace installs on a disposable Actions runner."""
from __future__ import annotations

import argparse
import functools
import json
import os
import shutil
import sys
import tempfile
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from scripts import build_plugin_payload as builder
from scripts.release import homebrew_support as shared
from scripts.release.plugin_bundle import CATALOG, PAYLOAD, catalog, encoded


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass


def require_disposable_profile() -> None:
    if os.environ.get('GITHUB_ACTIONS') != 'true':
        raise ValueError('Codex install smoke requires a disposable GitHub Actions runner')
    if os.environ.get('CODEX_HOME'):
        raise ValueError('Codex install smoke does not allow CODEX_HOME overrides')
    home = Path.home()
    if any(path.exists() for path in [home / '.codex/auth.json', home / '.codex/config.toml',
                                     home / '.codex/plugins', home / '.agents/plugins']):
        raise ValueError('Codex profile is already populated; refusing to alter existing installation')


def run_smoke(codex: str) -> dict:
    require_disposable_profile()
    version = shared.command([codex, '--version']).stdout.strip()
    if version != 'codex-cli 0.166.0':
        raise ValueError('Codex smoke requires exactly codex-cli 0.166.0')
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        source = root / 'source'
        source.mkdir()
        def git(*args: str) -> str:
            return shared.command(['git', '-c', 'core.fsmonitor=false', *args], cwd=source).stdout.strip()
        git('init', '-q', '-b', 'marketplace')
        git('config', 'user.name', 'Marketplace Smoke')
        git('config', 'user.email', 'smoke@example.invalid')
        (source / CATALOG).parent.mkdir(parents=True)
        (source / CATALOG).write_bytes(encoded(catalog()))
        bare = root / 'marketplace.git'

        def install_fixture(number: str) -> None:
            payload = source / PAYLOAD
            if payload.exists():
                shutil.rmtree(payload)
            project = root / 'version.toml'
            project.write_text(f'version = "{number}"\n')
            builder.build_payload(payload, pyproject_path=project)
            git('add', '--all')
            git('commit', '-qm', f'fixture {number}')
            if not bare.exists():
                git('clone', '--bare', '-q', str(source), str(bare))
            else:
                git('push', '-q', str(bare), 'marketplace')
            shared.command(['git', '--git-dir', str(bare), 'update-server-info'])

        install_fixture('1.0.0')
        handler = functools.partial(QuietHandler, directory=str(root))
        with ThreadingHTTPServer(('127.0.0.1', 0), handler) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                url = f'http://127.0.0.1:{server.server_port}/marketplace.git'
                def cli(*args: str) -> str:
                    return shared.command([codex, 'plugin', *args], cwd=root, timeout=120).stdout
                shared.add_current_span_event('release.plugin.smoke', {'release.phase': 'install'})
                cli('marketplace', 'add', url, '--ref', 'marketplace', '--json')
                available = cli('list', '--available', '--marketplace', 'gh-address-cr-community', '--json')
                if 'gh-address-cr' not in available:
                    raise ValueError('plugin was not discovered')
                cli('add', 'gh-address-cr@gh-address-cr-community', '--json')
                first = installed_version(codex, cwd=root)
                if first != '1.0.0':
                    raise ValueError('first plugin installation did not load version 1.0.0')
                install_fixture('1.0.1')
                shared.add_current_span_event('release.plugin.smoke', {'release.phase': 'upgrade'})
                cli('marketplace', 'upgrade', 'gh-address-cr-community', '--json')
                after_catalog = installed_version(codex, cwd=root)
                # Re-adding an installed selection is the supported CLI install entrypoint.
                cli('add', 'gh-address-cr@gh-address-cr-community', '--json')
                if installed_version(codex, cwd=root) != '1.0.1':
                    raise ValueError('installed files did not update after refresh and plugin add')
                return {'codex_version': version, 'initial_version': first, 'version_after_catalog_refresh': after_catalog,
                        'installed_version': '1.0.1', 'status': 'passed'}
            finally:
                server.shutdown()
                thread.join(timeout=10)


def installed_version(codex: str, *, cwd: Path | None = None) -> str:
    result = shared.command([codex, 'plugin', 'list', '--marketplace', 'gh-address-cr-community', '--json'], cwd=cwd)
    rows = json.loads(result.stdout)['installed']
    selected = [row for row in rows if row['name'] == 'gh-address-cr' and row['marketplaceName'] == 'gh-address-cr-community'
                and row['installed'] is True and row['enabled'] is True]
    if len(selected) != 1:
        raise ValueError('expected exactly one active installed plugin')
    version = selected[0]['version']
    root = Path.home() / '.codex/plugins/cache/gh-address-cr-community/gh-address-cr' / version
    if json.loads((root / 'plugin.json').read_text())['version'] != version:
        raise ValueError('active installed manifest differs from selected version')
    for source in builder.SKILL_ROOT.rglob('*'):
        if source.is_file() and not builder.should_exclude(source.relative_to(builder.SKILL_ROOT)):
            if (root / 'skills/gh-address-cr' / source.relative_to(builder.SKILL_ROOT)).read_bytes() != source.read_bytes():
                raise ValueError('active installed skill content differs from expected source')
    return version


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codex', required=True)
    args = parser.parse_args()
    try:
        result = run_smoke(args.codex)
        print(json.dumps(result, indent=2))
        if os.environ.get('GITHUB_STEP_SUMMARY'):
            with Path(os.environ['GITHUB_STEP_SUMMARY']).open('a') as output:
                output.write('### Codex marketplace compatibility\n\n```json\n' + json.dumps(result, indent=2) + '\n```\n')
        return 0
    except (ValueError, OSError) as exc:
        print(f'Codex marketplace smoke failed: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(shared.traced_main(main))
