"""Prepare the pinned 100-task selection. Requires optional pyarrow==26.0.1.

Only downloads public data. Never executes downloaded code or starts an engine.
Cache contains acceptance data: never mount the cache in a candidate sandbox.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys
import tomllib
import urllib.request
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from teobench.medium import SEED, QUOTAS, MODELS, EFFORTS, select, digest

PINS = {
 'terminal': {'repository':'https://github.com/harbor-framework/terminal-bench-2-1',
              'revision':'7131e4375048a0e408a8fb404b5f499d726b695b'},
 'swe-pro': {'repository':'https://huggingface.co/datasets/ScaleAI/SWE-bench_Pro',
             'revision':'2d52cb3df914a3fcf80c7f66738b3a88ae37fc50',
             'file':'data/default/test-00000-of-00001.parquet'},
 'swe-verified': {'repository':'https://huggingface.co/datasets/SWE-bench/SWE-bench_Verified',
                  'revision':'78f471bf655a3137b2e8a75af1501690ec009ec3',
                  'file':'data/test-00000-of-00001.parquet'},
 'bird': {'repository':'https://huggingface.co/datasets/birdsql/bird_mini_dev',
          'revision':'5b256b5a9c17478f06ed6912612e9a14d17065c8',
          'file':'data/mini_dev_sqlite.jsonl'},
 'spreadsheet': {'repository':'https://huggingface.co/datasets/KAKA22/SpreadsheetBench-v2',
                 'revision':'5a2215ed4121945ab09d8723df2995602090b042',
                 'file':'spreadsheetbench-v2-09-10.zip',
                 'grader_repository':'https://github.com/RUCKBReasoning/SpreadsheetBench-2',
                 'grader_revision':'a7bdc2d358e052d35a94768e1f487c0d9e9c0011'},
}
FILES = {'swe-pro':'swe-pro.parquet','swe-verified':'swe-verified.parquet',
         'bird':'bird.jsonl','spreadsheet':'spreadsheet-v2.zip'}
EXPECTED = {
 'swe-pro.parquet':'1067f72c1f43bbc578276888625db3b836cebb535546c9eaf824c5d5dd104a7f',
 'swe-verified.parquet':'030cfd7f2a704c4c0226e7f104c725a3b41230b1d3517f9c915ad7ea5be3fa25',
 'bird.jsonl':'926af2a0d1b47e5d0d15a7aa8a34d4721007f4550a881555b6a89496b54a2606',
 'spreadsheet-v2.zip':'52699c974c30aced7125f3d12cdaabbbcbba8db804373d7397a5d3bdf68e5b3e',
}


def fetch(url,path,expected=None,limit=200_000_000):
    path.parent.mkdir(parents=True,exist_ok=True)
    if not path.exists():
        part=path.with_name(path.name+'.part')
        with urllib.request.urlopen(url,timeout=90) as response,part.open('wb') as out:
            size=0
            while chunk:=response.read(1024*1024):
                size+=len(chunk)
                if size>limit: raise ValueError('download_limit_exceeded')
                out.write(chunk)
        part.replace(path)
    data=path.read_bytes()
    if expected and hashlib.sha256(data).hexdigest()!=expected:
        raise ValueError('source_hash_mismatch: '+path.name)
    return data


def record(source,row,public,**extra):
    return dict(source=source,id=str(row['id']),stratum=str(row['stratum']),
                public_input_sha256=digest(public),source_record_sha256=digest(row['raw']),**extra)


def prepare(cache):
    import pyarrow.parquet as pq
    if __import__('pyarrow').__version__!='26.0.1':
        raise ValueError('preparation_requires_pyarrow_26_0_1')
    for source,name in FILES.items():
        pin=PINS[source]
        fetch(pin['repository']+'/resolve/'+pin['revision']+'/'+pin['file'],cache/name,EXPECTED[name])
    rev=PINS['terminal']['revision']
    tree=json.loads(fetch('https://api.github.com/repos/harbor-framework/terminal-bench-2-1/git/trees/'+rev+'?recursive=1',cache/'terminal-tree.json',limit=10_000_000))
    if tree.get('truncated'):
        raise ValueError('terminal_tree_truncated')
    entries=[t for t in tree['tree'] if t['path'].startswith('tasks/') and t['path'].endswith('/task.toml')]
    def terminal(entry):
        task_id=entry['path'].split('/')[1]
        raw=fetch('https://raw.githubusercontent.com/harbor-framework/terminal-bench-2-1/'+rev+'/'+entry['path'],cache/'terminal'/task_id/'task.toml',limit=100_000)
        if hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()!=entry['sha']:
            raise ValueError('terminal_git_blob_mismatch')
        config=tomllib.loads(raw.decode())
        env=config.get('environment',{})
        return {'id':task_id,'stratum':config.get('metadata',{}).get('category','uncategorized'),
                'raw':config,'environment':env}
    with ThreadPoolExecutor(8) as pool:
        all_terminal=list(pool.map(terminal,entries))
    # Resource filter is fixed before inference; never filter by model success.
    eligible=[r for r in all_terminal if r['environment'].get('gpus',0)==0
              and r['environment'].get('cpus',1)<=4
              and r['environment'].get('memory_mb',2048)<=8192
              and r['environment'].get('storage_mb',10240)<=40960]
    selected=[]
    for row in select(eligible,25,'terminal'):
        task_id=row['id']
        instruction=fetch('https://raw.githubusercontent.com/harbor-framework/terminal-bench-2-1/'+rev+'/tasks/'+task_id+'/instruction.md',cache/'terminal'/task_id/'instruction.md',limit=500_000).decode()
        selected.append(record('terminal',row,{'instruction':instruction},environment=row['environment'],
                               task_config_sha256=hashlib.sha256((cache/'terminal'/task_id/'task.toml').read_bytes()).hexdigest()))
    pools={'terminal':{'total':len(all_terminal),'resource_eligible':len(eligible)}}
    for source in ['swe-pro','swe-verified']:
        raw_rows=pq.read_table(cache/FILES[source]).to_pylist()
        rows=[{'id':r['instance_id'],'stratum':r['repo'],'raw':r} for r in raw_rows]
        pools[source]={'total':len(rows)}
        for row in select(rows,QUOTAS[source],source):
            r=row['raw']
            public={k:r[k] for k in ['problem_statement','requirements','interface'] if k in r}
            selected.append(record(source,row,public,repo=r['repo'],base_commit=r['base_commit'],
                                   language=r.get('repo_language','python'),
                                   **({'docker_image':r['docker_image']} if source=='swe-pro' else {})))
    raw_rows=[json.loads(line) for line in (cache/'bird.jsonl').read_text().splitlines() if line.strip()]
    rows=[{'id':str(r['question_id']),'stratum':r['db_id'],'raw':r} for r in raw_rows]
    pools['bird']={'total':len(rows)}
    for row in select(rows,15,'bird'):
        r=row['raw'];public={k:r[k] for k in ['db_id','question','evidence'] if k in r}
        selected.append(record('bird',row,public,database=r['db_id'],dialect='sqlite'))
    with zipfile.ZipFile(cache/'spreadsheet-v2.zip') as z:
        rows=[]
        for category in ['Debugging','Financial_Model','Template']:
            prefix='spreadsheetbench-v2/'+category+'/'
            for r in json.loads(z.read(prefix+'dataset.json')):
                rows.append({'id':category+'/'+r['id'],'stratum':category,'raw':r,
                             'family_key':category+'/'+r['golden_response_path'],'prefix':prefix})
        pools['spreadsheet']={'nonvisual_total':len(rows),'visualization_excluded':True}
        for row in select(rows,15,'spreadsheet'):
            r=row['raw'];input_name=row['prefix']+r['spreadsheet_path']
            # Zip members are read by exact name, never extracted onto the host.
            if '..' in PurePosixPath(input_name).parts:raise ValueError('unsafe_zip_member')
            data=z.read(input_name)
            selected.append(record('spreadsheet',row,{'instruction':r['instruction'],
                'workbook_sha256':hashlib.sha256(data).hexdigest()},category=row['stratum'],
                input_member=input_name,workbook_sha256=hashlib.sha256(data).hexdigest(),
                family_key=row['family_key']))
    pins={k:dict(v) for k,v in PINS.items()}
    for source,name in FILES.items(): pins[source]['download_sha256']=EXPECTED[name]
    manifest={'schema_version':'medium-selection-1','id':'medium-public-100-v1',
              'status':'selection_only_not_runtime_accepted','selection_seed':SEED,
              'selection_algorithm':'sha256_stratified_round_robin_v1',
              'source_pins':pins,'source_pools':pools,'models':MODELS,'efforts':EFFORTS,
              'source_weights':{k:0.2 for k in QUOTAS},'tasks':selected}
    manifest['sha256']=digest(manifest)
    return manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    manifest=prepare(args.cache)
    # Refuse to silently rewrite an already frozen selection.
    text=json.dumps(manifest,ensure_ascii=False,indent=2)+'\n'
    if args.output.exists() and args.output.read_text()!=text:
        raise ValueError('manifest_exists_with_different_content')
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(text)
    print(json.dumps({'status':'SELECTION_FROZEN_NOT_RUNTIME_ACCEPTED','tasks':100,
                      'sha256':manifest['sha256'],'pools':manifest['source_pools']}))


if __name__=='__main__':main()
