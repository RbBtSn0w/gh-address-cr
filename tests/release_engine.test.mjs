import test from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync, spawnSync } from 'node:child_process';
import { mkdtempSync, rmSync, writeFileSync, readFileSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { verifyRelease, configDigest } from '../scripts/release/consistency.mjs';
const engine = pathToFileURL(resolve('scripts/release/engine.mjs')).href;
const git = (cwd, ...args) => execFileSync('git', ['-c', 'core.fsmonitor=false', ...args], {cwd, encoding: 'utf8'}).trim();
function fixture() {
  const cwd = mkdtempSync(join(tmpdir(), 'gh-release-fixture-'));
  git(cwd, 'init', '--quiet', '-b', 'main');
  git(cwd, 'config', 'user.name', 'Fixture'); git(cwd, 'config', 'user.email', 'fixture@example.invalid');
  git(cwd, 'commit', '--quiet', '--allow-empty', '-m', 'fix: baseline');
  git(cwd, 'tag', 'v3.22.0');
  return cwd;
}
function runPlan(cwd) {
  // Isolate semantic-release's stdout hook from node:test's IPC stream.
  return spawnSync(process.execPath, ['--input-type=module', '-e',
    `import {planRelease} from ${JSON.stringify(engine)}; console.log(JSON.stringify(await planRelease(process.argv[1])));`, cwd],
    {encoding: 'utf8', timeout: 30000});
}
test('real API analyzes patch/refactor/minor/breaking/no-op, rejects invalid history', async () => {
  for (const [message, version] of [
    ['fix: repair', '3.22.1'], ['refactor: simplify', '3.22.1'], ['feat: capability', '3.23.0'],
    ['feat!: replace protocol', '4.0.0'], ['fix: repair\n\nBREAKING CHANGE: incompatible', '4.0.0'],
    ['build: metadata\n\nBREAKING CHANGE:   ', null], ['docs: guide', null],
    ['invalid history', 'error'], ['fixup! fix: hidden [skip release]', 'error'],
  ]) {
    const cwd = fixture();
    try {
      git(cwd, 'commit', '--quiet', '--allow-empty', '-m', message);
      const result = runPlan(cwd);
      if (version === 'error') { assert.notEqual(result.status, 0); continue; }
      assert.equal(result.status, 0, result.stderr);
      const plan = JSON.parse(result.stdout.trim().split('\n').at(-1));
      assert.equal(plan.version, version);
      assert.equal(typeof plan.notes, version === null ? "object" : "string");
      if (version !== null) assert.ok(plan.notes.length > 0);
      assert.equal(plan.completed, true);
      assert.equal(plan.candidate, git(cwd, 'rev-parse', 'HEAD'));
      assert.equal(plan.baseline.gitHead, git(cwd, 'rev-parse', 'v3.22.0'));
      assert.deepEqual(git(cwd, 'tag', '--list').split('\n'), ['v3.22.0']);
    } finally { rmSync(cwd, {recursive: true, force: true}); }
  }
});
test('consistency hook rejects every changed publication boundary', () => {
  const cwd = fixture();
  try {
    const candidate = git(cwd, 'rev-parse', 'HEAD');
    const baseline = {version: '3.22.0', gitHead: candidate, gitTag: 'v3.22.0'};
    const plan = {completed: true, candidate, baseline, config: configDigest(), version: '3.22.1'};
    const filename = join(cwd, 'plan.json');
    const context = {cwd, env: {RELEASE_PLAN: filename}, lastRelease: baseline, nextRelease: {version: '3.22.1'}};
    writeFileSync(filename, JSON.stringify(plan));
    verifyRelease({}, context);
    for (const changed of [{completed: false}, {candidate: 'a'.repeat(40)}, {baseline: {}}, {config: 'bad'}, {version: '3.22.2'}]) {
      writeFileSync(filename, JSON.stringify({...plan, ...changed}));
      assert.throws(() => verifyRelease({}, context), /drift/);
    }
    assert.throws(() => verifyRelease({}, {...context, env: {}}), /required/);
  } finally { rmSync(cwd, {recursive: true, force: true}); }
});
test('repeat after a completed release is proven no-op, absent baseline fails', () => {
  const cwd = fixture();
  try {
    git(cwd, 'commit', '--quiet', '--allow-empty', '-m', 'fix: repair');
    git(cwd, 'tag', 'v3.22.1');
    let result = runPlan(cwd);
    assert.equal(result.status, 0, result.stderr);
    assert.equal(JSON.parse(result.stdout.trim().split('\n').at(-1)).version, null);
    git(cwd, 'tag', '-d', 'v3.22.0', 'v3.22.1');
    result = runPlan(cwd);
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /baseline missing/);
  } finally {rmSync(cwd, {recursive: true, force: true});}
});
test('actual metadata-only workflow rejects malformed messages and preserves breaking parsing', async () => {
  const {readFileSync} = await import('node:fs');
  const yaml = readFileSync('.github/workflows/pr-commit-semantics.yml', 'utf8');
  const body = yaml.split('      - name: Validate intended squash message')[1].split('        run: |\n')[1];
  const script = body.split('\n').map(line => line.startsWith('          ') ? line.slice(10) : line).join('\n');
  for (const [title, description, accepted] of [
    ['fix: repair', '', true], ['feat!: replace', '', true], ['build: update', 'BREAKING CHANGE: incompatible', true],
    ['build: update', 'BREAKING CHANGE:   ', true], ['Malformed metadata', '', false], ['fixup! fix: repair', '', false],
  ]) {
    const result = spawnSync('bash', ['-c', script], {env: {...process.env, RELEASE_TOOLS: process.cwd(), PR_TITLE: title, PR_BODY: description}, encoding: 'utf8'});
    assert.equal(result.status === 0, accepted, result.stderr);
  }
});
test('official prepare rejects complete notes drift before service hooks or tag creation',()=>{
  for(const [sealedNotes,generatedNotes,accepted]of [['Original notes (2026-11-08)','Original notes (2026-11-09)',false],[undefined,'Original notes',false],['Original notes','Original notes',true]]){
    const cwd=fixture(),remote=cwd+'-remote.git',filename=cwd+'-plan.json',marker=cwd+'-published';
    try{
      const baseline={version:'3.22.0',gitHead:git(cwd,'rev-parse','v3.22.0'),gitTag:'v3.22.0'};
      git(cwd,'commit','--quiet','--allow-empty','-m','fix: release candidate');
      git(cwd,'clone','--quiet','--bare',cwd,remote);
      writeFileSync(filename,JSON.stringify({completed:true,candidate:git(cwd,'rev-parse','HEAD'),baseline,config:configDigest(),version:'3.22.1',notes:sealedNotes}));
      const result=spawnSync(process.execPath,[resolve('tests/fixtures/run_release_publication.mjs'),cwd,remote,filename,generatedNotes,marker],{encoding:'utf8',timeout:30000});
      assert.equal(result.status===0,accepted,result.stderr);
      const tags=git(cwd,'tag','--list');
      if(accepted){assert.match(tags,/v3.22.1/);assert.equal(readFileSync(marker,'utf8'),'published');}
      else{assert.match(result.stderr,/notes.*(?:drift|unavailable)/i);assert.equal(tags,'v3.22.0');assert.equal(existsSync(marker),false);}
    }finally{for(const path of [cwd,remote,filename,marker])rmSync(path,{recursive:true,force:true});}
  }
});
