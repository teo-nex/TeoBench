// Host Pi session; the model's ONLY tool executes inside a pre-created container.
// Engine creation, grading and credentials are never available as model tools.
import fs from 'node:fs';
import {spawn} from 'node:child_process';
import {pathToFileURL} from 'node:url';
import {createHash} from 'node:crypto';
import {providerFailure} from './pi_failure.mjs';

const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const hash = x => createHash('sha256').update(x).digest('hex');
let session, fatal, failure, started = false, requests = 0;
const history = [];
const save = extra => {
  fs.writeFileSync(input.resultPath+'.tmp', JSON.stringify({
    status: 'RUNNING', inference_started: started, requests, tool_history: history,
    kind: input.kind, receipt: {profile: input.profile.id, profile_sha256: input.profileHash,
      pi_version: input.profile.pi_version, benchmark_model: input.benchmarkModel,
      request_model: input.model, provider: input.provider, effort: input.effort,
      transport_sha256: input.transportHash, public_task_sha256: hash(input.prompt),
      tools: ['terminal'], no_personal_resources: true, no_retries: true,
      max_output_tokens: input.profile.max_output_tokens, max_tool_calls: input.profile.max_tool_calls},
    ...extra,
  }), {mode: 0o600});
  fs.renameSync(input.resultPath+'.tmp', input.resultPath);
};
const blocked = code => {throw new Error(code);};
const known = new Set(['invalid_container','unsupported_pi_version','exact_model_unavailable',
  'effort_mapping_unsupported','model_or_effort_substituted','profile_contaminated',
  'request_profile_mismatch','tool_budget_exceeded','invalid_terminal_arguments',
  'unfinished_response','sandbox_transport_error']);
const engineEnv = Object.fromEntries(Object.entries(process.env).filter(([key]) =>
  ['PATH','HOME','XDG_CONFIG_HOME','XDG_DATA_HOME','XDG_RUNTIME_DIR','TMPDIR','LANG','LC_ALL',
   'SystemRoot','SYSTEMROOT','USERPROFILE','COMSPEC','PATHEXT','TEMP','TMP'].includes(key)));

function terminal(command) {
  return new Promise((resolve, reject) => {
    const args = [...input.enginePrefix, 'exec', '-w', '/workspace', input.container,
      'timeout', '-s', 'KILL', '29', 'sh', '-lc', command];
    const child = spawn(input.engine, args, {env: engineEnv, stdio: ['ignore','pipe','pipe']});
    let output = '', truncated = false, timedOut = false;
    const collect = chunk => {
      if (Buffer.byteLength(output) >= 64000) {truncated = true; return;}
      output += chunk.toString('utf8').slice(0, 64000-output.length);
    };
    child.stdout.on('data',collect); child.stderr.on('data',collect);
    const timer = setTimeout(() => {timedOut = true; child.kill('SIGKILL');}, 30000);
    child.on('error', () => {clearTimeout(timer); reject(new Error('sandbox_transport_error'));});
    child.on('close', code => {clearTimeout(timer); resolve({exit_code: code, timed_out: timedOut, truncated, output});});
  });
}

try {
  if (!/^[a-f0-9]{64}$/.test(input.container)) blocked('invalid_container');
  const pkg = JSON.parse(fs.readFileSync(input.packagePath+'/package.json','utf8'));
  if (!['@earendil-works/pi-coding-agent','@mariozechner/pi-coding-agent'].includes(pkg.name)
      || pkg.version !== input.profile.pi_version) blocked('unsupported_pi_version');
  const sdk = await import(pathToFileURL(input.packagePath+'/dist/index.js').href);
  const settings = sdk.SettingsManager.inMemory(input.profile.settings);
  const runtime = await sdk.ModelRuntime.create({authPath: input.authPath, modelsPath: input.modelsPath,
    modelsStorePath: input.agentDir+'/models-cache.json', allowModelNetwork: false});
  const model = runtime.getModel(input.provider,input.model);
  if (!model || model.id !== input.model || model.provider !== input.provider) blocked('exact_model_unavailable');
  const mapped = model.thinkingLevelMap?.[input.effort];
  if (mapped !== undefined && mapped !== input.effort) blocked('effort_mapping_unsupported');
  const tool = sdk.defineTool({name: 'terminal', label: 'Task terminal',
    description: 'Execute a shell command in the isolated task container at /workspace. No host filesystem or network access. Each command has a 30 second limit and bounded output.',
    parameters: {type: 'object', properties: {command: {type: 'string'}}, required: ['command'], additionalProperties: false},
    execute: async (_id,args) => {
      if (!args || Object.keys(args).join() !== 'command' || typeof args.command !== 'string'
          || !args.command || args.command.length > 16000) {fatal = 'invalid_terminal_arguments'; blocked(fatal);}
      if (history.length >= input.profile.max_tool_calls) {fatal = 'tool_budget_exceeded'; blocked(fatal);}
      const result = await terminal(args.command);
      history.push({name: 'terminal', arguments: args, result}); save();
      return {content: [{type: 'text',text: JSON.stringify(result)}],details: {}};
    }});
  const loader = new sdk.DefaultResourceLoader({cwd: input.cwd, agentDir: input.agentDir, settingsManager: settings,
    noExtensions: true, noSkills: true, noPromptTemplates: true, noThemes: true, noContextFiles: true,
    systemPromptOverride: () => input.profile.system_prompt,
    appendSystemPromptOverride: () => [], agentsFilesOverride: () => ({agentsFiles: []})});
  await loader.reload();
  const result = await sdk.createAgentSession({cwd: input.cwd, agentDir: input.agentDir, model,
    thinkingLevel: input.effort, modelRuntime: runtime, resourceLoader: loader, settingsManager: settings,
    sessionManager: sdk.SessionManager.inMemory(), tools: ['terminal'], customTools: [tool]});
  session = result.session;
  if (result.modelFallbackMessage || session.model?.id !== input.model || session.model?.provider !== input.provider
      || session.thinkingLevel !== input.effort) blocked('model_or_effort_substituted');
  const generated = input.profile.system_prompt+'\nCurrent working directory: '+input.cwd.replaceAll('\\','/')+'\n';
  if (session.systemPrompt !== generated || session.state.messages.length
      || JSON.stringify(session.getActiveToolNames()) !== '["terminal"]') blocked('profile_contaminated');
  const original = runtime.streamSimple.bind(runtime);
  let lastSend = performance.now();
  runtime.streamSimple = async (actual,context,options) => {
    const users = context.messages.filter(m => m.role === 'user');
    if (actual.id !== input.model || actual.provider !== input.provider || options?.reasoning !== input.effort
        || context.systemPrompt !== generated
        || JSON.stringify((context.tools || []).map(t => t.name)) !== '["terminal"]'
        || users.length !== 1 || JSON.stringify(users[0].content) !== JSON.stringify([{type:'text',text:input.prompt}]))
      blocked('request_profile_mismatch');
    if (fatal) blocked(fatal);
    if (++requests > input.profile.max_tool_calls+1) blocked('tool_budget_exceeded');
    await new Promise(resolve => setTimeout(resolve, Math.max(0,input.profile.minimum_request_gap_seconds*1000-(performance.now()-lastSend))));
    lastSend = performance.now(); started = true; save();
    return original(actual,{...context, systemPrompt: input.profile.system_prompt},
      {...options,maxTokens:input.profile.max_output_tokens,maxRetries:0});
  };
  save({status: input.preflight ? 'PREFLIGHT_PASS' : 'READY'});
  if (!input.preflight) {
    await session.prompt(input.prompt,{expandPromptTemplates:false});
    const last = session.state.messages.at(-1);
    if (fatal) blocked(fatal);
    if (!started || last?.role !== 'assistant' || last.stopReason !== 'stop') {
      failure = providerFailure(last);
      blocked('unfinished_response');
    }
    save({status:'COMPLETED',answer:last.content.filter(c => c.type === 'text').map(c => c.text).join('')});
  }
} catch (error) {
  const code = known.has(error.message) ? error.message : 'pi_worker_error';
  save({status: started ? 'TRANSPORT_ERROR' : 'BLOCKED',error:code,
    ...(failure ? {provider_failure: failure} : {})});
  process.exitCode = 1;
} finally {session?.dispose();}
