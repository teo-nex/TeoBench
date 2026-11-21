import json,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bench import load_answer

class JSONInputTests(unittest.TestCase):
    def test_duplicate_keys_rejected(self):
        with self.assertRaises(ValueError):load_answer('{"count":1,"count":2}')
    def test_nonfinite_rejected(self):
        for text in ('{"x":NaN}','{"x":Infinity}'):
            with self.assertRaises(ValueError):load_answer(text)
    def test_valid_keys_order_free(self):
        self.assertEqual(load_answer('{"b":2,"a":1}'),{'a':1,'b':2})
if __name__=='__main__':unittest.main()
