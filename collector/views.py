"""Rebuildable timezone-aware display projections. Unknown is never silently zero."""
from collections import defaultdict
from datetime import datetime,time as daytime,timedelta
from zoneinfo import ZoneInfo
from core import FIELDS

def aggregate(rows):
    rows=list(rows)
    return {k:sum(e['usage'][k] for e in rows) if rows and all(e['usage'].get(k) is not None for e in rows) else None for k in FIELDS}

def project(rows,timezone,now):
    zone=ZoneInfo(timezone);date=datetime.fromtimestamp(now,zone).date()
    today=datetime.combine(date,daytime(),zone);week=today-timedelta(days=6);tomorrow=today+timedelta(days=1)
    dated=[e for e in rows if e.get('occurred_at') is not None and e['occurred_at']<=now]
    def between(a,b):return [e for e in dated if a<=e['occurred_at']<b]
    def bucket(a,b,label):return dict(label=label,start=a,end=b,interval=datetime.fromtimestamp(a,zone).strftime('%Y-%m-%d %H:%M')+' – '+datetime.fromtimestamp(b,zone).strftime('%Y-%m-%d %H:%M')+' '+timezone,**aggregate(between(a,b)))
    days=[bucket((week+timedelta(days=i)).timestamp(),(week+timedelta(days=i+1)).timestamp(),(week+timedelta(days=i)).strftime('%Y-%m-%d')) for i in range(7)]
    ranges={};groups={'today':between(today.timestamp(),tomorrow.timestamp()),'week':between(week.timestamp(),tomorrow.timestamp()),'all':rows}
    earliest=min((e['occurred_at'] for e in dated),default=None)
    for name,events in groups.items():
        models=defaultdict(list)
        for e in events:models[(e.get('model') or 'Unattributed',e.get('provider'))].append(e)
        ranked=sorted((dict(model=m,provider=p,total=aggregate(v)['total']) for (m,p),v in models.items()),key=lambda x:x['total'] or 0,reverse=True)
        if name=='today':
            # Absolute hourly timestamps also handle 23/25-hour DST days.
            n=int((tomorrow.timestamp()-today.timestamp())/3600)
            buckets=[bucket(today.timestamp()+i*3600,today.timestamp()+(i+1)*3600,datetime.fromtimestamp(today.timestamp()+i*3600,zone).strftime('%H:%M')) for i in range(n)]
        elif name=='week':buckets=days
        elif earliest is None:buckets=[]
        else:
            first=datetime.fromtimestamp(earliest,zone).date();count=(date-first).days+1;stride=max(1,(count+59)//60)
            starts=[datetime.combine(first+timedelta(days=i),daytime(),zone) for i in range(0,count,stride)]
            buckets=[bucket(d.timestamp(),min((d+timedelta(days=stride)).timestamp(),tomorrow.timestamp()),d.strftime('%Y-%m-%d')) for d in starts]
        ranges[name]=dict(buckets=buckets,models=ranked)
    undated=[e for e in rows if e.get('occurred_at') is None]
    return dict(totals={k:aggregate(v)['total'] for k,v in groups.items()},days=days,ranges=ranges,coverage=dict(earliest=datetime.fromtimestamp(earliest,zone).strftime('%Y-%m-%d') if earliest is not None else None,incomplete=True,undated_tokens=aggregate(undated)['total'],note='Captured history only; undated cumulative history excluded from daily charts.'))
