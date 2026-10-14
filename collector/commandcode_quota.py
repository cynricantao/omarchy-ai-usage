"""Read-only Command Code production quota API; never exports authentication or PII."""
from adapters import _number, _hash
import json
import os
import time
from datetime import datetime
from pathlib import Path
from urllib.request import Request, build_opener, HTTPRedirectHandler, ProxyHandler
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


# Published per-plan monthly credit allowances from the Command Code CLI
# 1.74.x plan table. Plan ids resolve by longest prefix, so 'individual-goat'
# matches before 'individual-go'. Unknown plans fail closed: no monthly row.
PLAN_CREDITS = {
    'individual-go': 10,
    'individual-go-v1': 10,
    'individual-goat': 70,
    'individual-pro': 30,
    'individual-pro-v1': 80,
    'individual-provider': 15,
    'individual-max': 150,
    'individual-ultra': 300,
    'teams-pro': 40,
}


def _plan_credits(plan_id):
    if not isinstance(plan_id, str):
        return None
    normalized = plan_id.lower().replace('_', '-')
    for key in sorted(PLAN_CREDITS, key=len, reverse=True):
        if normalized.startswith(key):
            return PLAN_CREDITS[key]
    return None


def _iso_timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.timestamp() if parsed.tzinfo else None
    except ValueError:
        return None


def quota_read(home=None):
    result=dict(tool='commandcode',status='unavailable',quotas=[])
    if os.environ.get('COMMANDCODE_API_ENV','prod') != 'prod' or os.environ.get('COMMANDCODE_SANDBOX') == 'true' or os.environ.get('COMMANDCODE_API_URL'):
        result['status']='unsupported_environment';return result
    home=Path(home) if home else Path.home()/'.commandcode'
    try:
        key=os.environ.get('COMMAND_CODE_API_KEY','').strip()
        if not key:
            path=home/'auth.json'
            if path.stat().st_size>65536:return result
            auth=json.loads(path.read_text())
            key=auth.get('apiKey') if isinstance(auth,dict) else None
        if not isinstance(key,str) or not key or '\n' in key or '\r' in key:
            result['status']='unauthorized';return result
        opener=build_opener(NoRedirect(),ProxyHandler({}))
        def get(endpoint):
            # Only fixed production-origin GETs; never follow credential-bearing redirects.
            request=Request('https://api.commandcode.ai'+endpoint,method='GET',headers={'Authorization':'Bearer '+key,'Accept':'application/json','User-Agent':'token-activity-readonly/1'})
            with opener.open(request,timeout=12) as response:
                payload=response.read(1048577)
            if len(payload)>1048576:raise ValueError('oversized quota data')
            return json.loads(payload)
        who=get('/alpha/whoami')
        org=who.get('org') if isinstance(who,dict) else None
        org_id=org.get('id') if isinstance(org,dict) else None
        query='?' + urlencode({'orgId':org_id}) if isinstance(org_id,str) and org_id else ''
        data=get('/alpha/billing/credits'+query)
        # The subscription names the plan allowance and reset period for the
        # monthly credit meter; losing it only drops that one row.
        subscription=None
        try:
            payload=get('/alpha/billing/subscriptions'+query)
            subscription=payload.get('data') if isinstance(payload,dict) else None
        except HTTPError as error:
            error.close()
        except (URLError,TimeoutError,OSError,ValueError):
            subscription=None
        account='local-profile-unverified:'+_hash('commandcode',str(home),org_id or 'personal')
        return parse_quotas(data,time.time(),account,subscription=subscription)
    except HTTPError as error:
        result['status']={401:'unauthorized',403:'unauthorized',429:'rate_limited'}.get(error.code,'offline')
        error.close()
    except (URLError,TimeoutError):result['status']='offline'
    except (OSError,ValueError,TypeError,AttributeError):result['status']='unavailable'
    return result



def parse_quotas(data, observed, account, subscription=None):
    result=dict(tool='commandcode',status='unavailable',quotas=[])
    windows=data.get('windowLimits') if isinstance(data,dict) else None
    if not isinstance(windows,dict):return result
    for key,minutes,label in [('fiveHour',300,'5-hour limit'),('weekly',10080,'Weekly limit')]:
        row=windows.get(key)
        if not isinstance(row,dict):continue
        used,cap=_number(row.get('used')),_number(row.get('cap'))
        percent=used/cap*100 if used is not None and cap is not None and cap>0 else None
        reset=_number(row.get('resetAt'))
        result['quotas'].append(dict(tool='commandcode',source='readonly_billing_api',account_id=account,
            label=label,quota_id=key,window_minutes=minutes,used_percent=percent,
            remaining_percent=max(0,100-percent) if percent is not None else None,
            resets_at=reset/1000 if reset is not None and reset > 0 else None,observed_at=observed,status='ok'))
    # Monthly credit meter, mirroring the provider's own plan arithmetic: the
    # pool is the plan allowance (or the rollover balance, whichever is
    # larger) plus purchased and free credits; usage is the depleted
    # difference; the reset is the active subscription's current period end.
    # Inactive subscriptions, unknown plans and missing readings fail closed.
    if isinstance(subscription,dict) and subscription.get('status')=='active':
        credits=data.get('credits') if isinstance(data.get('credits'),dict) else {}
        monthly=_number(credits.get('monthlyCredits'))
        purchased=_number(credits.get('purchasedCredits'))
        free=_number(credits.get('freeCredits'))
        plan=_plan_credits(subscription.get('planId'))
        reset=_iso_timestamp(subscription.get('currentPeriodEnd'))
        if monthly is not None and purchased is not None and free is not None and plan is not None and plan > 0 and reset is not None:
            pool=max(plan,monthly)+purchased+free
            remaining=monthly+purchased+free
            percent=(pool-remaining)/pool*100 if pool > 0 else None
            result['quotas'].append(dict(tool='commandcode',source='readonly_billing_api',account_id=account,
                label='Monthly limit',quota_id='monthly',window_minutes=None,used_percent=percent,
                remaining_percent=max(0,100-percent) if percent is not None else None,
                resets_at=reset,observed_at=observed,status='ok'))
    if result['quotas']:result['status']='ok'
    return result
