"""Real Pi + real container, scripted localhost provider; zero model inference.

This verifies transport/tool wiring only. It never loads Medium tasks/gold,
uses paid credentials or emits benchmark observations.
"""
import argparse
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import tempfile
import threading

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from teobench.medium import MODELS
from teobench.medium_pi_smoke import run


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine',choices=['podman','docker'],required=True)
    parser.add_argument('--image',required=True,help='existing local image with Python, sh and timeout')
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--preflight-all',action='store_true')
    args=parser.parse_args()
    requests=[]
    command="python -c 'import json,pathlib;d=json.loads(pathlib.Path(\"/workspace/input.json\").read_text());pathlib.Path(\"/workspace/output.json\").write_text(json.dumps({\"product\":d[\"a\"]*d[\"b\"]}))'"
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            value=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            requests.append(value)
            tools=[m for m in value['messages'] if m['role']=='tool']
            if not tools:
                delta={'role':'assistant','tool_calls':[{'index':0,'id':'scripted-smoke-call',
                    'type':'function','function':{'name':'terminal','arguments':json.dumps({'command':command})}}]}
                finish='tool_calls'
            else:delta={'role':'assistant','content':'SMOKE_DONE'};finish='stop'
            self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
            for d,f in [(delta,None),({},finish)]:
                event={'id':'scripted-smoke','object':'chat.completion.chunk','created':1,
                       'model':value['model'],'choices':[{'index':0,'delta':d,'finish_reason':f}]}
                self.wfile.write(('data: '+json.dumps(event)+'\n\n').encode())
            self.wfile.write(b'data: [DONE]\n\n');self.wfile.flush()
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    key='TEOBENCH_SCRIPTED_SMOKE_CREDENTIAL';prior=os.environ.get(key)
    os.environ[key]='synthetic-localhost-fixture-not-a-real-credential'
    try:
        with tempfile.TemporaryDirectory(prefix='teobench-scripted-provider-') as directory:
            routing=Path(directory)/'routing.json'
            routing.write_text(json.dumps({'base_url':f'http://127.0.0.1:{server.server_port}/v1',
                'api':'openai-completions','model_routes':{m:'codex/'+m for m in MODELS}}))
            result=run(output=args.output,transport_file=routing,key_env=key,engine=args.engine,
                       image=args.image,preflight_all=args.preflight_all)
        valid=all(r['model']=='codex/gpt-6-luna' and r.get('reasoning_effort')=='high'
                  and [t['function']['name'] for t in r.get('tools',[])]==['terminal'] for r in requests)
        valid=valid and (len(requests)==0 if args.preflight_all else len(requests)==2)
        if not valid:raise ValueError('scripted_provider_wire_contract_failed')
        result.update(provider_kind='scripted_localhost_fixture',real_model_requests=0,
                      scripted_requests=len(requests),wire_contract_verified=True)
        (args.output/'scripted-check.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps({k:result[k] for k in ['status','provider_kind','real_model_requests',
                                             'scripted_requests','wire_contract_verified','artifact_verified']}))
        if result['status']=='BLOCKED':raise SystemExit(2)
    finally:
        server.shutdown();server.server_close()
        if prior is None:os.environ.pop(key,None)
        else:os.environ[key]=prior


if __name__=='__main__':main()
