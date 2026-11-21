import copy,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import answer_tasks
from bench import grade_answer

class MoreAnswers(unittest.TestCase):
    def test_invoice(self):self.check_task('Q02')
    def test_quotes(self):self.check_task('Q03')
    def test_document(self):self.check_task('Q04')
    def test_partial(self):self.check_task('Q05')
    def test_timeline(self):self.check_task('Q06')
    def check_task(self,id):
        for seed in (11,29,47):
            t=next(t for t in answer_tasks.build(seed) if t['id']==id)
            a=answer_tasks.reference(t)
            self.assertTrue(grade_answer(t,a)['passed'],(id,seed,a))
            # Each mutation changes a different contract field; empty/extra checked too.
            mutants=[None,{},dict(a,extra=True)]
            for k,v in a.items():
                b=copy.deepcopy(a)
                if isinstance(v,list):b[k]=v[::-1] if len(v)>1 else []
                elif isinstance(v,dict):b[k]['source']='wrong-source'
                else:b[k]='WRONG'
                mutants.append(b)
            for b in mutants:self.assertFalse(grade_answer(t,b)['passed'],(id,seed,b))
            self.assertTrue(grade_answer(t,dict(reversed(list(a.items()))))['passed'])

if __name__=='__main__':unittest.main()
