// Product-owned fixed commands behind the shared release-train operations.
import {execFileSync} from 'node:child_process';
import {mkdirSync,readFileSync,rmSync,existsSync} from 'node:fs';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {validateOriginalPlan} from '../../.github/release-train/release-entrypoint.mjs';
import {reportExitCode} from '../../.github/release-train/release-result.mjs';
export const pipelineProtocolVersion=1;
export const analysisFile=({args=[]})=>{const index=args.indexOf('--output');return index<0?'dist/plan.json':args[index+1];};
export function planIdentity(plan,context) {
 if((plan.pipeline||context?.config?.schema_version===2)&&plan.version!==null&&typeof plan.tag!=='string')throw Error('Original engine tag is required for a versioned plan');
 return {candidate_sha:plan.candidate,version:plan.version??null,tag:plan.tag??(plan.version?`v${plan.version}`:undefined),notes:plan.notes,baseline_tag:plan.baseline?.gitTag??null};
}
const validate=context=>validateOriginalPlan(JSON.parse(readFileSync(join(context.cwd,'dist/plan.json'),'utf8')));
const run=(cwd,env,command,args)=>execFileSync(command,args,{cwd,env,stdio:'inherit'});
export function analyze({cwd,env,args=[]}) {
 if(Number(env.GITHUB_RUN_ATTEMPT||1)>1)throw Error('Original analysis cannot be rerun after possible publication. Recover the original sealed release or dispatch a new release for current main.');
 const index=args.indexOf('--output');const output=index<0?'dist/plan.json':args[index+1];
 mkdirSync(join(cwd,'dist'),{recursive:true});
 return run(cwd,env,process.execPath,['scripts/release/engine.mjs','plan',output]);
}
export function seal(context) {validate(context);const {cwd,env}=context;return run(cwd,env,'python',['-m','scripts.release.handoff','record','--candidate',env.CANDIDATE]);}
export function publish(context) {validate(context);const {cwd,env}=context;return run(cwd,env,process.execPath,['scripts/release/engine.mjs','publish','dist/plan.json']);}
export function recover(context) {validate(context);const {cwd,env}=context;return run(cwd,env,'python',['-m','scripts.release.recovery','--directory','dist']);}
export function report({cwd,env}) {
 const output=join(cwd,'release-result.json');
 rmSync(output,{force:true});
 let failure;
 try{run(cwd,env,process.execPath,[fileURLToPath(new URL('./observe.mjs',import.meta.url))]);}catch(error){failure=error;}
 if(failure&&!existsSync(output))throw failure;
 const result=JSON.parse(readFileSync(output,'utf8'));
 if(failure&&failure.status!==reportExitCode(result))throw failure;
 return result;
}
