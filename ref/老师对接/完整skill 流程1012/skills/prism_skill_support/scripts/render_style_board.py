"""Original-pixel editorial layout, offline embedded HTML; never creates or alters source assets."""
from pathlib import Path
import argparse, base64, html, json, math, mimetypes
from style_board_check import checked_ref, rectangle, sha

def number(value):
    if type(value) not in (int,float) or not math.isfinite(value):
        raise ValueError('Finite numeric layout values required')
    return value

def rect(value, W, H):
    x,y,w,h=[number(value[k]) for k in ('x','y','width','height')]
    if x<0 or y<0 or w<=0 or h<=0 or x+w>W or y+h>H:
        raise ValueError('Layout outside declared canvas')
    return x,y,w,h

def colour(value):
    import re
    if not isinstance(value,str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',value):
        raise ValueError('Use six-digit hex colours')
    return value

def render(board_path, out):
    from PIL import Image, ImageOps
    source=Path(board_path).resolve();base=source.parent
    b=json.loads(source.read_text('utf-8-sig'))
    if b.get('coordinate_space') != 'display_oriented':
        raise ValueError('Explicit display_oriented ROI coordinates required; do not reinterpret raw-pixel crops')
    canvas=b['canvas'];W=number(canvas['width']);H=number(canvas['height'])
    if W<=0 or H<=0: raise ValueError('Positive canvas size required')
    bg=colour(canvas.get('background','#EFEDE7'))
    tiles=[];sources=[]
    for tile in b['tiles']:
        image=checked_ref(tile['original_ref'],base)
        with Image.open(image) as im: im.verify()
        x,y,w,h=rect(tile['layout'],W,H);r=tile['rectangle'];rectangle(r)
        # Coordinates select a real source rectangle. Layout matches crop aspect to avoid stretching.
        with Image.open(image) as im:iw,ih=ImageOps.exif_transpose(im).size
        crop_ratio=iw*r['width']/(ih*r['height'])
        if abs((w/h)/crop_ratio-1)>.015:
            raise ValueError(tile['image_id']+': ROI aspect differs from layout; review crop instead of stretching')
        mime=mimetypes.guess_type(image.name)[0] or 'application/octet-stream'
        encoded=base64.b64encode(image.read_bytes()).decode('ascii')
        css=f'left:{x/W*100:.8f}%;top:{y/H*100:.8f}%;width:{w/W*100:.8f}%;height:{h/H*100:.8f}%;'
        img_css=f'image-orientation:from-image;width:{100/r["width"]:.8f}%;height:{100/r["height"]:.8f}%;left:{-100*r["x"]/r["width"]:.8f}%;top:{-100*r["y"]/r["height"]:.8f}%;'
        tiles.append(f'<div class="tile" style="{css}"><img alt="{html.escape(tile["image_id"],quote=True)}" src="data:{mime};base64,{encoded}" style="{img_css}"></div>')
        sources.append({'image_id':tile['image_id'],'source_ref':tile['original_ref'],'actual_source_sha256':sha(image),'rectangle':r,'layout':tile['layout']})
    text=[]
    for t in b.get('texts',[]):
        x,y,w,h=rect(t,W,H);size=number(t['font_size']);weight=700 if t.get('bold') else 400
        if size<=0:raise ValueError('Positive font size required')
        css=f'left:{x/W*100:.8f}%;top:{y/H*100:.8f}%;width:{w/W*100:.8f}%;height:{h/H*100:.8f}%;font-size:{size/W*100:.6f}cqw;font-weight:{weight};color:{colour(t.get("color","#292B2A"))};'
        text.append(f'<div class="copy" style="{css}">{html.escape(t["text"])}</div>')
    folder=Path(out).resolve();folder.mkdir(parents=True,exist_ok=False)
    for pure in (False,True):
        page='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        page+='<title>'+html.escape(b.get('title','Style study'))+'</title><style>*{box-sizing:border-box}body{margin:0;background:#ddd}.board{position:relative;container-type:inline-size;margin:auto;width:100%;max-width:'+str(W)+'px;aspect-ratio:'+str(W)+'/'+str(H)+';background:'+bg+';overflow:hidden}.tile,.copy{position:absolute}.tile{overflow:hidden}.tile img{position:absolute;max-width:none;display:block}.copy{white-space:pre-wrap;line-height:1.45;font-family:Arial,"Microsoft YaHei",sans-serif;overflow:hidden}@media print{body{background:white}@page{margin:0}}</style><main class="board">'
        page+=''.join(tiles)+('' if pure else ''.join(text))+'</main></html>'
        (folder/('pure-images.html' if pure else 'communication.html')).write_text(page,'utf-8')
    receipt={'board_ref':{'path':str(source),'sha256':sha(source)},'original_assets_unchanged':True,'source_pixels_repainted':False,'layout_sources':sources,'new_model_calls':0,'visual_review':'not_performed','font_dependencies':['Arial','Microsoft YaHei or compatible Chinese fallback'],'note':'Open both HTMLs and inspect text clipping/crop at intended display size; export through available document tools.'}
    (folder/'render-receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),'utf-8')
    return {'output':str(folder),'tile_count':len(tiles),'files':['communication.html','pure-images.html','render-receipt.json'],'visual_pass':False}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--board',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();print(json.dumps(render(a.board,a.out),ensure_ascii=False))
