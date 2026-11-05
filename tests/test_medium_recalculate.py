import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from teobench.medium_recalculate import main


class RecalculationReceiptTests(unittest.TestCase):
    def test_success_exit_without_rewriting_workbooks_is_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'input.xlsx';p.write_bytes(b'workbook')
            stopped=[]
            namespace={'start_libreoffice_service':lambda:True,'batch_open_files':lambda files:None,
                       'stop_libreoffice_service':lambda:stopped.append(True)}
            with patch('sys.argv',['helper','upstream.py',directory,'["input.xlsx"]']), \
                 patch('runpy.run_path',return_value=namespace):
                with self.assertRaisesRegex(RuntimeError,'did_not_replace_every_workbook'):main()
            self.assertEqual(stopped,[True]);self.assertFalse((Path(directory)/'recalculation.json').exists())

    def test_explicit_files_and_successful_replacements_recorded(self):
        with tempfile.TemporaryDirectory() as directory:
            paths=[Path(directory)/name for name in ('input.xlsx','gold.xlsx')]
            for p in paths:p.write_bytes(b'original')
            seen=[]
            def recalculate(files):
                seen.extend(files)
                for name in files:
                    p=Path(name);replacement=p.with_suffix('.tmp.xlsx');replacement.write_bytes(b'calculated');replacement.replace(p)
            namespace={'start_libreoffice_service':lambda:True,'batch_open_files':recalculate,
                       'stop_libreoffice_service':lambda:None}
            with patch('sys.argv',['helper','upstream.py',directory,'["input.xlsx","gold.xlsx"]']), \
                 patch('runpy.run_path',return_value=namespace):main()
            self.assertEqual(seen,[str(p) for p in paths])
            self.assertEqual(json.loads((Path(directory)/'recalculation.json').read_text()),
                             {'replaced':{'input.xlsx':True,'gold.xlsx':True}})
