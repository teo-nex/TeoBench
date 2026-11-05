"""SpreadsheetBench 2: official LibreOffice recalculation and item scoring."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import shlex
import zipfile

from .medium import digest
from .medium_container import TaskContainer, ContainerError


class SpreadsheetTask:
    def __init__(self,docker,task,cache,assets,prepared,image):
        self.docker=docker;self.task=task;self.image=image
        self.category=task['category'];self.prepared=Path(prepared)/task['id']
        self.assets=Path(assets)/'evaluators/spreadsheet'
        self.archive=Path(cache)/'spreadsheet-v2.zip'
        with zipfile.ZipFile(self.archive) as z:
            prefix='spreadsheetbench-v2/'+self.category+'/'
            rows=json.loads(z.read(prefix+'dataset.json'))
            self.row=next(r for r in rows if self.category+'/'+r['id']==task['id'])
        if digest(self.row)!=task['source_record_sha256']:
            raise ValueError('spreadsheet_source_record_mismatch')
        self.workdir='/app';self.candidate_seconds=1800

    def prepare(self):
        if (self.prepared/'prepared.json').exists():
            pins=json.loads((self.prepared/'prepared.json').read_text())
            if pins.get('preparation_version')!=2:
                raise ValueError('legacy_spreadsheet_preparation_unverified_use_new_directory')
            if pins['image']!=self.image:raise ValueError('spreadsheet_recalculation_image_changed')
            for name,expected in pins['recalculated_sha256'].items():
                if hashlib.sha256((self.prepared/name).read_bytes()).hexdigest()!=expected:
                    raise ValueError('spreadsheet_prepared_hash_mismatch')
            return pins
        self.prepared.mkdir(parents=True,exist_ok=True)
        with zipfile.ZipFile(self.archive) as z:
            prefix='spreadsheetbench-v2/'+self.category+'/'
            for field,name in [('spreadsheet_path','input.xlsx'),('golden_response_path','gold.xlsx')]:
                member=prefix+self.row[field]
                if '..' in member.split('/') or '\\' in member:raise ValueError('unsafe_spreadsheet_member')
                data=z.read(member)
                if name=='input.xlsx' and hashlib.sha256(data).hexdigest()!=self.task['workbook_sha256']:
                    raise ValueError('spreadsheet_input_hash_mismatch')
                (self.prepared/('raw-'+name)).write_bytes(data)
        with TaskContainer(self.docker,self.image,workdir='/app',memory_mb=2048) as c:
            c.exec('mkdir -p /recalculate')
            c.put(self.assets/'open_spreadsheet.py','/app/open_spreadsheet.py')
            for name in ('input.xlsx','gold.xlsx'):c.put(self.prepared/('raw-'+name),'/recalculate/'+name)
            c.put(Path(__file__).with_name('medium_recalculate.py'),'/app/recalculate.py')
            c.exec("python3 /app/recalculate.py /app/open_spreadsheet.py /recalculate '[\"input.xlsx\",\"gold.xlsx\"]'",timeout=300,
                   log=self.prepared/'recalculate.log')
            replacement=json.loads(c.read('/recalculate/recalculation.json',limit=10000))
            if replacement!={'replaced':{'input.xlsx':True,'gold.xlsx':True}}:
                raise ContainerError('spreadsheet_recalculation_receipt_invalid')
            for name in ('input.xlsx','gold.xlsx'):
                data=c.read('/recalculate/'+name,limit=32_000_000)
                # A failure to produce a valid workbook is infrastructure failure.
                with zipfile.ZipFile(__import__('io').BytesIO(data)) as z:
                    if 'xl/workbook.xml' not in z.namelist():raise ContainerError('recalculated_workbook_invalid')
                (self.prepared/name).write_bytes(data)
            _,versions=c.exec('libreoffice --version; python3 -c "import openpyxl; print(openpyxl.__version__)"')
        pins={'preparation_version':2,'replacement':replacement,'image':self.image,'task_record_sha256':self.task['source_record_sha256'],
              'recalculation_script_sha256':hashlib.sha256((self.assets/'open_spreadsheet.py').read_bytes()).hexdigest(),
              'runtime_versions':versions.decode().strip(),
              'recalculated_sha256':{n:hashlib.sha256((self.prepared/n).read_bytes()).hexdigest() for n in ('input.xlsx','gold.xlsx')}}
        (self.prepared/'prepared.json').write_text(json.dumps(pins,indent=2))
        return pins

    @property
    def prompt(self):
        return ('Work on /app/input.xlsx and save the completed workbook as /app/output.xlsx. '
            'Use the terminal and installed Python openpyxl / LibreOffice tools. '
            'Preserve unrelated cells, formulas and formatting. The submitted workbook will be '
            'recalculated with LibreOffice before the official grader checks it.\n\n'+self.row['instruction'])

    @contextmanager
    def container(self, *, grading=False):
        self.prepare()
        with TaskContainer(self.docker,self.image,workdir='/app',memory_mb=2048,cpus=1) as c:
            c.put(self.prepared/'input.xlsx','/app/input.xlsx')
            yield c

    def grade(self,answer,output):
        output=Path(output);output.mkdir(parents=True,exist_ok=True)
        if type(answer) is not bytes or len(answer)>32_000_000:raise ValueError('invalid_workbook_artifact')
        (output/'output.xlsx').write_bytes(answer)
        try:
            with zipfile.ZipFile(__import__('io').BytesIO(answer)) as z:
                if 'xl/workbook.xml' not in z.namelist():raise ValueError('missing_workbook')
        except (ValueError,zipfile.BadZipFile):
            result={'score':0,'reason':'invalid_workbook_artifact'}
            (output/'grade.json').write_text(json.dumps(result,indent=2))
            return result
        # Remap exact files, retaining all metadata that determines evaluation
        # mode (Color / Embedded) and the upstream answer-position contract.
        row=dict(self.row);row['spreadsheet_path']='input-'+Path(self.row['spreadsheet_path']).name
        row['golden_response_path']='gold.xlsx'
        (output/'item.json').write_text(json.dumps(row))
        driver='''import json\nfrom evaluation import process_single_item\nrow=json.load(open('/grade/item.json'))\nresult,missing=process_single_item(row,'/grade/data','/grade/outputs',{},'''+repr(self.category)+''')\njson.dump(dict(result=result,missing=missing),open('/grade/result.json','w'))\n'''
        (output/'driver.py').write_text(driver)
        with TaskContainer(self.docker,self.image,workdir='/grade',memory_mb=2048) as c:
            c.exec('mkdir -p /grade/data /grade/outputs')
            c.put(self.prepared/'input.xlsx','/grade/data/'+row['spreadsheet_path'])
            c.put(self.prepared/'gold.xlsx','/grade/data/gold.xlsx')
            candidate='/grade/outputs/'+str(row['id'])+'_output.xlsx'
            if '/' in str(row['id']) or '\\' in str(row['id']):raise ValueError('invalid_spreadsheet_output_id')
            c.put(output/'output.xlsx',candidate)
            c.put(self.assets/'open_spreadsheet.py','/grade/open_spreadsheet.py')
            c.put(Path(__file__).with_name('medium_recalculate.py'),'/grade/recalculate.py')
            c.exec('python3 /grade/recalculate.py /grade/open_spreadsheet.py /grade/outputs '+
                   shlex.quote(json.dumps([Path(candidate).name])),timeout=300,
                   log=output/'recalculate-output.log')
            c.put(self.assets/'evaluation.py','/grade/evaluation.py')
            c.put(output/'driver.py','/grade/driver.py');c.put(output/'item.json','/grade/item.json')
            c.exec('python3 /grade/driver.py',timeout=180,log=output/'verifier.log')
            result=json.loads(c.read('/grade/result.json',limit=100_000))
        score=result['result']['accuracy']
        if score not in (0.,1.):raise ContainerError('spreadsheet_reward_invalid')
        result.update(score=int(score),lifecycle='fresh_recalculated_workbook',
            evaluator_sha256=hashlib.sha256((self.assets/'evaluation.py').read_bytes()).hexdigest())
        (output/'grade.json').write_text(json.dumps(result,indent=2))
        return result

    def accept(self,output):
        self.prepare();output=Path(output);output.mkdir(parents=True,exist_ok=False)
        checks={name:self.grade(data,output/name)['score'] for name,data in (
            ('oracle',(self.prepared/'gold.xlsx').read_bytes()),('noop',(self.prepared/'input.xlsx').read_bytes()),
            ('corrupt',b'invalid workbook'))}
        result={'source':'spreadsheet','id':self.task['id'],'checks':checks,
                'status':'PASS' if checks=={'oracle':1,'noop':0,'corrupt':0} else 'BLOCKED',
                'model_requests':0,'primary_attempts':0}
        (output/'acceptance.json').write_text(json.dumps(result,indent=2))
        return result
