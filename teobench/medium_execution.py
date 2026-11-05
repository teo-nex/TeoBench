"""Launch one fresh Pi profile with container-only tools and per-request quota."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

from .medium import ROOT, EFFORTS, digest
from .medium_pi_smoke import transport
from .pi_runner import package_path, clean_environment, stop_process

PROFILE=ROOT/'Medium-Bench/pi-sandbox-v2.json'
WORKER=Path(__file__).with_name('medium_pi_agent.mjs')


def profile_identity():
    profile=json.loads(PROFILE.read_text())
    names=['medium_pi_agent.mjs','medium_execution.py','medium_quota.py','medium_container.py',
           'medium_egress.py','medium_image_tool.py','medium_atomic.mjs','pi_failure.mjs',
           'pi_runner.py','medium.py','medium_pi_smoke.py']
    files=[PROFILE]+[Path(__file__).with_name(n) for n in names]
    return profile,hashlib.sha256(b'\0'.join(p.read_bytes().replace(b'\r\n',b'\n') for p in files)).hexdigest()


def run_agent(*,container,prompt,model,effort,transport_file,output,python,quota_auth,
              account_hash,task_seconds,preflight=False,key_env='TEOBENCH_GATEWAY_KEY',pi_package=None,
              runtime_guard=None):
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
    routing=transport(transport_file,key_env)
    profile,profile_hash=profile_identity()
    package=package_path(pi_package);node=shutil.which('node')
    if not node:raise ValueError('installed_node_required')
    if effort not in EFFORTS:raise ValueError('frozen_effort_required')
    route=routing['model_routes'][model]
    with tempfile.TemporaryDirectory(prefix='teobench-medium-profile-') as directory:
        root=Path(directory);agent=root/'agent';agent.mkdir();work=root/'work';work.mkdir()
        config={'providers':{'teobench-gateway':{'baseUrl':routing['base_url'],'api':routing['api'],
            'apiKey':key_env,'models':[{'id':route,'name':route,'reasoning':True,'input':['text','image'],
            'thinkingLevelMap':{e:e for e in EFFORTS},'contextWindow':profile['context_window'],
            'maxTokens':profile['max_output_tokens'],'cost':{'input':0,'output':0,'cacheRead':0,'cacheWrite':0}}]}}}
        (agent/'models.json').write_text(json.dumps(config));(agent/'auth.json').write_text('{}')
        receipt=output/'pi.json';sessions=output/'sessions';sessions.mkdir()
        engine_env=dict(container.docker.env);engine_env['PYTHONPATH']=str(ROOT)
        request={'packagePath':str(package),'cwd':str(work),'agentDir':str(agent),'authPath':str(agent/'auth.json'),
            'modelsPath':str(agent/'models.json'),'resultPath':str(receipt),'sessionDirectory':str(sessions),
            'profile':profile,'profileHash':profile_hash,'transportHash':digest(routing),
            'benchmarkModel':model,'model':route,'provider':'teobench-gateway','effort':effort,
            'engine':container.docker.executable,'engineEnvironment':engine_env,'container':container.id,
            'workdir':container.workdir,'prompt':prompt,'taskSeconds':task_seconds,'python':str(python),
            'quotaAuthPath':str(quota_auth),'accountHash':account_hash,'preflight':preflight}
        env=clean_environment(agent)
        for key in list(env):
            if key.lower().endswith('_proxy'):del env[key]
        env[key_env]=os.environ[key_env]
        start=time.monotonic()
        active=0;last_poll=start
        with (output/'worker-stderr.log').open('wb') as errors:
            process=subprocess.Popen([node,str(WORKER)],cwd=work,env=env,stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,stderr=errors,start_new_session=os.name!='nt',
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name=='nt' else 0)
            try:
                process.stdin.write(json.dumps(request).encode());process.stdin.close()
                while process.poll() is None:
                    time.sleep(.5)
                    if runtime_guard is not None:runtime_guard()
                    if receipt.exists():
                        try:value=json.loads(receipt.read_text())
                        except (OSError,ValueError):continue
                        current=time.monotonic()
                        if not value.get('quota_waiting'):active+=current-last_poll
                        last_poll=current
                        if active>task_seconds+90:
                            stop_process(process);break
                    elif time.monotonic()-start>90:
                        stop_process(process);break
            finally:
                if process.poll() is None:stop_process(process)
        if not receipt.exists():raise RuntimeError('pi_worker_no_receipt')
        value=json.loads(receipt.read_text())
        value['worker_exit_code']=process.returncode
        if value['status'] in ('RUNNING','READY','QUOTA_PAUSED','INITIALIZING'):
            # A killed process or interrupted stream cannot be silently rerun.
            value.update(status='INTERRUPTED_FIRST_ATTEMPT',error='worker_ended_without_final_receipt')
            receipt.write_text(json.dumps(value))
        return value
