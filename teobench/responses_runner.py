"""Client-independent, stateless Responses trials using only the Python stdlib.

Authentication/routing belongs to an explicitly selected gateway. No Codex/Pi
installation, user configuration, credential discovery, or model fallback.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from .response_stream import ResponseStream, ResponseStreamError

PROFILE = Path(__file__).resolve().parent.parent/'Easy-Bench/profiles/responses-clean-v1.json'
MAX_STREAM_BYTES = 16_000_000


def profile_identity():
    data = b'\0'.join(p.read_bytes().replace(b'\r\n', b'\n') for p in
        (PROFILE, Path(__file__), Path(__file__).with_name('response_stream.py')))
    return json.loads(PROFILE.read_text()), hashlib.sha256(data).hexdigest()


def mark_study(study):
    profile, fingerprint = profile_identity()
    marker = profile['id'] + ':' + fingerprint
    study['method'] = ('Execution profile ' + marker + '; Python stdlib Responses; '
        'fixed instructions; stateless per-task context; 16384 output-token cap; no retries. ' + study['method'])
    study['access_route'] = marker + '; ' + study['access_route']
    return study


def require_profile(study):
    profile, fingerprint = profile_identity()
    marker = profile['id'] + ':' + fingerprint
    if not study['access_route'].startswith(marker + '; ') or ('Execution profile ' + marker + ';') not in study['method']:
        raise ValueError('BLOCKED: create a separate checkpoint with --execution-profile responses-clean-v1')


def transport_config(path, provider='gateway'):
    from .campaign import plan
    if provider != 'gateway' or path is None:
        raise ValueError('BLOCKED: an explicit Responses gateway transport is required')
    value = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if not isinstance(value, dict) or set(value) != {'base_url', 'models'}:
        raise ValueError('BLOCKED: Responses transport requires only base_url and models')
    url = value['base_url']
    parsed = urlsplit(url) if isinstance(url, str) else None
    if (parsed is None or parsed.scheme not in ('http', 'https') or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or (parsed.scheme == 'http' and parsed.hostname not in ('127.0.0.1', 'localhost', '::1'))):
        raise ValueError('BLOCKED: gateway must use HTTPS or loopback HTTP, without URL credentials')
    models = value['models']
    config, _ = plan()
    if (not isinstance(models, dict) or set(models) != set(config['models'])
            or any(not isinstance(v, str) or not v or len(v) > 200 for v in models.values())
            or len(set(models.values())) != len(models)):
        raise ValueError('BLOCKED: explicit distinct routing IDs for all exact campaign models required')
    return value


def routing_hash(routing):
    return hashlib.sha256(json.dumps(routing, sort_keys=True).encode()).hexdigest()


def bind_route(study, provider, transport):
    fingerprint = routing_hash(transport_config(transport, provider))
    marker = 'Responses route ' + fingerprint + ';'
    prior = re.search(r'Responses route [^;]+;', study['method'])
    if prior and prior.group() != marker:
        raise ValueError('BLOCKED: gateway route changed; create a separate study')
    if not prior:
        if study['records']:
            raise ValueError('BLOCKED: existing records have no verified route binding')
        study['method'] += ' ' + marker
        study['access_route'] += '; responses:' + fingerprint
    return fingerprint


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('redirect_rejected')


def receive(response, state, deadline, checkpoint):
    """Bound SSE framing; terminal event, not EOF, defines completion."""
    pending = []
    total = 0
    while True:
        if time.monotonic() >= deadline:
            raise TimeoutError()
        # A separate deadline timer also terminates a slow trickle inside readline.
        response.fp.raw._sock.settimeout(max(0.001, deadline-time.monotonic()))
        raw = response.readline(1_000_001)
        total += len(raw)
        if len(raw) > 1_000_000 or total > MAX_STREAM_BYTES:
            raise ValueError('stream_limit')
        if not raw:
            return state.finish()
        line = raw.decode('utf-8').rstrip('\r\n')
        if line.startswith('data:'):
            pending.append(line[5:].lstrip(' '))
        elif not line and pending:
            payload = '\n'.join(pending)
            pending = []
            if payload == '[DONE]':
                return state.finish()
            output = state.feed(json.loads(payload))
            checkpoint()
            if output is not None:
                return output


def run(task_id, model, effort, provider='gateway', *, auth_file=None, transport=None,
        key_env='TEOBENCH_GATEWAY_KEY', preflight=False, expected_transport_hash=None, result_file=None):
    from .cli import load
    from .campaign import plan
    config, _ = plan()
    if model not in config['models'] or effort not in config['efforts']:
        raise ValueError('BLOCKED: exact campaign model/effort required')
    if auth_file is not None:
        raise ValueError('BLOCKED: use a gateway key environment variable, not a personal auth store')
    routing = transport_config(transport, provider)
    route_hash = routing_hash(routing)
    if expected_transport_hash is not None and route_hash != expected_transport_hash:
        raise ValueError('BLOCKED: transport changed after binding')
    key = os.environ.get(key_env)
    if not key or key.startswith('!') or '\n' in key or '\r' in key:
        raise ValueError('BLOCKED: gateway key environment variable required')
    tasks, answers, _ = load()
    task = next((t for t in tasks if t['id'] == task_id), None)
    if task is None:
        raise ValueError('unknown_task')
    profile, fingerprint = profile_identity()
    started = time.monotonic()
    deadline = started + profile['timeout_seconds']
    result = dict(status='PREFLIGHT_PASS' if preflight else 'READY', blocker=None,
        transport_error=None, answer='', tool_history=[], partial_output=[], inference_started=False,
        task_id=task_id, model=model, effort=effort, profile=profile['id'], profile_sha256=fingerprint,
        elapsed_seconds=0, requests=0,
        receipt=dict(profile_sha256=fingerprint, transport_sha256=route_hash,
            model=model, routing_model=routing['models'][model], effort=effort,
            system_prompt_sha256=hashlib.sha256(profile['system_prompt'].encode()).hexdigest(),
            tools=['lookup'] if task['family']=='tools' else [], max_output_tokens=profile['max_output_tokens']))
    state = None

    def checkpoint():
        result['elapsed_seconds'] = time.monotonic()-started
        if state is not None:
            result['partial_output'] = state.partial_output
        if result_file is not None:
            path = Path(result_file)
            temp = path.with_suffix('.tmp')
            temp.touch(mode=0o600, exist_ok=True)
            temp.write_text(json.dumps(result, ensure_ascii=False))
            temp.replace(path)

    checkpoint()
    if preflight:
        return result
    inputs = [{'role':'user', 'content':json.dumps(task)}]
    tools = []
    if task['family'] == 'tools':
        spec = task['tools'][0]
        tools = [dict(type='function', name='lookup', description=spec['description'], parameters=spec['parameters'])]
    # Ignore ambient HTTP proxies; the explicit gateway owns upstream routing.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    seen = set()
    try:
        while True:
            gap = profile['minimum_request_gap_seconds']
            if time.monotonic()+gap >= deadline:
                raise TimeoutError()
            time.sleep(gap)
            state = ResponseStream()
            payload = dict(model=routing['models'][model], instructions=profile['system_prompt'],
                input=inputs, reasoning={'effort':effort}, max_output_tokens=profile['max_output_tokens'],
                store=False, stream=True, tools=tools, parallel_tool_calls=False)
            request = urllib.request.Request(routing['base_url'].rstrip('/')+'/responses',
                data=json.dumps(payload).encode(), headers={'Authorization':'Bearer '+key,
                    'Content-Type':'application/json', 'Accept':'text/event-stream'})
            result['inference_started'] = True
            result['requests'] += 1
            checkpoint()
            with opener.open(request, timeout=max(0.001, deadline-time.monotonic())) as response:
                if response.headers.get_content_type() != 'text/event-stream':
                    raise ValueError('expected_event_stream')
                sock = response.fp.raw._sock
                def expire():
                    try:
                        sock.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                timer = threading.Timer(max(0.001, deadline-time.monotonic()), expire)
                timer.daemon = True
                timer.start()
                try:
                    output = receive(response, state, deadline, checkpoint)
                finally:
                    timer.cancel()
            calls = [item for item in output if item.get('type') == 'function_call']
            if any(item.get('type') not in ('message','reasoning','function_call') for item in output):
                raise ValueError('unexpected_output_tool')
            if not calls:
                text = ''.join(part['text'] for item in output if item.get('type') == 'message'
                    and item.get('role') == 'assistant' for part in item.get('content', [])
                    if part.get('type') == 'output_text' and isinstance(part.get('text'), str))
                if not text:
                    raise ValueError('missing_final_answer')
                result.update(status='COMPLETED', answer=text)
                break
            if task['family'] != 'tools':
                raise ValueError('unexpected_tool')
            inputs.extend(output)
            for call in calls:
                args = json.loads(call.get('arguments', ''))
                call_id = call.get('call_id')
                if (call.get('name') != 'lookup' or not isinstance(args, dict) or set(args) != {'id'}
                        or not isinstance(args['id'], str) or args['id'] not in answers[task_id]['catalog']
                        or not isinstance(call_id, str) or not call_id or call_id in seen
                        or len(result['tool_history']) >= task['max_rounds']):
                    raise ValueError('invalid_lookup_or_budget')
                seen.add(call_id)
                value = answers[task_id]['catalog'][args['id']]
                result['tool_history'].append(dict(name='lookup', arguments=args, ok=True, output=value))
                inputs.append(dict(type='function_call_output', call_id=call_id, output=json.dumps(value)))
                checkpoint()
    except (urllib.error.HTTPError, urllib.error.URLError, OSError, ValueError,
            ResponseStreamError, KeyboardInterrupt) as error:
        if isinstance(error, urllib.error.HTTPError):
            code = 'http_' + str(error.code)
            error.close()
        elif isinstance(error, ResponseStreamError):
            code = error.kind
        elif isinstance(error, (TimeoutError, socket.timeout)):
            code = 'timeout'
        elif isinstance(error, KeyboardInterrupt):
            code = 'interrupted'
        else:
            # Never include gateway error bodies, credentials or arbitrary exception text.
            code = str(error) if type(error) is ValueError and str(error) in {
                'redirect_rejected','stream_limit','expected_event_stream','unexpected_output_tool',
                'missing_final_answer','unexpected_tool','invalid_lookup_or_budget'} else 'transport_failed'
        if time.monotonic() >= deadline:
            code = 'timeout'
        if result['inference_started']:
            result.update(status='TRANSPORT_ERROR', transport_error=code)
        else:
            result.update(status='BLOCKED', blocker=code)
    checkpoint()
    return result
