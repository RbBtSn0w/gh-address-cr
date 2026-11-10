import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,mkdirSync,readFileSync,writeFileSync,rmSync} from 'node:fs';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
import * as adapter from '../scripts/release/train-adapter.mjs';
import {captureAnalysis} from '../.github/release-train/release-entrypoint.mjs';
import {createPipelinePlan} from '../.github/release-train/pipeline-contract.mjs';
import {reportExitCode} from '../.github/release-train/release-result.mjs';
const candidate='a'.repeat(40);
const identity={candidate_sha:candidate,version:'1.2.3',tag:'v1.2.3',notes:'Original notes',baseline_tag:'v1.2.2'};
const plan=()=>({completed:true,candidate,version:identity.version,tag:identity.tag,notes:identity.notes,baseline:{gitTag:identity.baseline_tag}});
const config=()=>JSON.parse(readFileSync(new URL('../.github/release-train.json',import.meta.url)));
function fixture(fn){const cwd=mkdtempSync(join(tmpdir(),'ghcr-pipeline-'));try{fn(cwd);}finally{rmSync(cwd,{recursive:true,force:true});}}
test('custom adapter captures the engine tag rather than selecting another release version',()=>fixture(cwd=>{
  assert.equal(adapter.pipelineProtocolVersion,1);
  assert.equal(adapter.analysisFile({args:[]}), 'dist/plan.json');
  assert.equal(adapter.analysisFile({args:['--output','sealed/plan.json']}), 'sealed/plan.json');
  assert.deepEqual(adapter.planIdentity(plan()),identity);
  const legacy=plan();delete legacy.tag;assert.equal(adapter.planIdentity(legacy).tag,identity.tag);
  assert.throws(()=>adapter.planIdentity(legacy,{config:{schema_version:2}}),/tag/);
  assert.throws(()=>adapter.planIdentity({...legacy,pipeline:{}}),/tag/);
  mkdirSync(join(cwd,'dist'));writeFileSync(join(cwd,'dist/plan.json'),JSON.stringify(plan()));
  captureAnalysis(adapter,{cwd,args:[],config:config(),env:{GITHUB_REPOSITORY:'example/ghcr',GITHUB_EVENT_NAME:'workflow_dispatch'}});
  const captured=JSON.parse(readFileSync(join(cwd,'dist/plan.json')));
  assert.equal(captured.tag,identity.tag);assert.equal(captured.pipeline.identity.tag,identity.tag);
}));
test('seal and recover reject mismatched original identity before spawning product commands',()=>fixture(cwd=>{
  mkdirSync(join(cwd,'dist'));
  const original=createPipelinePlan({config:config(),identity:{...identity,repository:'example/ghcr'}});
  writeFileSync(join(cwd,'dist/plan.json'),JSON.stringify({...plan(),notes:'Changed notes',pipeline:original}));
  for(const operation of ['seal','recover','publish'])assert.throws(()=>adapter[operation]({cwd,env:{CANDIDATE:candidate}}),/identity/);
}));
test('custom report returns parsed original goals and shared exit policy after configuration advances',()=>fixture(cwd=>{
  const original=config();const stage=structuredClone(original.pipeline.stages[0]);stage.id='original-only';
  original.pipeline.stages.push(stage);original.intended_targets.push('original-only');original.pipeline.goals.push({id:'original-only',stages:['original-only'],asynchronous:false,recovery:'unsupported'});
  mkdirSync(join(cwd,'result-input'));
  writeFileSync(join(cwd,'result-input/plan.json'),JSON.stringify({...plan(),pipeline:createPipelinePlan({config:original,identity:{...identity,repository:'example/ghcr'}})}));
  const env={...process.env,RELEASE_ENABLED:'true',GITHUB_SHA:candidate,RELEASE_TARGETS:'{}',RELEASE_NEEDS:JSON.stringify({verify:{result:'success',outputs:{source_sha:candidate,version:identity.version}}})};
  const result=adapter.report({cwd,env});
  assert.ok(result.intended_targets.includes('original-only'));
  assert.equal(result.pipeline.source,'original-plan');assert.equal(reportExitCode(result),1);
}));
for(const corruption of ['notes','digest'])test(`report retains diagnostics for original ${corruption} conflicts`,()=>fixture(cwd=>{
  mkdirSync(join(cwd,'result-input'));
  const original=createPipelinePlan({config:config(),identity:{...identity,repository:'example/fixture'}});
  const changed={...plan(),pipeline:original};
  if(corruption==='notes')changed.notes='Changed notes';
  else changed.pipeline={...original,digest:'sha256:'+'f'.repeat(64)};
  writeFileSync(join(cwd,'result-input/plan.json'),JSON.stringify(changed));
  const summary=join(cwd,'summary.md');
  const env={...process.env,RELEASE_ENABLED:'true',GITHUB_SHA:candidate,GITHUB_STEP_SUMMARY:summary,RELEASE_TARGETS:'{}',RELEASE_NEEDS:JSON.stringify({verify:{result:'success',outputs:{source_sha:candidate,version:identity.version}}})};
  const result=adapter.report({cwd,env});
  assert.equal(result.failure_stage,'report-inputs');assert.equal(result.verification,'failed');
  assert.equal(result.recovery.available,false);assert.equal(result.recovery.command,undefined);assert.equal(result.pipeline,undefined);
  assert.equal(reportExitCode(result),1);assert.match(readFileSync(summary,'utf8'),/Original.*pipeline|report-inputs/i);
  assert.equal(JSON.parse(readFileSync(join(cwd,'release-result.json'))).failure_stage,'report-inputs');
}));
