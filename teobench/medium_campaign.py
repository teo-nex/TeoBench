"""Medium 100 x 7 x 5 controller. Fail closed before any scored inference.

A private local configuration supplies paths and routing, never credentials.
The gateway key is read from TEOBENCH_GATEWAY_KEY only. No automatic submission.
"""
import argparse,hashlib,json,os,shutil,sys,time
from contextlib import contextmanager
from pathlib import Path

from .medium import ROOT,MODELS,EFFORTS,QUOTAS,verify,digest
from .medium_container import Docker,TaskContainer,ContainerError
from .medium_native import NativeTask
from .medium_bird import BirdTask
from .medium_spreadsheet import SpreadsheetTask
from .medium_verified import VerifiedTask
from .medium_execution import run_agent,profile_identity
from .medium_journal import Journal
from .medium_quota import CodexQuotaGuard


def source_hashes():
    files=sorted((ROOT/'teobench').glob('medium_*.py'))+sorted((ROOT/'teobench').glob('medium_*.mjs'))
    return {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes().replace(b'\r\n',b'\n')).hexdigest() for p in files}


class Campaign:
    def __init__(self,config):
        self.file=Path(config).resolve();self.cfg=json.loads(self.file.read_text())
        required={'cache','assets','databases','native_images','verified_prepared','spreadsheet_prepared',
                  'spreadsheet_image','proxy_image','docker','output','transport','quota_auth','acceptance'}
        if set(self.cfg)!=required:raise ValueError('medium_private_config_fields_mismatch')
        for key in ('cache','assets','databases','native_images','verified_prepared','spreadsheet_prepared',
                    'output','transport','quota_auth'):
            self.cfg[key]=str((self.file.parent/self.cfg[key]).resolve())
        self.out=Path(self.cfg['output']);self.out.mkdir(parents=True,exist_ok=True)
        self.manifest=verify();self.docker=Docker(executable=self.cfg['docker'])
        self.native=json.loads(Path(self.cfg['native_images']).read_text())
        self.assets=json.loads((Path(self.cfg['assets'])/'assets.json').read_text())
        if self.assets['manifest_sha256']!=self.manifest['sha256']:raise ValueError('runtime_assets_selection_mismatch')
        payload={k:v for k,v in self.assets.items() if k!='sha256'}
        if digest(payload)!=self.assets['sha256']:raise ValueError('runtime_assets_inventory_mismatch')
        for source,entries in self.assets['task_files'].items():
            for entry in entries:
                relative=Path(entry['member'])
                if relative.is_absolute() or '..' in relative.parts or '\\' in entry['member']:
                    raise ValueError('invalid_runtime_asset_member')
                p=Path(self.cfg['assets'])/source/entry['task_id']/relative
                if hashlib.sha256(p.read_bytes()).hexdigest()!=entry['sha256']:raise ValueError('runtime_asset_hash_mismatch')
        for name,expected in self.assets['evaluator_sha256'].items():
            p=Path(self.cfg['assets'])/'evaluators'/name
            if hashlib.sha256(p.read_bytes()).hexdigest()!=expected:raise ValueError('official_evaluator_hash_mismatch')

    def adapter(self,task):
        cfg=self.cfg;source=task['source']
        if source in ('terminal','swe-pro'):
            pin=next(p for p in self.native if p['source']==source and p['id']==task['id'])
            return NativeTask(self.docker,task,cfg['assets'],pin,cfg['proxy_image'])
        if source=='bird':return BirdTask(self.docker,task,cfg['cache'],cfg['assets'],cfg['databases'],cfg['proxy_image'])
        if source=='spreadsheet':return SpreadsheetTask(self.docker,task,cfg['cache'],cfg['assets'],cfg['spreadsheet_prepared'],cfg['spreadsheet_image'])
        return VerifiedTask(self.docker,task,cfg['cache'],cfg['verified_prepared'],cfg['proxy_image'])

    def pins(self):
        result=[]
        for task in self.manifest['tasks']:
            source=task['source']
            if source in ('terminal','swe-pro'):
                a=self.adapter(task);pin=next(p for p in self.native if p['source']==source and p['id']==task['id'])
                result.append({'source':source,'id':task['id'],'image':a.image_ref,
                               'compressed_bytes':pin['compressed_layer_bytes']})
            elif source=='swe-verified':
                path=Path(self.cfg['verified_prepared'])/task['id']/'spec.json'
                if not path.exists():continue
                spec=json.loads(path.read_text());pin=spec['image_pin']
                result.append({'source':source,'id':task['id'],'image':pin['immutable_image'],
                               'compressed_bytes':pin['compressed_layer_bytes']})
        return result

    def enforce_disk_reserve(self):
        if shutil.disk_usage(self.out).free<self.docker.reserve_bytes:
            raise ContainerError('host_disk_reserve_reached_no_further_inference')

    def check(self):
        profile,profile_hash=profile_identity();blockers=[];certs={}
        free=shutil.disk_usage(self.out).free;budget=free-self.docker.reserve_bytes
        pins=self.pins()
        if len(pins)!=70:blockers.append('not_all_70_task_image_manifests_pinned')
        oversized=[p for p in pins if p['compressed_bytes']>budget]
        if free<self.docker.reserve_bytes:blockers.append('host_disk_reserve_reached')
        if oversized:blockers.append('image_compressed_lower_bound_exceeds_free_disk_budget')
        for source in QUOTAS:
            configured=self.cfg['acceptance'].get(source)
            p=(self.file.parent/configured).resolve() if configured else None
            if p and p.is_file():cert=json.loads(p.read_text());certs[source]=cert
            else:cert={}
            checks=cert.get('checks',{})
            selected={(t['source'],t['id']) for t in self.manifest['tasks']}
            if (cert.get('status')!='PASS' or checks!={'oracle':1,'noop':0,'corrupt':0}
                    or (source,cert.get('id')) not in selected or cert.get('source')!=source
                    or cert.get('model_requests')!=0):
                blockers.append(source+'_oracle_and_negative_acceptance_pending')
        fixture_path=self.cfg['acceptance'].get('pi_fixture')
        fixture=json.loads((self.file.parent/fixture_path).read_text()) if fixture_path and (self.file.parent/fixture_path).is_file() else {}
        if (fixture.get('status')!='PASS' or fixture.get('profile_sha256')!=profile_hash
                or fixture.get('real_model_requests')!=0 or fixture.get('image_tool_tested') is not True
                or fixture.get('quota_checked_before_each_scripted_request') is not True):
            blockers.append('current_pi_terminal_image_quota_fixture_not_accepted')
        preflight_path=self.cfg['acceptance'].get('pi_preflight')
        preflight=json.loads((self.file.parent/preflight_path).read_text()) if preflight_path and (self.file.parent/preflight_path).is_file() else {}
        expected={(m,e) for m in MODELS for e in EFFORTS}
        got={(r.get('model'),r.get('effort')) for r in preflight.get('conditions',[])
             if r.get('status')=='PREFLIGHT_PASS' and r.get('profile_sha256')==profile_hash and r.get('requests')==0}
        if (preflight.get('status')!='PASS' or preflight.get('profile_sha256')!=profile_hash or got!=expected
                or preflight.get('real_model_requests')!=0):blockers.append('current_35_condition_pi_preflight_pending')
        for task in self.manifest['tasks']:
            if task['source']=='spreadsheet':
                path=Path(self.cfg['spreadsheet_prepared'])/task['id']/'prepared.json'
                if (not path.exists() or json.loads(path.read_text()).get('preparation_version')!=2):
                    blockers.append('spreadsheet_inputs_and_gold_not_all_recalculated');break
        dbpins={p['database']:p['sha256'] for p in json.loads((Path(self.cfg['databases'])/'manifest.json').read_text())['databases']}
        for task in self.manifest['tasks']:
            if task['source']=='bird':
                path=Path(self.cfg['databases'])/'gold-validation'/(task['id']+'.json')
                cert=json.loads(path.read_text()) if path.is_file() else {}
                if (cert.get('status')!='PASS' or cert.get('source_record_sha256')!=task['source_record_sha256']
                        or cert.get('database_sha256')!=dbpins[task['database']] or not cert.get('gold_rows')):
                    blockers.append('bird_gold_database_compatibility_not_all_validated');break
        return {'status':'READY' if not blockers else 'BLOCKED','primary_attempts_planned':3500,
            'primary_attempts_started':0,'manifest_sha256':self.manifest['sha256'],'profile_sha256':profile_hash,
            'blockers':blockers,'host_free_gib':round(free/1024**3,2),'reserve_gib':12,
            'compressed_images_over_budget':[{'source':p['source'],'id':p['id'],'gib':round(p['compressed_bytes']/1024**3,2)} for p in oversized],
            'uncompressed_image_sizes_not_guaranteed':True,'pinned_task_images':len(pins),'model_requests':0}

    def protocol(self):
        prepared={t['id']:json.loads((Path(self.cfg['spreadsheet_prepared'])/t['id']/'prepared.json').read_text())
                  for t in self.manifest['tasks'] if t['source']=='spreadsheet'}
        value={'manifest_sha256':self.manifest['sha256'],'profile_sha256':profile_identity()[1],
            'source_sha256':source_hashes(),'assets_sha256':self.assets['sha256'],'images':self.pins(),
            'verified_specs_sha256':{t['id']:hashlib.sha256((Path(self.cfg['verified_prepared'])/t['id']/'spec.json').read_bytes()).hexdigest()
                                     for t in self.manifest['tasks'] if t['source']=='swe-verified'},
            'spreadsheet_prepared':prepared,'databases':json.loads((Path(self.cfg['databases'])/'manifest.json').read_text()),
            'transport_sha256':digest(json.loads(Path(self.cfg['transport']).read_text())),
            'parallel_trials':1,'global_request_gap_seconds':4,'no_inference_retries':True,
            'quota_reserve_percent':30,'per_source_scores':True,'source_weights':{s:.2 for s in QUOTAS}}
        value['sha256']=digest(value);return value

    @contextmanager
    def lock(self):
        path=self.out/'controller.lock'
        try:fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        except FileExistsError:raise ValueError('controller_lock_exists_verify_owner_before_resuming') from None
        try:
            os.write(fd,json.dumps({'pid':os.getpid(),'started':time.time()}).encode());os.close(fd)
            yield
        finally:path.unlink()

    def run(self):
        with self.lock():
            readiness=self.check();(self.out/'readiness.json').write_text(json.dumps(readiness,indent=2))
            if readiness['status']!='READY':return readiness
            guard=CodexQuotaGuard(self.cfg['quota_auth']);guard.check()
            account_hash=hashlib.sha256(guard.account.encode()).hexdigest()
            protocol=self.protocol();path=self.out/'protocol.json'
            if path.exists() and json.loads(path.read_text())!=protocol:raise ValueError('existing_protocol_changed_no_resume')
            path.write_text(json.dumps(protocol,indent=2))
            journal=Journal(self.out/'study.sqlite',self.manifest,protocol['sha256'])
            try:
                # A saved artifact may be regraded without ever invoking a model.
                for source,task_id,model,effort,artifact_path,receipt_text in journal.db.execute(
                        "SELECT source,task,model,effort,artifact,receipt FROM attempts WHERE state='GENERATED'").fetchall():
                    task=next(t for t in self.manifest['tasks'] if t['source']==source and t['id']==task_id)
                    adapter=self.adapter(task);out=self.out/'tasks'/source/task_id/model/effort
                    if source=='terminal':grade=json.loads((out/'grade/grade.json').read_text())
                    else:
                        artifact=self.out/artifact_path;receipt=json.loads(receipt_text)
                        if hashlib.sha256(artifact.read_bytes()).hexdigest()!=receipt['captured_artifact_sha256']:
                            raise ValueError('saved_candidate_artifact_changed_no_regrade')
                        if isinstance(adapter,NativeTask):
                            adapter.prepare(out/'regrade-environment')
                            grade=adapter.grade_patch(artifact.read_bytes(),out/'regrade')
                        else:grade=adapter.grade(artifact.read_bytes(),out/'regrade')
                    journal.transition((source,task_id,model,effort),'GENERATED','GRADED',score=grade['score'])
                unresolved=journal.db.execute("SELECT COUNT(*) FROM attempts WHERE state='STARTED'").fetchone()[0]
                if unresolved:
                    return {'status':'BLOCKED','blocker':'interrupted_first_attempts_require_receipt_audit_no_retry',
                            'unresolved_slots':unresolved,'journal':journal.status()}
                for task in self.manifest['tasks']:
                    slots=[r for r in journal.slots(task) if r[2]=='PLANNED']
                    if not slots:continue
                    self.enforce_disk_reserve()
                    adapter=self.adapter(task);task_dir=self.out/'tasks'/task['source']/task['id']
                    task_dir.mkdir(parents=True,exist_ok=True)
                    if isinstance(adapter,NativeTask):adapter.prepare(task_dir/'environment')
                    elif isinstance(adapter,SpreadsheetTask):adapter.prepare()
                    for model,effort,_ in slots:
                        self.enforce_disk_reserve()
                        guard.check()
                        slot=(task['source'],task['id'],model,effort);out=task_dir/model/effort
                        out.mkdir(parents=True,exist_ok=False)
                        journal.transition(slot,'PLANNED','STARTED')
                        with adapter.container() as candidate:
                            result=run_agent(container=candidate,prompt=adapter.prompt,model=model,effort=effort,
                                transport_file=self.cfg['transport'],output=out/'agent',python=sys.executable,
                                quota_auth=self.cfg['quota_auth'],account_hash=account_hash,task_seconds=adapter.candidate_seconds,
                                runtime_guard=self.enforce_disk_reserve)
                            if result['status'] not in ('COMPLETED','BUDGET_EXHAUSTED'):
                                state='TRANSPORT_ERROR' if result['requests'] else 'INFRA_BLOCKED'
                                journal.transition(slot,'STARTED',state,requests=result['requests'],receipt=result)
                                (self.out/'status.json').write_text(json.dumps(journal.status(),indent=2))
                                # Stop after the first transport failure; no retries,
                                # no repeated charges on a broken route or profile.
                                return journal.status()
                            if task['source']=='terminal':
                                grade=adapter.verify_in(candidate,out/'grade');artifact=None
                            elif task['source'] in ('swe-pro','swe-verified'):
                                artifact=out/'candidate.diff';adapter.capture_patch(candidate,artifact)
                            else:
                                target='/app/answer.sql' if task['source']=='bird' else '/app/output.xlsx'
                                try:data=candidate.read(target,limit=1_000_000 if task['source']=='bird' else 32_000_000)
                                except ContainerError:
                                    # Establish a live daemon/container before treating
                                    # a missing/invalid submitted file as a wrong answer.
                                    self.docker.call(['inspect',candidate.id]);data=b''
                                artifact=out/('answer.sql' if task['source']=='bird' else 'output.xlsx');artifact.write_bytes(data)
                            if artifact:
                                result['captured_artifact_sha256']=hashlib.sha256(artifact.read_bytes()).hexdigest()
                            journal.transition(slot,'STARTED','GENERATED',requests=result['requests'],
                                               artifact=str(artifact.relative_to(self.out)) if artifact else None,receipt=result)
                        if task['source']!='terminal':
                            self.enforce_disk_reserve()
                            if isinstance(adapter,NativeTask):grade=adapter.grade_patch(artifact.read_bytes(),out/'grade')
                            else:grade=adapter.grade(artifact.read_bytes(),out/'grade')
                        journal.transition(slot,'GENERATED','GRADED',score=grade['score'])
                        status=journal.status();(self.out/'status.json').write_text(json.dumps(status,indent=2))
                        print(json.dumps({'source':task['source'],'task':task['id'],'model':model,'effort':effort,
                                          'score':grade['score'],'graded':status['graded']}),flush=True)
                return journal.status()
            finally:journal.close()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['check','prepare-metadata','accept','run'])
    p.add_argument('--config',type=Path,required=True);p.add_argument('--source',choices=list(QUOTAS));p.add_argument('--task')
    args=p.parse_args();campaign=Campaign(args.config)
    if args.action=='check':result=campaign.check()
    elif args.action=='prepare-metadata':
        for task in campaign.manifest['tasks']:
            if task['source']=='swe-verified':campaign.adapter(task).prepare_spec()
            elif task['source']=='spreadsheet':campaign.adapter(task).prepare()
            elif task['source']=='bird':campaign.adapter(task).validate_gold()
        result=campaign.check()
    elif args.action=='accept':
        if not args.source or not args.task:p.error('accept requires --source and --task')
        task=next(t for t in campaign.manifest['tasks'] if t['source']==args.source and t['id']==args.task)
        result=campaign.adapter(task).accept(campaign.out/'acceptance'/args.source/(args.task+'-'+str(time.time_ns())))
    else:result=campaign.run()
    print(json.dumps(result,indent=2))
    if result.get('status')=='BLOCKED':raise SystemExit(2)


if __name__=='__main__':main()
