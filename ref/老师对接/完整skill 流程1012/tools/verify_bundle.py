"""Offline bundle integrity, no installation or inference."""
from pathlib import Path
import hashlib,json,sys
ROOT=Path(__file__).resolve().parents[1]
def verify():
    manifest=json.loads((ROOT/'metadata/bundle-manifest.json').read_text(encoding='utf-8-sig'));bad=[]
    for row in manifest['files']:
        p=(ROOT/row['path']).resolve()
        if not p.is_relative_to(ROOT) or not p.is_file():bad.append({'path':row['path'],'error':'missing_or_outside'})
        elif hashlib.sha256(p.read_bytes()).hexdigest()!=row['sha256']:bad.append({'path':row['path'],'error':'hash_changed'})
    actual_skills=sorted(p.parent.name for p in (ROOT/'skills').glob('*/SKILL.md'))
    if len(actual_skills)!=manifest['skill_count'] or actual_skills!=manifest.get('skill_names',actual_skills):bad.append({'error':'skill_inventory_changed'})
    actual={p.relative_to(ROOT).as_posix() for p in ROOT.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc'}
    expected={r['path'] for r in manifest['files']}|{'metadata/bundle-manifest.json'}
    for extra in sorted(actual-expected):bad.append({'path':extra,'error':'unexpected_file'})
    return {'valid':not bad,'file_count':len(manifest['files']),'skills':manifest['skill_count'],'errors':bad,'model_calls':0}
if __name__=='__main__':
    result=verify();print(json.dumps(result,ensure_ascii=False));sys.exit(0 if result['valid'] else 2)
