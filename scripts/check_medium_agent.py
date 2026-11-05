"""Exercise the Medium v2 Pi client with a scripted localhost provider, no models."""
import argparse,base64,hashlib,json,os,sys,tempfile,threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from teobench.medium import MODELS,EFFORTS
from teobench.medium_container import Docker,TaskContainer
from teobench.medium_execution import run_agent,profile_identity
from teobench.medium_quota import CodexQuotaGuard


def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--docker',required=True);p.add_argument('--image',required=True)
 p.add_argument('--output',type=Path,required=True);p.add_argument('--preflight-all',action='store_true')
 p.add_argument('--quota-auth',type=Path,default=Path.home()/'.codex/auth.json')
 args=p.parse_args();args.output.mkdir(parents=True,exist_ok=False)
 expected_profile=profile_identity()[1]
 docker=Docker(executable=args.docker);info=docker.inspect(args.image)
 if not info:raise ValueError('existing_image_required')
 calls=[]
 png='iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a/ncAAAAASUVORK5CYII='
 shell="python3 -c 'import pathlib,base64;pathlib.Path(\"/app/probe.txt\").write_text(\"verified\");pathlib.Path(\"/app/probe.png\").write_bytes(base64.b64decode(\""+png+"\"))'"
 class Handler(BaseHTTPRequestHandler):
  def log_message(self,*_):pass
  def do_POST(self):
   value=json.loads(self.rfile.read(int(self.headers['Content-Length'])));calls.append(value)
   if len(calls)==1:name,arguments='terminal',{'command':shell}
   elif len(calls)==2:name,arguments='inspect_image',{'path':'/app/probe.png'}
   else:name=None
   if name:
    delta={'role':'assistant','tool_calls':[{'index':0,'id':'fixture-'+str(len(calls)),'type':'function','function':{'name':name,'arguments':json.dumps(arguments)}}]};finish='tool_calls'
   else:delta={'role':'assistant','content':'FIXTURE_COMPLETE'};finish='stop'
   self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
   for d,f in [(delta,None),({},finish)]:
    event={'id':'fixture','object':'chat.completion.chunk','created':1,'model':value['model'],'choices':[{'index':0,'delta':d,'finish_reason':f}]}
    self.wfile.write(('data: '+json.dumps(event)+'\n\n').encode())
   self.wfile.write(b'data: [DONE]\n\n');self.wfile.flush()
 server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
 key='TEOBENCH_SCRIPTED_MEDIUM_KEY';previous=os.environ.get(key);os.environ[key]='synthetic-fixture-not-a-real-credential'
 try:
  transport=args.output/'transport.json';transport.write_text(json.dumps({'base_url':f'http://127.0.0.1:{server.server_port}/v1','api':'openai-completions','model_routes':{m:'codex/'+m for m in MODELS}}))
  if args.preflight_all:account='not-used-without-inference'
  else:
   guard=CodexQuotaGuard(args.quota_auth);guard.check();account=hashlib.sha256(guard.account.encode()).hexdigest()
  combinations=[(m,e) for m in MODELS for e in EFFORTS] if args.preflight_all else [('gpt-6-luna','high')]
  results=[]
  with TaskContainer(docker,info['Id'],workdir='/app',memory_mb=512) as container:
   for model,effort in combinations:
    result=run_agent(container=container,prompt='Create /app/probe.txt containing verified. Inspect the task image if needed.',
     model=model,effort=effort,transport_file=transport,output=args.output/(model+'-'+effort),
     python=sys.executable,quota_auth=args.quota_auth,account_hash=account,task_seconds=180,
     preflight=args.preflight_all,key_env=key)
    assert result['receipt']['profile_sha256']==expected_profile
    results.append({'model':model,'effort':effort,'status':result['status'],'requests':result['requests'],
                    'profile_sha256':result['receipt']['profile_sha256']})
    if result['status']!=('PREFLIGHT_PASS' if args.preflight_all else 'COMPLETED'):raise ValueError('medium_v2_client_failed')
   if not args.preflight_all:
    assert container.read('/app/probe.txt')==b'verified'
    assert len(result['tool_history'])==2 and result['tool_history'][1]['name']=='inspect_image'
  expected=0 if args.preflight_all else 3
  assert len(calls)==expected
  for call in calls:
   assert call['model']=='codex/gpt-6-luna' and call['reasoning_effort']=='high'
   assert [t['function']['name'] for t in call['tools']]==['terminal','inspect_image']
  assert profile_identity()[1]==expected_profile
  record={'status':'PASS','kind':'scripted_fixture_not_benchmark','real_model_requests':0,
   'scripted_requests':len(calls),'conditions':results,'profile_sha256':expected_profile,
   'image_tool_tested':not args.preflight_all,'quota_checked_before_each_scripted_request':not args.preflight_all}
  (args.output/'acceptance.json').write_text(json.dumps(record,indent=2));print(json.dumps(record))
 finally:
  server.shutdown();server.server_close()
  if previous is None:os.environ.pop(key,None)
  else:os.environ[key]=previous


if __name__=='__main__':main()
