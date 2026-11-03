import base64
import contextlib
import hashlib
import io
import json
import os
import unittest
from unittest.mock import patch

from scripts import validate_study_pr as validator
from teobench import studies
from teobench.cli import load


class TrustedValidatorTests(unittest.TestCase):
    def test_real_json_blob_is_regraded_and_mixed_code_is_rejected(self):
        _,answers,_=load()
        study=studies.create('validator-test','test-route','test macOS environment')
        studies.add_record(study,'R02','model','high',json.dumps(answers['R02']['expected']),[])
        data=json.dumps(study).encode()
        sha=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
        files=[{'filename':'Easy-Bench/studies/validator-test/study.json','status':'added','sha':sha}]
        blob={'size':len(data),'encoding':'base64','content':base64.b64encode(data).decode()}
        def api(path):return files if '/files?' in path else blob
        with patch.object(validator,'require_complete',return_value={}), patch.object(validator,'api',side_effect=api):
            report=validator.validate_files('owner/repo','1')
            self.assertEqual(report[0]['records'],1)
            self.assertTrue(report[0]['answers_regraded'])
            files.append({'filename':'teobench/evaluate.py','status':'modified','sha':'0'*40})
            with patch.object(validator, 'validate', side_effect=AssertionError('must reject before grading')):
                with self.assertRaisesRegex(ValueError,'only_add_study_json'):
                    validator.validate_files('owner/repo','1')

    def test_trusted_workflow_resolves_pr_and_posts_verdict(self):
        calls=[]
        head='a'*40
        def api(path,payload=None):
            calls.append((path,payload))
            if '/actions/runs/' in path:
                return {'event':'pull_request','name':'Check Easy benchmark','head_sha':head,'pull_requests':[{'number':1}]}
            if '/statuses/' in path:return {}
            return {'number':1,'state':'open','head':{'sha':head}}
        env={'GITHUB_REPOSITORY':'owner/repo','SOURCE_RUN_ID':'123','STATUS_CONTEXT':'Easy study regrade','GITHUB_RUN_ID':'456'}
        with patch.dict(os.environ,env,clear=True), patch.object(validator,'api',side_effect=api), patch.object(validator,'validate_files',return_value=[]), contextlib.redirect_stdout(io.StringIO()):
            validator.main()
        self.assertEqual([payload['state'] for _,payload in calls if payload],['pending','success'])

    def test_superseded_run_cannot_approve_new_head(self):
        def api(path,payload=None):
            if '/actions/runs/' in path:
                return {'event':'pull_request','name':'Check Easy benchmark','head_sha':'a'*40,'pull_requests':[{'number':1}]}
            return {'state':'open','head':{'sha':'b'*40}}
        env={'GITHUB_REPOSITORY':'owner/repo','SOURCE_RUN_ID':'123'}
        with patch.dict(os.environ,env,clear=True), patch.object(validator,'api',side_effect=api), patch.object(validator,'validate_files') as grading, contextlib.redirect_stdout(io.StringIO()) as out:
            validator.main()
            self.assertFalse(grading.called)
            self.assertEqual(json.loads(out.getvalue())['status'],'SKIP')

    def test_accepted_study_cannot_be_rewritten(self):
        files=[{'filename':'Easy-Bench/studies/old-study/study.json','status':'modified','sha':'a'*40}]
        with patch.object(validator,'api',return_value=files), self.assertRaisesRegex(ValueError,'immutable'):
            validator.validate_files('owner/repo','1')


if __name__=='__main__':unittest.main()
