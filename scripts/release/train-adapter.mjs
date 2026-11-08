// Product-owned fixed commands behind the shared release-train operations.
import {execFileSync} from 'node:child_process';
import {mkdirSync} from 'node:fs';
import {join} from 'node:path';
const run=(cwd,env,command,args)=>execFileSync(command,args,{cwd,env,stdio:'inherit'});
export function analyze({cwd,env,args=[]}) {
 if(Number(env.GITHUB_RUN_ATTEMPT||1)>1)throw Error('Original analysis cannot be rerun after possible publication. Recover the original sealed release or dispatch a new release for current main.');
 const index=args.indexOf('--output');const output=index<0?'dist/plan.json':args[index+1];
 mkdirSync(join(cwd,'dist'),{recursive:true});
 return run(cwd,env,process.execPath,['scripts/release/engine.mjs','plan',output]);
}
export function seal({cwd,env}) {return run(cwd,env,'python',['-m','scripts.release.handoff','record','--candidate',env.CANDIDATE]);}
export function publish({cwd,env}) {return run(cwd,env,process.execPath,['scripts/release/engine.mjs','publish','dist/plan.json']);}
export function recover({cwd,env}) {return run(cwd,env,'python',['-m','scripts.release.recovery','--directory','dist']);}
export function report({cwd,env}) {return run(cwd,env,process.execPath,['scripts/release/observe.mjs']);}
