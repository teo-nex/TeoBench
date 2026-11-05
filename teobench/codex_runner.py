"""Optional native Codex adapter with disposable settings, home and sessions.

No inference at import, selection or preflight. Never load the participant's config.
"""
import base64
import copy
from collections import deque
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
PROFILE = ROOT / 'Easy-Bench/profiles/codex-clean-v1.json'


def digest(value):
    return hashlib.sha256(value).hexdigest()


def profile_identity():
    return json.loads(PROFILE.read_text(encoding='utf-8')), digest(b'\0'.join(
        p.read_bytes().replace(b'\r\n', b'\n') for p in (PROFILE, Path(__file__))))


def mark_study(study):
    profile, fingerprint = profile_identity()
    marker = profile['id'] + ':' + fingerprint
    study['method'] = ('Execution profile ' + marker + '; Codex ' + profile['codex_version'] +
        '; fixed instructions and client catalog; disposable home and ephemeral session; '
        'no personal resources; native output limit; no retries. ' + study['method'])
    study['access_route'] = marker + '; ' + study['access_route']
    return study


def require_profile(study):
    profile, fingerprint = profile_identity()
    marker = profile['id'] + ':' + fingerprint
    if not study['access_route'].startswith(marker + '; ') or ('Execution profile ' + marker + ';') not in study['method']:
        raise ValueError('BLOCKED: create a separate checkpoint with --execution-profile codex-clean-v1')


def executable(explicit=None):
    value = str(explicit) if explicit else shutil.which('codex')
    if not value:
        raise ValueError('BLOCKED: Codex CLI is not installed; no automatic installation')
    path = Path(value).expanduser().resolve()
    if path.suffix.lower() in ('.cmd', '.bat'):
        # Resolve an existing npm installation without executing its shell shim.
        arch = platform.machine().lower()
        target, package = ('aarch64-pc-windows-msvc', 'codex-win32-arm64') if arch in ('arm64', 'aarch64') else ('x86_64-pc-windows-msvc', 'codex-win32-x64')
        modules = path.parent/'node_modules'
        roots = (modules/'@openai'/package, modules/'@openai/codex/node_modules/@openai'/package,
                 modules/'@openai/codex')
        candidates = [root/'vendor'/target/subdir/'codex.exe' for root in roots for subdir in ('bin', 'codex')]
        path = next((p.resolve() for p in candidates if p.is_file()), None)
        if path is None:
            raise ValueError('BLOCKED: pass --codex-bin with the installed native codex.exe path; no compatible binary found beside the Windows shim')
    profile, _ = profile_identity()
    try:
        from .pi_runner import clean_environment as base_environment
        version_env = base_environment(Path(tempfile.gettempdir())/'teobench-version-only')
        result = subprocess.run([str(path), '--version'], env=version_env, capture_output=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError('BLOCKED: unable to run installed Codex CLI') from None
    if result.returncode or result.stdout.decode('utf-8', errors='replace').strip() != 'codex-cli ' + profile['codex_version']:
        raise ValueError('BLOCKED: codex-clean-v1 requires Codex CLI ' + profile['codex_version'])
    return path


def credentials(path=None, mode='chatgpt', *, minimum_lifetime=300):
    """Select auth only. Never copy a refresh token or permit implicit API billing."""
    if mode not in ('chatgpt', 'api-key'):
        raise ValueError('BLOCKED: unsupported Codex authentication mode')
    source = Path(path).expanduser() if path else Path(os.environ.get('CODEX_HOME', str(Path.home()/'.codex'))) / 'auth.json'
    data = {}
    if source.is_file():
        if source.stat().st_size > 2_000_000:
            raise ValueError('BLOCKED: invalid Codex credential store')
        data = json.loads(source.read_text(encoding='utf-8-sig'))
        if not isinstance(data, dict):
            raise ValueError('BLOCKED: invalid Codex credential store')
    if mode == 'api-key':
        key = os.environ.get('OPENAI_API_KEY') or data.get('OPENAI_API_KEY')
        if not isinstance(key, str) or not key or key.startswith('!'):
            raise ValueError('BLOCKED: no existing API key for explicitly selected API mode')
        return {'auth_mode':'apikey', 'OPENAI_API_KEY':key}
    tokens = data.get('tokens')
    if not isinstance(tokens, dict) or not all(isinstance(tokens.get(k), str) and tokens[k]
            for k in ('access_token', 'id_token', 'account_id')):
        raise ValueError('BLOCKED: existing file-based Codex ChatGPT sign-in required; API mode is never selected automatically')
    try:
        part = tokens['access_token'].split('.')[1]
        claims = json.loads(base64.urlsafe_b64decode(part + '=' * (-len(part) % 4)))
        expires = claims['exp']
        if not isinstance(expires, (float, int)) or isinstance(expires, bool) or not math.isfinite(expires) or expires < time.time() + minimum_lifetime:
            raise ValueError('expired')
    except (ValueError, KeyError, IndexError, TypeError):
        raise ValueError('BLOCKED: refresh the existing Codex sign-in normally; no token refresh or account changes in the disposable profile') from None
    return {'auth_mode':'chatgpt', 'OPENAI_API_KEY':None,
            'tokens':{k:tokens[k] for k in ('access_token','id_token','account_id')} | {'refresh_token':''},
            'last_refresh':datetime.now(timezone.utc).isoformat()}


def transport_config(path=None, mode='chatgpt'):
    if path is None:
        return {'provider':'teobench_openai', 'auth_mode':mode, 'base_url':None}
    value = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if not isinstance(value, dict) or set(value) != {'base_url'} or not isinstance(value['base_url'], str):
        raise ValueError('BLOCKED: Codex transport accepts only base_url')
    parsed = urlsplit(value['base_url'])
    if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('BLOCKED: transport URL must not contain credentials or query parameters')
    if mode != 'api-key':
        raise ValueError('BLOCKED: explicit gateways require --auth-mode api-key; never forward a ChatGPT token to an arbitrary endpoint')
    return {'provider':'teobench_gateway', 'auth_mode':mode, 'base_url':value['base_url']}


def bind_route(study, provider, transport, auth_mode='chatgpt'):
    routing_hash = digest(json.dumps(transport_config(transport, auth_mode), sort_keys=True).encode())
    marker = 'Codex route ' + routing_hash + ';'
    prior = re.search(r'Codex route [^;]+;', study['method'])
    if prior and prior.group() != marker:
        raise ValueError('BLOCKED: Codex authentication or transport changed; create a separate study')
    if not prior:
        if study['records']:
            raise ValueError('BLOCKED: existing records have no verified route binding')
        study['method'] += ' ' + marker
        study['access_route'] += '; codex:' + routing_hash
    return routing_hash


def clean_environment(home, agent):
    from .pi_runner import clean_environment as base_environment
    env = base_environment(agent)
    for k in list(env):
        if k.startswith('PI_'):
            del env[k]
    # Child-only home isolation. The user's actual home and settings are never modified.
    env.update(HOME=str(home), USERPROFILE=str(home), CODEX_HOME=str(agent),
               XDG_CONFIG_HOME=str(home/'config'), XDG_CACHE_HOME=str(home/'cache'),
               XDG_DATA_HOME=str(home/'data'), APPDATA=str(home/'appdata'), LOCALAPPDATA=str(home/'localappdata'))
    return env


def write_private(path, value):
    path.write_text(value, encoding='utf-8')
    path.chmod(0o600)


def configure(root, profile, config, model, effort, routing, auth):
    home, agent, cwd = root/'home', root/'codex', root/'work'
    for path in (home, agent, cwd):
        path.mkdir(mode=0o700)
    catalog = []
    for name in config['models']:
        item = copy.deepcopy(profile['model_template'])
        item['slug'] = item['display_name'] = name
        catalog.append(item)
    write_private(agent/'catalog.json', json.dumps({'models':catalog}))
    write_private(agent/'auth.json', json.dumps(auth))
    settings = dict(model_provider=routing['provider'], model=model, model_reasoning_effort=effort,
        approval_policy='never', sandbox_mode='read-only', cli_auth_credentials_store='file',
        project_doc_max_bytes=0, include_environment_context=False, include_permissions_instructions=False,
        include_collaboration_mode_instructions=False, include_apps_instructions=False,
        check_for_update_on_startup=False, web_search='disabled',
        model_context_window=profile['context_window'], model_auto_compact_token_limit=1_000_000_000,
        model_catalog_json=str(agent/'catalog.json'), suppress_unstable_features_warning=True)
    text = ''.join(k+' = '+json.dumps(v)+'\n' for k,v in settings.items())
    text += '\n[features]\n' + ''.join(k+' = false\n' for k in profile['disabled_features'])
    text += 'skip_host_skill_discovery = true\n'
    text += '\n[skills]\ninclude_instructions = false\n[skills.bundled]\nenabled = false\n'
    text += '\n[memories]\ngenerate_memories = false\nuse_memories = false\n'
    text += '\n[tools.update_plan]\nenabled = false\n[tools.experimental_request_user_input]\nenabled = false\n'
    text += '\n[history]\npersistence = "none"\n[analytics]\nenabled = false\n[feedback]\nenabled = false\n'
    text += '\n[model_providers.'+routing['provider']+']\nrequest_max_retries = 0\nstream_max_retries = 0\nsupports_websockets = false\n'
    name = 'TeoBench explicit gateway' if routing['base_url'] else 'OpenAI'
    text += 'name = '+json.dumps(name)+'\nwire_api = "responses"\nrequires_openai_auth = true\n'
    if routing['base_url']:
        text += 'base_url = '+json.dumps(routing['base_url'])+'\n'
    write_private(agent/'config.toml', text)
    return home, agent, cwd, settings


def verify_settings(value, settings, profile, routing):
    config = value.get('config', {})
    for key, expected in settings.items():
        actual = config.get(key)
        if key == 'model_catalog_json' and isinstance(actual, str):
            actual, expected = Path(actual).resolve(), Path(expected).resolve()
        if actual != expected:
            raise ProtocolError('effective_config_changed')
    flags = config.get('features') or {}
    if any(flags.get(k) is not False for k in profile['disabled_features']) or flags.get('skip_host_skill_discovery') is not True:
        raise ProtocolError('effective_features_changed')
    if config.get('mcp_servers') or config.get('hooks') or config.get('notify') or config.get('instructions') or config.get('developer_instructions'):
        raise ProtocolError('personal_resources_loaded')
    skills = config.get('skills') or {}
    if skills.get('include_instructions') is not False or skills.get('bundled', {}).get('enabled') is not False or skills.get('config'):
        raise ProtocolError('personal_resources_loaded')
    for provider in (config.get('model_providers') or {}).values():
        if any(provider.get(k) for k in ('auth','http_headers','env_http_headers','query_params','gateway_oauth','model_catalog_url','env_key')):
            raise ProtocolError('unexpected_provider_configuration')
    selected = (config.get('model_providers') or {}).get(routing['provider'], {})
    expected = dict(name='TeoBench explicit gateway' if routing['base_url'] else 'OpenAI',
                    wire_api='responses', requires_openai_auth=True,
                    request_max_retries=0, stream_max_retries=0, supports_websockets=False,
                    base_url=routing['base_url'])
    if any(selected.get(k) != v for k, v in expected.items()):
        raise ProtocolError('effective_transport_changed')


class ProtocolError(Exception):
    pass


class Client:
    """Bounded stdio JSON-RPC. Provider messages and credentials are never logged."""
    def __init__(self, process, deadline, on_request):
        self.process, self.deadline, self.on_request = process, deadline, on_request
        self.inbox = queue.Queue(maxsize=128)
        self.stopped = threading.Event()
        self.counter = 0
        self.pending = deque()
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self):
        def enqueue(value):
            while not self.stopped.is_set():
                try:
                    self.inbox.put(value, timeout=0.1)
                    return
                except queue.Full:
                    continue
        try:
            while not self.stopped.is_set():
                line = self.process.stdout.readline(8_000_001)
                if not line:
                    enqueue(None); return
                if len(line) > 8_000_000:
                    raise ValueError('oversized')
                enqueue(json.loads(line))
        except (ValueError, OSError):
            enqueue(None)

    def send(self, value):
        try:
            self.process.stdin.write((json.dumps(value)+'\n').encode()); self.process.stdin.flush()
        except (OSError, ValueError):
            raise ProtocolError('worker_terminated') from None

    def receive(self, pending=True):
        if pending and self.pending:
            return self.pending.popleft()
        remaining = self.deadline-time.monotonic()
        if remaining <= 0:
            raise ProtocolError('timeout')
        try:
            value = self.inbox.get(timeout=remaining)
        except queue.Empty:
            raise ProtocolError('timeout') from None
        if not isinstance(value, dict):
            raise ProtocolError('worker_terminated')
        if 'method' in value and 'id' in value:
            self.send({'id':value['id'], 'result':self.on_request(value)})
        return value

    def call(self, method, params):
        self.counter += 1
        request_id = self.counter
        self.send({'id':request_id, 'method':method, 'params':params})
        while True:
            value = self.receive(pending=False)
            if value.get('id') == request_id and 'method' not in value:
                if 'error' in value:
                    raise ProtocolError('rpc_rejected')
                return value.get('result', {})
            if 'method' in value and 'id' not in value:
                if len(self.pending) >= 128:
                    raise ProtocolError('protocol_overflow')
                self.pending.append(value)


def run(task_id, model, effort, provider='openai', *, codex_bin=None, auth_file=None,
        auth_mode='chatgpt', transport=None, preflight=False, expected_transport_hash=None, result_file=None):
    from .cli import load
    from .campaign import plan
    from .pi_runner import stop_process
    config, _ = plan()
    if model not in config['models'] or effort not in config['efforts'] or provider != 'openai':
        raise ValueError('BLOCKED: exact campaign model/effort and openai provider required')
    tasks, answers, _ = load()
    task = next((t for t in tasks if t['id'] == task_id), None)
    if task is None:
        raise ValueError('unknown_task')
    binary = executable(codex_bin)
    profile, fingerprint = profile_identity()
    routing = transport_config(transport, auth_mode)
    route_hash = digest(json.dumps(routing, sort_keys=True).encode())
    if expected_transport_hash is not None and expected_transport_hash != route_hash:
        raise ValueError('BLOCKED: transport changed after route binding')
    auth = credentials(auth_file, auth_mode, minimum_lifetime=profile['timeout_seconds']+60)
    started_at = time.monotonic()
    result = dict(status='BLOCKED', blocker=None, transport_error=None, answer='', tool_history=[],
        inference_started=False, task_id=task_id, model=model, effort=effort,
        profile=profile['id'], profile_sha256=fingerprint, profile_removed=False,
        receipt={'codex_version':profile['codex_version'], 'profile_sha256':fingerprint,
                 'transport_sha256':route_hash, 'auth_mode':auth_mode,
                 'system_prompt_sha256':digest(profile['system_prompt'].encode()),
                 'tools':['lookup'] if task['family']=='tools' else [], 'output_limit':'native'})
    def checkpoint():
        if result_file is not None:
            path = Path(result_file).resolve()
            write_private(path.with_suffix('.tmp'), json.dumps(result, ensure_ascii=False))
            path.with_suffix('.tmp').replace(path)
    with tempfile.TemporaryDirectory(prefix='teobench-codex-') as directory:
        root = Path(directory); root.chmod(0o700)
        home, agent, cwd, settings = configure(root, profile, config, model, effort, routing, auth)
        process = None
        thread_id = None
        def request(message):
            params = message.get('params', {})
            args = params.get('arguments')
            if (not result['inference_started'] or message['method'] != 'item/tool/call' or task['family'] != 'tools'
                    or params.get('threadId') != thread_id or params.get('tool') != 'lookup'
                    or params.get('namespace') not in (None, '') or not isinstance(args, dict)
                    or set(args) != {'id'} or not isinstance(args['id'], str)):
                raise ProtocolError('unexpected_tool_or_approval')
            catalog = answers[task_id]['catalog']
            if args['id'] not in catalog or len(result['tool_history']) >= task['max_rounds']:
                raise ProtocolError('invalid_lookup_or_budget')
            output = catalog[args['id']]
            result['tool_history'].append({'name':'lookup', 'arguments':args, 'ok':True, 'output':output})
            checkpoint()
            time.sleep(profile['minimum_request_gap_seconds'])
            return {'success':True, 'contentItems':[{'type':'inputText', 'text':json.dumps(output)}]}
        try:
            process = subprocess.Popen([str(binary), 'app-server', '--strict-config', '--listen', 'stdio://'],
                cwd=cwd, env=clean_environment(home, agent), stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, start_new_session=os.name!='nt',
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name=='nt' else 0)
            client = Client(process, started_at+profile['timeout_seconds'], request)
            initialized = client.call('initialize', {'clientInfo':{'name':'teobench', 'version':'1'}, 'capabilities':{'experimentalApi':True}})
            if Path(initialized.get('codexHome', '')).resolve() != agent.resolve():
                raise ProtocolError('profile_contaminated')
            client.send({'method':'initialized'})
            verify_settings(client.call('config/read', {'includeLayers':False}), settings, profile, routing)
            dynamic = []
            if task['family'] == 'tools':
                spec = task['tools'][0]
                dynamic = [{'type':'function', 'name':'lookup', 'description':spec['description'], 'inputSchema':spec['parameters'], 'deferLoading':False}]
            value = client.call('thread/start', dict(model=model, modelProvider=routing['provider'],
                baseInstructions=profile['system_prompt'], developerInstructions='', cwd=str(cwd),
                approvalPolicy='never', sandbox='read-only', ephemeral=True, allowProviderModelFallback=False,
                environments=[], runtimeWorkspaceRoots=[], dynamicTools=dynamic))
            thread_id = value.get('thread', {}).get('id')
            if (not thread_id or value.get('model') != model or value.get('modelProvider') != routing['provider']
                    or value.get('reasoningEffort') != effort or value.get('instructionSources') != []
                    or not value['thread'].get('ephemeral') or value.get('approvalPolicy') != 'never'
                    or value.get('sandbox', {}).get('type') != 'readOnly'):
                raise ProtocolError('profile_contaminated')
            result['status'] = 'PREFLIGHT_PASS' if preflight else 'READY'
            checkpoint()
            if not preflight:
                time.sleep(profile['minimum_request_gap_seconds'])
                result['inference_started'] = True; checkpoint()
                turn = client.call('turn/start', {'threadId':thread_id, 'model':model, 'effort':effort,
                    'input':[{'type':'text', 'text':json.dumps(task)}]})
                turn_id = turn.get('turn', {}).get('id')
                if not turn_id:
                    raise ProtocolError('missing_turn')
                messages = {}
                while True:
                    event = client.receive()
                    params = event.get('params', {})
                    if params.get('threadId') != thread_id:
                        continue
                    if event.get('method') == 'item/completed' and params.get('item', {}).get('type') == 'agentMessage':
                        item = params['item']; messages[item['id']] = item
                    if event.get('method') == 'turn/completed' and params.get('turn', {}).get('id') == turn_id:
                        finished = params['turn']
                        if finished.get('status') != 'completed':
                            raise ProtocolError('turn_failed_or_interrupted')
                        for item in finished.get('items', []):
                            if item.get('type') == 'agentMessage':
                                messages[item['id']] = item
                        final = [m for m in messages.values() if m.get('phase') in (None, 'final_answer')]
                        if not final or not isinstance(final[-1].get('text'), str):
                            raise ProtocolError('missing_final_answer')
                        result.update(status='COMPLETED', answer=final[-1]['text'])
                        checkpoint(); break
        except (ProtocolError, OSError, KeyboardInterrupt) as error:
            code = str(error) if isinstance(error, ProtocolError) else ('interrupted' if isinstance(error, KeyboardInterrupt) else 'worker_failed')
            started = result['inference_started']
            result.update(status='TRANSPORT_ERROR' if started else 'BLOCKED',
                blocker=None if started else code, transport_error=code if started else None)
            checkpoint()
        finally:
            if process is not None:
                try:
                    process.stdin.close()
                    process.wait(timeout=0.5)
                except (OSError, subprocess.TimeoutExpired):
                    stop_process(process)
                if 'client' in locals():
                    client.stopped.set()
                    client.reader.join(timeout=1)
                process.stdout.close()
    result.update(profile_removed=True, elapsed_seconds=time.monotonic()-started_at)
    checkpoint()
    return result
