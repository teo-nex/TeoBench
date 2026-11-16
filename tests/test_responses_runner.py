import json
import contextlib
import io
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from teobench import responses_runner as runner
from teobench.campaign import plan
from teobench.cli import load, execution_profile


class ResponsesRunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.requests = []
        self.mode = 'answer'
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                value = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                owner.requests.append(value)
                if owner.mode == 'http':
                    self.send_response(401)
                    self.end_headers()
                    self.wfile.write(b'secret-must-not-be-logged')
                    return
                if owner.mode == 'redirect':
                    self.send_response(307)
                    self.send_header('Location', '/stolen')
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.end_headers()
                if owner.mode == 'trickle':
                    try:
                        for _ in range(50):
                            self.wfile.write(b':')
                            self.wfile.flush()
                            time.sleep(0.02)
                    except OSError:
                        pass
                    return
                if owner.mode in ('partial', 'incomplete'):
                    events = [dict(type='response.output_text.delta', output_index=0, content_index=0, delta='partial')]
                    if owner.mode == 'incomplete':
                        events.append(dict(type='response.incomplete', response={'status':'incomplete'}))
                else:
                    prior = [x for x in value['input'] if x.get('type') == 'function_call_output']
                    if owner.mode in ('tools','invalid_tool','budget') and (len(prior) < 2 or owner.mode != 'tools'):
                        task = next(t for t in load()[0] if t['id'] == 'T01')
                        node = task['prompt'].split('root ')[1].split('.')[0]
                        if prior:
                            node = json.loads(prior[-1]['output'])['next'] or node
                        output = [dict(type='function_call', name='lookup' if owner.mode != 'invalid_tool' else 'shell',
                            call_id=str(len(prior)), arguments=json.dumps({'id':node}))]
                    else:
                        output = [dict(type='message', role='assistant', content=[dict(type='output_text', text='{"synthetic":true}')])]
                    events = [dict(type='response.completed', response={'status':'completed', 'output':output})]
                for event in events:
                    self.wfile.write(('data: '+json.dumps(event)+'\n\n').encode())
                self.wfile.flush()

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.routing = {'base_url':f'http://127.0.0.1:{self.server.server_port}/v1',
            'models':{m:'codex/'+m for m in plan()[0]['models']}}
        self.transport = self.root/'transport.json'
        self.transport.write_text(json.dumps(self.routing))
        profile, _ = runner.profile_identity()
        self.profile = dict(profile, minimum_request_gap_seconds=0)
        self.addCleanup(patch.stopall)
        patch.dict(os.environ, TEOBENCH_GATEWAY_KEY='synthetic-private-key', PERSONAL_SENTINEL='never-send').start()
        patch.object(runner, 'profile_identity', return_value=(self.profile, 'synthetic-fingerprint')).start()

    def run_trial(self, task='R01', **kw):
        return runner.run(task, 'gpt-6-luna', 'max', transport=self.transport,
            result_file=self.root/'receipt.json', **kw)

    def test_preflight_without_cli_or_network_for_all_conditions(self):
        with patch('shutil.which', side_effect=AssertionError('no CLI discovery')), patch('subprocess.Popen', side_effect=AssertionError('no process')):
            self.assertEqual(execution_profile('auto'), 'responses-clean-v1')
            for model in plan()[0]['models']:
                for effort in plan()[0]['efforts']:
                    result = runner.run('R01', model, effort, transport=self.transport, preflight=True)
                    self.assertEqual(result['status'], 'PREFLIGHT_PASS')
                    self.assertFalse(result['inference_started'])
        self.assertEqual(self.requests, [])

    def test_frozen_context_exact_route_and_effort_no_personal_data(self):
        result = self.run_trial()
        self.assertEqual(result['status'], 'COMPLETED', result)
        request = self.requests[0]
        self.assertEqual(request['model'], 'codex/gpt-6-luna')
        self.assertEqual(request['reasoning'], {'effort':'max'})
        self.assertEqual(request['instructions'], self.profile['system_prompt'])
        self.assertEqual(json.loads(request['input'][0]['content']), next(t for t in load()[0] if t['id']=='R01'))
        self.assertEqual(request['tools'], [])
        self.assertFalse(request['store'])
        self.assertNotIn('synthetic-private-key', json.dumps(result))
        self.assertNotIn('never-send', json.dumps(request))

    def test_lookup_receipts_and_context_round_trip(self):
        self.mode = 'tools'
        result = self.run_trial('T01')
        self.assertEqual(result['status'], 'COMPLETED', result)
        self.assertEqual(len(result['tool_history']), 2)
        self.assertEqual(len(self.requests), 3)
        self.assertEqual(self.requests[0]['tools'][0]['name'], 'lookup')
        self.assertEqual(self.requests[1]['input'][2]['type'], 'function_call_output')

    def test_invalid_tool_and_budget_fail_closed(self):
        for mode in ('invalid_tool','budget'):
            with self.subTest(mode=mode):
                self.mode = mode
                result = self.run_trial('T01')
                self.assertEqual(result['status'], 'TRANSPORT_ERROR')
                self.assertLessEqual(len(result['tool_history']), 4)

    def test_partial_and_incomplete_preserved_without_answer(self):
        for mode in ('partial','incomplete'):
            self.mode = mode
            result = self.run_trial()
            self.assertEqual(result['status'], 'TRANSPORT_ERROR')
            self.assertEqual(result['answer'], '')
            self.assertIn('partial', json.dumps(result['partial_output']))
            self.assertEqual(json.loads((self.root/'receipt.json').read_text()), result)

    def test_http_error_is_sanitized_no_retry(self):
        self.mode = 'http'
        result = self.run_trial()
        self.assertEqual(result['transport_error'], 'http_401')
        self.assertEqual(len(self.requests), 1)
        self.assertNotIn('secret-must-not-be-logged', json.dumps(result))

    def test_no_redirect_or_credential_forwarding(self):
        self.mode = 'redirect'
        result = self.run_trial()
        self.assertEqual(result['transport_error'], 'redirect_rejected')
        self.assertEqual(len(self.requests), 1)

    def test_route_binding_rejects_changed_endpoint(self):
        study = {'method':'test', 'access_route':'test', 'records':[]}
        fingerprint = runner.bind_route(study, 'gateway', self.transport)
        self.routing['base_url'] += '/changed'
        self.transport.write_text(json.dumps(self.routing))
        with self.assertRaisesRegex(ValueError, 'route changed'):
            runner.bind_route(study, 'gateway', self.transport)
        with self.assertRaisesRegex(ValueError, 'transport changed'):
            self.run_trial(expected_transport_hash=fingerprint)
        self.assertEqual(self.requests, [])

    def test_unsafe_routing_rejected_before_network(self):
        for url in ('http://example.com/v1','https://user:pass@example.com/v1','https://example.com/v1?key=secret'):
            self.routing['base_url'] = url
            self.transport.write_text(json.dumps(self.routing))
            with self.assertRaises(ValueError):
                self.run_trial()
        self.assertEqual(self.requests, [])

    def test_total_deadline_terminates_slow_trickle(self):
        self.mode = 'trickle'
        self.profile['timeout_seconds'] = 0.15
        start = time.monotonic()
        result = self.run_trial()
        self.assertEqual(result['transport_error'], 'timeout')
        self.assertLess(time.monotonic()-start, 0.8)

    def test_cli_checkpoint_records_original_and_rejects_duplicate(self):
        from teobench.cli import main
        study = self.root/'study.json'
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['study','create','--id','synthetic-study','--file',str(study),
                '--execution-profile','auto','--access-route','synthetic subscription gateway',
                '--environment','synthetic']), 0)
            args = ['responses-trial','--study',str(study),'--task','R01','--model','gpt-5.6-luna',
                '--effort','high','--replicate','1','--transport',str(self.transport)]
            self.assertEqual(main(args+['--output',str(self.root/'trial1')]), 0)
            original = study.read_bytes()
            self.assertEqual(main(args+['--output',str(self.root/'trial2')]), 2)
            self.assertEqual(study.read_bytes(), original)
            self.assertEqual(main(args+['--output',str(self.root/'trial1')]), 2)
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(len(json.loads(study.read_text())['records']), 1)
