import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,mkdirSync,cpSync,readFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join,resolve} from 'node:path';
import {spawnSync} from 'node:child_process';
const root=resolve('.');
function scaffold(run) {
 const cwd=mkdtempSync(join(tmpdir(),'ghcr-train-cli-'));
 try {
  mkdirSync(join(cwd,'scripts/release'),{recursive:true});mkdirSync(join(cwd,'.github'));
  cpSync(join(root,'.github/release-train'),join(cwd,'.github/release-train'),{recursive:true});
  cpSync(join(root,'.github/release-train.json'),join(cwd,'.github/release-train.json'));
  for(const name of ['train-adapter.mjs','observe.mjs'])cpSync(join(root,'scripts/release',name),join(cwd,'scripts/release',name));
  run(cwd);
 }finally{rmSync(cwd,{recursive:true,force:true});}
}
test('custom common CLI routes report into product adapter without external publication tools',()=>scaffold(cwd=> {
 const result=spawnSync(process.execPath,['.github/release-train/cli.mjs','report'],{cwd,encoding:'utf8',env:{...process.env,GITHUB_SHA:'a'.repeat(40),RELEASE_NEEDS:JSON.stringify({verify:{result:'failure'}}),RELEASE_ENABLED:'false',RELEASE_TARGETS:'{"github":"publish"}',GITHUB_STEP_SUMMARY:join(cwd,'summary.md')}});
 assert.equal(result.status,1,result.stderr);
 const output=JSON.parse(readFileSync(join(cwd,'release-result.json')));
 assert.equal(output.verification,'failed');assert.equal(output.publication,'disabled');assert.ok(output.intended_targets.includes('pypi'));
}));
test('custom analyzer blocks full reruns before loading engine or build tools',()=>scaffold(cwd=> {
 const result=spawnSync(process.execPath,['.github/release-train/cli.mjs','analyze'],{cwd,encoding:'utf8',env:{...process.env,GITHUB_RUN_ATTEMPT:'2'}});
 assert.notEqual(result.status,0);assert.match(result.stderr,/Original analysis cannot be rerun/);assert.doesNotMatch(result.stderr,/MODULE_NOT_FOUND/);
}));
