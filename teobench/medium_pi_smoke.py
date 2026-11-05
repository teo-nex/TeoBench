"""Explicit clean-Pi sandbox smoke. Never counts as a Medium observation.

Uses an EXISTING local container image and engine. No pulls, mounts, engine
installation, settings changes, host tools or benchmark gold data.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import tempfile
import time
from urllib.parse import urlsplit

from .medium import ROOT, MODELS, EFFORTS, digest
from .pi_runner import package_path, clean_environment, stop_process

PROFILE = ROOT/'Medium-Bench/pi-sandbox-v1.json'
WORKER = Path(__file__).with_name('medium_pi_trial.mjs')


def transport(path, key_env):
    value=json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if set(value) != {'base_url','api','model_routes'}:
        raise ValueError('transport_requires_base_url_api_model_routes')
    url=urlsplit(value['base_url'])
    if url.scheme not in ('http','https') or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError('invalid_transport_url')
    if value['api'] not in ('openai-responses','openai-completions'):
        raise ValueError('unsupported_transport_api')
    routes=value['model_routes']
    if (not isinstance(routes,dict) or set(routes)!=set(MODELS)
        or not all(isinstance(v,str) for v in routes.values()) or len(set(routes.values()))!=7):
        raise ValueError('all_seven_explicit_model_routes_required')
    # Routing prefixes may be added; a route may not alias a different model.
    if any(not isinstance(v,str) or v.split('/')[-1]!=k for k,v in routes.items()):
        raise ValueError('model_route_substitution_forbidden')
    if not re.fullmatch(r'[A-Z][A-Z0-9_]{0,79}',key_env):
        raise ValueError('invalid_credential_variable_name')
    return value


def run(*, output, transport_file, key_env='TEOBENCH_GATEWAY_KEY',
        engine='podman', connection=None, image='docker.io/library/python:3.14.6-alpine',
        model='gpt-6-luna',effort='high',preflight_all=False):
    if model not in MODELS or effort not in EFFORTS:raise ValueError('exact_model_effort_required')
    if engine not in ('podman','docker'):raise ValueError('unsupported_engine')
    if connection and (engine!='podman' or not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}',connection)):
        raise ValueError('invalid_engine_connection')
    binary=shutil.which(engine);node=shutil.which('node');package=package_path()
    if not binary or not node:raise ValueError('BLOCKED: installed engine and Node required')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_./:@-]{0,250}',image):raise ValueError('invalid_image')
    routing=transport(transport_file,key_env)
    if not os.environ.get(key_env):raise ValueError('BLOCKED: gateway credential missing from memory')
    profile=json.loads(PROFILE.read_text())
    profile_hash=hashlib.sha256(b'\0'.join(p.read_bytes() for p in (
        PROFILE,WORKER,Path(__file__),WORKER.with_name('pi_failure.mjs')))).hexdigest()
    prefix=['--connection',connection] if connection else []
    engine_env={k:v for k,v in os.environ.items() if k in {
        'PATH','HOME','XDG_CONFIG_HOME','XDG_DATA_HOME','XDG_RUNTIME_DIR','TMPDIR','LANG','LC_ALL',
        'SystemRoot','SYSTEMROOT','USERPROFILE','COMSPEC','PATHEXT','TEMP','TMP'}}
    def command(args,*,stdin=None,timeout=30):
        result=subprocess.run([binary,*prefix,*args],input=stdin,capture_output=True,text=True,
                              timeout=timeout,env=engine_env)
        if result.returncode:raise ValueError('BLOCKED: container engine operation failed: '+args[0])
        return result.stdout.strip()
    inspected=json.loads(command(['image','inspect',image]))[0]
    image_id=inspected.get('Id') or inspected.get('ID')
    if not re.fullmatch(r'(sha256:)?[a-f0-9]{64}',image_id or ''):raise ValueError('invalid_local_image_id')
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False);output.chmod(0o700)
    container=None
    try:
        container=command(['run','--detach','--pull=never','--network=none','--read-only',
            '--cap-drop=ALL','--security-opt=no-new-privileges','--pids-limit=64',
            '--memory=128m','--cpus=0.5','--user=65534:65534',
            '--tmpfs=/workspace:rw,size=16m,mode=1777','--tmpfs=/tmp:rw,size=16m,mode=1777',
            '--workdir=/workspace','--label=org.teobench.kind=pi-sandbox-smoke',image_id,
            'python','-c','import time; time.sleep(600)'])
        if not re.fullmatch(r'[a-f0-9]{64}',container):raise ValueError('invalid_container_receipt')
        a,b=secrets.randbelow(900)+100,secrets.randbelow(900)+100
        command(['exec','-i',container,'python','-c',
            'import sys,pathlib;pathlib.Path("/workspace/input.json").write_text(sys.stdin.read())'],
            stdin=json.dumps({'a':a,'b':b}))
        prompt=('This is a sandbox infrastructure smoke, not a benchmark observation. '
                'Use the terminal tool to read /workspace/input.json. Multiply a by b and write '
                'a JSON object with only the key product to /workspace/output.json. '
                'You must actually use the tool and create the file. Then return SMOKE_DONE.')
        conditions=[(m,e) for m in MODELS for e in EFFORTS] if preflight_all else [(model,effort)]
        results=[]
        for current_model,current_effort in conditions:
            with tempfile.TemporaryDirectory(prefix='teobench-pi-medium-') as directory:
                private=Path(directory);private.chmod(0o700)
                agent,work=private/'agent',private/'work';agent.mkdir();work.mkdir()
                route=routing['model_routes'][current_model]
                config={'providers':{'teobench-gateway':{'baseUrl':routing['base_url'],
                    'api':routing['api'],'apiKey':'$'+key_env,'models':[{'id':route,
                    'reasoning':True,'input':['text'],'thinkingLevelMap':{e:e for e in EFFORTS},
                    'contextWindow':profile['context_window'],'maxTokens':profile['max_output_tokens'],
                    'cost':{'input':0,'output':0,'cacheRead':0,'cacheWrite':0}}]}}}
                (agent/'models.json').write_text(json.dumps(config));(agent/'auth.json').write_text('{}')
                receipt=output/(current_model+'-'+current_effort+'.json')
                request=dict(packagePath=str(package),cwd=str(work),agentDir=str(agent),
                    authPath=str(agent/'auth.json'),modelsPath=str(agent/'models.json'),
                    resultPath=str(receipt),profile=profile,profileHash=profile_hash,
                    transportHash=digest(routing),benchmarkModel=current_model,
                    model=route,provider='teobench-gateway',effort=current_effort,
                    engine=binary,enginePrefix=prefix,container=container,prompt=prompt,
                    preflight=preflight_all,kind='sandbox_smoke_not_benchmark')
                env=clean_environment(agent);env[key_env]=os.environ[key_env]
                for name in ['XDG_CONFIG_HOME','XDG_DATA_HOME','XDG_RUNTIME_DIR']:
                    if name in engine_env:env[name]=engine_env[name]
                start=time.monotonic()
                proc=subprocess.Popen([node,str(WORKER)],cwd=work,env=env,stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=os.name!='nt',
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name=='nt' else 0)
                try:proc.communicate(json.dumps(request).encode(),timeout=180)
                except subprocess.TimeoutExpired:stop_process(proc)
                result=json.loads(receipt.read_text()) if receipt.exists() else {'status':'NO_RECEIPT'}
                results.append({'model':current_model,'effort':current_effort,'status':result['status'],
                                'requests':result.get('requests',0),'seconds':round(time.monotonic()-start,2)})
                if result['status'] not in ('COMPLETED','PREFLIGHT_PASS'):break
        expected_status='PREFLIGHT_PASS' if preflight_all else 'COMPLETED'
        success=len(results)==len(conditions) and all(r['status']==expected_status for r in results)
        artifact_verified=False
        if not preflight_all and success:
            artifact=json.loads(command(['exec',container,'python','-c',
                'import pathlib;print(pathlib.Path("/workspace/output.json").read_text())']))
            artifact_verified=artifact=={'product':a*b} and bool(result.get('tool_history'))
            success=success and artifact_verified
        summary={'status':('PREFLIGHT_PASS' if preflight_all else 'SMOKE_PASS') if success else 'BLOCKED',
            'kind':'sandbox_smoke_not_benchmark','profile':profile['id'],'profile_sha256':profile_hash,
            'image_id':image_id,'conditions':results,'artifact_verified':artifact_verified,
            'medium_primary_attempts':0,'no_image_pull':True,'no_host_mounts':True,'network':'none'}
        (output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
        return summary
    finally:
        if container:
            # Only the exact container created by this invocation; no pruning.
            command(['rm','--force',container])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--transport',required=True,type=Path)
    parser.add_argument('--key-env',default='TEOBENCH_GATEWAY_KEY')
    parser.add_argument('--engine',choices=['podman','docker'],default='podman')
    parser.add_argument('--connection')
    parser.add_argument('--image',default='docker.io/library/python:3.14.6-alpine')
    parser.add_argument('--model',choices=MODELS,default='gpt-6-luna')
    parser.add_argument('--effort',choices=EFFORTS,default='high')
    parser.add_argument('--preflight-all',action='store_true',help='35 exact selections, zero model requests')
    args=parser.parse_args()
    result=run(output=args.output,transport_file=args.transport,key_env=args.key_env,
        engine=args.engine,connection=args.connection,image=args.image,model=args.model,
        effort=args.effort,preflight_all=args.preflight_all)
    print(json.dumps(result,indent=2))
    if result['status']=='BLOCKED':raise SystemExit(2)


if __name__=='__main__':main()
