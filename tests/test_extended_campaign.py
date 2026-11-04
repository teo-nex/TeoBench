"""Synthetic fixtures for profile coverage and faithful failed-attempt storage."""
import copy
import json
import unittest
import contextlib
import io
import tempfile
from pathlib import Path
from teobench import campaign, studies
from teobench.cli import load


class ExtendedCampaignTests(unittest.TestCase):
    def setUp(self):
        self.study = studies.create('extended-unit-test', 'synthetic route',
                                    'synthetic test environment', campaign.EXTENDED_PROFILE)

    def test_explicit_profile_has_46_conditions_and_keeps_default_unchanged(self):
        self.assertEqual(len(campaign.plan()[1]), 1127)
        config, jobs = campaign.plan(campaign.EXTENDED_PROFILE)
        self.assertEqual(len(jobs), 1468)
        self.assertEqual([sum(j['phase']==p for j in jobs) for p in
                          ('pilot','primary','controls')], [40,1380,48])
        self.assertEqual(len({campaign.identity(j) for j in jobs}), 1468)
        self.assertEqual(len({(j['model'],j['effort']) for j in jobs
                              if j['phase']=='primary'}), 46)
        self.assertFalse(any(j['effort']=='ultra' and j['model'] in
                             ('gpt-6-luna','gpt-5.6-luna') for j in jobs))

    def test_extended_profile_still_requires_every_slot_and_rejects_extras(self):
        _, jobs = campaign.plan(campaign.EXTENDED_PROFILE)
        fixture = {'campaign_profile':campaign.EXTENDED_PROFILE, 'records':jobs}
        report = campaign.require_complete(fixture)
        self.assertEqual(report['expected_primary_conditions'],46)
        for phase in ('pilot','primary','controls'):
            missing=copy.deepcopy(fixture)
            missing['records'].remove(next(j for j in missing['records'] if j['phase']==phase))
            with self.assertRaisesRegex(ValueError,'incomplete_full_campaign'):
                campaign.require_complete(missing)
        extra=copy.deepcopy(fixture)
        extra['records'].append(dict(jobs[0],model='substitute-model'))
        with self.assertRaisesRegex(ValueError,'incomplete_full_campaign'):
            campaign.require_complete(extra)

    def test_profile_is_a_trusted_name_not_a_path(self):
        for profile in ('../../private.json','custom-profile','',None):
            invalid=copy.deepcopy(self.study)
            invalid['campaign_profile']=profile
            with self.assertRaisesRegex(ValueError,'unknown_campaign_profile'):
                studies.validate(invalid,regrade=False)

    def test_failed_argument_object_is_retained_and_fails_grading(self):
        history=[{'name':'lookup','arguments':{},'ok':False,
                  'output':{'error':'invalid arguments'}}]
        studies.add_record(self.study,'T03','test-model','ultra','{}',history)
        self.assertEqual(self.study['records'][0]['tool_history'],history)
        self.assertEqual(studies.validate(self.study)['semantic_pass'],0)
        forged=copy.deepcopy(self.study)
        forged['records'][0]['evaluation']['semantic_pass']=True
        with self.assertRaisesRegex(ValueError,'regrade_mismatch'):
            studies.validate(forged)
        legacy=studies.create('legacy-unit-test','route','environment')
        with self.assertRaisesRegex(ValueError,'tool_arguments|unknown_effort'):
            studies.add_record(legacy,'T03','test-model','high','{}',history)

    def test_successful_calls_remain_strict(self):
        history=[{'name':'lookup','arguments':{},'ok':True,'output':{}}]
        with self.assertRaisesRegex(ValueError,'tool_arguments'):
            studies.add_record(self.study,'T03','test-model','high','{}',history)

    def test_failed_call_log_is_bounded_without_truncation(self):
        failed={'name':'lookup','arguments':{},'ok':False,'output':{'error':'invalid'}}
        studies.add_record(self.study,'T05','test-model','high','{}',[failed]*107)
        self.assertEqual(len(self.study['records'][0]['tool_history']),107)
        self.assertEqual(studies.validate(self.study)['semantic_pass'],0)
        for history in ([failed]*257,
                        [dict(failed,ok=True,arguments={'id':'unknown'})]*101):
            value=studies.create('bounded-unit-test','route','environment',campaign.EXTENDED_PROFILE)
            with self.assertRaisesRegex(ValueError,'invalid_tool_history'):
                studies.add_record(value,'T05','test-model','high','{}',history)

    def test_a_better_retry_cannot_inflate_primary_score_or_fill_coverage(self):
        studies.add_record(self.study,'R01','test-model','high','{}',[])
        _, answers, _ = load()
        retry=copy.deepcopy(self.study['records'][0])
        retry.update(answer=json.dumps(answers['R01']['expected']),attempt=1,
                     started_at='2026-11-04T00:00:00+00:00')
        from teobench.evaluate import grade
        tasks,_,_=load()
        retry['evaluation']=grade(next(t for t in tasks if t['id']=='R01'),
                                  retry['answer'],answers['R01'])
        self.study['additional_attempts'].append(retry)
        report=studies.validate(self.study)
        self.assertEqual(report['records'],1)
        self.assertEqual(report['semantic_pass'],0)
        self.assertEqual(campaign.coverage(self.study)['phases']['primary']['recorded'],0)
        duplicate=copy.deepcopy(self.study)
        duplicate['additional_attempts'].append(copy.deepcopy(retry))
        with self.assertRaisesRegex(ValueError,'duplicate_additional_attempt'):
            studies.validate(duplicate,regrade=False)
        orphan=copy.deepcopy(self.study)
        orphan['additional_attempts'][0]['task_id']='R02'
        with self.assertRaisesRegex(ValueError,'invalid_additional_attempt'):
            studies.validate(orphan,regrade=False)
        gap=copy.deepcopy(self.study)
        gap['additional_attempts'][0]['attempt']=2
        with self.assertRaisesRegex(ValueError,'additional_attempt_sequence_has_gaps'):
            studies.validate(gap,regrade=False)

    def test_additional_attempts_are_regraded_even_though_not_scored(self):
        studies.add_record(self.study,'R01','test-model','high','{}',[])
        retry=copy.deepcopy(self.study['records'][0])
        retry.update(attempt=1,started_at='2026-11-04T00:00:00+00:00')
        retry['evaluation']['semantic_pass']=True
        self.study['additional_attempts']=[retry]
        with self.assertRaisesRegex(ValueError,'regrade_mismatch'):
            studies.validate(self.study)


    def test_record_helper_retains_retry_in_audit_ledger_only(self):
        studies.add_record(self.study,'R01','test-model','high','{}',[])
        studies.add_record(self.study,'R01','test-model','high','{}',[],
                           attempt=1, started_at='2026-11-04T00:00:00+00:00')
        self.assertEqual(len(self.study['records']),1)
        self.assertEqual(len(self.study['additional_attempts']),1)
        self.assertEqual(studies.validate(self.study)['additional_attempts'],1)
        legacy=studies.create('legacy-retry-test','route','environment')
        with self.assertRaisesRegex(ValueError,'additional_attempts_require_schema'):
            studies.add_record(legacy,'R01','test-model','high','{}',[],
                               attempt=1,started_at='2026-11-04T00:00:00+00:00')

    def test_cli_records_a_non_scoring_retry(self):
        from teobench.cli import main
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            report=Path(directory)/'study.json'
            answer=Path(directory)/'answer.txt'
            answer.write_text('{}',encoding='utf-8')
            self.assertEqual(main(['study','create','--id','cli-extended-test','--file',str(report),
                                   '--access-route','synthetic','--environment','synthetic',
                                   '--campaign-profile',campaign.EXTENDED_PROFILE]),0)
            args=['study','record','--file',str(report),'--task','R01','--model','test-model',
                  '--effort','high','--answer',str(answer)]
            self.assertEqual(main(args),0)
            self.assertEqual(main(args+['--attempt','1','--started-at','2026-11-04T00:00:00+00:00']),0)
            value=studies.load_json(report)
            self.assertEqual(value['schema_version'],'1.1')
            self.assertEqual(len(value['records']),1)
            self.assertEqual(len(value['additional_attempts']),1)


if __name__=='__main__':
    unittest.main()
