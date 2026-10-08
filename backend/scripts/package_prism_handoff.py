"""离线整理棱镜Skill、实际DNA与流程结果；不复制图片、不启动任何模型。"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import hashlib
import html
import json
from pathlib import Path
import re
import shutil
import tempfile
import zipfile
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / 'data/result/visual_workflow/h01_all13_20261005_expanded'
NAME = '棱镜_全流程Skills与结果交接_无原图_20261006'
TEXT_SUFFIXES = {'.json', '.jsonl', '.md', '.txt', '.py', '.cjs', '.js', '.ts', '.yaml', '.yml', '.toml', '.csv', '.html', '.css'}
IMAGE_SUFFIXES = {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp', '.svg', '.tif', '.tiff', '.avif', '.ico'}
SKIP_PARTS = {'__pycache__', 'node_modules', '.git', '.cache', '.pytest_cache', '.venv'}


def read(path):
    return json.loads(Path(path).read_bytes())


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''): h.update(chunk)
    return h.hexdigest()


def put(path, value):
    path = Path(path);path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


class Package:
    """保持源结果原字节；来源路径通过旁表映射，不改写历史JSON或哈希。"""
    def __init__(self, stage):
        self.stage = stage
        self.paths = {}
        self.omitted = []
        self.categories = {}

    def add(self, source, destination=None, category='source'):
        source = Path(source)
        if not source.is_file(): return
        if any(p in SKIP_PARTS for p in source.parts): return
        if source.suffix.lower() in IMAGE_SUFFIXES or source.suffix.lower() in {'.pdf', '.ppt', '.pptx', '.zip', '.pyc'}:
            self.omitted.append({'source': str(source), 'reason': '图片/文档解析原件/嵌套压缩包不在本次交接范围'})
            return
        if source.suffix.lower() not in TEXT_SUFFIXES: return
        raw = source.read_bytes()
        # 旧HTML也可能内嵌业务图；不能仅按扩展名排除原图后宣称包内没有像素。
        if re.search(rb'data:image/[^;,\s]+;base64,[A-Za-z0-9+/]{100}', raw):
            self.omitted.append({'source': str(source), 'sha256': hashlib.sha256(raw).hexdigest(), 'reason': '内嵌图片数据，保留对应纯结构结果而不复制本文件'})
            return
        destination = destination or 'workspace/' + source.relative_to(ROOT).as_posix()
        target = self.stage / destination
        if target.exists():
            if target.read_bytes() != raw: raise ValueError('目的路径冲突: ' + destination)
        else:
            target.parent.mkdir(parents=True, exist_ok=True);target.write_bytes(raw)
        self.paths[str(source.absolute())] = destination
        self.paths[str(source.resolve())] = destination
        self.categories[destination] = category

    def tree(self, source, destination=None, category='source', old_html=False):
        source = Path(source)
        for p in sorted(source.rglob('*')):
            if not p.is_file() or any(s in SKIP_PARTS for s in p.relative_to(source).parts): continue
            if p.suffix == '.html' and not old_html: continue
            self.add(p, (destination.rstrip('/') + '/' + p.relative_to(source).as_posix()) if destination else None, category)


def board_summary(stage):
    """只展示方向、DNA与图片身份信息，绝不生成图片标签或读取原图。"""
    report = read(RUN / 'codex61_20261006/round-result.json')
    families = {f['direction_id']: f for f in read(RUN / 'visual-families.json')['families']}
    cards = []
    for row in report['directions']:
        did = row['direction_id'];family = families[did]
        targets = read(RUN / 'targets-reviewed' / (did + '.json')).get('targets', [])
        byid = {t['candidate_id']: t for t in targets}
        group_path = RUN / 'grouping' / (did + '.json')
        group = read(group_path).get('model_report', {}) if group_path.exists() else {}
        ids = group.get('members', [])
        if did == 'H007': ids = [r['candidate_id'] for r in read(RUN / 'codex61_20261006/h007-paired-v2/summary.json')['candidate_records']]
        lines = []
        for cid in ids:
            t = byid.get(cid, {})
            lines.append('<tr><td>' + html.escape(cid) + '</td><td>' + html.escape(t.get('selected_scope', ''))
                + '</td><td><code>' + html.escape((t.get('image_ref') or {}).get('sha256', '')) + '</code></td></tr>')
        cards.append(f'<section><h2>{did} · {html.escape(family["family_name"])}</h2><p>{html.escape(row["display_status"])}</p>'
            + '<table><thead><tr><th>图片成员</th><th>比较对象与范围</th><th>图片SHA-256（用URL索引回查）</th></tr></thead><tbody>' + ''.join(lines) + '</tbody></table></section>')
    destination = stage / 'delivery/boards-summary.html';destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>13方向情绪板结构结果</title><style>body{max-width:1100px;margin:30px auto;padding:0 20px;font:16px/1.7 system-ui;color:#163d32}section{padding:20px;background:#f1f5f1;margin:20px 0}table{width:100%;border-collapse:collapse}td,th{padding:10px;border-bottom:1px solid #ccd8ce;text-align:left;overflow-wrap:anywhere}code{font-size:12px}</style>'
        '<h1>13方向情绪板结构结果 · 无图片交接版</h1><p><a href="../index.html">返回交接总说明</a> · <a href="../indexes/image-url-provenance.jsonl">图片URL来源索引</a></p>'
        '<p>以下只展示已保存的成员与状态。新通过1、历史复用2、预算停止9、配对来源不足1；三个通过板分别4/5/4张，均未达到6–8张目标。原图、实际取景及截图不随包交付，JSON中相应引用只保留元数据。</p>'
        + ''.join(cards) + '</html>', encoding='utf-8')


VERIFY = '''"""纯离线核对交接文件SHA与条数，不启动模型或网络。"""
import hashlib,json
from pathlib import Path
r=Path(__file__).resolve().parents[1]
m=json.loads((r/'metadata/manifest.json').read_bytes())
errors=[]
for f in m['files']:
 p=r/f['path'];h=hashlib.sha256()
 if not p.is_file():errors.append({'path':f['path'],'error':'missing'});continue
 with p.open('rb') as stream:
  for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
 if h.hexdigest()!=f['sha256']:errors.append({'path':f['path'],'error':'sha256'})
for name,count in [('dna-index.jsonl',8461),('source-images.jsonl',8774),('image-url-provenance.jsonl',8774)]:
 with (r/'indexes'/name).open(encoding='utf-8') as stream:actual=sum(bool(line.strip()) for line in stream)
 if actual!=count:errors.append({'path':name,'error':'row_count','actual':actual})
print(json.dumps({'checked_files':len(m['files']),'errors':errors,'model_calls':0},ensure_ascii=False))
raise SystemExit(bool(errors))
'''


def build(out):
    si = read('/tmp/prism_handoff_skills_inventory.json')
    oi = read('/tmp/prism_handoff_outputs_inventory.json')
    stage = Path(tempfile.mkdtemp(prefix='prism_handoff_20261006_')) / NAME
    stage.mkdir();package = Package(stage)
    for item in si['active_skills']:
        package.tree(item['resolved_source'], 'skills/active-project/' + Path(item['source']).name, 'active-skill', old_html=True)
    for item in si['portable_workflow']:
        package.tree(item['resolved_source'], 'skills/portable-workflow/skills/' + Path(item['source']).name, 'workflow-skill', old_html=True)
    suite = ROOT / 'ref/老师对接/最新完整流程/棱镜Skills组合_v1.1-local'
    for source in si['suite_ancillary_paths']:
        p = Path(source);dest = 'skills/portable-workflow/' + p.relative_to(suite).as_posix()
        if p.is_dir(): package.tree(p, dest, 'suite-reference', old_html=True)
        else: package.add(p, dest, 'suite-reference')
    for p in (ROOT / 'backend/app').rglob('*.py'): package.add(p, category='project-adapter')
    package.add(ROOT / 'backend/requirements.txt', category='project-adapter')
    for p in si['latest_runtime_source_paths']:
        p = Path(p)
        if p.is_dir(): package.tree(p, category='project-adapter')
        else: package.add(p, category='project-adapter')
    for p in (ROOT / 'backend/scripts').glob('*.py'):
        if p.name.startswith(('run_d02_', 'run_trend_r5', 'run_trend_quality', 'repair_trend_r5')) or p.name in {'publish_visual_delivery.py', 'package_prism_handoff.py'}:
            package.add(p, category='project-adapter')
    for p in (ROOT / 'backend/tests').glob('test_*.py'):
        if any(s in p.name for s in ('prism_r5', 'prism_dna', 'd02_ppt', 'trend_r5', 'visual_workflow', 'candidate_prioritization', 'codex_transport', 'paired_surfaces')):
            package.add(p, category='offline-test')
    for run in ('astra_full_20261001', 'astra_consensus_20261001'):
        package.tree(ROOT / 'data/result/trend_text_clusters' / run, category='trend-clusters')
    package.tree(Path(oi['stages']['research_clusters']['path']), category='research-clusters')
    package.tree(Path(oi['stages']['handshake']['path']), category='handshake')
    for source in oi['dna']['all_variant_source_paths']: package.add(source, category='actual-dna')
    # 不收巨大原图inputs和中间重复执行环境，只保存实际DNA批次身份及终态账本。
    for p in (ROOT / 'data/result/trend_dna/batches').glob('*/*.json'): package.add(p, category='dna-batch-ledger')
    for p in (ROOT / 'data/result/trend_dna/batches').glob('*/offline_repair*/*.json'): package.add(p, category='dna-batch-ledger')
    for p in (ROOT / 'data/userreseach_data/liked_images_d02_results/batches').rglob('*.json'):
        if len(p.relative_to(ROOT / 'data/userreseach_data/liked_images_d02_results/batches').parts) <= 2: package.add(p, category='research-dna-batch-ledger')
    keep = {'calls', 'targets', 'targets-reviewed', 'grouping', 'board-reviews', 'recall', 'full-corpus-v2', 'evidence-snapshots',
        'expansion-waves', 'codex61_20261006', 'local-priorities', 'combination-ledger', 'preparation'}
    for rt in (RUN, RUN.with_name('h01_all13_20261005')):
        for p in rt.iterdir():
            if p.is_file() and p.suffix in {'.json', '.jsonl'}: package.add(p, category='visual-run-state')
            elif p.is_dir() and p.name in keep: package.tree(p, category='visual-run-evidence')
    for n in ('PROGRESS.md', 'DECISIONS.md', 'BUGS.md', 'PRISM_R5_PPT_ENJOY_BATCH_20260930.md'):
        package.add(ROOT / 'docs' / n, category='project-documentation')
    package.add(ROOT / 'AGENTS.md', category='project-documentation')
    url_summary = read('/tmp/prism_handoff_url_sources.json')
    for source in url_summary['sources']:
        p = ROOT / source['source_path']
        if sha(p) != source['sha256']: raise ValueError('图片URL来源文件SHA变化')
        package.add(p, category='image-url-source-evidence')
    inventory = read(RUN / 'inventory.json')
    indexes = stage / 'indexes';indexes.mkdir(exist_ok=True)
    def lines(name, rows):
        with (indexes / name).open('w', encoding='utf-8') as stream:
            for row in rows: stream.write(json.dumps(row, ensure_ascii=False, separators=(',', ':')) + '\n')
    dna = []
    images = []
    for row in inventory:
        images.append({k: row[k] for k in ('image_sha256', 'source_kinds', 'source_paths', 'preferences', 'articles', 'batch_entries', 'dna_readiness')})
        if row['eligible_for_dna_recall']:
            selected = row['selected_dna_ref']
            if selected['path'] not in package.paths: raise ValueError('选定DNA没有打包: ' + selected['path'])
            if sha(selected['path']) != selected['sha256']: raise ValueError('选定DNA源SHA变化')
            dna.append({'image_sha256': row['image_sha256'], 'source_kinds': row['source_kinds'],
                'source_paths': row['source_paths'], 'research_preferences': row['preferences'], 'articles': row['articles'],
                'readiness': row['dna_readiness'], 'selected_dna_ref': selected,
                'selected_package_path': package.paths[selected['path']],
                'dna_variants': [{'original_ref': v['result_ref'], 'package_path': package.paths[v['result_ref']['path']]} for v in row['dna_variants']]})
    assert len(dna) == 8461 and len(images) == 8774
    lines('dna-index.jsonl', dna);lines('source-images.jsonl', images)
    shutil.copyfile('/tmp/prism_handoff_image_urls.jsonl', indexes / 'image-url-provenance.jsonl')
    put(indexes / 'stages.json', {**oi['stages'], 'dna': {k:v for k,v in oi['dna'].items() if 'source_paths' not in k},
        'semantic_screen': oi['semantic_screen'], 'round': oi['round'], 'image_url_coverage': url_summary})
    put(indexes / 'image-url-validation.json', url_summary)
    catalogue = []
    for s in si['active_skills'] + si['portable_workflow']:
        group = 'active-project' if s in si['active_skills'] else 'portable-workflow/skills'
        name = Path(s['source']).name
        entry = 'SKILL.md' if (Path(s['resolved_source']) / 'SKILL.md').exists() else 'references/contracts.md'
        catalogue.append({'name': name, 'path': 'skills/' + group + '/' + name + '/' + entry, 'original_source': s['source'], 'role':s['role']})
    put(indexes / 'skill-catalogue.json', catalogue)
    board_summary(stage)
    shutil.copyfile('/tmp/prism_handoff_overview.html', stage / 'index.html')
    shutil.copyfile('/tmp/prism_handoff_readme.md', stage / 'README.md')
    tool = stage / 'tools/verify_package.py';tool.parent.mkdir();tool.write_text(VERIFY, encoding='utf-8')
    put(stage / 'metadata/path-map.json', package.paths)
    put(stage / 'metadata/exclusions.json', {'business_original_images_included':False, 'screenshots_included':False,
        'pdf_parser_included':False, 'credentials_included':False,
        'notes':['原图/实际裁切/浏览器截图只保留路径、URL及SHA元信息。', '原始JSON保留字节和绝对路径；接收者通过path-map回查包内文件。',
            'Skill内图片校准文件同样不收；未来视觉执行须从原Skill来源补齐这些资源。', '组合原bundle-manifest仅作上游来源凭据；本包以metadata/manifest.json为准。'],
        'omitted_files':package.omitted})
    files = []
    for p in sorted(stage.rglob('*')):
        if p.is_file():
            rel = p.relative_to(stage).as_posix()
            files.append({'path':rel,'bytes':p.stat().st_size,'sha256':sha(p),'category':package.categories.get(rel,'handoff-index-or-guide')})
    put(stage / 'metadata/manifest.json', {'schema':'prism.metadata-only-handoff.v1', 'created_at':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
        'source_project':str(ROOT),'contains_original_images':False,'model_calls_during_packaging':0,
        'counts':{'usable_dna_images':8461,'actual_dna_version_files':len(oi['dna']['all_variant_source_paths']),'source_images':8774},
        'files':files,'manifest_self_hash':'清单不列自身，整个ZIP另附SHA256'})
    # 总说明的本地链接必须都能打开；外部URL只是来源链接，不代替包内文件。
    for page in [stage / 'index.html', stage / 'delivery/boards-summary.html']:
        for href in re.findall(r'href=["\']([^"\']+)', page.read_text(encoding='utf-8')):
            if href.startswith(('http:', 'https:', '#', 'mailto:')): continue
            if not (page.parent / href.split('#')[0]).exists(): raise ValueError('交接HTML链接缺失: ' + href)
    out = Path(out);out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists(): raise FileExistsError('不覆盖现有交接包: ' + str(out))
    temp = out.with_suffix('.zip.building')
    paths = sorted(p for p in stage.rglob('*') if p.is_file())
    print(json.dumps({'stage':str(stage),'files':len(paths),'bytes':sum(p.stat().st_size for p in paths),'phase':'zipping'},ensure_ascii=False),flush=True)
    with zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED,compresslevel=6,allowZip64=True) as archive:
        for i,p in enumerate(paths,1):
            archive.write(p, NAME + '/' + p.relative_to(stage).as_posix())
            if i % 4000 == 0: print(json.dumps({'packed':i,'total':len(paths)}),flush=True)
    with zipfile.ZipFile(temp) as archive:
        bad = archive.testzip()
        if bad: raise ValueError('ZIP CRC失败: ' + bad)
        if any(Path(n).suffix.lower() in IMAGE_SUFFIXES or Path(n).suffix.lower() == '.pdf' for n in archive.namelist()): raise ValueError('无图包出现图片/PDF')
    temp.replace(out)
    digest = sha(out);out.with_suffix('.zip.sha256').write_text(digest + '  ' + out.name + '\n',encoding='utf-8')
    summary = {'zip':str(out),'sha256':digest,'bytes':out.stat().st_size,'files':len(paths),'stage':str(stage),'model_calls':0}
    put(out.with_suffix('.zip.manifest.json'),summary)
    print(json.dumps(summary,ensure_ascii=False),flush=True)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',default=str(ROOT/'ref'/(NAME+'.zip')))
    build(parser.parse_args().out)
