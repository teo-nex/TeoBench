import base64
import copy
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import validate_study_pr as validator
from teobench import studies
from teobench.cli import ROOT, load


LEGACY_GRADER = '7764269832dde6894979d35ea0bbdd2b6aab0161b8ab796c5b5d405926316308'
PORTABLE_GRADER = '2a3a06139c1691e561d053330bbb44cc3b0042049767a3aab6e61008c15c896c'

BUBBLEWRAP_GRADER = '08214687c3a81703b01b2171f8e97442e8b7c33c1f30670e788963e2f50c6635'
PREVIOUS_PORTABLE_GRADER = '351c9710e3baf53251f4052cb8191035d7c2a99ab61b0537f34007cbf9229b8b'


class GraderCompatibilityTests(unittest.TestCase):
    def historical_study(self):
        _, answers, _ = load()
        study = studies.create('historical-test', 'test-route', 'synthetic environment')
        studies.add_record(study, 'R02', 'test-model', 'high',
                           json.dumps(answers['R02']['expected']), [])
        study['benchmark']['grader_sha256'] = LEGACY_GRADER
        return study

    def test_historical_validation_preserves_source_and_names_actual_regrader(self):
        study = self.historical_study()
        original = copy.deepcopy(study)
        report = studies.validate(study)
        self.assertEqual(report['semantic_pass'], 1)
        self.assertEqual(report['recorded_grader_sha256'], LEGACY_GRADER)
        self.assertEqual(report['regraded_with_sha256'], PORTABLE_GRADER)
        self.assertEqual(study, original)
        preview = studies.validate(study, regrade=False)
        self.assertFalse(preview['answers_regraded'])
        self.assertIsNone(preview['regraded_with_sha256'])

    def test_previous_graders_regrade_without_relabelling(self):
        for digest in [BUBBLEWRAP_GRADER, PREVIOUS_PORTABLE_GRADER]:
            with self.subTest(grader=digest):
                study = self.historical_study()
                study['benchmark']['grader_sha256'] = digest
                original = copy.deepcopy(study)
                report = studies.validate(study)
                self.assertEqual(report['recorded_grader_sha256'], digest)
                self.assertEqual(report['regraded_with_sha256'], PORTABLE_GRADER)
                self.assertEqual(study, original)

    def test_unknown_grader_or_unreviewed_future_regrader_is_rejected(self):
        study = self.historical_study()
        unknown = copy.deepcopy(study)
        unknown['benchmark']['grader_sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'benchmark_or_grader_version_mismatch'):
            studies.validate(unknown, regrade=False)
        with patch.object(studies, 'grader_digest', return_value='f' * 64):
            with self.assertRaisesRegex(ValueError, 'benchmark_or_grader_version_mismatch'):
                studies.validate(study, regrade=False)
        study['benchmark']['tasks_sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'benchmark_or_grader_version_mismatch'):
            studies.validate(study, regrade=False)

    def test_legacy_hash_does_not_bypass_regrading(self):
        study = self.historical_study()
        study['records'][0]['answer'] = '{}'
        with self.assertRaisesRegex(ValueError, 'regrade_mismatch'):
            studies.validate(study)

    def test_historical_studies_cannot_mix_in_new_records(self):
        study = self.historical_study()
        original = copy.deepcopy(study)
        with patch.object(studies, 'grade', side_effect=AssertionError('must not grade')):
            with self.assertRaisesRegex(ValueError, 'historical_study_is_read_only'):
                studies.add_record(study, 'R03', 'test-model', 'high', '{}', [])
        self.assertEqual(study, original)

    def test_historical_submissions_fail_before_network_or_campaign_checks(self):
        study = self.historical_study()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'study.json'
            studies.save(path, study)
            for publish in [False, True]:
                with patch.object(studies.subprocess, 'run', side_effect=AssertionError('network forbidden')):
                    with self.assertRaisesRegex(ValueError, 'historical_study_is_read_only'):
                        studies.publish(path, publish=publish, gh='gh')

    def test_trusted_validator_rejects_new_submissions_using_old_grader(self):
        study = self.historical_study()
        data = json.dumps(study).encode()
        sha = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        files = [{'filename': 'Easy-Bench/studies/historical-test/study.json',
                  'status': 'added', 'sha': sha}]
        blob = {'size': len(data), 'encoding': 'base64',
                'content': base64.b64encode(data).decode()}
        def api(path):
            return files if '/files?' in path else blob
        with patch.object(validator, 'api', side_effect=api):
            with self.assertRaisesRegex(ValueError, 'historical_study_is_read_only'):
                validator.validate_files('owner/repo', '1')

    def test_statistics_keep_grader_versions_separate_without_claiming_a_regrade(self):
        historical = studies.load_json(
            ROOT / 'Easy-Bench/studies/2026-11-03-reasoning-effort/study.json')
        first = historical['records'][0]
        historical['records'] = [row for row in historical['records']
                                 if (row['model'], row['effort']) == (first['model'], first['effort'])]
        current = copy.deepcopy(historical)
        current['study_id'] = 'synthetic-current-study'
        current['benchmark']['grader_sha256'] = studies.grader_digest()
        # Distinct synthetic model labels avoid the exact-answer-set deduper.
        for row in current['records']:
            row['model'] = 'synthetic-current-model'
        with tempfile.TemporaryDirectory() as directory:
            paths = [Path(directory) / name for name in ['historical.json', 'current.json']]
            for path, study in zip(paths, [historical, current]):
                studies.save(path, study)
            report = studies.statistics_report(paths, regrade=False)
        self.assertFalse(report['answers_regraded'])
        self.assertIsNone(report['regraded_with_sha256'])
        self.assertEqual(len(report['groups']), 2)
        self.assertEqual({group['grader_sha256'] for group in report['groups']},
                         {LEGACY_GRADER, PORTABLE_GRADER})
        self.assertTrue(all(group['regraded_with_sha256'] is None for group in report['groups']))

    def test_statistics_cli_regrades_all_1050_archived_results_without_rewriting(self):
        source = ROOT / 'Easy-Bench/studies/2026-11-03-reasoning-effort/study.json'
        original = source.read_bytes()
        old_summary = studies.load_json(ROOT / 'Easy-Bench/statistics/summary.json')
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'summary.json'
            result = subprocess.run([sys.executable, '-m', 'teobench', 'stats',
                                     '--output', str(output)], cwd=ROOT,
                                    capture_output=True, text=True, timeout=600 if sys.platform == "win32" else 180)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = studies.load_json(output)
            self.assertTrue(report['answers_regraded'])
            self.assertEqual(report['regraded_with_sha256'], PORTABLE_GRADER)
            self.assertEqual(len(report['groups']), 35)
            self.assertEqual(sum(group['task_results'] for group in report['groups']), 1050)
            for group in report['groups']:
                self.assertEqual(group['grader_sha256'], LEGACY_GRADER)
                self.assertEqual(group['regraded_with_sha256'], PORTABLE_GRADER)
            strip_provenance = lambda groups: [
                {key: value for key, value in group.items() if key != 'regraded_with_sha256'}
                for group in groups]
            self.assertEqual(strip_provenance(report['groups']), strip_provenance(old_summary['groups']))
            with output.with_suffix('.csv').open(newline='') as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 35)
            self.assertTrue(all(row['regraded_with_sha256'] == PORTABLE_GRADER for row in rows))
        self.assertEqual(source.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
