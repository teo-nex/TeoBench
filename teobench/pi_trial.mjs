// Trusted Pi SDK worker. No user resource discovery or persistent session.
import fs from 'node:fs';
import { pathToFileURL } from 'node:url';
import { createHash } from 'node:crypto';

const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const hash = value => createHash('sha256').update(value).digest('hex');
let session;
let started = false;
let calls = 0;
let fatal = null;
let receipt = null;
const history = [];
const checkpoint = extra => { fs.writeFileSync(input.resultPath + '.tmp', JSON.stringify({
  answer: '', tool_history: history, transport_error: null, inference_started: started, receipt,
  ...extra,
}), { mode: 0o600 }); fs.renameSync(input.resultPath + '.tmp', input.resultPath); };
const blocked = code => { throw new Error(code); };

try {
  const pkg = JSON.parse(fs.readFileSync(input.packagePath + '/package.json', 'utf8'));
  if (!['@earendil-works/pi-coding-agent', '@mariozechner/pi-coding-agent'].includes(pkg.name)
      || pkg.version !== input.profile.pi_version) blocked('unsupported_pi_version');
  const sdk = await import(pathToFileURL(input.packagePath + '/dist/index.js').href);
  const settings = sdk.SettingsManager.inMemory(input.profile.settings);
  const runtime = await sdk.ModelRuntime.create({
    authPath: input.authPath, modelsPath: input.modelsPath,
    modelsStorePath: input.agentDir + '/models-cache.json', allowModelNetwork: false,
  });
  const model = runtime.getModel(input.provider, input.model);
  if (!model || model.id !== input.model || model.provider !== input.provider) blocked('exact_model_unavailable');
  const mappedEffort = model.thinkingLevelMap?.[input.effort];
  if (mappedEffort !== undefined && mappedEffort !== input.effort) blocked('effort_mapping_unsupported');
  const allowed = input.task.family === 'tools' ? ['lookup'] : [];
  const lookup = input.task.tools?.[0];
  const tool = lookup && sdk.defineTool({
    name: 'lookup', label: 'lookup', description: lookup.description, parameters: lookup.parameters,
    execute: async (_id, args) => {
      if (fatal) blocked(fatal);
      if (!args || Object.keys(args).join() !== 'id' || typeof args.id !== 'string'
          || !Object.hasOwn(input.catalog, args.id)) {
        fatal = 'invalid_lookup'; blocked(fatal);
      }
      if (history.length >= input.task.max_rounds) { fatal = 'tool_budget_exceeded'; blocked(fatal); }
      const output = input.catalog[args.id];
      history.push({name: 'lookup', arguments: {id: args.id}, ok: true, output});
      checkpoint();
      return {content: [{type: 'text', text: JSON.stringify(output)}], details: {}};
    },
  });
  const loader = new sdk.DefaultResourceLoader({
    cwd: input.cwd, agentDir: input.agentDir, settingsManager: settings,
    noExtensions: true, noSkills: true, noPromptTemplates: true, noThemes: true, noContextFiles: true,
    systemPromptOverride: () => input.profile.system_prompt,
    appendSystemPromptOverride: () => [], agentsFilesOverride: () => ({agentsFiles: []}),
  });
  await loader.reload();
  const result = await sdk.createAgentSession({
    cwd: input.cwd, agentDir: input.agentDir, model, thinkingLevel: input.effort,
    modelRuntime: runtime, resourceLoader: loader, settingsManager: settings,
    sessionManager: sdk.SessionManager.inMemory(), tools: allowed, customTools: tool ? [tool] : [],
  });
  session = result.session;
  if (result.modelFallbackMessage || session.model?.id !== input.model
      || session.model?.provider !== input.provider || session.thinkingLevel !== input.effort)
    blocked('model_or_effort_substituted');
  const generatedPrompt = input.profile.system_prompt + '\nCurrent working directory: ' + input.cwd.replaceAll('\\', '/') + '\n';
  if (session.systemPrompt !== generatedPrompt || session.state.messages.length !== 0
      || JSON.stringify(session.getActiveToolNames().sort()) !== JSON.stringify(allowed))
    blocked('profile_contaminated');
  const base = receipt = {profile: input.profile.id, profile_sha256: input.profileHash, pi_version: pkg.version,
    provider: input.provider, model: input.model, effort: input.effort,
    system_prompt_sha256: hash(input.profile.system_prompt), tools: allowed,
    transport_sha256: input.transportHash, max_output_tokens: input.profile.max_output_tokens};
  const original = runtime.streamSimple.bind(runtime);
  let lastSend = performance.now();
  runtime.streamSimple = async (actual, context, options) => {
    if (fatal) blocked(fatal);
    if (actual.id !== input.model || actual.provider !== input.provider
        || context.systemPrompt !== generatedPrompt
        || JSON.stringify((context.tools || []).map(t => t.name).sort()) !== JSON.stringify(allowed)
        || options?.reasoning !== input.effort) blocked('request_profile_mismatch');
    if (++calls > (input.task.max_rounds || 1) + 1) blocked('round_budget_exceeded');
    const userMessages = context.messages.filter(m => m.role === 'user');
    if (userMessages.length !== 1 || JSON.stringify(userMessages[0].content) !== JSON.stringify([{type: 'text', text: JSON.stringify(input.task)}]))
      blocked('request_profile_mismatch');
    await new Promise(resolve => setTimeout(resolve, Math.max(0, input.profile.minimum_request_gap_seconds * 1000 - (performance.now() - lastSend))));
    lastSend = performance.now();
    started = true;
    checkpoint({receipt: base, requests: calls});
    return original(actual, {...context, systemPrompt: input.profile.system_prompt}, {...options, maxTokens: input.profile.max_output_tokens, maxRetries: 0});
  };
  checkpoint({receipt: base, status: input.preflight ? 'PREFLIGHT_PASS' : 'READY', model_completion_tested: false});
  if (!input.preflight) {
    await session.prompt(JSON.stringify(input.task), {expandPromptTemplates: false});
    const messages = session.state.messages;
    const last = messages.at(-1);
    if (fatal) blocked(fatal);
    if (!started || last?.role !== 'assistant' || last.stopReason !== 'stop') blocked('unfinished_response');
    const answer = last.content.filter(c => c.type === 'text').map(c => c.text).join('');
    checkpoint({answer, receipt: base, status: 'COMPLETED', requests: calls});
  }
} catch (error) {
  // Error messages may contain provider/account data. Publish stable classifications only.
  const known = new Set(['unsupported_pi_version','exact_model_unavailable','model_or_effort_substituted','effort_mapping_unsupported',
    'profile_contaminated','request_profile_mismatch','tool_budget_exceeded','round_budget_exceeded',
    'invalid_lookup','unfinished_response']);
  const code = known.has(error.message) ? error.message : 'pi_worker_error';
  checkpoint({status: started ? 'TRANSPORT_ERROR' : 'BLOCKED', transport_error: started ? code : null,
    blocker: started ? null : code, requests: calls});
  process.exitCode = 1;
} finally {
  session?.dispose();
}
