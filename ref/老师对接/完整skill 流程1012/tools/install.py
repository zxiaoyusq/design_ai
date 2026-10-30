"""Copy this complete suite into an explicitly selected skills directory; dry-run default."""
from pathlib import Path
import argparse,json,shutil

ROOT=Path(__file__).resolve().parents[1]
def install(dest,apply=False):
    dest=Path(dest).expanduser().resolve();items=sorted(p for p in (ROOT/'skills').iterdir() if p.is_dir())
    conflicts=[p.name for p in items if (dest/p.name).exists()]
    plan={'destination':str(dest),'folders':[p.name for p in items],'conflicts':conflicts,'would_install':not conflicts,'applied':False,'model_calls':0}
    if not apply:return plan
    if conflicts:raise ValueError('Existing folders are not overwritten. Back them up deliberately or choose a new destination: '+', '.join(conflicts))
    for p in items:
        target=(dest/p.name).resolve()
        if not target.is_relative_to(dest):raise ValueError('Install target escapes named destination')
    dest.mkdir(parents=True,exist_ok=True)
    for p in items:shutil.copytree(p,dest/p.name)
    plan['applied']=True;return plan
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--dest',required=True);p.add_argument('--apply',action='store_true');a=p.parse_args();print(json.dumps(install(a.dest,a.apply),ensure_ascii=False))
