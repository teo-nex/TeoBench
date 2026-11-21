import copy,json,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import answer_tasks as a
from bench import grade_answer
class SemanticMutants(unittest.TestCase):
    def mutate(self,id,fn):
        for seed in (11,29,47):
            t=next(t for t in a.build(seed) if t['id']==id);answer=a.reference(t);fn(answer)
            self.assertFalse(grade_answer(t,answer)['passed'],(id,seed))
    def test_invoice_total_only(self):self.mutate('Q02',lambda x:x.update(total='0.00'))
    def test_invoice_round_half_up(self):self.mutate('Q02',lambda x:x['line_totals'].__setitem__(0,'0.03'))
    def test_invoice_numeric_not_money_string(self):self.mutate('Q02',lambda x:x.update(total=float(x['total'])))
    def test_quotes_duplicate_candidate(self):self.mutate('Q03',lambda x:x['selected'].append(copy.deepcopy(x['selected'][0])))
    def test_quotes_wrong_attribution_evidence(self):self.mutate('Q03',lambda x:x['selected'][0].update(source='s2'))
    def test_quotes_wrong_text(self):self.mutate('Q03',lambda x:x['selected'][0].update(quote='пересказ'))
    def test_doc_stale_value_correct_source(self):self.mutate('Q04',lambda x:x['retry_limit'].update(value=x['retry_limit']['value']-10))
    def test_doc_unknown_guessed(self):self.mutate('Q04',lambda x:x['region'].update(value='north'))
    def test_doc_bool_value(self):self.mutate('Q04',lambda x:x['timeout_s'].update(value=True))
    def test_partial_wrong_known_value(self):self.mutate('Q05',lambda x:x['workers'].update(value=999))
    def test_partial_guessed_budget(self):self.mutate('Q05',lambda x:x['budget'].update(value=0))
    def test_partial_missing_source_omitted(self):self.mutate('Q05',lambda x:x.update(missing_sources=[]))
    def test_timeline_local_time(self):self.mutate('Q06',lambda x:x['utc'].__setitem__(0,'2026-11-15T08:00:00Z'))
    def test_timeline_historical_code(self):self.mutate('Q06',lambda x:x['codes'].__setitem__(0,401))
    def test_timeline_extra_event(self):self.mutate('Q06',lambda x:x['event_ids'].append('historical'))
if __name__=='__main__':unittest.main()
