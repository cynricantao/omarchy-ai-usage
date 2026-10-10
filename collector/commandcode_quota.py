"""Read-only Command Code production quota API; never exports authentication or PII."""
from adapters import _number, _hash
import json
import os
import time
from pathlib import Path
from urllib.request import Request, build_opener, HTTPRedirectHandler, ProxyHandler
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
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
        endpoint='/alpha/billing/credits'+('?' + urlencode({'orgId':org_id}) if isinstance(org_id,str) and org_id else '')
        data=get(endpoint)
        account='local-profile-unverified:'+_hash('commandcode',str(home),org_id or 'personal')
        return parse_quotas(data,time.time(),account)
    except HTTPError as error:
        result['status']={401:'unauthorized',403:'unauthorized',429:'rate_limited'}.get(error.code,'offline')
        error.close()
    except (URLError,TimeoutError):result['status']='offline'
    except (OSError,ValueError,TypeError,AttributeError):result['status']='unavailable'
    return result



def parse_quotas(data, observed, account):
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
    if result['quotas']:result['status']='ok'
    return result
