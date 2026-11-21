import json,sys,tempfile,unittest,sqlite3,tarfile,io
from pathlib import Path
from contextlib import closing
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import artifact_tasks as a

class ArtifactTests(unittest.TestCase):
    def test_edit(self):self.check('S01')
    def test_import(self):self.check('S02')
    def test_cleanup(self):self.check('S03')
    def test_report(self):self.check('S04')
    def check(self,id):
        for seed in (11,29,47):
            t=next(t for t in a.build(seed) if t['id']==id)
            with tempfile.TemporaryDirectory() as d:
                w=Path(d);a.setup(t,w)
                self.assertFalse(a.grade(t,w)['passed'])
                a.reference(t,w)
                self.assertTrue(a.grade(t,w)['passed'],(id,seed,a.grade(t,w)))
                # Force a concrete, task-specific wrong-state after real reference actions.
                if id=='S01':(w/'other.ini').write_text('timeout_s = 35\n')
                if id=='S02':
                    with closing(sqlite3.connect(w/'data.db')) as db, db:db.execute("UPDATE clients SET email='wrong' WHERE id=1")
                if id=='S03':(w/'data/f00.txt').unlink()
                if id=='S04':(w/'report.json').write_text('{}')
                self.assertFalse(a.grade(t,w)['passed'])
    def test_symlink_rejected(self):
        t=a.build(11)[0]
        with tempfile.TemporaryDirectory() as d:
            w=Path(d);a.setup(t,w);a.reference(t,w)
            (w/'other.ini').unlink();(w/'other.ini').symlink_to('/etc/passwd')
            self.assertFalse(a.grade(t,w)['passed'])

if __name__=='__main__':unittest.main()
