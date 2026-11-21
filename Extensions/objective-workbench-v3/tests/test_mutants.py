import io,json,sqlite3,sys,tarfile,tempfile,unittest
from pathlib import Path
from contextlib import closing
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import artifact_tasks as a

class Mutants(unittest.TestCase):
    def run_case(self,id,mutate):
        for seed in (11,29,47):
            t=next(t for t in a.build(seed) if t['id']==id)
            with tempfile.TemporaryDirectory() as d:
                w=Path(d);a.setup(t,w);a.reference(t,w);mutate(w)
                self.assertFalse(a.grade(t,w)['passed'],(id,seed))
    def test_edit_wrong_target_value(self):self.run_case('S01',lambda w:(w/'worker.ini').write_text('timeout_s = 34\n'))
    def test_edit_extra_file(self):self.run_case('S01',lambda w:(w/'backup.ini').write_text('extra'))
    def test_import_changed_order(self):
        def mutate(w):
            with closing(sqlite3.connect(w/'data.db')) as db,db:db.execute('UPDATE orders SET amount=amount+1 WHERE id=1')
        self.run_case('S02',mutate)
    def test_import_extra_schema(self):
        def mutate(w):
            with closing(sqlite3.connect(w/'data.db')) as db,db:db.execute('CREATE VIEW surprise AS SELECT * FROM clients')
        self.run_case('S02',mutate)
    def test_import_changed_code(self):self.run_case('S02',lambda w:(w/'importer.py').write_text('# done'))
    def test_cleanup_wrong_archive_bytes(self):
        def mutate(w):
            with tarfile.open(w/'archive.tar','w') as tf:
                for n in json.loads((w/'manifest.json').read_text()):
                    b=b'wrong';m=tarfile.TarInfo(n);m.size=len(b);tf.addfile(m,io.BytesIO(b))
        self.run_case('S03',mutate)
    def test_cleanup_duplicate_member(self):
        def mutate(w):
            with tarfile.open(w/'archive.tar','a') as tf:
                n=json.loads((w/'manifest.json').read_text())[0];b=b'x';m=tarfile.TarInfo(n);m.size=1;tf.addfile(m,io.BytesIO(b))
        self.run_case('S03',mutate)
    def test_cleanup_traversal_link(self):
        def mutate(w):
            with tarfile.open(w/'archive.tar','a') as tf:
                m=tarfile.TarInfo('../escape');m.type=tarfile.SYMTYPE;m.linkname='/etc/passwd';tf.addfile(m)
        self.run_case('S03',mutate)
    def test_report_wrong_total(self):
        def mutate(w):
            p=w/'report.json';r=json.loads(p.read_text());r['totals']['North']+=1;p.write_text(json.dumps(r))
        self.run_case('S04',mutate)
    def test_report_wrong_unmatched_order(self):
        def mutate(w):
            p=w/'report.json';r=json.loads(p.read_text());r['unmatched'].reverse();p.write_text(json.dumps(r))
        self.run_case('S04',mutate)
    def test_report_duplicate_json_key(self):
        def mutate(w):
            p=w/'report.json';s=p.read_text();p.write_text('{"totals":{},'+s[1:])
        self.run_case('S04',mutate)
    def test_report_equivalent_format(self):
        for seed in (11,29,47):
            t=next(t for t in a.build(seed) if t['id']=='S04')
            with tempfile.TemporaryDirectory() as d:
                w=Path(d);a.setup(t,w);a.reference(t,w);p=w/'report.json';v=json.loads(p.read_text());p.write_text(json.dumps(dict(reversed(list(v.items()))),indent=4));self.assertTrue(a.grade(t,w)['passed'])
    def test_cleanup_equivalent_order_metadata(self):
        for seed in (11,29,47):
            t=next(t for t in a.build(seed) if t['id']=='S03')
            with tempfile.TemporaryDirectory() as d:
                w=Path(d);a.setup(t,w);a.reference(t,w)
                with tarfile.open(w/'archive.tar','w') as tf:
                    for n in reversed(t['expected']['allowed']):
                        b=t['files'][n].encode();m=tarfile.TarInfo(n);m.size=len(b);m.mtime=12345;tf.addfile(m,io.BytesIO(b))
                self.assertTrue(a.grade(t,w)['passed'])

if __name__=='__main__':unittest.main()
