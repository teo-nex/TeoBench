"""Fail-closed subscription quota checks. Never consumes or resets credits.

Run on the trusted orchestrator, never inside a candidate container. The native
auth file is read only; bearer tokens and balances are never returned in receipts.
"""
import base64
import hashlib
import json
import math
from pathlib import Path
import time
import urllib.error
import urllib.request


class QuotaBlocked(RuntimeError):
    def __init__(self, reason, snapshot=None):
        super().__init__(reason)
        self.snapshot = snapshot or {'allowed': False, 'reason': reason}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise QuotaBlocked('subscription_quota_redirect_denied')


def assess_usage(data, *, ceiling=70):
    if type(ceiling) not in (int, float) or not 0 < ceiling <= 80:
        raise ValueError('quota_ceiling_must_be_between_zero_and_eighty')
    def blocked(reason):
        return {'allowed': False, 'reason': reason}
    if not isinstance(data, dict) or data.get('plan_type') not in ('pro', 'plus'):
        return blocked('subscription_plan_not_verified')
    rate = data.get('rate_limit')
    if not isinstance(rate, dict):
        return blocked('subscription_quota_missing')
    rates = [rate]
    additional = data.get('additional_rate_limits')
    if additional is not None:
        if not isinstance(additional, list):
            return blocked('additional_quota_schema_unknown')
        for item in additional:
            if not isinstance(item, dict) or not isinstance(item.get('rate_limit'), dict):
                return blocked('additional_quota_schema_unknown')
            # Conservatively stop for any constrained family, rather than guess
            # how an upstream display name maps to the seven frozen model IDs.
            rates.append(item['rate_limit'])
    used, resets = [], []
    for limit in rates:
        if limit.get('allowed') is not True or limit.get('limit_reached') is not False:
            return blocked('subscription_limit_reached')
        windows = [limit.get(k) for k in ('primary_window', 'secondary_window')]
        if not any(w is not None for w in windows):
            return blocked('subscription_window_missing')
        for window in windows:
            if window is None:
                continue
            if not isinstance(window, dict):
                return blocked('subscription_window_unknown')
            value = window.get('used_percent')
            if (type(value) not in (int, float) or not math.isfinite(value)
                    or not 0 <= value <= 100):
                return blocked('subscription_usage_unknown')
            used.append(value)
            reset = window.get('reset_at')
            if type(reset) in (int, float) and math.isfinite(reset) and reset > 0:
                resets.append(reset)
    maximum = max(used)
    allowed = maximum < ceiling
    return {'allowed': allowed, 'reason': 'included_quota_available' if allowed else 'subscription_reserve_reached',
            'max_used_percent': maximum, 'stop_at_percent': ceiling,
            'reset_at': min(resets) if resets else None}


class CodexQuotaGuard:
    def __init__(self, auth_file, *, ceiling=70, opener=None, now=time.time, expected_account_hash=None):
        self.auth_file = Path(auth_file)
        self.ceiling = ceiling
        self.opener = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
        self.now = now
        self.account = None
        self.expected_account_hash=expected_account_hash

    def check(self):
        try:
            auth = json.loads(self.auth_file.read_text(encoding='utf-8-sig'))
            if not isinstance(auth,dict) or auth.get('auth_mode') != 'chatgpt':
                raise QuotaBlocked('subscription_auth_required')
            token = auth['tokens']['access_token']
            if not isinstance(token,str):raise QuotaBlocked('subscription_auth_required')
            part = token.split('.')[1]
            claims = json.loads(base64.urlsafe_b64decode(part + '=' * (-len(part) % 4)))
            if not isinstance(claims,dict):raise QuotaBlocked('subscription_auth_required')
            if claims.get('exp', 0) - self.now() < 3600:
                raise QuotaBlocked('subscription_auth_expires_soon')
            account = claims.get('https://api.openai.com/auth', {}).get('chatgpt_account_id')
            if not isinstance(account, str) or not account:
                raise QuotaBlocked('subscription_account_unknown')
            if self.account is not None and account != self.account:
                raise QuotaBlocked('subscription_account_changed')
            if self.expected_account_hash and hashlib.sha256(account.encode()).hexdigest()!=self.expected_account_hash:
                raise QuotaBlocked('subscription_account_changed')
            self.account = account
            headers = {'Authorization': 'Bearer ' + token, 'chatgpt-account-id': account,
                       'Accept': 'application/json', 'User-Agent': 'codex-cli/0.162.1',
                       'Version': '0.162.1', 'originator': 'codex_cli_rs'}
            request = urllib.request.Request('https://chatgpt.com/backend-api/wham/usage', headers=headers)
            with self.opener.open(request, timeout=20) as response:
                raw = response.read(1_000_001)
                if len(raw) > 1_000_000:
                    raise QuotaBlocked('subscription_quota_response_too_large')
                data = json.loads(raw)
            result = assess_usage(data, ceiling=self.ceiling)
            if not result['allowed']:
                raise QuotaBlocked(result['reason'], result)
            return result
        except QuotaBlocked:
            raise
        except (OSError, ValueError, KeyError, TypeError, IndexError, urllib.error.URLError):
            # Do not expose exception strings: they can include provider bodies,
            # paths or credentials. Never fall back when usage cannot be read.
            raise QuotaBlocked('subscription_quota_unavailable') from None


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--auth-file',type=Path,required=True)
    parser.add_argument('--account-sha256',required=True)
    args=parser.parse_args()
    try:
        value=CodexQuotaGuard(args.auth_file,expected_account_hash=args.account_sha256).check()
    except QuotaBlocked as error:value=error.snapshot
    print(json.dumps(value))
    raise SystemExit(0 if value['allowed'] else 3)
