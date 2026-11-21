import json,subprocess,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class CLITests(unittest.TestCase):
    def test_export_reference_grade_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            dest=Path(d)/'package'
            result=subprocess.run([sys.executable,str(ROOT/'cli.py'),'export','--out',str(dest)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            manifest=json.loads((dest/'manifest.json').read_text())
            self.assertEqual(manifest['task_templates'],10)
            pub=json.loads((dest/'public/Q01/task.json').read_text())
            self.assertNotIn('expected',pub)
            reply=Path(d)/'answer.json'
            result=subprocess.run([sys.executable,str(ROOT/'cli.py'),'reference','Q01','--out',str(reply)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            result=subprocess.run([sys.executable,str(ROOT/'cli.py'),'grade','Q01','--submission',str(reply)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertTrue(json.loads(result.stdout)['passed'])
            reply.write_text('{}')
            result=subprocess.run([sys.executable,str(ROOT/'cli.py'),'grade','Q01','--submission',str(reply)],capture_output=True,text=True)
            self.assertEqual(result.returncode,1)
            self.assertFalse(json.loads(result.stdout)['passed'])
    def test_no_overwrite_export(self):
        with tempfile.TemporaryDirectory() as d:
            result=subprocess.run([sys.executable,str(ROOT/'cli.py'),'export','--out',d],capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0)
if __name__=='__main__':unittest.main()
