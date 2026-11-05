"""Extract only canonical selected databases from the pinned public data image.

The image is data-only: create a stopped container, never execute its entrypoint.
No personal registry credentials, host mounts, broad extraction or image pruning.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import threading
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from teobench.medium import verify
from teobench.medium_container import Docker,ContainerError

IMAGE='3036197201/bird-mini-dev-sqlite@sha256:4c213bf136e5ee6a4b7565ab03a8c2f4d507f34cd60bcf84322ab47d9a2080df'


def canonical_members(databases):
    # This pinned image overlays Mini-Dev's corrected toxicology DB on the
    # shared dev databases. Both versions have the same basename and size.
    return {('bird/mini_dev/dev_databases/' if name=='toxicology' else 'bird/dev/dev_databases/')+
            name+'/'+name+'.sqlite':name for name in databases}


def prepare(output,docker):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    if (output/'manifest.json').exists():raise ValueError('existing_database_manifest_preserved_use_new_directory')
    selected={t['database'] for t in verify()['tasks'] if t['source']=='bird'}
    wanted=canonical_members(selected);found={}
    docker.pull(IMAGE,log=output/'image-pull.log',disk_path=output)
    owner='teobench-data-'+uuid.uuid4().hex
    _,raw=docker.call(['create','--name',owner,'--label','org.teobench.owner='+owner,
                     '--network=none','--entrypoint=/does-not-run',IMAGE],timeout=180)
    cid=raw.decode().strip()
    try:
        with (output/'copy-errors.log').open('wb') as errors:
            process=subprocess.Popen([docker.executable,'cp',cid+':/bird','-'],stdout=subprocess.PIPE,
                                     stderr=errors,env=docker.env)
            timer=threading.Timer(1200,process.kill);timer.start()
            try:
                with tarfile.open(fileobj=process.stdout,mode='r|') as archive:
                    for member in archive:
                        name=member.name.removeprefix('./')
                        if name not in wanted:continue
                        database=wanted[name]
                        if database in found:raise ValueError('duplicate_canonical_database_member')
                        if not member.isfile() or not 16<=member.size<=2_000_000_000:
                            raise ValueError('invalid_canonical_database_member')
                        part=output/(database+'.part');remaining=member.size;digest=hashlib.sha256()
                        with archive.extractfile(member) as source,part.open('wb') as dest:
                            while remaining:
                                # All output is owned and bounded; never write below reserve.
                                if shutil.disk_usage(output).free<docker.reserve_bytes:
                                    raise ContainerError('host_disk_reserve_reached')
                                data=source.read(min(1024**2,remaining))
                                if not data:raise ValueError('truncated_database')
                                dest.write(data);digest.update(data);remaining-=len(data)
                        with part.open('rb') as stream:
                            if stream.read(16)!=b'SQLite format 3\0':raise ValueError('invalid_sqlite_header')
                        part.replace(output/(database+'.sqlite'))
                        found[database]={'database':database,'member':name,'bytes':member.size,'sha256':digest.hexdigest()}
                if process.wait(timeout=20):raise ContainerError('database_stream_failed')
            finally:
                timer.cancel()
                if process.poll() is None:process.kill();process.wait()
                process.stdout.close()
        if set(found)!=selected:raise ValueError('canonical_database_set_incomplete')
        record={'image':IMAGE,'databases':[found[k] for k in sorted(found)],'model_requests':0}
        (output/'manifest.json').write_text(json.dumps(record,indent=2))
        return {'status':'CANONICAL_DATABASES_EXTRACTED_NOT_GRADED','databases':len(found),'model_requests':0}
    finally:
        _,raw=docker.call(['inspect','--format','{{json .Config.Labels}}',cid])
        if json.loads(raw).get('org.teobench.owner')!=owner:raise ContainerError('dataset_container_owner_changed')
        docker.call(['rm',cid],timeout=180)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--docker');args=p.parse_args()
    print(json.dumps(prepare(args.output,Docker(executable=args.docker))))
