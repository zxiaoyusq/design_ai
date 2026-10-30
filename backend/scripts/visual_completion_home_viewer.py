"""为发布版首页提供完整原图网格和逐图弹窗，保留封存图板的取景与结果。"""
import json
import re

CSS = '''<style id="home-image-viewer-style">
.cards{grid-template-columns:1fr}
.preview-frame{margin:18px 0;width:100%}
.preview-hotspots{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px}
.preview-hotspot{display:block;background:#f7f7f3;border:1px solid #e3e7df;border-radius:9px;padding:0;cursor:zoom-in;min-width:0;text-align:left;color:#64716b;overflow:hidden}
.home-thumbnail{display:block;width:100%;aspect-ratio:4/3;object-fit:contain;object-position:center;background:#f7f7f3}
.home-thumbnail-caption{display:block;padding:8px 12px;font-size:12px}
.preview-hotspot:hover{border-color:#315c45;box-shadow:0 0 0 1px #315c45}
.preview-hotspot:focus-visible{outline:3px solid #315c45;outline-offset:3px}
@media(max-width:900px){.preview-hotspots{grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}}
@media(max-width:650px){article{padding:16px}.home-thumbnail-caption{padding:7px 9px;font-size:11px}}
#home-image-viewer{width:min(1200px,calc(100vw - 24px));max-height:calc(100dvh - 24px);padding:20px;border:0;border-radius:14px;color:#273431;overflow:auto}
#home-image-viewer::backdrop{background:#10231be0}
.viewer-heading,.viewer-controls{display:flex;gap:12px;justify-content:space-between;align-items:center}
.viewer-heading h2{margin:0;font-size:20px}.viewer-heading button{flex-shrink:0}
#home-original{display:block;width:100%;height:min(65dvh,760px);object-fit:contain;margin:16px 0;background:#f6f5f1}
#home-scope{margin:8px 0}.viewer-controls{flex-wrap:wrap}#home-image-count{margin:0;color:#64716b}
@media(max-width:650px){#home-image-viewer{padding:14px}.viewer-heading h2{font-size:17px}.viewer-heading button,.viewer-controls button{padding:8px 12px}#home-original{height:55dvh}}
</style>'''
DIALOG = '''<dialog id="home-image-viewer" aria-labelledby="home-image-title"><div class="viewer-heading"><h2 id="home-image-title"></h2><button type="button" id="home-image-close" aria-label="关闭图片预览">关闭</button></div><img id="home-original" alt=""><p id="home-scope"></p><div class="viewer-controls"><button type="button" id="home-image-previous">上一张</button><p id="home-image-count" aria-live="polite"></p><button type="button" id="home-image-next">下一张</button><a id="home-image-source" target="_blank" rel="noopener noreferrer">查看来源文章</a></div></dialog>'''
JS = '''<script id="home-image-viewer-script">
(()=>{const boards=JSON.parse(document.getElementById('home-board-data').textContent);
const dialog=document.getElementById('home-image-viewer'),image=document.getElementById('home-original');
let currentBoard=null,currentIndex=0;
function showImage(board,index){currentBoard=board;currentIndex=index;const tile=board.tiles[index];image.src=tile.original_data;image.alt=tile.scope;document.getElementById('home-image-title').textContent=board.title;document.getElementById('home-scope').textContent=tile.scope;document.getElementById('home-image-count').textContent=(index+1)+' / '+board.tiles.length;const source=document.getElementById('home-image-source');source.hidden=!tile.source_url;source.href=tile.source_url||'';document.getElementById('home-image-previous').disabled=index===0;document.getElementById('home-image-next').disabled=index===board.tiles.length-1;}
for(const card of document.querySelectorAll('article')){
  const link=card.querySelector('a[href^="boards/"]'),preview=card.querySelector('.preview');
  if(!link||!preview)continue;
  const board=boards.find(b=>b.board_url===link.getAttribute('href'));
  if(!board)continue;
  const frame=document.createElement('div');frame.className='preview-frame';
  preview.replaceWith(frame);
  const gallery=document.createElement('div');gallery.className='preview-hotspots';
  board.tiles.forEach((tile,index)=>{
    const button=document.createElement('button');button.type='button';button.className='preview-hotspot';
    button.setAttribute('aria-label','放大查看 '+board.title+' 第'+(index+1)+'张');button.title='点击放大原图';
    // 主页展示完整来源照片，实际取景范围继续在图板页和原图弹窗说明中保留。
    const thumbnail=document.createElement('img');thumbnail.className='home-thumbnail';
    thumbnail.src=tile.original_data;thumbnail.alt=tile.scope||tile.label;
    thumbnail.loading='lazy';thumbnail.decoding='async';
    const caption=document.createElement('span');caption.className='home-thumbnail-caption';
    caption.textContent='第 '+(index+1)+' 张 · 点击放大';
    button.append(thumbnail,caption);
    button.onclick=()=>{showImage(board,index);dialog.showModal();document.body.style.overflow='hidden';};
    gallery.append(button);
  });
  frame.append(gallery);
}
document.getElementById('home-image-close').onclick=()=>dialog.close();dialog.addEventListener('close',()=>{document.body.style.overflow='';image.removeAttribute('src');});dialog.addEventListener('click',event=>{if(event.target!==dialog)return;const r=dialog.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)dialog.close();});
document.getElementById('home-image-previous').onclick=()=>{if(currentIndex>0)showImage(currentBoard,currentIndex-1);};document.getElementById('home-image-next').onclick=()=>{if(currentIndex<currentBoard.tiles.length-1)showImage(currentBoard,currentIndex+1);};dialog.addEventListener('keydown',event=>{if(event.key==='ArrowLeft'&&currentIndex>0){event.preventDefault();showImage(currentBoard,currentIndex-1);}if(event.key==='ArrowRight'&&currentIndex<currentBoard.tiles.length-1){event.preventDefault();showImage(currentBoard,currentIndex+1);}});
})();</script>'''

def enhance_index(html: str, boards: list[dict]) -> str:
    # 首页和弹窗使用相同的原图地址；懒加载只下载当前浏览位置附近的照片。
    data=[{'title':board['title'],'board_url':board['board_url'],'tiles':[{**tile,'original_data':tile['original_data'].removeprefix('../')} for tile in board['tiles']]} for board in boards]
    payload=json.dumps(data,ensure_ascii=False).replace('</','<\\/')
    html=html.replace('</style>','</style>'+CSS,1)
    html=html.replace('点击图板可查看原图、取景范围与来源。','主页完整展示每张原图，点击可放大；“查看图板与原图”可查看实际取景范围。',1)
    return html.replace('</html>',DIALOG+'<script type="application/json" id="home-board-data">'+payload+'</script>'+JS+'</html>',1)


def refresh_index(html: str) -> str:
    """更新已发布主页的展示层，复用原图片索引，不重建或修改封存图板。"""
    if 'id="home-board-data"' not in html:
        raise ValueError('主页缺少原图片索引，无法更新完整原图展示')
    style_pattern = r'<style(?: id="home-image-viewer-style")?>\s*(?:\.preview-frame|\.cards)[\s\S]*?</style>'
    script_pattern = r'<script(?: id="home-image-viewer-script")?>\s*\(\(\)=>\{const boards=JSON.parse\(document.getElementById\(\'home-board-data\'\)[\s\S]*?</script>'
    html, styles = re.subn(style_pattern, lambda _: CSS, html)
    html, scripts = re.subn(script_pattern, lambda _: JS, html)
    if styles != 1 or scripts != 1:
        raise ValueError('主页展示层标记不唯一，停止替换以保留当前页面')
    return html.replace('点击预览中的任意图片可放大原图；“查看图板与原图”可进入完整图板。',
                        '主页完整展示每张原图，点击可放大；“查看图板与原图”可查看实际取景范围。', 1)


if __name__ == '__main__':
    import argparse
    import hashlib
    from pathlib import Path

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('page', type=Path, help='已发布主页，例如 zhangxiaoyu.html')
    args = parser.parse_args()
    content = refresh_index(args.page.read_text(encoding='utf-8')).encode('utf-8')
    temporary = args.page.with_name(args.page.name + '.tmp')
    temporary.write_bytes(content)
    temporary.replace(args.page)
    digest = hashlib.sha256(content).hexdigest()
    comparison = args.page.parent / 'comparison-manifest.json'
    if comparison.exists():
        manifest = json.loads(comparison.read_text(encoding='utf-8'))
        # 历史 source_sha256 仍指向切换前的原主页；新哈希独立标记展示层版本。
        manifest['authors']['zhangxiaoyu'].update(page_sha256=digest, display_mode='full-originals')
        comparison.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    deployment = args.page.parent / 'deployment-manifest.json'
    if deployment.exists():
        manifest = json.loads(deployment.read_text(encoding='utf-8'))
        manifest['public_files'] = [
            {'path': str(file.relative_to(args.page.parent)),
             'sha256': hashlib.sha256(file.read_bytes()).hexdigest(), 'bytes': file.stat().st_size}
            for file in sorted(args.page.parent.rglob('*'))
            if file.is_file() and file != deployment
        ]
        deployment.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'page': str(args.page), 'sha256': digest, 'display_mode': 'full-originals'}))
