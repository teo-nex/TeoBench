// Clean Pi host controller. Every model tool acts in one owned task container.
import fs from 'node:fs';
import {spawn} from 'node:child_process';
import {pathToFileURL} from 'node:url';
import {createHash} from 'node:crypto';
import {providerFailure} from './pi_failure.mjs';
import {checkpointFile} from './medium_atomic.mjs';
const input=JSON.parse(fs.readFileSync(0,'utf8'));
const hash=x=>createHash('sha256').update(x).digest('hex');
let session,fatal,failure,requests=0,started=false,images=0,paused=0,quotaWaiting=false,timer;
const origin=performance.now(),history=[],dispatches=[];
const engineEnv=Object.fromEntries(Object.entries(input.engineEnvironment).filter(([k])=>
 ['PATH','HOME','USERPROFILE','SystemRoot','SYSTEMROOT','COMSPEC','PATHEXT','TEMP','TMP','DOCKER_HOST','DOCKER_CONFIG','PYTHONPATH'].includes(k)));
const activeSeconds=()=>Math.max(0,(performance.now()-origin-paused)/1000);
const receipt={profile:input.profile.id,profile_sha256:input.profileHash,pi_version:input.profile.pi_version,
 benchmark_model:input.benchmarkModel,request_model:input.model,provider:input.provider,effort:input.effort,
 transport_sha256:input.transportHash,public_task_sha256:hash(input.prompt),
 tools:['terminal','inspect_image'],no_personal_resources:true,no_retries:true};
const save=extra=>{
 const value={status:'RUNNING',inference_started:started,requests,tool_history:history,dispatches,
  active_seconds:activeSeconds(),quota_waiting:quotaWaiting,quota_wait_seconds:paused/1000,receipt,...extra};
 checkpointFile(input.resultPath,value);
};
const blocked=code=>{throw new Error(code);};
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
function command(executable,args,env,stdin='',seconds=60,limit=64000){
 return new Promise((resolve,reject)=>{
  const child=spawn(executable,args,{env,stdio:['pipe','pipe','pipe']});
  let output=Buffer.alloc(0),truncated=false,timedOut=false;
  child.stdout.on('data',chunk=>{if(output.length+chunk.length>limit)truncated=true;output=Buffer.concat([output,chunk]).subarray(0,limit);});
  // Engine errors cannot carry gateway credentials. Keep stderr separate from
  // image JSON, and bounded for diagnostics rather than forwarding host paths.
  let errors=Buffer.alloc(0);
  child.stderr.on('data',chunk=>{errors=Buffer.concat([errors,chunk]).subarray(0,64000);});
  child.stdin.on('error',()=>{});child.stdin.end(stdin);
  const deadline=setTimeout(()=>{timedOut=true;child.kill('SIGKILL');},seconds*1000);
  child.on('error',()=>{clearTimeout(deadline);reject(new Error('sandbox_transport_error'));});
  child.on('close',code=>{clearTimeout(deadline);resolve({exit_code:code,timed_out:timedOut,truncated,
   output:output.toString('utf8'),errors:errors.toString('utf8')});});
 });
}
async function quota(){
 const begin=performance.now();
 try{
  for(;;){
   const check=await command(input.python,['-m','teobench.medium_quota','--auth-file',input.quotaAuthPath,
    '--account-sha256',input.accountHash],engineEnv,'',30,4000);
   let value;try{value=JSON.parse(check.output);}catch{value={allowed:false,reason:'quota_check_unavailable'};}
   if(check.exit_code===0&&value.allowed===true){quotaWaiting=false;save({quota:value});return;}
   quotaWaiting=true;save({status:'QUOTA_PAUSED',quota:{allowed:false,reason:value.reason||'quota_check_unavailable'}});
   if(input.preflight)blocked('quota_unavailable');
   await sleep(60000);
  }
 }finally{paused+=performance.now()-begin;}
}
try{
 save({status:'INITIALIZING',phase:'validating_input'});
 if(!/^[a-f0-9]{64}$/.test(input.container))blocked('invalid_container');
 if(!/^\/[A-Za-z0-9_./-]*$/.test(input.workdir)||input.workdir.split('/').includes('..'))blocked('invalid_workdir');
 const pkg=JSON.parse(fs.readFileSync(input.packagePath+'/package.json','utf8'));
 if(pkg.name!=='@earendil-works/pi-coding-agent'||pkg.version!==input.profile.pi_version)blocked('unsupported_pi_version');
 const sdk=await import(pathToFileURL(input.packagePath+'/dist/index.js').href);
 save({status:'INITIALIZING',phase:'loading_runtime'});
 const settings=sdk.SettingsManager.inMemory(input.profile.settings);
 const runtime=await sdk.ModelRuntime.create({authPath:input.authPath,modelsPath:input.modelsPath,
  modelsStorePath:input.agentDir+'/models-cache.json',allowModelNetwork:false});
 const model=runtime.getModel(input.provider,input.model);
 if(!model||model.id!==input.model||model.provider!==input.provider)blocked('exact_model_unavailable');
 const mapped=model.thinkingLevelMap?.[input.effort];
 if(mapped!==undefined&&mapped!==input.effort)blocked('effort_mapping_unsupported');
 function budget(){
  if(history.length>=input.profile.max_tool_calls){fatal='tool_budget_exceeded';blocked(fatal);}
  if(activeSeconds()>input.taskSeconds){fatal='task_budget_exceeded';blocked(fatal);}
 }
 const terminal=sdk.defineTool({name:'terminal',label:'Task terminal',
  description:`Execute a shell command in the isolated task container at ${input.workdir}. No host filesystem access. Commands have a ${input.profile.command_timeout_seconds} second limit and bounded output. Public HTTP(S) access, when enabled by this task, is available through the supplied proxy environment. Long jobs may be started in the background with redirected output and polled.`,
  parameters:{type:'object',properties:{command:{type:'string'}},required:['command'],additionalProperties:false},
  execute:async(_id,args)=>{
   budget();
   if(!args||Object.keys(args).join()!=='command'||typeof args.command!=='string'||!args.command||args.command.length>16000)blocked('invalid_terminal_arguments');
   const result=await command(input.engine,['exec','-w',input.workdir,input.container,'timeout','-s','KILL',
    String(input.profile.command_timeout_seconds-1),'sh','-lc',args.command],engineEnv,'',input.profile.command_timeout_seconds,64000);
   const safe={exit_code:result.exit_code,timed_out:result.timed_out,truncated:result.truncated,
    output:result.output+(result.errors?'\n'+result.errors:'')};
   history.push({name:'terminal',arguments:args,result:safe});save();
   return {content:[{type:'text',text:JSON.stringify(safe)}],details:{}};
  }});
 const image=sdk.defineTool({name:'inspect_image',label:'Task image',
  description:'Read a PNG or JPEG image from an absolute path inside the isolated task container. Maximum 4 MB per image. Convert or resize other formats with the terminal first. No host files are accessible.',
  parameters:{type:'object',properties:{path:{type:'string'}},required:['path'],additionalProperties:false},
  execute:async(_id,args)=>{
   budget();
   if(!args||Object.keys(args).join()!=='path'||typeof args.path!=='string'||!args.path.startsWith('/')||args.path.length>1000)blocked('invalid_image_arguments');
   if(++images>input.profile.max_image_calls){fatal='image_budget_exceeded';blocked(fatal);}
   const response=await command(input.python,['-m','teobench.medium_image_tool'],engineEnv,
    JSON.stringify({engine:input.engine,container:input.container,path:args.path}),75,5600000);
   let result;try{result=JSON.parse(response.output);}catch{}
   if(response.exit_code!==0||!result?.data){
    history.push({name:'inspect_image',arguments:args,error:'image_unavailable'});save();
    return {content:[{type:'text',text:'Image unavailable. Use a regular PNG or JPEG file under 4 MB.'}],details:{}};
   }
   history.push({name:'inspect_image',arguments:args,sha256:hash(Buffer.from(result.data,'base64')),mimeType:result.mimeType});save();
   return {content:[{type:'image',data:result.data,mimeType:result.mimeType}],details:{}};
  }});
 const loader=new sdk.DefaultResourceLoader({cwd:input.cwd,agentDir:input.agentDir,settingsManager:settings,
  noExtensions:true,noSkills:true,noPromptTemplates:true,noThemes:true,noContextFiles:true,
  systemPromptOverride:()=>input.profile.system_prompt,appendSystemPromptOverride:()=>[],agentsFilesOverride:()=>({agentsFiles:[]})});
 await loader.reload();
 save({status:'INITIALIZING',phase:'creating_clean_session'});
 const manager=sdk.SessionManager.create(input.cwd,input.sessionDirectory);
 const result=await sdk.createAgentSession({cwd:input.cwd,agentDir:input.agentDir,model,thinkingLevel:input.effort,
  modelRuntime:runtime,resourceLoader:loader,settingsManager:settings,sessionManager:manager,
  tools:['terminal','inspect_image'],customTools:[terminal,image]});
 session=result.session;
 if(result.modelFallbackMessage||session.model?.id!==input.model||session.model?.provider!==input.provider||session.thinkingLevel!==input.effort)blocked('model_or_effort_substituted');
 const generated=input.profile.system_prompt+'\nCurrent working directory: '+input.cwd.replaceAll('\\','/')+'\n';
 if(session.systemPrompt!==generated||session.state.messages.length||JSON.stringify(session.getActiveToolNames())!=='["terminal","inspect_image"]')blocked('profile_contaminated');
 session.subscribe(event=>{if(event.type==='message_end'&&event.message?.role==='assistant'&&dispatches.length){
  dispatches.at(-1).status='RESPONSE_RECORDED';dispatches.at(-1).stop_reason=event.message.stopReason;save();
 }});
 const original=runtime.streamSimple.bind(runtime);let lastSend=performance.now();
 runtime.streamSimple=async(actual,context,options)=>{
  const users=context.messages.filter(m=>m.role==='user');
  if(actual.id!==input.model||actual.provider!==input.provider||options?.reasoning!==input.effort||context.systemPrompt!==generated
   ||JSON.stringify((context.tools||[]).map(t=>t.name))!=='["terminal","inspect_image"]'||users.length!==1
   ||JSON.stringify(users[0].content)!==JSON.stringify([{type:'text',text:input.prompt}]))blocked('request_profile_mismatch');
  if(fatal)blocked(fatal);budget();
  await quota();
  await sleep(Math.max(0,input.profile.minimum_request_gap_seconds*1000-(performance.now()-lastSend)));
  if(++requests>input.profile.max_tool_calls+1){fatal='request_budget_exceeded';blocked(fatal);}
  lastSend=performance.now();started=true;
  dispatches.push({number:requests,status:'DISPATCHING',context_sha256:hash(JSON.stringify({...context,systemPrompt:input.profile.system_prompt})),timestamp:new Date().toISOString()});
  save({session_file:manager.getSessionFile()});
  return original(actual,{...context,systemPrompt:input.profile.system_prompt},
   {...options,maxTokens:input.profile.max_output_tokens,maxRetries:0});
 };
 save({status:input.preflight?'PREFLIGHT_PASS':'READY',session_file:manager.getSessionFile()});
 if(!input.preflight){
  timer=setInterval(()=>{if(!quotaWaiting&&activeSeconds()>input.taskSeconds&&!fatal){fatal='task_budget_exceeded';session.abort().catch(()=>{});}},1000);
  await session.prompt(input.prompt,{expandPromptTemplates:false});
  const last=session.state.messages.at(-1);
  if(fatal)blocked(fatal);
  if(last?.stopReason==='length'){fatal='output_budget_exceeded';blocked(fatal);}
  if(!started||last?.role!=='assistant'||last.stopReason!=='stop'){failure=providerFailure(last);blocked('unfinished_response');}
  save({status:'COMPLETED',answer:last.content.filter(c=>c.type==='text').map(c=>c.text).join('')});
 }
}catch(error){
 const known=new Set(['invalid_container','invalid_workdir','unsupported_pi_version','exact_model_unavailable','effort_mapping_unsupported',
  'model_or_effort_substituted','profile_contaminated','request_profile_mismatch','invalid_terminal_arguments','invalid_image_arguments',
  'tool_budget_exceeded','image_budget_exceeded','task_budget_exceeded','request_budget_exceeded','output_budget_exceeded',
  'unfinished_response','sandbox_transport_error','quota_unavailable']);
 const code=known.has(error.message)?error.message:'pi_worker_error';
 const budget=code.endsWith('_budget_exceeded');
 save({status:budget?'BUDGET_EXHAUSTED':started?'TRANSPORT_ERROR':'BLOCKED',error:code,...(failure?{provider_failure:failure}:{})});
 process.exitCode=1;
}finally{clearInterval(timer);session?.dispose();}
