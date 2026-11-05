import copy
import base64
import io
import json
from pathlib import Path
import tempfile
import unittest
import urllib.error

from teobench.medium_quota import assess_usage, CodexQuotaGuard, QuotaBlocked, NoRedirect


class QuotaTests(unittest.TestCase):
    def fixture(self, percent=4):
        return {'plan_type': 'pro', 'rate_limit': {'allowed': True, 'limit_reached': False,
            'primary_window': {'used_percent': percent, 'reset_at': 2000000000},
            'secondary_window': None}, 'credits': {'has_credits': True, 'balance': 'private-balance'}}

    def test_credits_never_override_included_quota(self):
        self.assertTrue(assess_usage(self.fixture())['allowed'])
        for percent in [70, 80, 100]:
            self.assertFalse(assess_usage(self.fixture(percent))['allowed'])

    def test_no_account_or_balance_in_receipt(self):
        self.assertNotIn('private', str(assess_usage(self.fixture())))
        self.assertNotIn('credits', str(assess_usage(self.fixture())))

    def test_unknown_values_fail_closed(self):
        for value in [None, '4', True, float('nan'), float('inf'), -1, 101]:
            self.assertFalse(assess_usage(self.fixture(value))['allowed'])

    def test_both_windows_and_additional_families_checked(self):
        data=self.fixture()
        data['rate_limit']['secondary_window']={'used_percent': 75}
        self.assertFalse(assess_usage(data)['allowed'])
        data=self.fixture()
        data['additional_rate_limits']=[{'rate_limit': copy.deepcopy(self.fixture(90)['rate_limit'])}]
        self.assertFalse(assess_usage(data)['allowed'])

    def test_unknown_or_exhausted_quota_never_fails_open(self):
        for data in [{}, None, {'plan_type': 'pro'}, {'plan_type': 'api'}]:
            self.assertFalse(assess_usage(data)['allowed'])
        for key,value in [('allowed',False), ('limit_reached',True), ('primary_window',None)]:
            data=self.fixture();data['rate_limit'][key]=value
            self.assertFalse(assess_usage(data)['allowed'])
        data=self.fixture();data['additional_rate_limits']={'unknown': 0}
        self.assertFalse(assess_usage(data)['allowed'])

    def test_reserve_cannot_be_disabled(self):
        for ceiling in [0, 81, 100, '70', True, float('nan')]:
            with self.assertRaises(ValueError):assess_usage(self.fixture(),ceiling=ceiling)

    def auth(self,path,account='private-account',expires=10000):
        claims={'exp':expires,'https://api.openai.com/auth':{'chatgpt_account_id':account}}
        token='private-token.'+base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip('=')+'.signature'
        path.write_text(json.dumps({'auth_mode':'chatgpt','tokens':{'access_token':token}}))

    def test_live_guard_readonly_and_account_change_rejected(self):
        class Opener:
            def __init__(self,data):self.data=data;self.calls=0
            def open(self,request,timeout):
                self.calls+=1
                assert request.full_url=='https://chatgpt.com/backend-api/wham/usage'
                return io.BytesIO(json.dumps(self.data).encode())
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'auth.json';self.auth(path);original=path.read_bytes()
            opener=Opener(self.fixture());guard=CodexQuotaGuard(path,opener=opener,now=lambda:0)
            self.assertTrue(guard.check()['allowed']);self.assertEqual(original,path.read_bytes())
            self.auth(path,account='different-account')
            with self.assertRaisesRegex(QuotaBlocked,'subscription_account_changed'):guard.check()
            self.assertEqual(opener.calls,1)

    def test_unavailable_usage_expiring_auth_and_redirect_never_fall_back(self):
        class Unavailable:
            def open(self,*args,**kwargs):raise urllib.error.URLError('private-token-provider-body')
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'auth.json';self.auth(path)
            with self.assertRaises(QuotaBlocked) as error:
                CodexQuotaGuard(path,opener=Unavailable(),now=lambda:0).check()
            self.assertNotIn('private',str(error.exception));self.assertFalse(error.exception.snapshot['allowed'])
            self.auth(path,expires=10)
            with self.assertRaisesRegex(QuotaBlocked,'subscription_auth_expires_soon'):
                CodexQuotaGuard(path,opener=Unavailable(),now=lambda:0).check()
            with self.assertRaisesRegex(QuotaBlocked,'subscription_quota_redirect_denied'):
                NoRedirect().redirect_request(None,None,None,None,None,None)
