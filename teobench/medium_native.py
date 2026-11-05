"""Pinned Terminal 2.1 and Pro V2 adapters, with source-specific lifecycle.

Only public instructions enter candidate containers. Tests arrive after the
candidate ends. Pro replays the captured diff in a fresh pristine container;
Terminal preserves its running system state as required by upstream tests.
"""
from contextlib import contextmanager, nullcontext
import hashlib
import json
from pathlib import Path
import shlex
import tomllib

from .medium import digest
from .medium_container import TaskContainer, PublicEgress, ContainerError


class NativeTask:
    def __init__(self, docker, task, assets, image_record, proxy_image):
        self.docker=docker;self.task=task;self.proxy_image=proxy_image
        self.base=Path(assets)/task['source']/task['id']
        self.config=tomllib.loads((self.base/'task.toml').read_text())
        self.pro=task['source']=='swe-pro'
        expected=task.get('docker_image') or task['environment']['docker_image']
        if (image_record['status']!='METADATA_PASS' or image_record['image']!=expected
                or image_record['source']!=task['source'] or image_record['id']!=task['id']):
            raise ValueError('image_inventory_task_mismatch')
        self.image_ref=expected.rsplit(':',1)[0]+'@'+image_record['platform_manifest_digest']
        self.image=None;self.workdir=None

    def prepare(self,output):
        output=Path(output);output.mkdir(parents=True,exist_ok=True)
        info=self.docker.pull(self.image_ref,log=output/'image-pull.log',disk_path=output)
        self.image=info['Id'];self.workdir=info['Config'].get('WorkingDir') or '/app'
        (output/'image.json').write_text(json.dumps({'image':self.image_ref,'id':self.image,
            'workdir':self.workdir,'size_bytes':info.get('Size')},indent=2))

    @property
    def prompt(self):
        return (self.base/'instruction.md').read_text()

    @property
    def candidate_seconds(self):
        return int(self.config['agent']['timeout_sec'])

    @contextmanager
    def container(self, *, grading=False):
        if not self.image:raise ContainerError('task_image_not_prepared')
        # Pro's agent phase is offline; its verifier and Terminal use public
        # HTTP(S), with host/private ranges unreachable in either phase.
        public=grading or not self.pro and self.config['environment'].get('allow_internet',False)
        network=PublicEgress(self.docker,self.proxy_image) if public else nullcontext(None)
        with network as egress:
            env=self.config.get('environment',{}).get('env',{}).copy()
            if egress:env.update(egress.environment)
            resources=self.config['environment']
            with TaskContainer(self.docker,self.image,workdir=self.workdir,
                    memory_mb=resources.get('memory_mb',2048),cpus=resources.get('cpus',1),
                    network=egress.name if egress else 'none',environment=env) as container:
                yield container

    def capture_patch(self,container,output):
        # Intent-to-add captures new files while retaining the exact base HEAD.
        # Candidate git hooks/config are untrusted: disable external diff/textconv.
        command="git -c core.hooksPath=/dev/null add -N -- . && git -c core.hooksPath=/dev/null -c core.externalDiff= diff --no-ext-diff --no-textconv --binary HEAD > /tmp/teobench-candidate.diff"
        container.exec(command,timeout=60)
        patch=container.read('/tmp/teobench-candidate.diff',limit=16_000_000)
        Path(output).write_bytes(patch)
        return patch

    def apply_patch(self,container,patch,output):
        path=Path(output)/'candidate.diff';path.write_bytes(patch)
        if not patch.strip():return False
        container.put(path,'/tmp/teobench-replay.diff')
        code,_=container.exec('git -c core.hooksPath=/dev/null apply --check /tmp/teobench-replay.diff && git -c core.hooksPath=/dev/null apply /tmp/teobench-replay.diff',check=False)
        return code==0

    def verify_in(self,container,output):
        output=Path(output);output.mkdir(parents=True,exist_ok=True)
        container.exec('mkdir -p /logs/verifier && rm -f /logs/verifier/reward.txt && rm -rf /tests')
        container.put(self.base/'tests','/tests')
        code,_=container.exec('bash /tests/test.sh',timeout=int(self.config['verifier']['timeout_sec'])+30,
                              check=False,log=output/'verifier.log')
        try:
            value=container.read('/logs/verifier/reward.txt',limit=1024).decode().strip()
        except ContainerError:
            raise ContainerError('official_verifier_reward_missing') from None
        if value not in ('0','1'):raise ContainerError('official_verifier_reward_invalid')
        result={'score':int(value),'verifier_exit_code':code,
                'lifecycle':'fresh_patch_replay' if self.pro else 'same_container_system_state',
                'test_script_sha256':hashlib.sha256((self.base/'tests/test.sh').read_bytes()).hexdigest()}
        (output/'grade.json').write_text(json.dumps(result,indent=2))
        return result

    def grade_patch(self,patch,output):
        Path(output).mkdir(parents=True,exist_ok=True)
        with self.container(grading=True) as grader:
            if not self.apply_patch(grader,patch,output):
                result={'score':0,'reason':'empty_or_unapplicable_patch','lifecycle':'fresh_patch_replay'}
                (Path(output)/'grade.json').write_text(json.dumps(result,indent=2))
                return result
            return self.verify_in(grader,output)

    def accept(self,output):
        """No model requests. Gold, untouched candidate and malformed patch checks."""
        output=Path(output);output.mkdir(parents=True,exist_ok=False)
        self.prepare(output)
        checks={}
        with self.container() as candidate:
            candidate.put(self.base/'solution','/solution')
            candidate.exec('bash /solution/solve.sh',timeout=self.candidate_seconds+30,
                           log=output/'oracle.log')
            if self.pro:
                patch=self.capture_patch(candidate,output/'oracle.diff')
            else:
                checks['oracle']=self.verify_in(candidate,output/'oracle')['score']
        if self.pro:
            (output/'oracle').mkdir()
            checks['oracle']=self.grade_patch(patch,output/'oracle')['score']
            (output/'corrupt').mkdir()
            checks['corrupt']=self.grade_patch(b'not a git patch\n',output/'corrupt')['score']
        # Unlike rejecting an empty patch up front, running the native no-op
        # verifier establishes that the base image cannot pass by itself.
        with self.container(grading=True) as candidate:
            checks['noop']=self.verify_in(candidate,output/'noop')['score']
        if not self.pro and self.task['id']=='regex-log':
            # A syntactically malformed submitted regex tests a corrupt
            # artifact separately from a missing/no-op submission.
            with self.container(grading=True) as candidate:
                bad=output/'invalid-regex.txt';bad.write_text('[')
                candidate.put(bad,'/app/regex.txt')
                checks['corrupt']=self.verify_in(candidate,output/'corrupt')['score']
        passed=checks=={'oracle':1,'noop':0,'corrupt':0}
        record={'source':self.task['source'],'id':self.task['id'],'status':'PASS' if passed else 'BLOCKED',
                'checks':checks,'model_requests':0,'primary_attempts':0,'image':self.image_ref}
        record['sha256']=digest(record)
        (output/'acceptance.json').write_text(json.dumps(record,indent=2))
        return record
