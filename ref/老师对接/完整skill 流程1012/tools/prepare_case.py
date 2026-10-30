"""Bind the included public-image historical case at its current location; no inference."""
from pathlib import Path
import argparse,hashlib,json,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'skills/prism_skill_support/scripts'))
from io_utils import read,write,ref,fresh
from render_board import build

def prepare(out):
 base=ROOT/'cases/linear-relief';src=read(base/'board-portable.json');tiles=[]
 for row in src['tiles']:
  row=dict(row);old=row['image_ref'];path=(base/old['path']).resolve()
  if not path.is_relative_to(base) or hashlib.sha256(path.read_bytes()).hexdigest()!=old['sha256']:raise ValueError('Case source identity mismatch')
  row['image_ref']=ref(path);tiles.append(row)
 data={'title':src['title'],'branch':src['branch'],'stage_status':src['stage_status'],'tiles':tiles}
 folder=fresh(out);write(folder/'board.current.json',data)
 page,audit=build(data);write(folder/'board.html',page);write(folder/'render-audit.json',audit)
 return {'out':str(folder),'historical_case_replayed':True,'images':len(tiles),'new_model_calls':0,'new_visual_qualification':False}
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--out',required=True);a=p.parse_args();print(json.dumps(prepare(a.out),ensure_ascii=False))
