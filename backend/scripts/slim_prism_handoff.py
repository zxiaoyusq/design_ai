"""从完整交接快照整理正式结果版；保留每份DNA及URL来源字节，不执行模型。"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parents[2]
FULL_NAME = '棱镜_全流程Skills与结果交接_无原图_20261006'
SLIM_NAME = '棱镜_全流程Skills与结果交接_精简无原图_20261006'
BASE = 'workspace/data/result/visual_workflow/'
RUNS = ('h01_all13_20261005_expanded', 'h01_all13_20261005')
CORE_CALL_FILES = {'answer.json', 'receipt.json', 'request.json'}
CANONICAL_DIRS = {'targets', 'targets-reviewed', 'grouping', 'board-reviews', 'preparation'}
CANONICAL_FILES = {'inventory.json', 'dna-evidence.jsonl', 'visual-families.json', 'project.json',
    'visual-budget-policy.json', 'execution-boundary.json', 'continuation-status.json', 'expansion-progress.json',
    'candidate-exhaustion.json', 'failed-register.json', 'inherited-negative-scopes.json', 'root-proposed-family-policy.json',
    'inventory-summary.json', 'root-final-review.json', 'inherited-root-final-review.json'}


def dump(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()


def retain(path, dna_paths, url_source_paths):
    if path in dna_paths or path in url_source_paths: return True
    if path.startswith(('skills/', 'indexes/', 'workspace/backend/', 'workspace/docs/', 'delivery/')): return True
    if path in {'index.html', 'README.md', 'workspace/AGENTS.md', 'tools/verify_package.py', 'metadata/exclusions.json'}: return True
    if path.startswith('workspace/data/result/trend_text_clusters/astra_consensus_20261001/final/'): return True
    if path.startswith('workspace/data/result/user_research_clusters/users_selected_5_astra_20260930/'): return True
    h01 = 'workspace/data/result/semantic_handshake/astra_full_20261001/'
    if path.startswith(h01):
        tail = path[len(h01):]
        return '/' not in tail and tail not in {'snapshot.json', 'proposal.json'}
    if path.startswith(('workspace/data/userreseach_data/liked_images_d02_results/batches/', 'workspace/data/result/trend_dna/batches/')):
        return Path(path).name in {'manifest.json', 'final_entries.json', 'selection.json', 'summary.json', 'failures.json', 'report.json'}
    for run in RUNS:
        prefix = BASE + run + '/'
        if not path.startswith(prefix): continue
        tail = path[len(prefix):];head = tail.split('/')[0]
        if '/' not in tail:
            # 只留一份8千图的DNA/图片清单；旧目录中的同内容大副本不再随包携带。
            return tail in CANONICAL_FILES and not (run == RUNS[1] and tail in {'inventory.json', 'dna-evidence.jsonl'})
        if head == 'preparation':
            # preparation也含旧整库输入副本；只留入口源码，不能把目录当成纯代码全收。
            return tail.count('/') == 1 and Path(tail).suffix in {'.py', '.cjs'}
        if head in CANONICAL_DIRS:
            return not (run == RUNS[1] and head in {'targets', 'targets-reviewed'})
        if head == 'calls':
            call_id = tail.split('/')[1]
            return Path(tail).name in CORE_CALL_FILES and not call_id.startswith('full-corpus-')
        if head == 'recall': return tail in {'recall/semantic-coverage.jsonl', 'recall/full-corpus-coverage.json', 'recall/full-corpus-failures.json'}
        if head == 'full-corpus-v2': return tail in {'full-corpus-v2/plan.json', 'full-corpus-v2/execution.json', 'full-corpus-v2/system.prompt.txt'}
        if head == 'codex61_20261006':
            return tail in {'codex61_20261006/round-result.json', 'codex61_20261006/round-manifest.json',
                'codex61_20261006/h007-paired-v2/summary.json', 'codex61_20261006/event-classification-recovery/recovery.json'}
    return False


def main(source, out):
    source = Path(source);out = Path(out)
    if out.exists(): raise FileExistsError('不覆盖已有精简包')
    with zipfile.ZipFile(source) as src:
        roots = {n.split('/')[0] for n in src.namelist()};assert len(roots) == 1
        root = roots.pop() + '/';infos = {i.filename[len(root):]: i for i in src.infolist() if not i.is_dir()}
        old_manifest = json.loads(src.read(root + 'metadata/manifest.json'))
        old_files = {f['path']: f for f in old_manifest['files']}
        dna_rows = [json.loads(line) for line in src.read(root + 'indexes/dna-index.jsonl').splitlines()]
        dna_paths = {r['selected_package_path'] for r in dna_rows}
        dna_paths.update(v['package_path'] for r in dna_rows for v in r['dna_variants'])
        url_validation = json.loads(src.read(root + 'indexes/image-url-validation.json'))
        url_sources = {s['archive_path'] for s in url_validation['sources']}
        assert len(dna_rows) == 8461 and len(dna_paths) == 8565
        for row in dna_rows:
            assert old_files[row['selected_package_path']]['sha256'] == row['selected_dna_ref']['sha256']
            for variant in row['dna_variants']:
                assert old_files[variant['package_path']]['sha256'] == variant['original_ref']['sha256']
        for s in url_validation['sources']: assert old_files[s['archive_path']]['sha256'] == s['sha256']
        selected = {p for p in infos if retain(p, dna_paths, url_sources)}
        assert dna_paths <= selected and url_sources <= selected
        edition = {'edition':'正式结果精简版', 'all_dna_versions_preserved':8565, 'dna_image_identities':8461,
            'url_source_files_preserved':len(url_sources), 'original_pixels_included':False,
            'removed_process_files':len(infos)-len(selected), 'full_process_archive':source.name,
            'note':'删除重复快照、中间模型输入、原始事件日志、旧聚类运行档案；未修改或截断DNA。保留原JSON里的历史引用；被删过程引用可在完整版回查。'}
        banner = '<p style="padding:14px;background:#e8f1f6;border-radius:8px"><strong>正式结果精简版：</strong>全部DNA与图片URL来源保留；重复快照、事件日志和中间输入不随本包交付，需要完整过程审计时使用完整版。</p>'
        replacements = {}
        page = src.read(root + 'index.html').decode()
        replacements['index.html'] = page.replace('<body>', '<body>' + banner, 1).encode()
        replacements['README.md'] = ('# 正式结果精简版\n\n全部8,565份DNA版本与8,461张图片身份、URL追溯源文件保持原字节。'
            '移除重复快照、原始事件日志、中间输入和旧聚类运行档案；当前元数据中对被删过程文件的历史引用可在完整版回查。'
            '不包含原图。所有文本阶段最终结果、最终图板结构及核心请求/答复/回执保留。\n\n').encode() + src.read(root + 'README.md')
        stages = json.loads(src.read(root + 'indexes/stages.json'));stages['handoff_edition'] = edition
        replacements['indexes/stages.json'] = dump(stages)
        exclusions = json.loads(src.read(root + 'metadata/exclusions.json'));exclusions['slim_edition'] = edition
        replacements['metadata/exclusions.json'] = dump(exclusions)
        path_map = json.loads(src.read(root + 'metadata/path-map.json'))
        replacements['metadata/path-map.json'] = dump({p:dest for p,dest in path_map.items() if dest in selected})
        replacements['metadata/slim-edition.json'] = dump(edition)
        selected.update(replacements)
        files = []
        temp = out.with_suffix('.zip.building')
        print(json.dumps({'selected_files':len(selected),'actual_dna_files':len(dna_paths),'phase':'writing'},ensure_ascii=False),flush=True)
        with zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED,compresslevel=6,allowZip64=True) as dest:
            for p in sorted(selected):
                raw = replacements[p] if p in replacements else src.read(root + p)
                digest = hashlib.sha256(raw).hexdigest()
                if p not in replacements:
                    assert digest == old_files[p]['sha256'], p
                files.append({'path':p,'bytes':len(raw),'sha256':digest,'category':old_files.get(p,{}).get('category','slim-guide')})
                dest.writestr(SLIM_NAME + '/' + p, raw)
            manifest = {**old_manifest, 'edition':edition, 'files':files}
            dest.writestr(SLIM_NAME + '/metadata/manifest.json', dump(manifest))
    # 全文件CRC与SHA，而非只看压缩命令返回；还核对说明链接及索引行数。
    with zipfile.ZipFile(temp) as z:
        assert z.testzip() is None
        for f in files: assert hashlib.sha256(z.read(SLIM_NAME + '/' + f['path'])).hexdigest() == f['sha256'],f['path']
        for name,count in [('dna-index.jsonl',8461),('source-images.jsonl',8774),('image-url-provenance.jsonl',8774)]:
            assert len(z.read(SLIM_NAME + '/indexes/' + name).splitlines()) == count
        present = set(z.namelist())
        for href in re.findall(r'href=["\']([^"\']+)', z.read(SLIM_NAME + '/index.html').decode()):
            if not href.startswith(('http:', 'https:', '#')): assert SLIM_NAME + '/' + href.split('#')[0] in present,href
        assert not any(Path(n).suffix.lower() in {'.png','.jpg','.jpeg','.gif','.webp','.svg','.pdf'} for n in present)
    temp.replace(out)
    h = hashlib.sha256()
    with out.open('rb') as stream:
        for b in iter(lambda:stream.read(1024*1024),b''):h.update(b)
    out.with_suffix('.zip.sha256').write_text(h.hexdigest() + '  ' + out.name + '\n',encoding='utf-8')
    result = {'zip':str(out),'bytes':out.stat().st_size,'sha256':h.hexdigest(),'files':len(files)+1,'dna_files':len(dna_paths),
        'source_bytes':source.stat().st_size,'reduction_percent':round((1-out.stat().st_size/source.stat().st_size)*100,1),'model_calls':0}
    out.with_suffix('.zip.manifest.json').write_bytes(dump(result))
    print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',default=str(ROOT/'ref'/(FULL_NAME+'.zip')))
    p.add_argument('--out',default=str(ROOT/'ref'/(SLIM_NAME+'.zip')))
    a=p.parse_args();main(a.source,a.out)
