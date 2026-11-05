"""Optional isolated Pi trials. Imported lazily; offline CLI stays offline."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tempfile
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
PROFILE = ROOT / 'Easy-Bench/profiles/pi-clean-v1.json'
WORKER = Path(__file__).with_name('pi_trial.mjs')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def profile_identity():
    profile = json.loads(PROFILE.read_text(encoding='utf-8'))
    return profile, digest(b'\0'.join(p.read_bytes().replace(b'\r\n', b'\n') for p in (PROFILE, WORKER, Path(__file__))))


def mark_study(study):
    profile, fingerprint = profile_identity()
    marker = profile['id'] + ':' + fingerprint
    study['method'] = ('Execution profile ' + marker + '; Pi ' + profile['pi_version'] +
        '; fixed system prompt; fresh in-memory session; no personal resources; ' +
        str(profile['max_output_tokens']) + ' output-token cap; no retries. ' + study['method'])
    study['access_route'] = marker + '; ' + study['access_route']
    return study


def require_profile(study):
    profile, fingerprint = profile_identity()
    marker = profile['id'] + ':' + fingerprint
    if not study['access_route'].startswith(marker + '; ') or ('Execution profile ' + marker + ';') not in study['method']:
        raise ValueError('BLOCKED: create a separate checkpoint with --execution-profile pi-clean-v1; never mix historical or different profiles')


def bind_route(study, provider, transport):
    profile, _ = profile_identity()
    routing_hash = digest(json.dumps(transport_config(transport, provider, profile), sort_keys=True).encode())
    marker = 'Pi route ' + provider + ':' + routing_hash + ';'
    prior = re.search(r'Pi route [^;]+;', study['method'])
    if prior and prior.group() != marker:
        raise ValueError('BLOCKED: Pi provider or transport changed; create a separate study')
    if not prior:
        if study['records']:
            raise ValueError('BLOCKED: existing records have no verified route binding')
        study['method'] += ' ' + marker
        study['access_route'] += '; ' + provider + ':' + routing_hash
    return routing_hash


def package_path(explicit=None):
    if explicit:
        path = Path(explicit).expanduser().resolve()
    else:
        executable = shutil.which('pi')
        if not executable:
            raise ValueError('BLOCKED: Pi is not installed; no automatic installation')
        path = Path(executable).resolve().parent.parent.parent
        if not (path / 'package.json').is_file():
            raise ValueError('BLOCKED: pass --pi-package with the installed Pi package directory')
    data = json.loads((path / 'package.json').read_text(encoding='utf-8'))
    profile = json.loads(PROFILE.read_text(encoding='utf-8'))
    if data.get('name') not in ('@earendil-works/pi-coding-agent', '@mariozechner/pi-coding-agent') or data.get('version') != profile['pi_version']:
        raise ValueError('BLOCKED: pi-clean-v1 requires Pi ' + profile['pi_version'])
    return path


def clean_environment(agent_dir, source=None):
    source = os.environ if source is None else source
    names = {'PATH','HOME','USERPROFILE','SystemRoot','SYSTEMROOT','COMSPEC','PATHEXT',
             'TMP','TEMP','TMPDIR','LANG','LC_ALL','SSL_CERT_FILE','SSL_CERT_DIR',
             'HTTPS_PROXY','HTTP_PROXY','ALL_PROXY','NO_PROXY','https_proxy','http_proxy','all_proxy','no_proxy'}
    result = {key: value for key, value in source.items() if key in names}
    result.update(PI_CODING_AGENT_DIR=str(agent_dir), PI_OFFLINE='1', PI_TELEMETRY='0')
    return result


def selected_auth(path, provider):
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(data, dict):
        raise ValueError('BLOCKED: invalid Pi credential store')
    entry = data.get(provider)
    if entry is None:
        return {}
    if not isinstance(entry, dict) or entry.get('type') not in ('api_key','oauth'):
        raise ValueError('BLOCKED: unsupported Pi credential entry')
    def command(value):
        if isinstance(value, str):
            return value.startswith('!')
        if isinstance(value, dict):
            return any(command(v) for v in value.values())
        if isinstance(value, list):
            return any(command(v) for v in value)
        return False
    if command(entry):
        raise ValueError('BLOCKED: executable credential resolvers are unsupported')
    return {provider: entry}


def transport_config(path, provider, profile):
    """Explicit routing only. Never import personal models.json or overrides."""
    if path is None:
        return {'providers': {}}
    value = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if not isinstance(value, dict) or set(value) != {'base_url','api','models'}:
        raise ValueError('BLOCKED: transport requires only base_url, api and models')
    if not isinstance(value['base_url'], str):
        raise ValueError('BLOCKED: transport base_url must be a string')
    parsed = urlsplit(value['base_url'])
    if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('BLOCKED: transport URL must not contain credentials or query parameters')
    if value['api'] not in ('openai-completions','openai-responses'):
        raise ValueError('BLOCKED: unsupported explicit transport API')
    from .campaign import plan
    config, _ = plan()
    models = value['models']
    if not isinstance(models, list) or not models or not all(isinstance(m, str) and m in config['models'] for m in models) or len(set(models)) != len(models):
        raise ValueError('BLOCKED: transport must list exact campaign model IDs')
    return {'providers': {provider: {'baseUrl': value['base_url'], 'api': value['api'],
        'models': [{'id': m, 'reasoning': True, 'input': ['text'],
                    'contextWindow': profile['context_window'], 'maxTokens': profile['max_output_tokens'],
                    'cost': {'input': 0,'output': 0,'cacheRead': 0,'cacheWrite': 0}} for m in models]}}}


def stop_process(process):
    if process.poll() is not None:
        return
    if os.name == 'nt':
        subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=10, check=False)
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except PermissionError:
            # Some macOS host policies permit signalling the owned child but not a process group.
            process.kill()
    process.wait(timeout=10)


def run(task_id, model, effort, provider, *, pi_package=None, auth_file=None, transport=None, preflight=False, expected_transport_hash=None, result_file=None):
    from .cli import load
    from .campaign import plan
    config, _ = plan()
    if model not in config['models'] or effort not in config['efforts']:
        raise ValueError('BLOCKED: exact default campaign model and effort required')
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', provider):
        raise ValueError('BLOCKED: invalid provider label')
    tasks, answers, _ = load()
    task = next((t for t in tasks if t['id'] == task_id), None)
    if task is None:
        raise ValueError('unknown_task')
    package = package_path(pi_package)
    node = shutil.which('node')
    if not node:
        raise ValueError('BLOCKED: installed Node.js required; no automatic installation')
    profile = json.loads(PROFILE.read_text(encoding='utf-8'))
    _, profile_hash = profile_identity()
    routing = transport_config(transport, provider, profile)
    if expected_transport_hash is not None and digest(json.dumps(routing,sort_keys=True).encode()) != expected_transport_hash:
        raise ValueError('BLOCKED: transport changed after route binding')
    auth_source = Path(auth_file).expanduser() if auth_file else Path(os.environ.get('PI_CODING_AGENT_DIR', str(Path.home()/'.pi/agent'))) / 'auth.json'
    auth = selected_auth(auth_source, provider)
    env_key = {'openai':'OPENAI_API_KEY','openai-codex':'OPENAI_API_KEY','anthropic':'ANTHROPIC_API_KEY',
               'google':'GEMINI_API_KEY','openrouter':'OPENROUTER_API_KEY'}.get(provider)
    if not auth and env_key and os.environ.get(env_key):
        auth = {provider: {'type':'api_key','key':os.environ[env_key]}}
    if not auth:
        raise ValueError('BLOCKED: no existing credentials for selected Pi provider')
    with tempfile.TemporaryDirectory(prefix='teobench-pi-') as directory:
        root = Path(directory)
        root.chmod(0o700)
        cwd, agent = root/'work', root/'agent'
        cwd.mkdir(); agent.mkdir()
        for name, value in [('auth.json',auth),('models.json',routing)]:
            path = agent/name
            path.write_text(json.dumps(value), encoding='utf-8'); path.chmod(0o600)
        output = Path(result_file).resolve() if result_file else root/'result.json'
        request = dict(packagePath=str(package), cwd=str(cwd), agentDir=str(agent),
                       authPath=str(auth_source.resolve()) if auth.get(provider, {}).get('type') == 'oauth' else str(agent/'auth.json'), modelsPath=str(agent/'models.json'),
                       resultPath=str(output), profile=profile, profileHash=profile_hash,
                       transportHash=digest(json.dumps(routing,sort_keys=True).encode()),
                       task=task, catalog=answers[task_id].get('catalog', {}) if task['family']=='tools' else {},
                       provider=provider, model=model, effort=effort, preflight=preflight)
        started = time.monotonic()
        process = subprocess.Popen([node,str(WORKER)], cwd=cwd, env=clean_environment(agent),
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=os.name!='nt', creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name=='nt' else 0)
        timeout = False
        interrupted = False
        payload = json.dumps(request).encode()
        deadline = started + 240
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timeout = True
                    stop_process(process)
                    break
                try:
                    process.communicate(payload, timeout=min(0.2, remaining))
                    break
                except subprocess.TimeoutExpired:
                    payload = None  # communicate resumes any pending input safely.
                    try:
                        terminal = json.loads(output.read_text(encoding='utf-8')) if output.stat().st_size <= 8_000_000 else {}
                    except (OSError,ValueError):
                        terminal = {}
                    if terminal.get('status') in ('COMPLETED','PREFLIGHT_PASS','BLOCKED','TRANSPORT_ERROR'):
                        # A completed answer must not become a timeout while waiting for client cleanup/EOF.
                        try:
                            process.wait(timeout=1)
                        except subprocess.TimeoutExpired:
                            stop_process(process)
                        break
        except KeyboardInterrupt:
            interrupted = True
            stop_process(process)
        except BaseException:
            stop_process(process)
            raise
        try:
            if output.stat().st_size > 8_000_000:
                raise ValueError('oversized_result')
            result = json.loads(output.read_text(encoding='utf-8'))
        except (OSError,ValueError):
            result = {'status':'BLOCKED','blocker':'worker_did_not_return_receipt',
                      'answer':'','tool_history':[],'transport_error':None,'inference_started':False}
        if result.get('status') not in ('COMPLETED','PREFLIGHT_PASS','BLOCKED','TRANSPORT_ERROR'):
            result.update(status='TRANSPORT_ERROR' if result.get('inference_started') else 'BLOCKED',
                          answer='', transport_error='worker_terminated' if result.get('inference_started') else None,
                          blocker=None if result.get('inference_started') else 'worker_terminated')
        if timeout or interrupted:
            result.update(status='TRANSPORT_ERROR' if result.get('inference_started') else 'BLOCKED',
                          answer='', transport_error=('interrupted' if interrupted else 'timeout') if result.get('inference_started') else None,
                          blocker=None if result.get('inference_started') else ('preflight_interrupted' if interrupted else 'preflight_timeout'))
        result.update(task_id=task_id, model=model, effort=effort, elapsed_seconds=time.monotonic()-started,
                      profile=profile['id'], profile_sha256=profile_hash)
        return result
