// Read-only product asset observation; no downloaded code is executed.
import {execFileSync} from 'node:child_process';
import {readFileSync,writeFileSync,mkdirSync} from 'node:fs';
import {join,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {observeGitHub,refineGitHubAssets,recoveryFromArtifact} from '../../.github/release-train/observe-github.mjs';
export function observePlatforms({cwd=process.cwd(),env=process.env,read=path=>JSON.parse(execFileSync('gh',['api',path],{encoding:'utf8',timeout:30000})),download=path=>execFileSync('gh',['api',path,'-H','Accept: application/octet-stream'],{timeout:60000,maxBuffer:256*1024*1024})}={}) {
 const load=name=>{try{return JSON.parse(readFileSync(join(cwd,name)));}catch{return null;}};
 const original=load('result-input/plan.json');
 const plan={candidate_sha:original?.candidate,version:original?.version,tag:original?.version?`v${original.version}`:null,notes:original?.notes};
 let observation={targets:{github:{status:'not-run'},stable_tag:{status:'not-run'}},errors:[]};
 let recovery={available:false,blocked_reason:'No original sealed artifact and verified tag are available'};
 if(env.RELEASE_ENABLED==='true'&&plan.version){
  observation=observeGitHub({plan,repository:env.GITHUB_REPOSITORY,read});
  if(observation.recovery?.state==='repairable'){
   try{
    const sealed=load('result-input/handoff.json');if(sealed?.candidate!==plan.candidate_sha)throw Error('Original Python handoff is unavailable');const expected=Object.fromEntries(Object.entries(sealed.files).filter(([name])=>name.endsWith('.whl')||name.endsWith('.tar.gz')));if(Object.keys(expected).length!==2)throw Error('Original wheel and sdist are required');
    observation=refineGitHubAssets({observation,expectedAssets:Object.fromEntries(Object.entries(expected).map(([name,digest])=>[name,`sha256:${digest}`])),readAsset:asset=>download(`repos/${env.GITHUB_REPOSITORY}/releases/assets/${asset.id}`)});
   }catch(error){observation.targets.github={status:'unknown',reason:error.message};observation.errors.push(error.message);observation.recovery={...observation.recovery,state:'unknown',reason:error.message};}
  }
  if(env.RECOVERY_ARTIFACT_ID&&env.ORIGINAL_RUN_ID){
   try{
    const run=read(`repos/${env.GITHUB_REPOSITORY}/actions/runs/${env.ORIGINAL_RUN_ID}`);
    const artifact=read(`repos/${env.GITHUB_REPOSITORY}/actions/artifacts/${env.RECOVERY_ARTIFACT_ID}`);
    recovery=recoveryFromArtifact({plan,repository:env.GITHUB_REPOSITORY,sourceRunId:env.ORIGINAL_RUN_ID,artifactId:env.RECOVERY_ARTIFACT_ID,run,artifact,tagVerified:observation.targets.stable_tag.status==='completed',publicationObservation:observation,allowCurrentRunId:env.GITHUB_RUN_ID,recoveryArtifactPrefix:'release-main-verified'});
   }catch(error){recovery={available:false,blocked_reason:error.message};}
  }
 }
 mkdirSync(join(cwd,'publication-input'),{recursive:true});
 writeFileSync(join(cwd,'publication-input/github-observation.json'),JSON.stringify(observation,null,2)+'\n');
 writeFileSync(join(cwd,'publication-input/recovery-availability.json'),JSON.stringify(recovery,null,2)+'\n');
 return {observation,recovery};
}
if(process.argv[1]&&resolve(process.argv[1])===fileURLToPath(import.meta.url))observePlatforms();
