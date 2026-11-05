"""First-attempt journal: unique matrix slots, durable state, no reroll on resume."""
import json
from pathlib import Path
import sqlite3
import time
from .medium import MODELS, EFFORTS, digest


class Journal:
    def __init__(self,path,manifest,protocol_hash):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(self.path)
        self.db.execute('PRAGMA journal_mode=WAL');self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS attempts(
          source TEXT NOT NULL,task TEXT NOT NULL,model TEXT NOT NULL,effort TEXT NOT NULL,
          state TEXT NOT NULL DEFAULT 'PLANNED',requests INTEGER NOT NULL DEFAULT 0,
          score INTEGER,artifact TEXT,receipt TEXT,updated REAL,
          PRIMARY KEY(source,task,model,effort),CHECK(score IS NULL OR score IN (0,1)));
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,stamp REAL,slot TEXT,state TEXT,detail TEXT);
        ''')
        expected={'manifest_sha256':manifest['sha256'],'protocol_sha256':protocol_hash}
        present=dict(self.db.execute('SELECT key,value FROM metadata'))
        if present and present!=expected:
            self.db.close()
            raise ValueError('existing_study_protocol_mismatch')
        with self.db:
            self.db.executemany('INSERT OR IGNORE INTO metadata VALUES(?,?)',expected.items())
            self.db.executemany('INSERT OR IGNORE INTO attempts(source,task,model,effort) VALUES(?,?,?,?)',
                [(t['source'],t['id'],m,e) for t in manifest['tasks'] for m in MODELS for e in EFFORTS])
        if self.db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0]!=3500:
            raise ValueError('study_matrix_not_3500')

    def slots(self,task):
        rows=list(self.db.execute('SELECT model,effort,state FROM attempts WHERE source=? AND task=?',
                                 (task['source'],task['id'])))
        # Fixed hash order avoids putting every model at the same quota/time
        # position, while keeping each task's 35 paired observations together.
        return sorted(rows,key=lambda r:digest([task['source'],task['id'],r[0],r[1]]))

    def transition(self,slot,expected,state,*,requests=None,score=None,artifact=None,receipt=None):
        now=time.time()
        with self.db:
            row=self.db.execute('SELECT state FROM attempts WHERE source=? AND task=? AND model=? AND effort=?',slot).fetchone()
            if not row or row[0]!=expected:raise ValueError('first_attempt_state_conflict_no_retry')
            self.db.execute('UPDATE attempts SET state=?, requests=COALESCE(?,requests),score=?,artifact=COALESCE(?,artifact),receipt=COALESCE(?,receipt),updated=? WHERE source=? AND task=? AND model=? AND effort=?',
                (state,requests,score,artifact,json.dumps(receipt) if receipt is not None else None,now,*slot))
            self.db.execute('INSERT INTO events(stamp,slot,state,detail) VALUES(?,?,?,?)',
                (now,json.dumps(slot),state,json.dumps({'requests':requests,'score':score})))

    def status(self):
        states=dict(self.db.execute('SELECT state,COUNT(*) FROM attempts GROUP BY state'))
        graded=states.get('GRADED',0)
        return {'status':'COMPLETE' if graded==3500 else 'INCOMPLETE','slots':3500,'states':states,
            'primary_attempts':self.db.execute('SELECT COUNT(*) FROM attempts WHERE requests>0').fetchone()[0],
            'graded':graded,'correct':self.db.execute('SELECT COUNT(*) FROM attempts WHERE score=1').fetchone()[0],
            'transport_errors':states.get('TRANSPORT_ERROR',0),'missing_scores':3500-graded}

    def close(self):self.db.close()
