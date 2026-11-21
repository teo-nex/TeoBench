import sys, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bench import exact, grade_answer

class ContractTests(unittest.TestCase):
    def test_equivalent_object_key_order(self):
        self.assertTrue(exact({'b':[2,3], 'a':1},{'a':1,'b':[2,3]}))
    def test_no_bool_integer_alias(self):
        self.assertFalse(exact({'count':True},{'count':1}))
    def test_no_extra_keys(self):
        self.assertFalse(exact({'count':1,'claim':'ok'},{'count':1}))
    def test_correct_answer_accepted(self):
        task={'expected':{'count':2}}
        self.assertTrue(grade_answer(task,{'count':2})['passed'])
    def test_wrong_answer_rejected(self):
        self.assertFalse(grade_answer({'expected':{'count':2}},{'count':3})['passed'])
    def test_malformed_answer_is_result_not_exception(self):
        for value in [None,[],True,1,'answer']:
            self.assertFalse(grade_answer({'expected':{'count':2}},value)['passed'])

if __name__=='__main__': unittest.main()
