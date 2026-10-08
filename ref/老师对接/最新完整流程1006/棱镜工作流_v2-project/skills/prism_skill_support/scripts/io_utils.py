"""Local evidence IO. Importing this module performs no actions."""
from pathlib import Path
import hashlib,json,math

def read(path):
    def pairs(items):
        out={}
        for k,v in items:
            if k in out:raise ValueError('duplicate JSON key: '+k)
            out[k]=v
        return out
    def bad(x):raise ValueError('nonfinite JSON: '+x)
    return json.loads(Path(path).read_text(encoding='utf-8-sig'),object_pairs_hook=pairs,parse_constant=bad)
def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def ref(path):
    p=Path(path).resolve()
    if not p.is_file():raise ValueError('File missing: '+str(p))
    return {'path':str(p),'sha256':sha(p)}
def checked(value,parse=True):
    if not isinstance(value,dict) or set(value)!={'path','sha256'}:raise ValueError('FileRef required')
    if ref(value['path'])!=value:raise ValueError('File identity changed')
    return read(value['path']) if parse else Path(value['path'])
def write(path,value):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('x',encoding='utf-8',newline='\n') as f:f.write(value if isinstance(value,str) else json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    return ref(p)
def fresh(path):
    p=Path(path).resolve();p.mkdir(parents=True,exist_ok=False);return p
def resolve(path,base):
    p=Path(path);return p.resolve() if p.is_absolute() else (Path(base)/p).resolve()
def store_content(body,folder,suffix):
    """Short filename for Windows; full SHA remains the identity and collision guard."""
    full=hashlib.sha256(body).hexdigest();folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    target=folder/(full[:20]+suffix)
    if target.exists():
        if sha(target)!=full:raise ValueError('Content filename collision or changed archived bytes')
    else:
        with target.open('xb') as f:f.write(body)
    return target
def rectangle(value):
    for k in ('x','y','width','height'):
        if type(value.get(k)) not in (int,float) or not math.isfinite(value[k]):raise ValueError('Finite rectangle required')
    if value['x']<0 or value['y']<0 or value['width']<=0 or value['height']<=0 or value['x']+value['width']>1.0000001 or value['y']+value['height']>1.0000001:raise ValueError('Rectangle outside original image')
    return value
