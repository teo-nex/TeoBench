"""Offline policy tests and optional real-Pi tests against a localhost fake server."""
import copy
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from teobench import pi_runner


class PiPolicyTests(unittest.TestCase):
    def test_windows_npm_shim_discovers_the_actual_package_without_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            prefix=Path(directory)/'npm prefix with spaces';prefix.mkdir()
            shim=prefix/'pi.cmd'
            shim.write_text('@echo off\n"%dp0%\\node_modules\\@earendil-works\\pi-coding-agent\\dist\\bundle\\cli.js" %*\n')
            package=prefix/'node_modules/@earendil-works/pi-coding-agent';package.mkdir(parents=True)
            (package/'package.json').write_text(json.dumps({'name':'@earendil-works/pi-coding-agent','version':'0.85.1'}))
            with patch('teobench.pi_runner.shutil.which',return_value=str(shim)), \
                 patch('teobench.pi_runner.subprocess.Popen',side_effect=AssertionError('do not execute shim')):
                self.assertEqual(pi_runner.package_path(),package.resolve())

    def test_windows_shim_must_not_silently_choose_another_installed_pi(self):
        with tempfile.TemporaryDirectory() as directory:
            prefix=Path(directory);shim=prefix/'pi.cmd'
            shim.write_text('"%dp0%\\node_modules\\@mariozechner\\pi-coding-agent\\dist\\cli.js"')
            for scope,version in [('@mariozechner','0.1.0'),('@earendil-works','0.85.1')]:
                package=prefix/'node_modules'/scope/'pi-coding-agent';package.mkdir(parents=True)
                (package/'package.json').write_text(json.dumps({'name':scope+'/pi-coding-agent','version':version}))
            with patch('teobench.pi_runner.shutil.which',return_value=str(shim)):
                with self.assertRaisesRegex(ValueError,'requires Pi 0.85.1'):pi_runner.package_path()

    def test_environment_drops_runtime_injection_and_unrelated_secrets(self):
        env = pi_runner.clean_environment('/clean', {'PATH':'/bin','HOME':'/real-home',
            'NODE_OPTIONS':'--import personal-hook.mjs','PI_PACKAGE_DIR':'/personal',
            'CODEX_HOME':'/private','ANTHROPIC_API_KEY':'unrelated','OPENAI_API_KEY':'private',
            'PI_CODING_AGENT_DIR':'/personal','PI_CODING_AGENT_SESSION_DIR':'/old-sessions'})
        self.assertEqual(env['HOME'],'/real-home')
        self.assertEqual(env['PI_CODING_AGENT_DIR'],'/clean')
        self.assertEqual(set(env), {'PATH','HOME','PI_CODING_AGENT_DIR','PI_OFFLINE','PI_TELEMETRY'})

    def test_auth_selects_only_one_provider_and_preserves_source(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'auth.json'
            original=json.dumps({'chosen':{'type':'api_key','key':'synthetic'},'other':{'key':'unrelated'}})
            p.write_text(original)
            self.assertEqual(pi_runner.selected_auth(p,'chosen'), {'chosen':{'type':'api_key','key':'synthetic'}})
            self.assertEqual(p.read_text(),original)
            p.write_text(json.dumps({'chosen':{'type':'api_key','key':'!do-not-run'}}))
            with self.assertRaisesRegex(ValueError,'executable credential'):
                pi_runner.selected_auth(p,'chosen')

    def test_transport_rejects_settings_commands_keys_and_model_aliases(self):
        profile=json.loads(pi_runner.PROFILE.read_text())
        base={'base_url':'https://example.test/v1','api':'openai-completions','models':['gpt-6-luna']}
        bad=[dict(base,apiKey='private'),dict(base,settings={}),dict(base,models=['luna']),
             dict(base,base_url='https://user:password@example.test/v1'),
             dict(base,base_url='https://example.test/v1?key=private'),dict(base,api='!command')]
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'transport.json'
            for value in bad:
                with self.subTest(value=value):
                    p.write_text(json.dumps(value))
                    with self.assertRaises(ValueError):pi_runner.transport_config(p,'chosen',profile)
            p.write_text(json.dumps(base));result=pi_runner.transport_config(p,'chosen',profile)
            model=result['providers']['chosen']['models'][0]
            self.assertEqual(model['maxTokens'],profile['max_output_tokens'])
            self.assertTrue(model['reasoning'])

    def test_invalid_model_effort_and_provider_fail_before_process(self):
        with patch('teobench.pi_runner.subprocess.Popen',side_effect=AssertionError('must not launch')):
            for model,effort,provider in [('alias','high','provider'),('gpt-6-luna','ultra','provider'),
                                          ('gpt-6-luna','high','provider/private')]:
                with self.assertRaisesRegex(ValueError,'BLOCKED'):
                    pi_runner.run('R01',model,effort,provider)

    def test_clean_cohort_and_route_binding_cannot_mix_historical_or_changed_profiles(self):
        from teobench import studies
        study=studies.create('clean-profile-test','Pi benchmark','synthetic offline fixture')
        original=copy.deepcopy(study)
        with self.assertRaisesRegex(ValueError,'separate checkpoint'):pi_runner.require_profile(study)
        pi_runner.mark_study(study);pi_runner.require_profile(study)
        first=pi_runner.bind_route(study,'chosen',None)
        self.assertEqual(first,pi_runner.bind_route(study,'chosen',None))
        with self.assertRaisesRegex(ValueError,'provider or transport changed'):pi_runner.bind_route(study,'other',None)
        self.assertNotEqual(study['access_route'],original['access_route'])
        self.assertEqual(study['benchmark'],original['benchmark'])
        studies.validate(study,regrade=False)

    def test_checkpoint_records_result_without_reinference_and_refuses_replay(self):
        from teobench import studies,campaign
        from teobench.cli import main
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory);file=p/'study.json'
            study=pi_runner.mark_study(studies.create('clean-profile-test','Pi benchmark','synthetic fixture'))
            studies.save(file,study);job=campaign.coverage(study)['next_trial']
            receipt={'status':'COMPLETED','profile':'pi-clean-v1','profile_sha256':'fixture',
                     'answer':'synthetic wrong answer','tool_history':[], 'transport_error':None,
                     'inference_started':True,'elapsed_seconds':1}
            args=['pi-trial','--study',str(file),'--task',job['task_id'],'--model',job['model'],
                  '--effort',job['effort'],'--replicate',str(job['replicate']),'--provider','benchmark']
            with patch('teobench.pi_runner.run',return_value=receipt) as run:
                self.assertEqual(main(args+['--output',str(p/'first')]),0)
                self.assertEqual(run.call_count,1)
                self.assertEqual(main(args+['--output',str(p/'second')]),2)
                self.assertEqual(run.call_count,1)
            saved=studies.load_json(file)
            self.assertEqual(len(saved['records']),1)
            self.assertEqual(saved['records'][0]['replicate'],1)
            self.assertFalse(saved['records'][0]['evaluation']['semantic_pass'])

    def worker_result(self, status, interrupted=False):
        import subprocess
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);package=root/'package';package.mkdir()
            (package/'package.json').write_text(json.dumps({'name':'@earendil-works/pi-coding-agent','version':'0.85.1'}))
            auth=root/'auth.json';auth.write_text(json.dumps({'benchmark':{'type':'api_key','key':'synthetic'}}))
            class Process:
                calls=0
                def wait(self,timeout):
                    raise subprocess.TimeoutExpired('synthetic cleanup hang',timeout)
                def communicate(self,payload,timeout):
                    self.calls+=1
                    if payload is not None:
                        request=json.loads(payload);self.output=Path(request['resultPath'])
                    if self.calls==1:
                        self.output.write_text(json.dumps({'status':status,'inference_started':True,
                            'answer':'completed answer' if status=='COMPLETED' else '',
                            'tool_history':[], 'transport_error':None}))
                        if interrupted:raise KeyboardInterrupt()
                        raise subprocess.TimeoutExpired('synthetic child',timeout)
                    self.output.write_text(json.dumps({'status':'COMPLETED','inference_started':True,
                        'answer':'completed answer','tool_history':[], 'transport_error':None}))
            process=Process()
            with patch('teobench.pi_runner.subprocess.Popen',return_value=process), \
                 patch('teobench.pi_runner.shutil.which',return_value='node'), \
                 patch('teobench.pi_runner.stop_process') as stop:
                value=pi_runner.run('R01','gpt-6-luna','high','benchmark',pi_package=package,
                    auth_file=auth,result_file=root/'persistent.json')
                return value,process.calls,stop.call_count

    def test_completed_result_does_not_wait_for_worker_eof(self):
        result,calls,stops=self.worker_result('COMPLETED')
        self.assertEqual(result['status'],'COMPLETED')
        self.assertEqual(result['answer'],'completed answer')
        self.assertEqual(calls,1)
        self.assertEqual(stops,1)

    def test_ready_preflight_is_not_mistaken_for_completed_inference(self):
        result,calls,_=self.worker_result('READY')
        self.assertEqual(result['status'],'COMPLETED')
        self.assertEqual(calls,2)

    def test_interruption_preserves_original_attempt_as_transport_error(self):
        result,_,stops=self.worker_result('READY',interrupted=True)
        self.assertEqual(result['status'],'TRANSPORT_ERROR')
        self.assertEqual(result['transport_error'],'interrupted')
        self.assertEqual(result['answer'],'')
        self.assertEqual(stops,1)

    def test_unsupported_pi_version_fails_without_install_or_inference(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory);(p/'package.json').write_text(json.dumps({'name':'@earendil-works/pi-coding-agent','version':'0.1'}))
            with self.assertRaisesRegex(ValueError,'requires Pi'):pi_runner.package_path(p)


class PiInstalledIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:cls.package=pi_runner.package_path(os.environ.get('TEOBENCH_PI_PACKAGE'))
        except (ValueError,OSError):raise unittest.SkipTest('optional pinned Pi SDK is not installed; no packages downloaded')
        if not shutil.which('node'):raise unittest.SkipTest('optional Node.js not installed')

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.requests=[];self.tool_mode=False
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                value=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                owner.requests.append(value)
                tools=[m for m in value['messages'] if m['role']=='tool']
                if owner.tool_mode and len(tools)<2:
                    from teobench.cli import load
                    _,answers,_=load();catalog=answers['T01']['catalog']
                    task=next(t for t in load()[0] if t['id']=='T01')
                    first=task['prompt'].split('root ')[1].split('.')[0]
                    node=first if not tools else catalog[first]['next']
                    delta={'role':'assistant','tool_calls':[{'index':0,'id':'test-call-'+str(len(tools)),
                        'type':'function','function':{'name':'lookup','arguments':json.dumps({'id':node})}}]}
                    finish='tool_calls'
                else:delta={'role':'assistant','content':'{"synthetic":true}'};finish='stop'
                self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
                for d,f in [(delta,None),({},finish)]:
                    chunk={'id':'test','object':'chat.completion.chunk','created':1,'model':'gpt-6-luna',
                           'choices':[{'index':0,'delta':d,'finish_reason':f}]}
                    self.wfile.write(('data: '+json.dumps(chunk)+'\n\n').encode())
                self.wfile.write(b'data: [DONE]\n\n');self.wfile.flush()
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        threading.Thread(target=self.server.serve_forever,daemon=True).start()
        self.addCleanup(self.server.server_close);self.addCleanup(self.server.shutdown)
        self.auth=self.root/'auth.json';self.auth.write_text(json.dumps({'benchmark':{'type':'api_key','key':'synthetic'}}))
        self.transport=self.root/'transport.json';self.transport.write_text(json.dumps({
            'base_url':f'http://127.0.0.1:{self.server.server_port}/v1','api':'openai-completions','models':['gpt-6-luna']}))

    def run_trial(self,task='R01',**kw):
        return pi_runner.run(task,'gpt-6-luna','high','benchmark', pi_package=self.package,
            auth_file=self.auth, transport=self.transport, **kw)

    def test_real_pi_sends_only_frozen_prompt_and_public_task(self):
        poison=self.root/'poison.mjs';poison.write_text('throw new Error("PERSONAL_HOOK_LOADED")')
        personal=self.root/'personal';personal.mkdir()
        for name in ('AGENTS.md','SYSTEM.md','APPEND_SYSTEM.md'):
            (personal/name).write_text('PERSONAL_SENTINEL_MUST_NOT_REACH_MODEL')
        (personal/'settings.json').write_text(json.dumps({'defaultModel':'wrong-model','extensions':[str(poison)]}))
        with patch.dict(os.environ,{'NODE_OPTIONS':'--import '+str(poison),'PI_CODING_AGENT_DIR':str(self.root/'personal')}):
            result=self.run_trial()
        self.assertEqual(result['status'],'COMPLETED',result)
        self.assertEqual(result['answer'],'{"synthetic":true}')
        self.assertEqual(len(self.requests),1)
        request=self.requests[0];profile=json.loads(pi_runner.PROFILE.read_text())
        self.assertEqual(request['messages'][0]['content'],profile['system_prompt'])
        self.assertEqual(len(request['messages']),2)
        self.assertEqual(request['reasoning_effort'],'high')
        self.assertEqual(request['max_completion_tokens'],16384)
        self.assertFalse(request.get('tools'))
        self.assertNotIn(str(self.root),json.dumps(request))
        self.assertNotIn('catalog',json.dumps(request))

    def test_preflight_has_zero_inference_and_no_session_history(self):
        result=self.run_trial(preflight=True)
        self.assertEqual(result['status'],'PREFLIGHT_PASS',result)
        self.assertFalse(result['inference_started'])
        self.assertEqual(self.requests,[])

    def test_all_campaign_efforts_select_exactly_and_extended_efforts_reach_wire(self):
        from teobench import campaign
        config,_=campaign.plan()
        routing=json.loads(self.transport.read_text());routing['models']=config['models']
        self.transport.write_text(json.dumps(routing))
        for model in config['models']:
            for effort in config['efforts']:
                with self.subTest(model=model,effort=effort):
                    result=pi_runner.run('R01',model,effort,'benchmark',pi_package=self.package,
                        auth_file=self.auth,transport=self.transport,preflight=True)
                    self.assertEqual(result['status'],'PREFLIGHT_PASS',result)
        self.assertEqual(self.requests,[])
        for effort in ('xhigh','max'):
            result=pi_runner.run('R01','gpt-6-luna',effort,'benchmark',pi_package=self.package,
                auth_file=self.auth,transport=self.transport)
            self.assertEqual(result['status'],'COMPLETED',result)
            self.assertEqual(self.requests[-1]['reasoning_effort'],effort)

    def test_tool_task_executes_trusted_lookup_and_retains_receipts(self):
        self.tool_mode=True
        result=self.run_trial('T01')
        self.assertEqual(result['status'],'COMPLETED',result)
        self.assertEqual(len(result['tool_history']),2)
        self.assertEqual(len(self.requests),3)
        for request in self.requests:
            self.assertEqual([t['function']['name'] for t in request['tools']],['lookup'])
        self.assertTrue(all(r['ok'] for r in result['tool_history']))

    def test_missing_exact_model_blocks_before_inference(self):
        value=json.loads(self.transport.read_text());value['models']=['gpt-5.6-luna']
        self.transport.write_text(json.dumps(value))
        result=self.run_trial()
        self.assertEqual(result['status'],'BLOCKED',result)
        self.assertEqual(result['blocker'],'exact_model_unavailable')
        self.assertEqual(self.requests,[])

    def test_provider_catalog_effort_remapping_is_blocked_before_inference(self):
        profile=json.loads(pi_runner.PROFILE.read_text())
        routing=pi_runner.transport_config(self.transport,'benchmark',profile)
        routing['providers']['benchmark']['models'][0]['thinkingLevelMap']['high']='low'
        with patch('teobench.pi_runner.transport_config',return_value=routing):
            result=self.run_trial()
        self.assertEqual(result['status'],'BLOCKED',result)
        self.assertEqual(result['blocker'],'effort_mapping_unsupported')
        self.assertEqual(self.requests,[])
