"""Maintenance dry-run by default. Only reviewed cache candidates can be removed."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from transcomic.maintenance import inventory,cleanup,active_work,require_idle
from transcomic.update.metadata import UpdateError


def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args(argv)
    folder=ROOT/'artifacts/cleanup-review';folder.mkdir(parents=True,exist_ok=True)
    try:
        processes=active_work();require_idle(ROOT,processes)
        plan=inventory(ROOT)
        plan['process_ids']=processes
        plan['git_head']=subprocess.check_output(['git','-C',str(ROOT),'rev-parse','HEAD']).decode().strip()
        plan['git_status']=subprocess.check_output(['git','-C',str(ROOT),'status','--porcelain']).decode('utf8')
        (folder/'inventory.json').write_text(json.dumps(plan,indent=2),encoding='utf8')
        pending=[c for c in plan['candidates'] if not c['safe']]
        pending += [{'path':name,'reason':'evidence/build/config/data/unknown; no removal authorized'} for name in ('artifacts','build','dist','docs','installer','ddd') if (ROOT/name).exists()]
        pending += [{'path':p.name,'reason':'user data or unknown file; keep'} for p in ROOT.iterdir() if p.is_file() and p.suffix.lower() in ('.docx','.txt','.db','.sqlite3','.png')]
        (folder/'pending-review.json').write_text(json.dumps(pending,indent=2),encoding='utf8')
        report={'dry_run':not args.apply,'candidates':sum(c['safe'] for c in plan['candidates']),
                'root_items':plan['root_items'],'files':plan['file_count'],'pending':len(pending)}
        if args.apply:
            report['cleanup']=cleanup(ROOT,plan,Path(os.environ['LOCALAPPDATA'])/'TransComicMaintenance')
            report['after_root_items']=len(list(ROOT.iterdir()))
        (folder/('cleanup-result.json' if args.apply else 'dry-run.json')).write_text(json.dumps(report,indent=2),encoding='utf8')
        print(json.dumps(report));return 0
    except (UpdateError,OSError,ValueError):
        print('CLEANUP BLOCKED: review process/journal/path/inventory; no broad deletion');return 2


if __name__=='__main__':raise SystemExit(main())
