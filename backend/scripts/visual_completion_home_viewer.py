"""为发布版首页的4×2预览提供逐图原图弹窗，不改封存结果及照片字节。"""
import json

CSS = '''<style>
.preview-frame{position:relative;margin:0 auto;width:100%;max-width:604px}
.preview-frame .preview{width:100%;height:auto;max-height:none}
.preview-hotspots{position:absolute;inset:0;display:grid;grid-template-columns:repeat(4,minmax(0,1fr));grid-template-rows:repeat(2,minmax(0,1fr))}
.preview-hotspot{background:transparent;border:0;border-radius:0;padding:0;cursor:zoom-in;min-width:0}
.preview-hotspot:hover{background:#ffffff16;box-shadow:inset 0 0 0 2px #315c45}
.preview-hotspot:focus-visible{outline:3px solid #315c45;outline-offset:-3px}
#home-image-viewer{width:min(1200px,calc(100vw - 24px));max-height:calc(100dvh - 24px);padding:20px;border:0;border-radius:14px;color:#273431;overflow:auto}
#home-image-viewer::backdrop{background:#10231be0}
.viewer-heading,.viewer-controls{display:flex;gap:12px;justify-content:space-between;align-items:center}
.viewer-heading h2{margin:0;font-size:20px}.viewer-heading button{flex-shrink:0}
#home-original{display:block;width:100%;height:min(65dvh,760px);object-fit:contain;margin:16px 0;background:#f6f5f1}
#home-scope{margin:8px 0}.viewer-controls{flex-wrap:wrap}#home-image-count{margin:0;color:#64716b}
@media(max-width:650px){#home-image-viewer{padding:14px}.viewer-heading h2{font-size:17px}.viewer-heading button,.viewer-controls button{padding:8px 12px}#home-original{height:55dvh}}
</style>'''
DIALOG = '''<dialog id="home-image-viewer" aria-labelledby="home-image-title"><div class="viewer-heading"><h2 id="home-image-title"></h2><button type="button" id="home-image-close" aria-label="关闭图片预览">关闭</button></div><img id="home-original" alt=""><p id="home-scope"></p><div class="viewer-controls"><button type="button" id="home-image-previous">上一张</button><p id="home-image-count" aria-live="polite"></p><button type="button" id="home-image-next">下一张</button><a id="home-image-source" target="_blank" rel="noopener noreferrer">查看来源文章</a></div></dialog>'''
JS = '''<script>
(()=>{const boards=JSON.parse(document.getElementById('home-board-data').textContent);
const dialog=document.getElementById('home-image-viewer'),image=document.getElementById('home-original');
let currentBoard=null,currentIndex=0;
function showImage(board,index){currentBoard=board;currentIndex=index;const tile=board.tiles[index];image.src=tile.original_data;image.alt=tile.scope;document.getElementById('home-image-title').textContent=board.title;document.getElementById('home-scope').textContent=tile.scope;document.getElementById('home-image-count').textContent=(index+1)+' / '+board.tiles.length;const source=document.getElementById('home-image-source');source.hidden=!tile.source_url;source.href=tile.source_url||'';document.getElementById('home-image-previous').disabled=index===0;document.getElementById('home-image-next').disabled=index===board.tiles.length-1;}
for(const card of document.querySelectorAll('article')){const link=card.querySelector('a[href^="boards/"]'),preview=card.querySelector('.preview');if(!link||!preview)continue;const board=boards.find(b=>b.board_url===link.getAttribute('href'));if(!board)continue;const frame=document.createElement('div');frame.className='preview-frame';preview.replaceWith(frame);frame.append(preview);const hotspots=document.createElement('div');hotspots.className='preview-hotspots';board.tiles.forEach((tile,index)=>{const button=document.createElement('button');button.type='button';button.className='preview-hotspot';button.setAttribute('aria-label','放大查看 '+board.title+' 第'+(index+1)+'张');button.title='点击查看原图';button.onclick=()=>{showImage(board,index);dialog.showModal();document.body.style.overflow='hidden';};hotspots.append(button);});frame.append(hotspots);}
document.getElementById('home-image-close').onclick=()=>dialog.close();dialog.addEventListener('close',()=>{document.body.style.overflow='';image.removeAttribute('src');});dialog.addEventListener('click',event=>{if(event.target!==dialog)return;const r=dialog.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)dialog.close();});
document.getElementById('home-image-previous').onclick=()=>{if(currentIndex>0)showImage(currentBoard,currentIndex-1);};document.getElementById('home-image-next').onclick=()=>{if(currentIndex<currentBoard.tiles.length-1)showImage(currentBoard,currentIndex+1);};dialog.addEventListener('keydown',event=>{if(event.key==='ArrowLeft'&&currentIndex>0){event.preventDefault();showImage(currentBoard,currentIndex-1);}if(event.key==='ArrowRight'&&currentIndex<currentBoard.tiles.length-1){event.preventDefault();showImage(currentBoard,currentIndex+1);}});
})();</script>'''

def enhance_index(html: str, boards: list[dict]) -> str:
    # 弹窗按完整预览格映射原照片；加载仍为点击时按需请求，首页不下载全部原图。
    data=[{'title':board['title'],'board_url':board['board_url'],'tiles':[{**tile,'original_data':tile['original_data'].removeprefix('../')} for tile in board['tiles']]} for board in boards]
    payload=json.dumps(data,ensure_ascii=False).replace('</','<\\/')
    html=html.replace('</style>','</style>'+CSS,1)
    html=html.replace('点击图板可查看原图、取景范围与来源。','点击预览中的任意图片可放大原图；“查看图板与原图”可进入完整图板。',1)
    return html.replace('</html>',DIALOG+'<script type="application/json" id="home-board-data">'+payload+'</script>'+JS+'</html>',1)
