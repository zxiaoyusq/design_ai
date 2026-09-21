"""为现有趋势 JSON 补下载图片，保留文章文本，并同步 JSONL 与下载报告。"""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
import json
from pathlib import Path
import shutil

try:
    from scripts.prepare_trend_data import PROJECT_ROOT, download_image, write_outputs
except ModuleNotFoundError:
    from prepare_trend_data import PROJECT_ROOT, download_image, write_outputs


def main(argv=None):
    """图片目录可以与 JSON 分离；回填路径始终相对 JSON 所在目录。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--json', type=Path, default=PROJECT_ROOT / 'data/trend_data/article_table_2/trends.json')
    parser.add_argument('--images-dir', type=Path, default=PROJECT_ROOT / 'data/trend_data/images')
    parser.add_argument('--workers', type=int, default=12)
    parser.add_argument('--timeout', type=float, default=30)
    parser.add_argument('--retries', type=int, default=2)
    args = parser.parse_args(argv)
    if args.workers < 1 or args.timeout <= 0 or args.retries < 0:
        parser.error('workers、timeout 必须大于零，retries 不得小于零')
    path, images_dir = args.json.resolve(), args.images_dir.resolve()
    if path.name != 'trends.json':
        parser.error('输入文件名必须为 trends.json，与既有 JSONL/报告输出约定一致')
    data = json.loads(path.read_text(encoding='utf-8'))
    records = data['trends']
    images = [image for record in records for image in record['images']]
    # 运行前保留原索引；断点重跑复用通过图片解码和哈希检查的缓存。
    backup = path.parent / 'backups' / datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')
    backup.mkdir(parents=True)
    for name in ('trends.json', 'trends.jsonl', 'download_report.json'):
        source = path.parent / name
        if source.exists():
            shutil.copy2(source, backup / name)
    print(f'开始补图：{len(records)} 条趋势，{len(images)} 个图片引用；目录 {images_dir}', flush=True)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        jobs = {pool.submit(download_image, image, path.parent, args.timeout, args.retries,
                            images_dir=images_dir): image for image in images}
        for completed, future in enumerate(as_completed(jobs), 1):
            entry = jobs[future]
            result = future.result()
            # 上次失败的错误信息不能残留在成功记录中。
            if result['status'] == 'downloaded':
                for key in ('error', 'attempts', 'http_status'):
                    result.pop(key, None)
            entry.clear()
            entry.update(result)
            if completed % 100 == 0 or completed == len(images):
                counts = write_outputs(path.parent, records, data['source'])
                print(f"图片 {completed}/{len(images)}：成功 {counts['downloaded']}，失败 {counts['failed']}，缓存 {counts['cached']}", flush=True)
    counts = write_outputs(path.parent, records, data['source'])
    print(json.dumps(counts, ensure_ascii=False), flush=True)
    return 2 if counts['failed'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
