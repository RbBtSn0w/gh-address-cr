import semanticRelease from 'semantic-release';
import {writeFileSync} from 'node:fs';
import {fileURLToPath,pathToFileURL} from 'node:url';

const [cwd,remote,filename,notes,marker]=process.argv.slice(2);
const consistency=fileURLToPath(new URL('../../scripts/release/consistency.mjs',import.meta.url));
await semanticRelease({
  branches:['main'],repositoryUrl:pathToFileURL(remote).href,ci:false,
  plugins:[
    {analyzeCommits:()=> 'patch',generateNotes:()=>notes},
    consistency,
    {prepare:()=>writeFileSync(marker,'prepared'),publish:()=>writeFileSync(marker,'published')},
  ],
},{cwd,env:{PATH:process.env.PATH,RELEASE_PLAN:filename,GIT_CONFIG_NOSYSTEM:'1',GIT_CONFIG_GLOBAL:'/dev/null'},stdout:{write(){}},stderr:{write(){}}});
