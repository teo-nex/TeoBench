import json,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parent
out=ROOT/'validation'/time.strftime('%Y%m%dT%H%M%SZ',time.gmtime());out.mkdir(parents=True)
start=time.monotonic()
tests=subprocess.run([sys.executable,'-W','error::ResourceWarning','-m','unittest','discover','-s','tests','-v'],cwd=ROOT,capture_output=True,text=True,timeout=90)
(out/'tests.log').write_text(tests.stdout+tests.stderr)
if tests.returncode:raise SystemExit('tests failed: '+str(out/'tests.log'))
records=[]
for seed in (11,29,47):
    export=out/f'package-{seed}'
    subprocess.run([sys.executable,'cli.py','export','--seed',str(seed),'--out',str(export)],cwd=ROOT,check=True,capture_output=True,timeout=20)
    manifest=json.loads((export/'manifest.json').read_text())
    for id in manifest['ids']:
        dst=out/'reference'/str(seed)/id
        if id.startswith('Q'):dst=dst.with_suffix('.json')
        subprocess.run([sys.executable,'cli.py','reference',id,'--seed',str(seed),'--out',str(dst)],cwd=ROOT,check=True,capture_output=True,timeout=20)
        graded=subprocess.run([sys.executable,'cli.py','grade',id,'--seed',str(seed),'--submission',str(dst)],cwd=ROOT,capture_output=True,text=True,timeout=20)
        result=json.loads(graded.stdout)
        assert graded.returncode==0 and result['passed'],(seed,id,result)
        records.append({'seed':seed,'id':id,**result})
report={'validation_only':True,'model_benchmark_run':False,'unit_test_exit_code':tests.returncode,'reference_grades':records,'passed':len(records),'templates':10,'seed_variants':3,'elapsed_s':round(time.monotonic()-start,2),'test_log':str(out/'tests.log')}
(out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps({'unit_tests':'PASS','reference_cli_roundtrips':len(records),'all_passed':all(x['passed'] for x in records),'report':str(out/'report.json'),'elapsed_s':report['elapsed_s']}))
