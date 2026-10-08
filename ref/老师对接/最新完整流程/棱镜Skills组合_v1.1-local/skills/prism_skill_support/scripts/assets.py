"""Bounded original-image acquisition and contact sheets; no image modification."""
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.parse import urlsplit
import argparse,base64,hashlib,html,io,json,mimetypes,shutil
from io_utils import read,write,fresh,ref,resolve

MIME={'.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg','.webp':'image/webp','.gif':'image/gif'}
def acquire(plan_path,out,download=False):
    from PIL import Image
    pp=Path(plan_path).resolve();plan=read(pp);folder=fresh(out);rows=[];seen=set()
    for item in plan['images']:
        iid=item['image_id']
        if iid in seen:raise ValueError('Duplicate image_id')
        seen.add(iid);entry={**item};body=None
        try:
            if item.get('local_path'):body=resolve(item['local_path'],pp.parent).read_bytes();method='local_original'
            elif download:
                url=item['image_url']
                if urlsplit(url).scheme not in ('http','https'):raise ValueError('Only supplied HTTP(S) image URLs')
                with urlopen(Request(url,headers={'User-Agent':'Mozilla/5.0'}),timeout=30) as r:body=r.read(25*1024*1024+1)
                if len(body)>25*1024*1024:raise ValueError('Image larger than25MiB')
                method='single_HTTP_GET_no_retry'
            else:
                rows.append({**entry,'status':'not_downloaded','reason':'No local file and --download absent'});continue
            with Image.open(io.BytesIO(body)) as im:im.verify()
            with Image.open(io.BytesIO(body)) as im:w,h,fmt=im.width,im.height,im.format
            ext={'PNG':'.png','JPEG':'.jpg','WEBP':'.webp','GIF':'.gif'}.get(fmt)
            if not ext:raise ValueError('Unsupported decoded format')
            target=folder/'originals'/(hashlib.sha256(body).hexdigest()+ext);target.parent.mkdir(exist_ok=True)
            if not target.exists():target.write_bytes(body)
            entry.update(status='decoded_original',original_ref=ref(target),pixels=[w,h],acquisition_method=method,source_pixels_modified=False)
        except Exception as e:entry.update(status='source_unavailable_or_invalid',error=str(e))
        rows.append(entry)
    write(folder/'manifest.json',{'images':rows,'input_ref':ref(pp),'model_calls':0,'image_retouching':False});return {'images':len(rows),'decoded':sum(r['status']=='decoded_original' for r in rows),'out':str(folder)}
def gallery(manifest_path,out):
    rows=read(manifest_path)['images'];tiles=[]
    for r in rows:
        if r.get('status')!='decoded_original':continue
        p=Path(r['original_ref']['path'])
        if ref(p)!=r['original_ref']:raise ValueError('Original bytes changed')
        uri='data:'+MIME[p.suffix.lower()]+';base64,'+base64.b64encode(p.read_bytes()).decode()
        caption=html.escape(str(r.get('article_id',''))+' / '+r['image_id'])
        tiles.append('<figure><img src="'+uri+'" alt="'+caption+'"><figcaption>'+caption+'</figcaption></figure>')
    body='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>原图导航</title><style>body{font:14px Arial;margin:24px}main{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}figure{margin:0}img{width:100%;height:240px;object-fit:contain;background:#f5f5f5}@media(max-width:700px){main{grid-template-columns:repeat(2,1fr)}}</style><h1>原图导航 · 不是最终质量判断</h1><main>'+''.join(tiles)+'</main></html>'
    write(out,body);return {'out':str(out),'embedded_originals':len(tiles),'model_calls':0}
if __name__=='__main__':
    p=argparse.ArgumentParser();s=p.add_subparsers(dest='cmd',required=True)
    a=s.add_parser('acquire');a.add_argument('--plan',required=True);a.add_argument('--out',required=True);a.add_argument('--download',action='store_true')
    a=s.add_parser('gallery');a.add_argument('--manifest',required=True);a.add_argument('--out',required=True)
    a=p.parse_args();print(json.dumps(acquire(a.plan,a.out,a.download) if a.cmd=='acquire' else gallery(a.manifest,a.out),ensure_ascii=False))
