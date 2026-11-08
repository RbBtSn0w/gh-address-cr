import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {mkdtempSync, readFileSync, mkdirSync, writeFileSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join, resolve} from 'node:path';
import test from 'node:test';
const script = resolve('scripts/release/observe.mjs');
const candidate = 'a'.repeat(40);
function observe(receipts = {}, environment = {}) {
  const cwd = mkdtempSync(join(tmpdir(), 'ghcr-outcome-v2-'));
  try {
    mkdirSync(join(cwd, 'publication-input')); mkdirSync(join(cwd, 'result-input'));
    writeFileSync(join(cwd, 'result-input/plan.json'), JSON.stringify({candidate, version: '1.2.3', baseline: {gitTag: 'v1.2.2'}, completed: true, notes: 'Original notes'}));
    writeFileSync(join(cwd,'result-input/handoff.json'),JSON.stringify({candidate,files:{'fixture.whl':'a'.repeat(64),'fixture.tar.gz':'b'.repeat(64)}}));
    for (const [name, value] of Object.entries(receipts)) writeFileSync(join(cwd, 'publication-input', name), JSON.stringify(value));
    const needs = {verify: {result: 'success', outputs: {source_sha: candidate, version: '1.2.3', released: 'true'}}, publish: {result: 'success'}, 'publish-pypi': {result: 'success'}, 'publish-homebrew': {result: 'success'}, 'publish-plugin-marketplace': {result: 'success'}, 'recovery-input': {result: 'skipped'}};
    const result = spawnSync(process.execPath, [script], {cwd, env: {...process.env, GITHUB_STEP_SUMMARY: join(cwd, 'summary.md'), RELEASE_NEEDS: JSON.stringify(needs), RELEASE_TARGETS: '{"github": "publish", "pypi": "publish-pypi", "homebrew": "publish-homebrew", "marketplace": "publish-plugin-marketplace"}', RELEASE_ENABLED: 'true', GITHUB_SHA: candidate, GITHUB_REPOSITORY: 'example/ghcr',...environment}, encoding: 'utf8'});
    assert.ok([0,1].includes(result.status),result.stderr);
    return {...JSON.parse(readFileSync(join(cwd,'release-result.json'))),report_exit_code:result.status};
  } finally {rmSync(cwd, {recursive: true, force: true});}
}
test('job success cannot substitute for GitHub/PyPI/Homebrew/Marketplace receipts', () => {
  const result = observe();
  assert.notEqual(result.publication, 'completed');
  assert.equal(result.schema_version, 2);
  assert.equal(result.report_exit_code,1);
  assert.equal(result.targets.pypi.status, 'unknown');
});
test('a partial wheel-only PyPI receipt never completes the channel', () => {
  const result = observe({'pypi-receipt.json': {candidate, version: '1.2.3', files: {'package.whl': {status: 'verified', sha256: 'a'.repeat(64)}}}});
  assert.notEqual(result.targets.pypi.status, 'completed');
});

const remote={status:'completed',candidate_sha:candidate,version:'1.2.3',observed_at:'2026-11-08T00:00:00Z',remote_id:'42',url:'https://example.invalid/channel'};
const fileDigests={'fixture.whl':'a'.repeat(64),'fixture.tar.gz':'b'.repeat(64)};
const complete={
 'github-observation.json':{targets:{github:remote,stable_tag:remote}},
 'pypi-receipt.json':{candidate,version:'1.2.3',observed_at:remote.observed_at,expected_files:fileDigests,files:Object.fromEntries(Object.entries(fileDigests).map(([name,sha256])=>[name,{sha256,status:'verified'}]))},
 'homebrew-receipt.json':remote,'marketplace-receipt.json':remote,
};
test('all agreed channels require their own exact candidate remote receipt',()=> {
 const result=observe(complete);assert.equal(result.publication,'completed');assert.equal(result.report_exit_code,0);
 assert.deepEqual(result.intended_targets,['stable_tag','github','pypi','homebrew','marketplace']);
});
test('environment mapping cannot omit an intended committed channel',()=> {
 const result=observe({'github-observation.json':complete['github-observation.json']},{RELEASE_TARGETS:'{"github":"publish"}'});
 assert.ok(result.intended_targets.includes('marketplace'));assert.notEqual(result.publication,'completed');
});
test('failed receipt download remains a failed report stage',()=> {
 const result=observe(complete,{REPORT_DOWNLOADS:'{"pypi":{"outcome":"failure"}}'});
 assert.equal(result.failure_stage,'report-input');assert.equal(result.report_exit_code,1);assert.notEqual(result.publication,'completed');
});
test('self-consistent PyPI receipt cannot replace original sealed digests',()=> {
 const altered=structuredClone(complete);
 altered['pypi-receipt.json'].files['fixture.whl'].sha256='c'.repeat(64);
 altered['pypi-receipt.json'].expected_files['fixture.whl']='c'.repeat(64);
 assert.notEqual(observe(altered).targets.pypi.status,'completed');
});
