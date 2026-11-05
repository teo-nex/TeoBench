import tempfile
import unittest
from pathlib import Path
from teobench.medium import verify, MODELS, EFFORTS
from teobench.medium_journal import Journal


class JournalTests(unittest.TestCase):
    def test_full_matrix_first_attempt_and_protocol_lock(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'study.sqlite';manifest=verify()
            j=Journal(path,manifest,'protocol-a')
            self.assertEqual(j.status()['states'],{'PLANNED':3500})
            task=manifest['tasks'][0];slots=j.slots(task)
            self.assertEqual({(m,e) for m,e,_ in slots},{(m,e) for m in MODELS for e in EFFORTS})
            slot=(task['source'],task['id'],*slots[0][:2])
            j.transition(slot,'PLANNED','STARTED')
            with self.assertRaises(ValueError):j.transition(slot,'PLANNED','STARTED')
            j.transition(slot,'STARTED','TRANSPORT_ERROR',requests=1)
            self.assertEqual(j.status()['primary_attempts'],1)
            self.assertEqual(j.status()['graded'],0)
            j.close()
            resumed=Journal(path,manifest,'protocol-a')
            self.assertEqual(resumed.status()['transport_errors'],1)
            resumed.close()
            with self.assertRaises(ValueError):Journal(path,manifest,'protocol-b')
