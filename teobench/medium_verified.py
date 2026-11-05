"""Verified: original 4.1.0 specification, scripts and score parser; fresh replay."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from .medium import digest
from .medium_native import NativeTask
from .medium_images import resolve
from .medium_container import ContainerError


class VerifiedTask(NativeTask):
    def __init__(self,docker,task,cache,prepared,proxy_image,*,trusted_python=sys.executable):
        import pyarrow.parquet as pq
        self.docker=docker;self.task=task;self.proxy_image=proxy_image;self.trusted_python=trusted_python
        self.row=next(r for r in pq.read_table(Path(cache)/'swe-verified.parquet').to_pylist() if r['instance_id']==task['id'])
        if digest(self.row)!=task['source_record_sha256']:raise ValueError('verified_source_record_mismatch')
        self.prepared=Path(prepared)/task['id'];self.prepared.mkdir(parents=True,exist_ok=True)
        self.pro=True;self.image=None;self.workdir='/testbed'
        self.config={'agent':{'timeout_sec':1800},'verifier':{'timeout_sec':1800},
                     'environment':{'cpus':1,'memory_mb':4096,'allow_internet':False}}

    def helper(self,request):
        env=self.docker.env.copy()
        env['PYTHONPATH']=str(Path(__file__).resolve().parent.parent)
        run=subprocess.run([self.trusted_python,'-m','teobench.medium_swe_helper'],
            input=json.dumps(request).encode(),capture_output=True,env=env,timeout=180)
        if run.returncode:
            (self.prepared/'helper-error.log').write_bytes(run.stderr)
            raise ContainerError('official_swe_helper_failed')
        try:return json.loads(run.stdout)
        except ValueError:raise ContainerError('official_swe_helper_receipt_invalid') from None

    def prepare_spec(self):
        record=self.prepared/'spec.json'
        if record.exists():self.spec=json.loads(record.read_text())
        else:
            self.spec=self.helper({'action':'spec','row':self.row})
            self.spec['image_pin']=resolve(self.spec['image'])
            record.write_text(json.dumps(self.spec,indent=2))
        self.image_ref=self.spec['image_pin']['immutable_image']
        return self.spec

    def prepare(self,output):
        output=Path(output);output.mkdir(parents=True,exist_ok=True)
        self.prepare_spec()
        info=self.docker.pull(self.image_ref,log=output/'image-pull.log',disk_path=output)
        self.image=info['Id']
        (output/'image.json').write_text(json.dumps({'image':self.image_ref,'id':self.image,
                                                  'size_bytes':info.get('Size')},indent=2))

    @property
    def prompt(self):
        return ('Fix the following issue in the repository at /testbed. Modify the source files; '
                'the grader captures your git diff, replays it in a fresh base container and runs '
                'the official regression tests.\n\n'+self.row['problem_statement'])

    def verify_in(self,container,output):
        output=Path(output);output.mkdir(parents=True,exist_ok=True)
        script=output/'eval.sh';script.write_text(self.spec['eval_script'])
        container.put(script,'/eval.sh')
        code,_=container.exec('bash /eval.sh',timeout=1830,check=False,log=output/'verifier.log')
        patch=(output/'candidate.diff').read_text() if (output/'candidate.diff').exists() else 'noop'
        report=self.helper({'action':'grade','spec':self.spec['spec'],
            'prediction':{'instance_id':self.task['id'],'model_name_or_path':'teobench-medium',
                          'model_patch':patch},'log_path':str((output/'verifier.log').resolve())})
        result={'score':int(report[self.task['id']]['resolved']),'verifier_exit_code':code,
                'lifecycle':'fresh_patch_replay','official_report':report,
                'eval_script_sha256':hashlib.sha256(script.read_bytes()).hexdigest()}
        (output/'grade.json').write_text(json.dumps(result,indent=2))
        return result

    def accept(self,output):
        output=Path(output);output.mkdir(parents=True,exist_ok=False);self.prepare(output)
        checks={}
        (output/'oracle').mkdir();checks['oracle']=self.grade_patch(self.row['patch'].encode(),output/'oracle')['score']
        (output/'corrupt').mkdir();checks['corrupt']=self.grade_patch(b'invalid patch',output/'corrupt')['score']
        with self.container(grading=True) as c:checks['noop']=self.verify_in(c,output/'noop')['score']
        result={'source':'swe-verified','id':self.task['id'],'checks':checks,
                'status':'PASS' if checks=={'oracle':1,'corrupt':0,'noop':0} else 'BLOCKED',
                'model_requests':0,'primary_attempts':0,'image':self.image_ref}
        (output/'acceptance.json').write_text(json.dumps(result,indent=2))
        return result
