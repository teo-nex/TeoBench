"""Mini-Dev SQLite: one permitted DB, fresh read-only execution grader."""
from contextlib import contextmanager, closing
import hashlib
import json
from pathlib import Path
import sqlite3
import time

from .medium import digest
from .medium_container import TaskContainer, ContainerError


class BirdTask:
    def __init__(self,docker,task,cache,assets,databases,image):
        self.docker=docker;self.task=task;self.image=image
        rows=[json.loads(line) for line in (Path(cache)/'bird.jsonl').read_text().splitlines() if line.strip()]
        self.row=next(r for r in rows if str(r['question_id'])==task['id'])
        if digest(self.row)!=task['source_record_sha256']:
            raise ValueError('bird_source_record_mismatch')
        self.database=Path(databases)/(task['database']+'.sqlite')
        pins=json.loads((Path(databases)/'manifest.json').read_text())
        names=[r['database'] for r in pins['databases']]
        if len(names)!=len(set(names)):raise ValueError('ambiguous_duplicate_database_manifest')
        pin=next(r for r in pins['databases'] if r['database']==task['database'])
        with self.database.open('rb') as stream:actual=hashlib.file_digest(stream,'sha256').hexdigest()
        if actual!=pin['sha256']:raise ValueError('bird_database_hash_mismatch')
        self.database_sha256=actual
        self.gold_validation=Path(databases)/'gold-validation'/(task['id']+'.json')
        self.evaluator=Path(assets)/'evaluators/bird/evaluate.py'
        self.workdir='/app';self.candidate_seconds=900

    def validate_gold(self):
        """Trusted public gold SQL only; candidate SQL always runs in Docker."""
        started=time.monotonic();count=0
        allowed={sqlite3.SQLITE_SELECT,sqlite3.SQLITE_READ,sqlite3.SQLITE_FUNCTION,sqlite3.SQLITE_RECURSIVE}
        with closing(sqlite3.connect(self.database.resolve().as_uri()+'?mode=ro',uri=True)) as connection:
            connection.enable_load_extension(False)
            connection.set_authorizer(lambda operation,*args:sqlite3.SQLITE_OK if operation in allowed else sqlite3.SQLITE_DENY)
            connection.set_progress_handler(lambda:int(time.monotonic()-started>600),100000)
            for _ in connection.execute(self.row['SQL']):
                count+=1
                if count>1_000_000:raise ValueError('bird_gold_result_size_limit')
        if not count:raise ValueError('bird_gold_empty_for_selected_database_release')
        result={'source':'bird','id':self.task['id'],'status':'PASS','gold_rows':count,
                'source_record_sha256':self.task['source_record_sha256'],
                'database_sha256':self.database_sha256,'model_requests':0}
        self.gold_validation.parent.mkdir(parents=True,exist_ok=True)
        if self.gold_validation.exists() and json.loads(self.gold_validation.read_text())!=result:
            raise ValueError('existing_bird_gold_validation_changed')
        self.gold_validation.write_text(json.dumps(result,indent=2))
        return result

    @property
    def prompt(self):
        return ('Answer the following SQLite database question. The only permitted database is /app/db.sqlite. '
            'Inspect its schema and data with the terminal. Write exactly one SQL query to /app/answer.sql. '
            'The grader executes it against a fresh read-only copy of the same database.\n\n'
            'Question: '+self.row['question']+'\nEvidence: '+self.row.get('evidence',''))

    @contextmanager
    def container(self, *, grading=False):
        with TaskContainer(self.docker,self.image,workdir='/app',memory_mb=2048,cpus=1) as c:
            c.put(self.database,'/app/db.sqlite')
            yield c

    def grade(self,answer,output):
        output=Path(output);output.mkdir(parents=True,exist_ok=True)
        if type(answer) is not bytes or len(answer)>1_000_000:raise ValueError('invalid_sql_artifact')
        (output/'answer.sql').write_bytes(answer)
        # Gold and the official evaluator never enter the model's container.
        (output/'gold.sql').write_text(self.row['SQL'])
        with self.container(grading=True) as c:
            c.exec('mkdir -p /tests /logs/verifier')
            c.put(output/'answer.sql','/app/answer.sql');c.put(output/'gold.sql','/tests/gold.sql')
            c.put(self.evaluator,'/tests/evaluate.py')
            c.exec('python3 /tests/evaluate.py',timeout=1250,log=output/'verifier.log')
            reward=c.read('/logs/verifier/reward.txt',limit=100).strip()
            if reward not in (b'0.0',b'1.0'):raise ContainerError('bird_reward_invalid')
        result={'score':int(float(reward)),'lifecycle':'fresh_pristine_database',
                'evaluator_sha256':hashlib.sha256(self.evaluator.read_bytes()).hexdigest()}
        (output/'grade.json').write_text(json.dumps(result,indent=2))
        return result

    def accept(self,output):
        output=Path(output);output.mkdir(parents=True,exist_ok=False)
        checks={name:self.grade(sql,output/name)['score'] for name,sql in (
            ('oracle',self.row['SQL'].encode()),('noop',b''),('corrupt',b'SELECT * FROM teobench_nonexistent_table_728410;'))}
        result={'source':'bird','id':self.task['id'],'checks':checks,
                'status':'PASS' if checks=={'oracle':1,'noop':0,'corrupt':0} else 'BLOCKED',
                'model_requests':0,'primary_attempts':0}
        (output/'acceptance.json').write_text(json.dumps(result,indent=2))
        return result
