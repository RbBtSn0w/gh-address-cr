// Read-only product asset observation; no downloaded code is executed.
import {execFileSync} from 'node:child_process';
import {createHash} from 'node:crypto';
import {readFileSync,writeFileSync,mkdirSync} from 'node:fs';
import {join,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {observeGitHub,recoveryFromArtifact} from '../../.github/release-train/observe-github.mjs';
const sha=bytes=>createHash('sha256').update(bytes).digest('hex');
export function observePlatforms({cwd=process.cwd(),env=process.env,read=path=>JSON.parse(execFileSync('gh',['api',path],{encoding:'utf8',timeout:30000})),download=path=>execFileSync('gh',['api',path,'-H','Accept: application/octet-stream'],{timeout:60000,maxBuffer:256*1024*1024})}={}) {
 const load=name=>{try{return JSON.parse(readFileSync(join(cwd,name)));}catch{return null;}};
 const original=load('result-input/plan.json');
 const plan={candidate_sha:original?.candidate,version:original?.version,tag:original?.version?`v${original.version}`:null,notes:original?.notes};
 let observation={targets:{github:{status:'not-run'},stable_tag:{status:'not-run'}},errors:[]};
 let recovery={available:false,blocked_reason:'No original sealed artifact and verified tag are available'};
 if(env.RELEASE_ENABLED==='true'&&plan.version){
  observation=observeGitHub({plan,repository:env.GITHUB_REPOSITORY,read});
  if(observation.targets.github.status==='completed'){
   try{
    const sealed=load('result-input/handoff.json');if(sealed?.candidate!==plan.candidate_sha)throw Error('Original Python handoff is unavailable');const expected=Object.fromEntries(Object.entries(sealed.files).filter(([name])=>name.endsWith('.whl')||name.endsWith('.tar.gz')));if(Object.keys(expected).length!==2)throw Error('Original wheel and sdist are required');
    const release=read(`repos/${env.GITHUB_REPOSITORY}/releases/tags/${encodeURIComponent(plan.tag)}`);
    if(!Object.keys(expected).length)throw Error('Original asset digests are unavailable');
    for(const [name,digest]of Object.entries(expected)){
     const matches=release.assets.filter(asset=>asset.name===name);
     if(matches.length!==1||sha(download(`repos/${env.GITHUB_REPOSITORY}/releases/assets/${matches[0].id}`))!==digest)throw Error('GitHub asset bytes differ from the original verified payload');
    }
    observation.targets.github.files=expected;
   }catch(error){observation.targets.github={status:'unknown',reason:error.message};observation.errors.push(error.message);}
  }
  if(env.RECOVERY_ARTIFACT_ID&&env.ORIGINAL_RUN_ID){
   try{
    const run=read(`repos/${env.GITHUB_REPOSITORY}/actions/runs/${env.ORIGINAL_RUN_ID}`);
    const artifact=read(`repos/${env.GITHUB_REPOSITORY}/actions/artifacts/${env.RECOVERY_ARTIFACT_ID}`);
    recovery=recoveryFromArtifact({plan,repository:env.GITHUB_REPOSITORY,sourceRunId:env.ORIGINAL_RUN_ID,artifactId:env.RECOVERY_ARTIFACT_ID,run,artifact,tagVerified:observation.targets.stable_tag.status==='completed',allowCurrentRunId:env.GITHUB_RUN_ID,recoveryArtifactPrefix:'release-main-verified'});
   }catch(error){recovery={available:false,blocked_reason:error.message};}
  }
 }
 mkdirSync(join(cwd,'publication-input'),{recursive:true});
 writeFileSync(join(cwd,'publication-input/github-observation.json'),JSON.stringify(observation,null,2)+'\n');
 writeFileSync(join(cwd,'publication-input/recovery-availability.json'),JSON.stringify(recovery,null,2)+'\n');
 return {observation,recovery};
}
if(process.argv[1]&&resolve(process.argv[1])===fileURLToPath(import.meta.url))observePlatforms();
