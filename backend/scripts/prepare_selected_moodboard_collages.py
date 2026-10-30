"""依据用户拒绝记录准备16:9拼贴页面，保留原取景，交给浏览器导出图片。"""

from __future__ import annotations

import argparse
import hashlib
from html import escape
import itertools
import json
from pathlib import Path
import shutil

from PIL import Image
from publish_moodboard_review_collection import page_data


WIDTH, HEIGHT, GAP = 3840, 2160, 16


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def partitions(count: int):
    """枚举连续分行，维持保留图的来源顺序；只用于几何排版，不做审美选员。"""
    for rows in range(1, min(count, 3) + 1):
        for cuts in itertools.combinations(range(1, count), rows - 1):
            boundaries = (0, *cuts, count)
            yield [list(range(start, end)) for start, end in zip(boundaries, boundaries[1:])]


def layout(aspects: list[float]) -> dict:
    """以完整取景等比例适配，选择可见照片面积最大的分行，不为铺满追加裁切。"""
    best = None
    for rows in partitions(len(aspects)):
        natural_heights = [(WIDTH - GAP * (len(row) - 1)) / sum(aspects[i] for i in row) for row in rows]
        scale = (HEIGHT - GAP * (len(rows) - 1)) / sum(natural_heights)
        placements = []
        filled_area = 0
        y = 0.0
        for row, natural_height in zip(rows, natural_heights):
            row_height = natural_height * scale
            available_width = WIDTH - GAP * (len(row) - 1)
            aspect_sum = sum(aspects[index] for index in row)
            x = 0.0
            for index in row:
                width = available_width * aspects[index] / aspect_sum
                image_height = min(row_height, width / aspects[index])
                image_width = image_height * aspects[index]
                placements.append({'index': index, 'cell': [x, y, width, row_height],
                                   'frame': [x + (width - image_width) / 2, y + (row_height - image_height) / 2, image_width, image_height]})
                filled_area += image_width * image_height
                x += width + GAP
            y += row_height + GAP
        candidate = {'rows': [len(row) for row in rows], 'placements': placements, 'photo_area_ratio': filled_area / (WIDTH * HEIGHT)}
        if best is None or candidate['photo_area_ratio'] > best['photo_area_ratio']:
            best = candidate
    return best


def board_html(title: str, images: list[dict], composition: dict) -> str:
    layers = []
    for placement in composition['placements']:
        image = images[placement['index']]
        x, y, width, height = placement['frame']
        left, top, roi_width, roi_height = image['preview_roi']
        # 冻结视窗以CSS重放；图片只等比例缩放，整板不包含标题、状态或来源字样。
        frame_style = f'left:{x:.6f}px;top:{y:.6f}px;width:{width:.6f}px;height:{height:.6f}px'
        photo_style = f'width:{100 / roi_width:.10f}%;height:{100 / roi_height:.10f}%;left:{-100 * left / roi_width:.10f}%;top:{-100 * top / roi_height:.10f}%'
        layers.append(f'<div class="frame" data-instance-id="{escape(image["id"], quote=True)}" style="{frame_style}"><img src="../{escape(image["preview"], quote=True)}" alt="{escape(image["label"], quote=True)}" style="{photo_style}"></div>')
    return ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>' + escape(title) + '</title>'
            '<style>*{box-sizing:border-box}html,body{margin:0;width:3840px;height:2160px;overflow:hidden;background:white}'
            '#canvas{position:relative;width:3840px;height:2160px;background:white}.frame{position:absolute;overflow:hidden}'
            '.frame img{position:absolute;display:block;max-width:none}</style></head><body><div id="canvas">'
            + ''.join(layers) + '</div></body></html>')


def prepare(collection: Path, feedback_file: Path, reference_file: Path, output: Path) -> dict:
    data = page_data(collection.read_text(encoding='utf-8'), 'collection-data')
    feedback = json.loads(feedback_file.read_text(encoding='utf-8'))
    if feedback['collection_identity'] != data['identity']:
        raise ValueError('标注集合身份不匹配，不能套用到当前图片')
    records = {row['instance_id']: row for row in feedback['records']}
    images = [image for board in data['boards'] for image in board['images']]
    if len(records) != len(feedback['records']) or set(records) != {image['id'] for image in images}:
        raise ValueError('标注存在重复或缺失图片位置')
    for image in images:
        row = records[image['id']]
        if row['image_sha256'] != image['sha256'] or row['roi'] != image['roi'] or row['status'] not in {'rejected', 'unmarked'}:
            raise ValueError('标注中的图片身份、取景或状态无效')
    output.mkdir(parents=True, exist_ok=False)
    (output / 'assets').mkdir()
    (output / 'boards').mkdir()
    (output / 'images').mkdir()
    copied = set()
    board_rows = []
    source_labels = {'ppt': '老师PPT', 'reference': '参考网页', 'bounded': '本轮网页'}
    for number, board in enumerate(data['boards'], 1):
        # 用户本次明确要求只保留通过图，按已有界面的排除式标注保留unmarked。
        # 原始JSON仍是unmarked，不将此操作写回为既有人工或模型的PASS。
        selected = [image for image in board['images'] if records[image['id']]['status'] == 'unmarked']
        if not selected:
            raise ValueError(f'此版没有可保留图片：{board["title"]}')
        aspects = []
        for image in selected:
            for relative in {image['original'], image['preview']}:
                source = (collection.parent / relative).resolve()
                if not source.is_relative_to(collection.parent.resolve()):
                    raise ValueError('图片路径超出来源目录')
                if relative not in copied:
                    if digest(source) != source.stem:
                        raise ValueError('来源图片SHA不匹配')
                    shutil.copyfile(source, output / relative)
                    copied.add(relative)
            with Image.open(output / image['preview']) as photo:
                width, height = photo.size
            roi = image['preview_roi']
            aspects.append(width * roi[2] / (height * roi[3]))
        composition = layout(aspects)
        filename = f'{number:02d}_{source_labels[board["source"]]}_{board["source_index"]:02d}'
        html_path = f'boards/{filename}.html'
        image_path = f'images/{filename}.jpeg'
        (output / html_path).write_text(board_html(board['title'], selected, composition), encoding='utf-8')
        board_rows.append({'board_id': board['id'], 'title': board['title'], 'source': board['source'],
                           'source_label': source_labels[board['source']], 'source_index': board['source_index'],
                           'html': html_path, 'image': image_path, 'width': WIDTH, 'height': HEIGHT,
                           'retained_count': len(selected), 'rejected_count': len(board['images']) - len(selected),
                           'layout': composition, 'images': [{'instance_id': image['id'], 'image_id': image['image_id'],
                           'sha256': image['sha256'], 'roi': image['roi'], 'preview_roi': image['preview_roi'],
                           'original': image['original'], 'preview': image['preview'], 'source_status': 'unmarked'} for image in selected]})
    cards = []
    for row in board_rows:
        cards.append(f'<article><h2>{row["source_label"]} · {row["source_index"]:02d} · {escape(row["title"])}</h2>'
                     f'<p>保留 {row["retained_count"]} 张，去掉 {row["rejected_count"]} 张不通过图片。</p>'
                     f'<a href="{escape(row["image"], quote=True)}" target="_blank"><img src="{escape(row["image"], quote=True)}" loading="lazy" alt="{escape(row["title"], quote=True)}"></a>'
                     f'<a href="{escape(row["image"], quote=True)}" download>下载 16:9 图片</a></article>')
    index = ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
             '<title>保留图片 · 16:9 情绪板</title><style>body{margin:0;background:#f4f5ef;color:#243d33;font:15px/1.6 system-ui,sans-serif}'
             'main{max-width:1400px;margin:auto;padding:30px 20px}h1{font-size:30px}h2{font-size:19px;font-weight:500}article{background:white;margin:24px 0;padding:18px;border:1px solid #dce2d8;border-radius:10px}'
             'img{display:block;width:100%;height:auto;margin:14px 0}a{color:#285c42}p{color:#67796d}</style></head><body><main><h1>保留图片 · 16:9 情绪板</h1>'
             '<p>依据本次选图记录去掉不通过图片，保留43个图片位置，分别生成12张3840×2160图片。仅一张保留图的版仍保持单图，不补图。点击整板查看原尺寸。</p>'
             '<a href="selected-moodboards-16x9.zip" download>下载全部12张图片 ZIP</a>' + ''.join(cards) + '</main></body></html>')
    (output / 'index.html').write_text(index, encoding='utf-8')
    manifest = {'schema_version': 'prism.selected_collages.v1', 'collection_identity': data['identity'],
                'feedback_ref': {'path': str(feedback_file), 'sha256': digest(feedback_file)},
                'collection_ref': {'path': str(collection), 'sha256': digest(collection)},
                'layout_reference_ref': {'path': str(reference_file), 'sha256': digest(reference_file)},
                'selection_basis': 'current_user_request_retain_unmarked_after_rejection',
                'source_feedback_modified': False, 'new_visual_pass_awarded': False,
                'width': WIDTH, 'height': HEIGHT, 'gap': GAP,
                'board_count': len(board_rows), 'retained_count': sum(row['retained_count'] for row in board_rows),
                'source_images_modified': False, 'additional_crop': False, 'boards': board_rows}
    (output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return {'output': str(output), 'board_count': manifest['board_count'], 'retained_count': manifest['retained_count'],
            'per_board_counts': [row['retained_count'] for row in board_rows]}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--collection', type=Path, default=Path('frontend/public/visual-workflow/moodboard-image-review-20261012/index.html'))
    parser.add_argument('--feedback', type=Path, default=Path('ref/问题反馈/情绪版选图.json'))
    parser.add_argument('--reference', type=Path, default=Path('ref/参考情绪版/20261013-101701.jpeg'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.collection, args.feedback, args.reference, args.output), ensure_ascii=False, indent=2))
