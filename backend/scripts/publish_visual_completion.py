"""发布七方向离线图板：校验并外置原图，公开副本不携带本机审计路径。"""
from __future__ import annotations
import argparse, base64, hashlib, json, re
from pathlib import Path
from visual_completion_home_viewer import enhance_index

DATA = re.compile(r'const DATA=(.*?);const \$', re.S)
IMAGE = re.compile(r'data:(image/(?:png|jpeg|webp));base64,([A-Za-z0-9+/=]+)')
EXTENSIONS = {'image/png': 'png', 'image/jpeg': 'jpg', 'image/webp': 'webp'}

def publish(source: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    (output/'assets').mkdir(); (output/'boards').mkdir()
    assets, pages, home_boards = {}, [], []
    def asset(data_url: str, prefix: str, expected: str | None = None) -> str:
        match = IMAGE.fullmatch(data_url)
        if not match: raise ValueError('不支持的图片格式')
        content = base64.b64decode(match[2], validate=True)
        sha = hashlib.sha256(content).hexdigest()
        if expected and expected != sha: raise ValueError('原图SHA不匹配')
        name = sha + '.' + EXTENSIONS[match[1]]
        if sha not in assets:
            (output/'assets'/name).write_bytes(content)
            assets[sha] = {'path':'assets/'+name, 'sha256':sha, 'bytes':len(content)}
        return prefix+'assets/'+name
    for file in sorted((source/'boards').glob('*.html')):
        text = file.read_text(); match = DATA.search(text)
        if not match: raise ValueError('缺少当前图板DATA')
        original = json.loads(match[1]); tiles=[]
        for row in original['tiles']:
            # 只保留网页实际显示所需字段；文件引用仍保存在原封存交付中。
            tile={k:row[k] for k in ['image_id','label','pixels','rectangle','scope','limits','source_url'] if k in row}
            tile['original_data']=asset(row['original_data'],'../',row['image_ref']['sha256'])
            tiles.append(tile)
        public={k:original[k] for k in ['title','direction_id','branch','target_count','stage_status','native_gate_state','notes','user_approved'] if k in original}
        public['tiles']=tiles
        home_boards.append({'title':public['title'],'board_url':'boards/'+file.name,'tiles':tiles})
        text=text[:match.start(1)]+json.dumps(public,ensure_ascii=False).replace('</','<\\/')+text[match.end(1):]
        target=output/'boards'/file.name;target.write_text(text)
        pages.append({'path':'boards/'+file.name,'source_sha256':hashlib.sha256(file.read_bytes()).hexdigest(),'page_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'tile_count':len(tiles)})
    index=(source/'index.html').read_text()
    index=IMAGE.sub(lambda m:asset(m[0],''),index)
    index=enhance_index(index,home_boards)
    (output/'index.html').write_text(index)
    summary=json.loads((source/'summary.json').read_text())
    public_summary={k:summary[k] for k in ['created_at','model_policy','AI_visual_review_accepted_count','user_approved_count','quantity_policy','completed_evaluation_direction_count','source_identity_scope','original_negative_count_per_direction']}
    public_summary['directions']=[{k:e[k] for k in ['direction_id','title','branch','status_label','visual_review_accepted','image_count','registered_project_count','brief_gap','user_approved']} for e in summary['directions']]
    public_summary['directions']=[{**e,'board_url':'boards/'+e['direction_id']+'.html'} for e in public_summary['directions']]
    (output/'summary.json').write_text(json.dumps(public_summary,ensure_ascii=False,indent=2)+'\n')
    links=json.loads((source/'source-image-links.json').read_text())
    public_links={'rows':[{k:r[k] for k in ['direction_id','image_id','label','article_id','source_group_id','source_project_id','image_url','source_url','rectangle','scope','limits','exact_original_SHA_match'] if k in r} for r in links['rows']]}
    (output/'source-image-links.json').write_text(json.dumps(public_links,ensure_ascii=False,indent=2)+'\n')
    report=['# 七方向8图交付','',f'已评估7方向，{summary["AI_visual_review_accepted_count"]}方向通过AI整板审阅，人工反馈尚未确认。','', '| 方向 | 分支 | 结果 | 参考图／登记项目 |','| --- | --- | --- | --- |']
    for e in public_summary['directions']:report.append(f'| {e["title"]} | {e["branch"]} | {e["status_label"]} | {e["image_count"]}／{e["registered_project_count"]} |')
    report+=['','## 未解决事项','']
    for e in public_summary['directions']:report += ['### '+e['title'],'',e['brief_gap'],'']
    report+=['原图字节、ROI及真实验收结果沿用封存交付；图片仅外置供浏览器加载。资料内具名项目／系列不代表发布事实、精确SKU或物理材料认证。','']
    (output/'report.md').write_text('\n'.join(report))
    manifest={'index_source_sha256':hashlib.sha256((source/'index.html').read_bytes()).hexdigest(),'pages':pages,'assets':list(assets.values()),'unique_asset_count':len(assets),'source_qualification_changed':False,'source_images_recompressed':False}
    manifest['public_files']=[{'path':str(f.relative_to(output)),'sha256':hashlib.sha256(f.read_bytes()).hexdigest(),'bytes':f.stat().st_size} for f in sorted(output.rglob('*')) if f.is_file()]
    (output/'deployment-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    return {'page_count':len(pages)+1,'unique_asset_count':len(assets),'original_tiles':sum(p['tile_count'] for p in pages),'index_bytes':(output/'index.html').stat().st_size,'board_page_bytes':sum((output/p['path']).stat().st_size for p in pages)}

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('source',type=Path);parser.add_argument('output',type=Path);args=parser.parse_args();print(json.dumps(publish(args.source,args.output),ensure_ascii=False))
