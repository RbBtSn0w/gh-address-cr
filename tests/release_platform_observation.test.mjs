import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,mkdirSync,writeFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createHash} from 'node:crypto';
import {observePlatforms} from '../scripts/release/observe-platforms.mjs';
const candidate='a'.repeat(40),version='1.2.3';
const hash=bytes=>createHash('sha256').update(bytes).digest('hex');
function exercise({changed=false,missing=false,notes='Original notes',draft=false,denied=false,duplicate=false}={}) {
 const cwd=mkdtempSync(join(tmpdir(),'ghcr-platform-'));
 const files={'fixture.whl':Buffer.from('wheel'),'fixture.tar.gz':Buffer.from('sdist')};
 try {
  mkdirSync(join(cwd,'result-input'));
  writeFileSync(join(cwd,'result-input/plan.json'),JSON.stringify({candidate,version,notes:'Original notes',completed:true}));
  writeFileSync(join(cwd,'result-input/handoff.json'),JSON.stringify({candidate,files:Object.fromEntries(Object.entries(files).map(([name,bytes])=>[name,hash(bytes)]))}));
  const assets=Object.keys(files).map((name,index)=>({name,id:index+1}));
  const read=path=> {
   if(path.includes('/git/ref/'))return {ref:'refs/tags/v'+version,object:{type:'commit',sha:candidate}};
   if(path.includes('/releases/tags/')){if(denied)throw Error('Permission denied');return {id:7,tag_name:'v'+version,body:notes,draft,prerelease:false,assets:duplicate?[...assets,assets[0]]:missing?assets.slice(0,1):assets};}
   if(path.endsWith('/actions/runs/11'))return {id:11,head_sha:candidate,head_branch:'main',event:'schedule',status:'in_progress',run_attempt:2,path:'.github/workflows/release.yml',repository:{full_name:'example/ghcr'}};
   if(path.endsWith('/actions/artifacts/22'))return {id:22,name:'release-main-verified-1',expired:false,workflow_run:{id:11,head_sha:candidate},digest:'sha256:'+'f'.repeat(64),expires_at:'2099-01-01T00:00:00Z'};
   throw Error(path);
  };
  return observePlatforms({cwd,env:{GITHUB_REPOSITORY:'example/ghcr',RELEASE_ENABLED:'true',GITHUB_RUN_ID:'11',ORIGINAL_RUN_ID:'11',RECOVERY_ARTIFACT_ID:'22'},read,
   download:path=>changed?Buffer.from('changed'):Object.values(files)[Number(path.split('/').at(-1))-1]});
 } finally {rmSync(cwd,{recursive:true,force:true});}
}
test('original handoff bytes and first-failure IDs survive prior-attempt producer',()=> {
 const result=exercise();assert.equal(result.observation.targets.github.status,'completed');
 assert.equal(result.recovery.available,true);assert.equal(result.recovery.source_attempt,1);
 assert.match(result.recovery.command,/-f source_run_id=11 -f artifact_id=22/);
});
test('missing or different remote wheel/sdist cannot complete GitHub target',()=> {
 for(const changes of [{changed:true},{missing:true}])assert.equal(exercise(changes).observation.targets.github.status,'unknown');
});
test('known notes or byte conflicts and unreadable channels never offer recovery',()=> {
 for(const changes of [{notes:'Conflicting notes'},{changed:true},{duplicate:true},{denied:true}]){
  const result=exercise(changes);assert.equal(result.recovery.available,false);
  assert.ok(result.recovery.blocked_reason);assert.equal(result.recovery.command,undefined);
 }
});
test('missing assets and content-matching drafts remain eligible for original recovery',()=> {
 for(const changes of [{missing:true},{draft:true}])assert.equal(exercise(changes).recovery.available,true);
});
