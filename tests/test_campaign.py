import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from teobench import campaign, studies
from teobench.cli import ROOT, main


class CampaignTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.primary = studies.load_json(ROOT/'Easy-Bench/studies/2026-11-03-reasoning-effort/study.json')
        cls.complete = copy.deepcopy(cls.primary)
        by_key = {(r['model'],r['effort'],r['task_id']):r for r in cls.primary['records']}
        _, jobs = campaign.plan()
        # Explicitly synthetic coverage fixtures, not new inference or public studies.
        for job in jobs:
            if job['phase']!='primary':
                row=copy.deepcopy(by_key[(job['model'],job['effort'],job['task_id'])])
                row['replicate']=job['replicate'];cls.complete['records'].append(row)

    def test_authoritative_plan_has_exact_original_matrix_and_checks(self):
        config,jobs=campaign.plan()
        self.assertEqual(len(config['models']),7)
        self.assertEqual(config['efforts'],['low','medium','high','xhigh','max'])
        self.assertEqual(len(jobs),1127)
        self.assertEqual(len({campaign.identity(j) for j in jobs}),1127)
        self.assertEqual(sum(j['phase']=='primary' for j in jobs),1050)
        self.assertEqual(sum(j['phase']=='pilot' for j in jobs),35)
        self.assertEqual(sum(j['phase']=='controls' for j in jobs),42)

    def test_one_condition_cannot_be_claimed_or_submitted_as_full_study(self):
        partial=copy.deepcopy(self.primary)
        partial['benchmark']['grader_sha256']=studies.grader_digest()
        first=partial['records'][0]
        partial['records']=[r for r in partial['records'] if (r['model'],r['effort'])==(first['model'],first['effort'])]
        self.assertEqual(len(partial['records']),30)
        report=campaign.coverage(partial)
        self.assertFalse(report['primary_complete'])
        self.assertEqual(report['complete_primary_conditions'],1)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'study.json';studies.save(path,partial)
            with patch('teobench.studies.subprocess.run',side_effect=AssertionError('network forbidden')):
                with self.assertRaisesRegex(ValueError,'incomplete_full_campaign'):
                    studies.publish(path,publish=True,gh='gh')

    def test_all_primary_conditions_are_required_and_legacy_is_not_full_protocol(self):
        report=campaign.coverage(self.primary)
        self.assertTrue(report['primary_complete'])
        self.assertEqual(report['complete_primary_conditions'],35)
        self.assertFalse(report['full_protocol_complete'])
        with self.assertRaisesRegex(ValueError,'incomplete_full_campaign'):
            campaign.require_complete(self.primary)
        missing=copy.deepcopy(self.complete)
        missing['records']=[r for r in missing['records'] if not(r['model']=='gpt-6-astra' and r['effort']=='max')]
        self.assertFalse(campaign.coverage(missing)['primary_complete'])
        with self.assertRaisesRegex(ValueError,'incomplete_full_campaign'):
            campaign.require_complete(missing)

    def test_full_protocol_has_35_primary_conditions_and_resumes_without_repeating(self):
        report=campaign.require_complete(self.complete)
        self.assertEqual(report['status'],'COMPLETE')
        self.assertEqual(report['complete_primary_conditions'],35)
        self.assertIsNone(report['next_trial'])
        missing=copy.deepcopy(self.complete)
        row=missing['records'].pop(123)
        next_trial=campaign.coverage(missing)['next_trial']
        self.assertEqual(campaign.identity(next_trial),campaign.identity(row))
        self.assertFalse(campaign.coverage(missing)['primary_complete'])

    def test_wrong_model_or_effort_cannot_replace_missing_slot(self):
        for key,value in [('model','substitute-model'),('effort','default')]:
            study=copy.deepcopy(self.complete);study['records'][0][key]=value
            with self.assertRaisesRegex(ValueError,'incomplete_full_campaign'):
                campaign.require_complete(study)

    def test_trusted_pr_validator_calls_same_completion_gate(self):
        from scripts import validate_study_pr as validator
        import base64,hashlib
        study=copy.deepcopy(self.primary);study['records']=study['records'][:30];study['study_id']='partial-test'
        data=json.dumps(study).encode();sha=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
        files=[{'filename':'Easy-Bench/studies/partial-test/study.json','status':'added','sha':sha}]
        blob={'size':len(data),'encoding':'base64','content':base64.b64encode(data).decode()}
        def api(path):return files if '/files?' in path else blob
        with patch.object(validator,'api',side_effect=api),patch.object(validator,'validate',return_value={'records':30}):
            with self.assertRaisesRegex(ValueError,'incomplete_full_campaign'):
                validator.validate_files('owner/repo','1')

if __name__=='__main__':unittest.main()
