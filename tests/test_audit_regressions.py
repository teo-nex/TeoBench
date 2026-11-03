"""Failure paths found by the cross-platform audit; no model calls."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from teobench import studies
from teobench.cli import ROOT
from teobench.evaluate import python_outputs, sql_outputs
from teobench.sandbox import local_docker_client


class AuditRegressionTests(unittest.TestCase):
    def test_macos_nested_sandbox_denial_is_not_a_model_failure(self):
        failed = subprocess.CompletedProcess([], 71, '',
                    'sandbox-exec: sandbox_apply: Operation not permitted\n')
        with patch.dict('os.environ', {'TEOBENCH_PYTHON_SANDBOX': 'seatbelt'}), \
                patch('teobench.evaluate.sys.platform', 'darwin'), \
                patch('teobench.evaluate.sandbox_command', return_value=['sandbox-exec']), \
                patch('teobench.evaluate.subprocess.run', return_value=failed), \
                patch('teobench.evaluate.docker_run') as docker:
            with self.assertRaisesRegex(RuntimeError, 'OS_sandbox_unavailable_macos_seatbelt_setup_failed'):
                python_outputs('def solve(x): return x', [1])
            docker.assert_not_called()

    def test_generator_cannot_reach_trusted_worker_globals(self):
        source = 'def solve(x):\n g = (g.gi_frame.f_back.f_back.f_globals for _ in [0])\n return sorted(next(g))'
        with self.assertRaisesRegex(ValueError, 'worker_ValueError'):
            python_outputs(source, [1])

    def test_failed_serialization_preserves_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'study.json'
            studies.save(path, {'records': [1]})
            original = path.read_bytes()
            with patch('teobench.studies.os.replace', side_effect=OSError('disk failure')):
                with self.assertRaises(OSError):
                    studies.save(path, {'records': [1, 2]})
            self.assertEqual(path.read_bytes(), original)

    def test_invalid_record_does_not_poison_in_memory_checkpoint(self):
        study = studies.create('audit-study', 'synthetic', 'synthetic')
        original = copy.deepcopy(study)
        with self.assertRaisesRegex(ValueError, 'unknown_effort'):
            studies.add_record(study, 'R01', 'synthetic', 'invalid', '{}', [])
        self.assertEqual(study, original)

    def test_size_validation_matches_the_bytes_written_to_disk(self):
        study = studies.create('audit-study', 'synthetic', 'synthetic')
        studies.add_record(study, 'R01', 'synthetic', 'high', '{}', [])
        size = len((json.dumps(study, ensure_ascii=False, indent=2)+'\n').encode('utf-8'))
        with patch.object(studies, 'MAX_BYTES', size-1):
            with self.assertRaisesRegex(ValueError, 'study_exceeds_8MB'):
                studies.validate(study, regrade=False)

    def test_regrade_cannot_count_broken_sandbox_as_a_model_failure(self):
        study = studies.create('audit-study', 'synthetic', 'synthetic')
        failed = dict(semantic_pass=False, strict_pass=False, passed_cases=0,
                      total_cases=50, error='RuntimeError: sandbox_worker_exit_137')
        with patch.object(studies, 'grade', return_value=failed):
            studies.add_record(study, 'C01', 'synthetic', 'high', 'def solve(x): return x', [])
        unavailable = dict(failed, error='RuntimeError: OS_sandbox_unavailable_docker_start_failed')
        with patch.object(studies, 'grade', return_value=unavailable):
            with self.assertRaisesRegex(ValueError, 'grader_environment_unavailable'):
                studies.validate(study)

    def test_parallel_cli_records_are_all_retained(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'study.json'
            answer = Path(directory) / 'answer.txt'
            answer.write_text('{}', encoding='utf-8')
            studies.save(path, studies.create('parallel-study', 'synthetic', 'synthetic'))
            # Each CLI process slows down its save to expose overlapping reads.
            script = '''import sys, time
from teobench import studies
from teobench.cli import main
original = studies.save
def slow_save(*args):
    time.sleep(0.2)
    return original(*args)
studies.save = slow_save
raise SystemExit(main(sys.argv[1:]))
'''
            workers = [subprocess.Popen([sys.executable, '-c', script, 'study', 'record',
                        '--file', str(path), '--answer', str(answer), '--task', 'R01',
                        '--model', 'synthetic-'+str(i), '--effort', 'high'], cwd=ROOT,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE) for i in range(4)]
            for worker in workers:
                stdout, stderr = worker.communicate(timeout=30)
                self.assertEqual(worker.returncode, 0, (stdout, stderr))
            self.assertEqual(len(studies.load_json(path)['records']), 4)

    def test_sql_allocation_is_bounded_before_creating_large_value(self):
        # SQLite can compute a huge zero blob's length without allocating it;
        # a length limit must still reject it before any 1 GB value is exposed.
        with self.assertRaises(Exception):
            sql_outputs('SELECT length(hex(zeroblob(1000000000)))', {'tables': {}})
        self.assertEqual(sql_outputs('SELECT 1', {'tables': {}}), [[1]])

    def test_windows_rejects_remote_docker_before_sending_any_answer(self):
        with patch('teobench.sandbox.sys.platform', 'win32'), \
                patch('teobench.sandbox.shutil.which', return_value='docker.exe'):
            with patch.dict('os.environ', {'DOCKER_HOST': 'tcp://remote.invalid:2375', 'DOCKER_CONTEXT': ''}):
                with patch('teobench.sandbox.subprocess.run') as run:
                    with self.assertRaisesRegex(RuntimeError, 'local_named_pipe_required'):
                        local_docker_client()
                    run.assert_not_called()
            with patch.dict('os.environ', {'DOCKER_CONTEXT': 'remote'}):
                with patch('teobench.sandbox.subprocess.run', return_value=
                           subprocess.CompletedProcess([], 0, 'ssh://remote.invalid', '')):
                    with self.assertRaisesRegex(RuntimeError, 'local_named_pipe_required'):
                        local_docker_client()

    def test_csv_metadata_cannot_execute_spreadsheet_formulas(self):
        from teobench.cli import main
        import contextlib
        import csv
        import io
        fields = ['model', 'effort', 'access_route', 'environment', 'grader_sha256',
                  'regraded_with_sha256', 'studies', 'runs', 'task_results',
                  'median_pass_rate', 'mean_pass_rate', 'min_pass_rate', 'max_pass_rate', 'transport_errors']
        for formula in ['=1+1', '+1+1', '-1+1', '@SUM(1)', '  =1+1', '\t=1+1']:
            with self.subTest(formula=formula), tempfile.TemporaryDirectory() as directory:
                row = {key: 0 for key in fields}
                row['model'] = formula
                report = {'groups': [row]}
                target = Path(directory)/'summary.json'
                with patch.object(studies, 'statistics_report', return_value=report), contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(main(['stats', '--output', str(target)]), 0)
                with target.with_suffix('.csv').open(newline='', encoding='utf-8') as handle:
                    self.assertEqual(next(csv.DictReader(handle))['model'], "'"+formula)
                self.assertEqual(studies.load_json(target)['groups'][0]['model'], formula)


if __name__ == '__main__':
    unittest.main()
