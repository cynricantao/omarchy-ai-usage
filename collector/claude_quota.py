"""Read-only Claude Code (claude.ai) usage windows; never exports authentication or PII.

Claude Code reads this same first-party endpoint for its /usage overlay:
GET https://api.anthropic.com/api/oauth/usage with the existing OAuth bearer
token, no redirects, bounded timeout.

Window readings come from the structured `limits` array when the build sends
one (kind 'session' = 5-hour window, kind 'weekly_all' = weekly window, each
with an explicit `percent`). Otherwise they come from `five_hour`/`seven_day`,
whose `utilization` is a percentage of the window (0-100) in percent-shaped
payloads and a 0-1 fraction in older fraction-only payloads. `resets_at` is
ISO 8601 in both shapes. Missing readings stay None and are never guessed.
"""
from adapters import _number, _hash, _stamp
import json
import os
import time
from pathlib import Path
from urllib.request import Request, build_opener, HTTPRedirectHandler, ProxyHandler
from urllib.error import HTTPError, URLError


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


# A payload carrying any of these keys reports utilization as a percentage.
# A payload without them is an older fraction-only response.
PERCENT_MARKERS=('limits','seven_day_breakdown','weekly_scoped_shares')
# (limits kind, window minutes, display label, legacy key)
WINDOWS=(('session',300,'5-hour limit','five_hour'),('weekly_all',10080,'Weekly limit','seven_day'))


def percent_shaped(data):
    return isinstance(data,dict) and any(key in data for key in PERCENT_MARKERS)


def window_percent(value,fraction):
    raw=_number(value)
    if raw is None:return None
    percent=raw*100 if fraction else raw
    return min(100.0,max(0.0,percent))


def quota_read(home=None):
    result=dict(tool='claude',status='unavailable',quotas=[])
    # Non-first-party transports bypass the OAuth usage read entirely;
    # refuse rather than guessing another origin.
    for name in ('CLAUDE_CODE_USE_BEDROCK','CLAUDE_CODE_USE_VERTEX','ANTHROPIC_BASE_URL','ANTHROPIC_UNIX_SOCKET'):
        if os.environ.get(name):
            result['status']='unsupported_environment';return result
    home=Path(home) if home else Path(os.environ.get('CLAUDE_CONFIG_DIR') or Path.home()/'.claude')
    try:
        token=os.environ.get('CLAUDE_CODE_OAUTH_TOKEN','').strip()
        if not token:
            path=home/'.credentials.json'
            try:
                if path.stat().st_size>65536:return result
                creds=json.loads(path.read_text())
            except FileNotFoundError:
                # No stored credential to read: fail closed as unauthorized so a
                # stale reading is never presented as the current window.
                result['status']='unauthorized';return result
            oauth=creds.get('claudeAiOauth') if isinstance(creds,dict) else None
            token=oauth.get('accessToken') if isinstance(oauth,dict) else None
        if not isinstance(token,str) or not token or '\n' in token or '\r' in token:
            result['status']='unauthorized';return result
        opener=build_opener(NoRedirect(),ProxyHandler({}))
        request=Request('https://api.anthropic.com/api/oauth/usage',method='GET',headers={'Authorization':'Bearer '+token,'Accept':'application/json','User-Agent':'token-activity-readonly/1'})
        with opener.open(request,timeout=12) as response:
            payload=response.read(1048577)
        if len(payload)>1048576:raise ValueError('oversized quota data')
        data=json.loads(payload)
        account='local-profile-unverified:'+_hash('claude',str(home))
        return parse_quotas(data,time.time(),account)
    except HTTPError as error:
        result['status']={401:'unauthorized',403:'unauthorized',429:'rate_limited'}.get(error.code,'offline')
        error.close()
    except (URLError,TimeoutError):result['status']='offline'
    except (OSError,ValueError,TypeError,AttributeError):result['status']='unavailable'
    return result


def parse_quotas(data, observed, account):
    result=dict(tool='claude',status='unavailable',quotas=[])
    if not isinstance(data,dict):return result
    marks=percent_shaped(data)
    limits={}
    for row in data.get('limits') or []:
        if isinstance(row,dict) and isinstance(row.get('kind'),str):limits.setdefault(row['kind'],row)
    for kind,minutes,label,legacy in WINDOWS:
        limit=limits.get(kind);field=data.get(legacy)
        limit=limit if isinstance(limit,dict) else None
        field=field if isinstance(field,dict) else None
        if limit is None and field is None:continue
        percent=window_percent(limit.get('percent'),False) if limit is not None else None
        resets=_stamp(limit.get('resets_at')) if limit is not None else None
        if field is not None:
            if percent is None:
                raw=_number(field.get('utilization'))
                # A percentage in percent-shaped payloads; a 0-1 fraction in
                # older payloads; above 1 means a percentage in either shape.
                percent=window_percent(raw,raw is not None and raw<=1 and not marks)
            if resets is None:resets=_stamp(field.get('resets_at'))
        result['quotas'].append(dict(tool='claude',source='readonly_oauth_usage',account_id=account,
            label=label,quota_id=legacy,window_minutes=minutes,used_percent=percent,
            remaining_percent=max(0,100-percent) if percent is not None else None,
            resets_at=resets,observed_at=observed,status='ok'))
    if result['quotas']:result['status']='ok'
    return result
