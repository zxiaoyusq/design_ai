"""Offline, reversible original-image views and boards. Never awards visual PASS."""
from pathlib import Path
import argparse,base64,html,json
from io_utils import read,write,checked,rectangle,ref
from assets import MIME

def from_native(g):
    b=g['prepared_snapshot']['brief'];tiles=[]
    for m in g['members']:
        u=m['exact_unit'];im=u['image']
        tiles.append({'image_ref':im['image_ref'],'article_id':im['source_group_id'],'source_group_id':im['source_group_id'],'rectangle':u['view']['rectangle'],'scope':u['target']['selected_scope'],'limits':u['view']['limits'],'source_url':'','label':m['unit_alias']})
    return {'title':b['family_name'],'branch':b['branch'],'target_count':b['count_policy']['target'],'stage_status':g['status'],'notes':g.get('blockers',[]),'tiles':tiles}
def build(data):
    from PIL import Image
    tiles=[];keys=set();article_keys=set();sha_keys=set();small=[]
    for n,t in enumerate(data['tiles'],1):
        p=checked(t['image_ref'],False);r=rectangle(t['rectangle']);aid=str(t.get('article_id',''));source=t.get('source_project_id') or t.get('source_group_id') or aid
        if not aid or not source or aid in article_keys or source in keys or t['image_ref']['sha256'] in sha_keys:raise ValueError('Missing or duplicate article/source/image in a board')
        keys.add(source);article_keys.add(aid);sha_keys.add(t['image_ref']['sha256'])
        with Image.open(p) as im:im.verify()
        with Image.open(p) as im:w,h=im.size;orientation=im.getexif().get(274,1)
        if orientation!=1:raise ValueError('Original EXIF orientation requires an explicitly registered view transform first')
        rw,rh=w*r['width'],h*r['height']
        if min(rw,rh)<400:small.append({'index':n,'source_pixels_in_ROI':[round(rw),round(rh)]})
        mime=MIME.get(p.suffix.lower())
        if not mime:raise ValueError('Unsupported original image')
        url=t.get('source_url','')
        if url and not url.startswith(('https://','http://')):raise ValueError('Source link must be HTTP(S)')
        tiles.append({**t,'pixels':[w,h],'label':str(t.get('label') or n),'original_data':'data:'+mime+';base64,'+base64.b64encode(p.read_bytes()).decode()})
    payload=json.dumps({**data,'tiles':tiles},ensure_ascii=False,separators=(',',':')).replace('</','<\\/')
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>棱镜图板审阅</title><style>*{box-sizing:border-box}body{margin:0;color:#24343d;background:white;font:15px/1.6 "Microsoft YaHei",Arial}main{max-width:1600px;margin:auto;padding:28px}h1{font-size:26px;font-weight:500}p{color:#66757e}.grid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:10px}.tile{display:flex;align-items:center;justify-content:center;aspect-ratio:1;background:#f6f6f4;border:0;padding:0;cursor:pointer}.view{position:relative;display:block;overflow:hidden}.view img{position:absolute;max-width:none;object-fit:fill}dialog{width:min(1100px,95vw);border:1px solid #ccd4d9;padding:20px}dialog::backdrop{background:#102331bb}dialog img{width:100%;max-height:65vh;object-fit:contain}.detail{font-size:13px}button{font:inherit}button:focus-visible,a:focus-visible{outline:3px solid #477c97}details{margin-top:24px}pre{white-space:pre-wrap;word-break:break-word}@media(max-width:700px){.grid{grid-template-columns:repeat(2,minmax(0,1fr))}main{padding:16px}}</style><main><h1 id="title"></h1><p id="state"></p><div id="grid" class="grid"></div><details><summary>判定和显示边界</summary><p>此工具仅按已声明范围显示原图，未新增视觉判断。数量、语义、视觉和用户反馈需各自保留真实审阅记录。点击图片可查看原图、范围和限制。</p><pre id="notes"></pre></details></main><dialog id="viewer"><button id="close">关闭</button><img id="original" alt="原图"><p id="scope"></p><p class="detail" id="limits"></p><p class="detail" id="roi"></p><a id="source" target="_blank" rel="noopener noreferrer">来源页</a></dialog><script>const DATA=__DATA__;const $=id=>document.getElementById(id);$('title').textContent=DATA.title;$('state').textContent=DATA.branch+' · '+DATA.tiles.length+'张 / 目标'+(DATA.target_count??'未定')+' · '+(DATA.stage_status??'尚未评审');$('notes').textContent=(DATA.notes??[]).join(String.fromCharCode(10));for(const t of DATA.tiles){const b=document.createElement('button');b.className='tile';b.setAttribute('aria-label',t.label+' '+t.scope);const v=document.createElement('span');v.className='view';const r=t.rectangle,a=r.width*t.pixels[0]/(r.height*t.pixels[1]);v.style.width=(a>=1?100:100*a)+'%';v.style.height=(a>=1?100/a:100)+'%';const im=document.createElement('img');im.src=t.original_data;im.alt=t.scope;Object.assign(im.style,{width:(100/r.width)+'%',height:(100/r.height)+'%',left:(-100*r.x/r.width)+'%',top:(-100*r.y/r.height)+'%'});v.append(im);b.append(v);b.onclick=()=>{$('original').src=t.original_data;$('scope').textContent=t.scope;$('limits').textContent=(t.limits??[]).join('；');$('roi').textContent='取景（原图比例）：'+JSON.stringify(t.rectangle)+'；真实原图像素：'+t.pixels.join('×');$('source').hidden=!t.source_url;$('source').href=t.source_url||'';$('viewer').showModal()};$('grid').append(b)}$('close').onclick=()=>$('viewer').close();</script></html>'''.replace('__DATA__',payload)
    return page,{'pictures':len(tiles),'same_registered_source_and_SHA_unique':True,'project_ids_present_for_all':all(t.get('source_project_id') for t in tiles),'project_identity_semantically_verified_by_this_tool':False,'low_ROI_pixels':small,'visual_PASS_awarded':False,'external_image_resources':0}
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--manifest');p.add_argument('--native-group');p.add_argument('--out',required=True);a=p.parse_args()
    if bool(a.manifest)==bool(a.native_group):raise ValueError('Choose --manifest or --native-group')
    data=read(a.manifest or a.native_group);data=from_native(data) if a.native_group else data;page,report=build(data);write(a.out,page);write(str(a.out)+'.render.json',{**report,'source_ref':ref(a.manifest or a.native_group)});print(json.dumps(report,ensure_ascii=False))
