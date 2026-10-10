#!/usr/bin/env python3
"""Token activity diagnostic commands; no model calls or credential reading."""
import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path
from runtime import configure,load_settings
from observer import atomic_json

def locations():
    home=Path.home()
    return (Path(os.environ.get('XDG_DATA_HOME',home/'.local/share'))/'token-activity',Path(os.environ.get('XDG_CONFIG_HOME',home/'.config'))/'token-activity/settings.json')

def main():
    os.umask(0o077)
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['status','export','backup','settings','configure','rescan','discover','once','serve'])
    parser.add_argument('value',nargs='?');args=parser.parse_args();root,config=locations()
    if args.command=='settings':print(json.dumps(load_settings(config)));return
    if args.command=='configure':
        print(json.dumps(configure(config,json.loads(args.value or '{}'))));atomic_json(root/'rescan.json',{'requested_at':time.time()});return
    if args.command=='rescan':atomic_json(root/'rescan.json',{'requested_at':time.time()});print('Rescan requested');return
    if args.command=='discover':
        from adapters import discover
        print(json.dumps(discover(load_settings(config)),indent=2));return
    if args.command in ('once','serve'):
        from service import run
        run(root,config,once=args.command=='once');return
    path=root/'usage.sqlite3'
    if not path.exists():print(json.dumps({'state':'not collected yet','database':str(path)}));return
    with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=5) as db:
        if args.command=='status':
            print(json.dumps(dict(database=str(path),integrity=db.execute('pragma quick_check').fetchone()[0],events=db.execute('select count(*) from events').fetchone()[0],revisions=db.execute('select count(*) from event_revisions').fetchone()[0],health=[dict(source=r[0],status=r[1],observed_at=r[2]) for r in db.execute('select * from health')]),indent=2))
        elif args.command=='export':
            for (data,) in db.execute('select data from events order by id'):print(data)
        elif args.command=='backup':
            dest=root/'backups'/('usage-'+time.strftime('%Y%m%dT%H%M%S',time.gmtime())+'-'+str(time.time_ns())+'.sqlite3');dest.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            with sqlite3.connect(dest) as target:db.backup(target)
            os.chmod(dest,0o600);print(dest)

if __name__=='__main__':
    try:main()
    except (ValueError,OSError,sqlite3.Error) as e:
        print('Token activity: '+type(e).__name__+'; inspect local settings/source permissions',file=sys.stderr);sys.exit(1)
