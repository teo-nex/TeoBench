import copy,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bench import build, reference_answer,grade_answer

class AnswerTasks(unittest.TestCase):
    def test_log_reference_and_mutants(self):
        for seed in (11,29,47):
            task=next(t for t in build(seed) if t['id']=='Q01')
            answer=reference_answer(task)
            self.assertTrue(grade_answer(task,answer)['passed'])
            for wrong in (None,{},dict(answer,failed_events=answer['failed_events']+1),dict(answer,failed_ids=answer['failed_ids'][::-1]),dict(answer,extra='ignored?')):
                self.assertFalse(grade_answer(task,wrong)['passed'],(seed,wrong))
            self.assertTrue(grade_answer(task,dict(reversed(list(answer.items()))))['passed'])

if __name__=='__main__':unittest.main()
