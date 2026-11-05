"""Offline policy tests; installed native Codex only talks to a synthetic localhost server."""
import base64
import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from teobench import codex_runner as runner


def jwt(expires):
    return 'synthetic.'+base64.urlsafe_b64encode(json.dumps({'exp':expires}).encode()).decode().rstrip('=')+'.synthetic'


class CodexPolicyTests(unittest.TestCase):
    def test_windows_shim_resolves_existing_native_binary_without_a_shell(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);shim=root/'codex.cmd';shim.write_text('DO NOT EXECUTE')
            binary=root/'node_modules/@openai/codex-win32-x64/vendor/x86_64-pc-windows-msvc/bin/codex.exe'
            binary.parent.mkdir(parents=True);binary.write_bytes(b'synthetic')
            version=runner.profile_identity()[0]['codex_version']
            with patch('teobench.codex_runner.platform.machine',return_value='AMD64'), \
                    patch('teobench.codex_runner.subprocess.run',return_value=subprocess.CompletedProcess([],0,('codex-cli '+version).encode(),b'')) as run:
                self.assertEqual(runner.executable(shim),binary.resolve())
                self.assertEqual(run.call_args.args[0],[str(binary.resolve()),'--version'])
                self.assertNotIn('shell',run.call_args.kwargs)

    def test_missing_pi_selects_installed_codex_without_installing(self):
        from teobench.cli import execution_profile
        with patch('teobench.pi_runner.package_path', side_effect=ValueError('absent')), \
                patch('teobench.codex_runner.executable', return_value=Path('/synthetic/codex')) as check:
            self.assertEqual(execution_profile('auto'),'codex-clean-v1')
            check.assert_called_once_with()

    def test_available_pi_stays_selected(self):
        from teobench.cli import execution_profile
        with patch('teobench.pi_runner.package_path', return_value=Path('/synthetic/pi')), \
                patch('teobench.pi_runner.shutil.which', return_value='node'), \
                patch('teobench.codex_runner.executable', side_effect=AssertionError('must not select Codex')):
            self.assertEqual(execution_profile('auto'),'pi-clean-v1')

    def test_chatgpt_selection_never_falls_back_to_api_billing(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'OPENAI_API_KEY':'synthetic-api-key'}):
            path=Path(directory)/'auth.json'; path.write_text(json.dumps({'OPENAI_API_KEY':'synthetic-api-key'}))
            with self.assertRaisesRegex(ValueError,'never selected automatically'):
                runner.credentials(path)
            self.assertEqual(runner.credentials(path,'api-key')['OPENAI_API_KEY'],'synthetic-api-key')

    def test_selected_credentials_exclude_refresh_token_and_preserve_source(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'auth.json'
            value={'tokens':{'access_token':jwt(time.time()+3600), 'id_token':'synthetic-id',
                'account_id':'synthetic-account', 'refresh_token':'DO-NOT-COPY'}, 'personal_config':'DO-NOT-COPY'}
            raw=json.dumps(value); path.write_text(raw)
            auth=runner.credentials(path)
            self.assertEqual(auth['tokens']['refresh_token'],'')
            self.assertNotIn('DO-NOT-COPY',json.dumps(auth))
            self.assertEqual(path.read_text(),raw)
            for expiration in [time.time()-1,float('nan'),True,'invalid']:
                value['tokens']['access_token']=jwt(expiration);path.write_text(json.dumps(value))
                with self.assertRaisesRegex(ValueError,'existing Codex sign-in normally'):
                    runner.credentials(path)

    def test_chatgpt_tokens_cannot_be_sent_to_an_arbitrary_gateway(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'transport.json';path.write_text(json.dumps({'base_url':'https://example.test/v1'}))
            with self.assertRaisesRegex(ValueError,'never forward a ChatGPT token'):
                runner.transport_config(path)
            self.assertEqual(runner.transport_config(path,'api-key')['provider'],'teobench_gateway')
            for value in [{'base_url':'https://example.test/v1','headers':{}},
                          {'base_url':'https://user:secret@example.test/v1'},
                          {'base_url':'https://example.test/v1?key=private'}]:
                path.write_text(json.dumps(value))
                with self.assertRaises(ValueError):runner.transport_config(path,'api-key')

    def test_clean_child_environment_does_not_modify_parent(self):
        with patch.dict(os.environ, {'HOME':'/original-home','CODEX_HOME':'/original-profile',
                'NODE_OPTIONS':'--import private-hook','OPENAI_API_KEY':'private','CODEX_THREAD_ID':'old-thread'}):
            env=runner.clean_environment(Path('/temporary-home'),Path('/temporary-profile'))
            self.assertEqual(env['HOME'],'/temporary-home')
            self.assertEqual(env['CODEX_HOME'],'/temporary-profile')
            self.assertNotIn('NODE_OPTIONS',env);self.assertNotIn('OPENAI_API_KEY',env)
            self.assertNotIn('CODEX_THREAD_ID',env)
            self.assertEqual(os.environ['HOME'],'/original-home')
            self.assertEqual(os.environ['CODEX_HOME'],'/original-profile')

    def test_route_and_profile_cannot_mix_pi_or_changed_authentication(self):
        from teobench import studies,pi_runner
        study=studies.create('codex-profile-test','Codex benchmark','synthetic fixture')
        with self.assertRaises(ValueError):runner.require_profile(pi_runner.mark_study(copy.deepcopy(study)))
        runner.mark_study(study);runner.require_profile(study)
        runner.bind_route(study,'openai',None)
        with self.assertRaisesRegex(ValueError,'authentication or transport changed'):
            runner.bind_route(study,'openai',None,auth_mode='api-key')
        studies.validate(study,regrade=False)

    def test_cli_records_original_codex_attempt_and_refuses_replay(self):
        from teobench import studies,campaign
        from teobench.cli import main
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);file=root/'study.json'
            study=runner.mark_study(studies.create('codex-profile-test','Codex benchmark','synthetic fixture'))
            studies.save(file,study);job=campaign.coverage(study)['next_trial']
            receipt=dict(status='COMPLETED', profile='codex-clean-v1', profile_sha256='fixture',
                answer='synthetic wrong answer',tool_history=[],transport_error=None,
                inference_started=True,elapsed_seconds=1,profile_removed=True)
            args=['codex-trial','--study',str(file),'--task',job['task_id'],'--model',job['model'],
                '--effort',job['effort'],'--replicate',str(job['replicate'])]
            with patch('teobench.codex_runner.run',return_value=receipt) as run:
                self.assertEqual(main(args+['--output',str(root/'first')]),0)
                self.assertEqual(main(args+['--output',str(root/'replay')]),2)
                self.assertEqual(run.call_count,1)
            self.assertEqual(len(studies.load_json(file)['records']),1)
            self.assertEqual(json.loads((root/'first/receipt.json').read_text())['answer'],receipt['answer'])


class CodexInstalledIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:cls.binary=runner.executable(os.environ.get('TEOBENCH_CODEX_BIN'))
        except (ValueError,OSError):raise unittest.SkipTest('optional pinned native Codex is not installed; no downloads')

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.requests=[];self.tool_mode=False;self.fail=False
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));owner.requests.append(body)
                outputs=[i for i in body.get('input',[]) if i.get('type')=='function_call_output']
                self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
                if owner.fail:
                    events=[{'type':'response.failed','response':{'id':'synthetic','status':'failed','error':{'code':'server_error','message':'private upstream detail'}}}]
                else:
                    if owner.tool_mode and len(outputs)<2:
                        from teobench.cli import load
                        tasks,answers,_=load();task=next(t for t in tasks if t['id']=='T01')
                        first=task['prompt'].split('root ')[1].split('.')[0]
                        node=first if not outputs else answers['T01']['catalog'][first]['next']
                        item={'type':'function_call','id':'fc-'+str(len(outputs)), 'call_id':'call-'+str(len(outputs)),
                              'name':'lookup','arguments':json.dumps({'id':node}), 'status':'completed'}
                    else:
                        item={'id':'msg-synthetic','type':'message','role':'assistant','status':'completed',
                              'content':[{'type':'output_text','text':'synthetic answer','annotations':[]}]}
                    events=[{'type':'response.created','response':{'id':'synthetic','status':'in_progress','output':[]}},
                        {'type':'response.output_item.added','output_index':0,'item':dict(item,status='in_progress')},
                        {'type':'response.output_item.done','output_index':0,'item':item},
                        {'type':'response.completed','response':{'id':'synthetic','status':'completed','output':[item],
                            'usage':{'input_tokens':10,'output_tokens':4,'total_tokens':14}}}]
                for event in events:self.wfile.write(('data: '+json.dumps(event)+'\n\n').encode())
                self.wfile.flush()
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        threading.Thread(target=self.server.serve_forever,daemon=True).start()
        self.addCleanup(self.server.server_close);self.addCleanup(self.server.shutdown)
        self.auth=self.root/'auth.json';self.auth.write_text(json.dumps({'OPENAI_API_KEY':'synthetic'}))
        self.transport=self.root/'transport.json';self.transport.write_text(json.dumps({'base_url':f'http://127.0.0.1:{self.server.server_port}/v1'}))

    def trial(self,task='R01',model='gpt-6-luna',effort='high',**options):
        return runner.run(task,model,effort,codex_bin=self.binary,auth_file=self.auth,
            auth_mode='api-key',transport=self.transport,**options)

    def test_clean_request_and_profile_deleted_while_original_profile_and_result_survive(self):
        personal=self.root/'personal';personal.mkdir()
        (personal/'config.toml').write_text('developer_instructions="PERSONAL_SENTINEL"\n')
        (personal/'AGENTS.md').write_text('PERSONAL_SENTINEL')
        before={p.name:p.read_bytes() for p in personal.iterdir()};created=[]
        configure=runner.configure
        def capture(*args):
            created.append(args[0]);return configure(*args)
        with patch.dict(os.environ,{'CODEX_HOME':str(personal),'NODE_OPTIONS':'--import PERSONAL_SENTINEL'}), \
                patch('teobench.codex_runner.configure',side_effect=capture):
            result=self.trial(effort='max',result_file=self.root/'receipt.json')
        self.assertEqual(result['status'],'COMPLETED',result)
        self.assertTrue(result['profile_removed']);self.assertTrue(created)
        self.assertTrue(all(not p.exists() for p in created))
        self.assertEqual({p.name:p.read_bytes() for p in personal.iterdir()},before)
        self.assertEqual(json.loads((self.root/'receipt.json').read_text())['answer'],'synthetic answer')
        self.assertEqual(len(self.requests),1);body=self.requests[0]
        self.assertEqual(body['reasoning']['effort'],'max')
        self.assertFalse(body.get('tools'))
        self.assertEqual(len(body['input']),2)
        self.assertEqual(body['input'][0]['content'][0]['text'],runner.profile_identity()[0]['system_prompt'])
        self.assertNotIn('PERSONAL_SENTINEL',json.dumps(body));self.assertNotIn(str(self.root),json.dumps(body))

    def test_all_35_conditions_preflight_without_inference_or_retained_profiles(self):
        from teobench import campaign
        config,_=campaign.plan()
        for model in config['models']:
            for effort in config['efforts']:
                with self.subTest(model=model,effort=effort):
                    result=self.trial(model=model,effort=effort,preflight=True)
                    self.assertEqual(result['status'],'PREFLIGHT_PASS',result)
                    self.assertFalse(result['inference_started']);self.assertTrue(result['profile_removed'])
        self.assertEqual(self.requests,[])

    def test_default_chatgpt_route_preflight_does_not_override_reserved_provider(self):
        auth=self.root/'chatgpt.json'
        auth.write_text(json.dumps({'tokens':{'access_token':jwt(time.time()+3600),
            'id_token':jwt(time.time()+3600),'account_id':'synthetic-account','refresh_token':'DO-NOT-COPY'}}))
        before=auth.read_bytes()
        result=runner.run('R01','gpt-6-luna','high',codex_bin=self.binary,auth_file=auth,preflight=True)
        self.assertEqual(result['status'],'PREFLIGHT_PASS',result)
        self.assertFalse(result['inference_started']);self.assertTrue(result['profile_removed'])
        self.assertEqual(auth.read_bytes(),before);self.assertFalse(self.requests)

    def test_trusted_lookup_only_and_extended_effort_survives_tool_rounds(self):
        self.tool_mode=True
        result=self.trial('T01',effort='xhigh')
        self.assertEqual(result['status'],'COMPLETED',result)
        self.assertEqual(len(result['tool_history']),2)
        self.assertEqual(len(self.requests),3)
        for body in self.requests:
            self.assertEqual([t['name'] for t in body['tools']],['lookup'])
            self.assertEqual(body['reasoning']['effort'],'xhigh')
        self.assertTrue(result['profile_removed'])

    def test_failed_turn_still_removes_profile_and_keeps_original_receipt(self):
        self.fail=True
        result=self.trial(result_file=self.root/'receipt.json')
        self.assertEqual(result['status'],'TRANSPORT_ERROR',result)
        self.assertTrue(result['profile_removed']);self.assertEqual(result['answer'],'')
        self.assertEqual(len(self.requests),1)
        self.assertNotIn('private upstream detail',(self.root/'receipt.json').read_text())

    def test_interruption_removes_profile_without_inference(self):
        receive=runner.Client.receive
        def interrupt(client,*args,**kwargs):
            if client.counter==2:raise KeyboardInterrupt()
            return receive(client,*args,**kwargs)
        with patch.object(runner.Client,'receive',interrupt):
            result=self.trial(preflight=True,result_file=self.root/'receipt.json')
        self.assertEqual(result['status'],'BLOCKED',result)
        self.assertEqual(result['blocker'],'interrupted');self.assertTrue(result['profile_removed'])
        self.assertFalse(self.requests)

    def test_interruption_after_dispatch_preserves_attempt_and_removes_profile(self):
        receive=runner.Client.receive
        def interrupt(client,*args,**kwargs):
            if client.counter==4:raise KeyboardInterrupt()
            return receive(client,*args,**kwargs)
        with patch.object(runner.Client,'receive',interrupt):
            result=self.trial(result_file=self.root/'receipt.json')
        self.assertEqual(result['status'],'TRANSPORT_ERROR',result)
        self.assertEqual(result['transport_error'],'interrupted');self.assertTrue(result['profile_removed'])
        self.assertTrue(result['inference_started'])
        self.assertEqual(json.loads((self.root/'receipt.json').read_text())['status'],'TRANSPORT_ERROR')
