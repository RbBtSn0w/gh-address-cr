import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {mkdtempSync, readFileSync, mkdirSync, writeFileSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join, resolve} from 'node:path';
import test from 'node:test';
const script = resolve('scripts/release/observe.mjs');
function observe(needs, receipt) {
  const cwd = mkdtempSync(join(tmpdir(), 'release-observation-'));
  try {
    if (receipt) { mkdirSync(join(cwd, 'publication-input')); for(const [name, value] of Object.entries(receipt)) writeFileSync(join(cwd, 'publication-input', name), JSON.stringify(value)); }
    execFileSync(process.execPath, [script], {cwd, env: {...process.env, GITHUB_STEP_SUMMARY: join(cwd, 'summary.md'), RELEASE_NEEDS: JSON.stringify(needs), RELEASE_TARGETS: '{"github": "publish", "pypi": "publish-pypi"}', RELEASE_ENABLED: 'true', RELEASE_OPERATION: 'release', GITHUB_SHA: 'a'.repeat(40)}, stdio: 'pipe'});
    const result = JSON.parse(readFileSync(join(cwd, 'release-result.json')));
    assert.match(readFileSync(join(cwd, 'summary.md'), 'utf8'), /Verification:/);
    return result;
  } finally {rmSync(cwd, {recursive: true, force: true});}
}
test('always result reports failed verification even when all publishers are skipped', () => {
  const result = observe({verify: {result: 'failure'}, 'recovery-input': {result: 'skipped'}, 'publish': {result: 'skipped'}, 'publish-pypi': {result: 'skipped'}, release: {result:'skipped'}});
  assert.equal(result.verification, 'failed');
  assert.equal(result.publication, 'failed');
});
test('completed GitHub and failed PyPI remain a partial publication', () => {
  const result = observe({verify: {result: 'success', outputs: {source_sha: 'a'.repeat(40),version: '1.2.3'}}, publish: {result: 'success'}, 'publish-pypi': {result: 'failure'}});
  assert.equal(result.targets.github.status, 'completed');
  assert.equal(result.targets.pypi.status, 'unknown');
  assert.equal(result.publication, 'partial');
});
