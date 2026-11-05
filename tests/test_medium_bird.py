import hashlib
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from teobench.medium_bird import BirdTask


class BirdGoldValidationTests(unittest.TestCase):
    def adapter(self,directory,sql):
        task=BirdTask.__new__(BirdTask)
        task.database=Path(directory)/'db.sqlite'
        with closing(sqlite3.connect(task.database)) as c:
            c.execute('CREATE TABLE IF NOT EXISTS sample(value INTEGER)')
            c.execute('INSERT INTO sample VALUES(7)')
            c.commit()
        task.database_sha256=hashlib.sha256(task.database.read_bytes()).hexdigest()
        task.task={'id':'1','source_record_sha256':'record'};task.row={'SQL':sql}
        task.gold_validation=Path(directory)/'gold-validation/1.json'
        return task

    def test_trusted_gold_nonempty_and_readonly_database_receipt(self):
        with tempfile.TemporaryDirectory() as d:
            task=self.adapter(d,'SELECT value FROM sample')
            result=task.validate_gold()
            self.assertEqual(result['gold_rows'],1);self.assertEqual(result['model_requests'],0)
            self.assertEqual(hashlib.sha256(task.database.read_bytes()).hexdigest(),task.database_sha256)

    def test_empty_gold_or_write_never_certifies_database(self):
        for query in ('SELECT value FROM sample WHERE 0','DELETE FROM sample'):
            with self.subTest(query=query),tempfile.TemporaryDirectory() as d:
                task=self.adapter(d,query)
                with self.assertRaises((ValueError,sqlite3.DatabaseError)):task.validate_gold()
                self.assertFalse(task.gold_validation.exists())
